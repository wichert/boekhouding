"""Tests for CAMT.053 conversion and its CLI command."""

from __future__ import annotations

import csv

from typer.testing import CliRunner

from boekhouding.camt053 import COLUMNS, parse_camt053, write_csv
from boekhouding.cli import app

CAMT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt><Stmt>
    <Id>STMT1</Id>
    <Acct><Id><IBAN>NL00TEST0123456789</IBAN></Id><Ccy>EUR</Ccy><Nm>Testrekening</Nm></Acct>
    <Ntry>
      <NtryRef>1</NtryRef><Amt Ccy="EUR">264.81</Amt><CdtDbtInd>CRDT</CdtDbtInd>
      <BookgDt><Dt>2026-01-01</Dt></BookgDt><ValDt><Dt>2026-01-02</Dt></ValDt>
      <BkTxCd><Prtry><Cd>1025</Cd></Prtry></BkTxCd>
      <NtryDtls><TxDtls><RltdPties><Dbtr><Nm>Jan Jansen</Nm></Dbtr></RltdPties>
        <RmtInf><Ustrd>Rente over periode</Ustrd><Ustrd>01-01-2025 t/m 31-12-2025</Ustrd></RmtInf>
      </TxDtls></NtryDtls>
    </Ntry>
    <Ntry>
      <NtryRef>2</NtryRef><Amt Ccy="EUR">50.00</Amt><CdtDbtInd>DBIT</CdtDbtInd>
      <BookgDt><Dt>2026-03-05</Dt></BookgDt><ValDt><Dt>2026-03-05</Dt></ValDt>
      <BkTxCd><Prtry><Cd>501</Cd></Prtry></BkTxCd>
      <NtryDtls><TxDtls><RltdPties><Cdtr><Nm>Leverancier BV</Nm></Cdtr>
        <CdtrAcct><Id><IBAN>NL11TEST9876543210</IBAN></Id></CdtrAcct></RltdPties>
        <RmtInf><Ustrd>Afschrijving</Ustrd></RmtInf></TxDtls></NtryDtls>
    </Ntry>
  </Stmt></BkToCstmrStmt>
</Document>
"""


def test_parse_camt053_rows(tmp_path):
    xml_path = tmp_path / "camt.xml"
    xml_path.write_text(CAMT_XML, encoding="utf-8")
    rows = parse_camt053(xml_path)

    assert len(rows) == 2
    credit, debit = rows
    assert credit["account_iban"] == "NL00TEST0123456789"
    assert credit["account_name"] == "Testrekening"
    assert credit["booking_date"] == "2026-01-01"
    assert credit["value_date"] == "2026-01-02"
    assert credit["amount"] == "264.81"
    assert credit["direction"] == "CRDT"
    assert credit["counterparty_name"] == "Jan Jansen"
    assert credit["description"] == "Rente over periode 01-01-2025 t/m 31-12-2025"
    assert debit["direction"] == "DBIT"
    assert debit["counterparty_name"] == "Leverancier BV"
    assert debit["counterparty_iban"] == "NL11TEST9876543210"


def test_camt053_cli_writes_csv(tmp_path):
    xml_path = tmp_path / "camt.xml"
    xml_path.write_text(CAMT_XML, encoding="utf-8")
    out_path = tmp_path / "out" / "camt.csv"

    result = CliRunner().invoke(app, ["camt053-to-csv", str(xml_path), "-o", str(out_path)])

    assert result.exit_code == 0, result.output
    with out_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert reader.fieldnames == COLUMNS
    assert [row["entry_ref"] for row in rows] == ["1", "2"]


def test_write_csv_creates_parent(tmp_path):
    target = write_csv([], tmp_path / "new" / "camt.csv")
    assert target.exists()
