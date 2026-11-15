import csv
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from boekhouding.auditfile_report import (
    load_auditfile_text,
    AuditfileError,
    AuditLine,
    analyze_auditfile,
    match_lines,
    parse_auditfile,
    supplier_tokens,
    write_account_csv,
    write_lines_csv,
    write_unmatched_csv,
)
from boekhouding.cli import app

runner = CliRunner()


"""Tests voor XAF-auditfile-analyse en het bijbehorende CLI-commando."""


def mk(desc, debit="0", credit="0", date="2025-01-01", tid="1", rid="1"):
    return AuditLine(
        transaction_id=tid,
        record_id=rid,
        effective_date=date,
        debit=Decimal(debit),
        credit=Decimal(credit),
        description=desc,
    )


def _line(rid, account, date, desc, debit=None, credit=None):
    body = (
        f"<line><recordID>{rid}</recordID><accountID>{account}</accountID>"
        f"<effectiveDate>{date}</effectiveDate><description>{desc}</description>"
    )
    if debit is not None:
        body += f"<debitAmount>{debit}</debitAmount>"
    if credit is not None:
        body += f"<creditAmount>{credit}</creditAmount>"
    return body + "</line>"


def _txn(tid, date, lines):
    return (
        f"<transaction><transactionID>{tid}</transactionID>"
        f"<transactionDate>{date}</transactionDate>{''.join(lines)}</transaction>"
    )


def _write_auditfile(path, transactions):
    xml = (
        '<?xml version="1.0" encoding="ISO-8859-1"?>'
        "<auditfile><header/><generalLedger/>"
        f"<transactions>{''.join(transactions)}</transactions></auditfile>"
    )
    path.write_text(xml, encoding="utf-8")
    return path


@pytest.fixture
def sample_auditfile(tmp_path):
    transactions = [
        _txn(1, "2025-01-01", [_line(1, "1500", "2025-01-01", "Beginbalans", credit="100.00")]),
        _txn(2, "2025-01-05", [_line(2, "1500", "2025-01-05", "Leverancier A", credit="50.00")]),
        _txn(3, "2025-01-06", [_line(3, "1500", "2025-01-06", "Leverancier A", debit="50.00")]),
        _txn(4, "2025-01-10", [_line(4, "4200", "2025-01-10", "Leverancier A", debit="50.00")]),
        _txn(5, "2025-01-11", [_line(5, "1500", "2025-01-11", "Café zonder tegenboeking", credit="12.34")]),
    ]
    return _write_auditfile(tmp_path / "audit-2025.xaf", transactions)


def test_parse_auditfile_returns_only_requested_account(sample_auditfile):
    lines = parse_auditfile(sample_auditfile, "1500")
    assert len(lines) == 4
    assert all(line.description for line in lines)
    assert {line.record_id for line in lines} == {"1", "2", "3", "5"}


def test_parse_auditfile_parses_amounts_as_decimal(sample_auditfile):
    lines = {line.record_id: line for line in parse_auditfile(sample_auditfile, "1500")}
    assert lines["1"].credit == Decimal("100.00")
    assert lines["1"].debit == Decimal("0")
    assert lines["3"].debit == Decimal("50.00")
    assert lines["3"].movement == Decimal("-50.00")


def test_parse_auditfile_empty_account_returns_empty(sample_auditfile):
    assert parse_auditfile(sample_auditfile, "9999") == []


def test_load_auditfile_reads_utf8_despite_iso_declaration(sample_auditfile):
    text = load_auditfile_text(sample_auditfile)
    assert "Café" in text


def test_load_auditfile_falls_back_to_latin1(tmp_path):
    path = tmp_path / "latin1.xaf"
    xml = '<?xml version="1.0" encoding="ISO-8859-1"?><auditfile><t>Caf\xe9</t></auditfile>'
    path.write_bytes(xml.encode("iso-8859-1"))
    assert "Café" in load_auditfile_text(path)


def test_parse_auditfile_invalid_xml_raises(tmp_path):
    path = tmp_path / "broken.xaf"
    path.write_text("<auditfile><transactions>", encoding="utf-8")
    with pytest.raises(AuditfileError):
        parse_auditfile(path, "1500")


def test_supplier_tokens_strips_references_and_stopwords():
    assert supplier_tokens("Leverancier A") == frozenset({"leverancier"})
    assert supplier_tokens("KPN B.V. Mobiel mei") == frozenset({"kpn"})
    assert supplier_tokens("[Teveel € 6,00 op € 240,65] Renewi Nederland B.V.") == frozenset(
        {"renewi", "nederland"}
    )


def test_match_lines_pairs_exact_amount_and_supplier():
    lines = [
        mk("Leverancier A", credit="50.00", date="2025-01-05"),
        mk("Leverancier A", debit="50.00", date="2025-01-06"),
    ]
    result = match_lines(lines)
    assert len(result.matched) == 1
    assert result.unmatched_credits == []
    assert result.unmatched_debits == []


def test_match_lines_allows_betalingsverschil_within_tolerance():
    lines = [
        mk("KPN B.V.", credit="30.00"),
        mk("KPN B.V. Mobiel januari", debit="30.50"),
    ]
    result = match_lines(lines)
    assert len(result.matched) == 1
    assert result.matched[0].difference == Decimal("-0.50")
    assert result.unmatched_debits == []


def test_match_lines_matches_multiple_payments_to_one_invoice():
    lines = [
        mk("Leverancier C", credit="80.00"),
        mk("Leverancier C", debit="60.00"),
        mk("Leverancier C", debit="20.00"),
    ]
    result = match_lines(lines)
    assert len(result.matched) == 1
    assert len(result.matched[0].closings) == 2
    assert result.unmatched_debits == []


def test_match_lines_handles_negative_correction():
    lines = [
        mk("Leverancier A", credit="100.00"),
        mk("Leverancier A", credit="-100.00"),
    ]
    result = match_lines(lines)
    assert len(result.matched) == 1
    assert result.unmatched_credits == []
    assert result.unmatched_debits == []


def test_match_lines_excludes_beginbalans():
    lines = [mk("Beginbalans", credit="100.00")]
    result = match_lines(lines)
    assert len(result.opening_balance) == 1
    assert result.unmatched_credits == []


def test_match_lines_reports_both_unmatched_directions():
    lines = [
        mk("Leverancier D", credit="999.00", date="2025-02-01"),
        mk("Leverancier E", debit="555.00", date="2025-02-02"),
    ]
    result = match_lines(lines)
    assert [line.description for line in result.unmatched_credits] == ["Leverancier D"]
    assert [line.description for line in result.unmatched_debits] == ["Leverancier E"]
    assert result.unmatched_credit_total == Decimal("999.00")
    assert result.unmatched_debit_total == Decimal("555.00")


def test_write_lines_csv_uses_requested_columns(tmp_path):
    target = tmp_path / "lines.csv"
    lines = [
        mk("Leverancier A", credit="50.00", date="2025-01-06"),
        mk("Leverancier A", debit="50.00", date="2025-01-05"),
    ]
    write_lines_csv(lines, target)
    rows = list(csv.reader(target.open(newline="", encoding="utf-8")))
    assert rows[0] == ["effectiveDate", "debitAmount", "creditAmount", "description"]
    assert rows[1] == ["2025-01-05", "50.00", "", "Leverancier A"]
    assert rows[2] == ["2025-01-06", "", "50.00", "Leverancier A"]


def test_write_unmatched_csv_classifies_duplicate_payment(tmp_path):
    target = tmp_path / "unmatched.csv"
    lines = [mk("[Dubbel betaald] Leverancier A", debit="50.00")]
    write_unmatched_csv(match_lines(lines), target)
    rows = list(csv.reader(target.open(newline="", encoding="utf-8")))
    assert rows[0] == [
        "richting",
        "effectiveDate",
        "debitAmount",
        "creditAmount",
        "description",
        "transactionID",
        "mogelijke_oorzaak",
    ]
    assert rows[1][0] == "DEBET zonder credit (betaling zonder factuur)"
    assert rows[1][2] == "50.00"
    assert rows[1][3] == ""
    assert rows[1][6] == "dubbele betaling"


def test_analyze_auditfile_writes_both_files(sample_auditfile, tmp_path):
    report = analyze_auditfile(sample_auditfile, "1500", tmp_path / "out")
    assert report.line_count == 4
    assert report.credit_total == Decimal("162.34")
    assert report.debit_total == Decimal("50.00")
    assert report.movement == Decimal("112.34")
    assert report.matched_count == 1
    assert len(report.unmatched_credits) == 1
    assert report.lines_path.exists()
    assert report.unmatched_path.exists()


def test_cli_auditfile_account_report(sample_auditfile, tmp_path):
    out = tmp_path / "cli-out"
    result = runner.invoke(
        app,
        ["auditfile-account-report", str(sample_auditfile), "-a", "1500", "-o", str(out)],
    )
    assert result.exit_code == 0
    assert (out / "account-1500-lines.csv").exists()
    assert (out / "account-1500-unmatched.csv").exists()


def test_cli_auditfile_account_report_missing_account(sample_auditfile, tmp_path):
    result = runner.invoke(
        app,
        ["auditfile-account-report", str(sample_auditfile), "-a", "9999", "-o", str(tmp_path)],
    )
    assert result.exit_code == 1


def _line_with_document(rid, account, date, desc, document, debit=None, credit=None):
    body = (
        f"<line><recordID>{rid}</recordID><accountID>{account}</accountID>"
        f"<documentID>{document}</documentID>"
        f"<effectiveDate>{date}</effectiveDate><description>{desc}</description>"
    )
    if debit is not None:
        body += f"<debitAmount>{debit}</debitAmount>"
    if credit is not None:
        body += f"<creditAmount>{credit}</creditAmount>"
    return body + "</line>"


@pytest.fixture
def document_auditfile(tmp_path):
    transactions = [
        _txn(
            1,
            "2025-02-01",
            [_line_with_document(1, "1500", "2025-02-01", "Leverancier A", " F 12 345 ", credit="50.00")],
        ),
        _txn(
            2,
            "2025-02-05",
            [_line_with_document(2, "1500", "2025-02-05", "Leverancier A", "", debit="50.00")],
        ),
        _txn(
            3,
            "2025-02-06",
            [_line_with_document(3, "4200", "2025-02-06", "Andere rekening", "X1", debit="10.00")],
        ),
    ]
    return _write_auditfile(tmp_path / "audit-document.xaf", transactions)


def test_parse_auditfile_captures_document_id(document_auditfile):
    lines = {line.record_id: line for line in parse_auditfile(document_auditfile, "1500")}
    assert lines["1"].document_id == "F 12 345"
    assert lines["2"].document_id == ""


def test_write_account_csv_uses_requested_columns(document_auditfile, tmp_path):
    target = tmp_path / "account.csv"
    lines = parse_auditfile(document_auditfile, "1500")
    write_account_csv(lines, target)
    rows = list(csv.reader(target.open(newline="", encoding="utf-8")))
    assert rows[0] == ["date", "description", "debit", "credit", "factuur"]
    assert rows[1] == ["2025-02-01", "Leverancier A", "", "50.00", "F12345"]
    assert rows[2] == ["2025-02-05", "Leverancier A", "50.00", "", ""]


def test_cli_account_to_csv_writes_file(document_auditfile, tmp_path):
    target = tmp_path / "cli-account.csv"
    result = runner.invoke(
        app,
        ["account-to-csv", str(document_auditfile), "1500", "-o", str(target)],
    )
    assert result.exit_code == 0
    rows = list(csv.reader(target.open(newline="", encoding="utf-8")))
    assert rows[0] == ["date", "description", "debit", "credit", "factuur"]
    assert len(rows) == 3


def test_cli_account_to_csv_empty_account(document_auditfile, tmp_path):
    result = runner.invoke(
        app,
        ["account-to-csv", str(document_auditfile), "9999", "-o", str(tmp_path / "none.csv")],
    )
    assert result.exit_code == 1

