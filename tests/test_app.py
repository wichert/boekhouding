import os
import re

from fastapi.testclient import TestClient

from boekhouding.app import create_app


def make_client(*, audit_file=None):
    return TestClient(create_app(audit_file=audit_file))


def assert_app_shell(response):
    assert response.status_code == 200
    assert '<div id="app"></div>' in response.text


def write_audit_fixture(tmp_path):
    audit_file = tmp_path / "auditlog-2026.xaf"
    audit_file.write_text(
        """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<auditfile>
  <header><companyName>Test Vereniging</companyName><fiscalYear>2026</fiscalYear><startDate>2026-01-01</startDate><endDate>2026-12-31</endDate></header>
  <customersSuppliers>
    <customerSupplier><custSupID>c1</custSupID><type>Cred</type><companyName>Acme Supplies</companyName></customerSupplier>
  </customersSuppliers>
  <generalLedger>
    <ledgerAccount><accountID>1500</accountID><accountDesc>Crediteuren</accountDesc><accountType>Blns</accountType><leadCode>1500</leadCode></ledgerAccount>
    <ledgerAccount><accountID>4340</accountID><accountDesc>Kantoor</accountDesc><accountType>WenV</accountType><leadCode>4340</leadCode></ledgerAccount>
  </generalLedger>
  <transactions>
    <numberEntries>2</numberEntries><totalDebit>12.34</totalDebit><totalCredit>12.34</totalCredit>
    <journal>
      <journalID>1500</journalID><description>Crediteuren</description>
      <transaction>
        <transactionID>tx1</transactionID><period>1</period><transactionDate>2026-01-02</transactionDate>
        <line><recordID>r1</recordID><accountID>1500</accountID><custSupID>c1</custSupID><documentID>doc1</documentID><effectiveDate>2026-01-02</effectiveDate><description>Invoice Acme</description><creditAmount>12.34</creditAmount><costDesc/><vat><vatCode>0</vatCode><vatPercentage>0</vatPercentage></vat></line>
        <line><recordID>r2</recordID><accountID>4340</accountID><custSupID>c1</custSupID><documentID>doc1</documentID><effectiveDate>2026-01-02</effectiveDate><description>Invoice Acme</description><debitAmount>7.00</debitAmount><costDesc/><vat><vatCode>0</vatCode><vatPercentage>0</vatPercentage></vat></line>
        <line><recordID>r3</recordID><accountID>4340</accountID><custSupID>c1</custSupID><documentID>doc1</documentID><effectiveDate>2026-01-02</effectiveDate><description>Invoice Acme extra</description><debitAmount>5.34</debitAmount><costDesc/><vat><vatCode>0</vatCode><vatPercentage>0</vatPercentage></vat></line>
      </transaction>
    </journal>
  </transactions>
</auditfile>
""",
        encoding="utf-8",
    )
    return audit_file


def test_frontpage_and_health():
    client = make_client()
    assert_app_shell(client.get("/"))
    assert client.get("/health").json() == {"status": "ok"}


def test_transactions_page_serves_unified_frontend():
    client = make_client()

    response = client.get("/transactions")
    balance_response = client.get("/transactions/balance")
    accounts_response = client.get("/transactions/accounts")
    bookings_response = client.get("/transactions/bookings")
    account_response = client.get("/transactions/accounts/1500")

    assert_app_shell(response)
    assert_app_shell(balance_response)
    assert_app_shell(accounts_response)
    assert_app_shell(bookings_response)
    assert_app_shell(account_response)


def test_transactions_balance_page_with_year_serves_unified_frontend():
    client = make_client()

    response = client.get("/transactions/balance?year=2025")
    bookings_response = client.get("/transactions/bookings?year=2025")

    assert_app_shell(response)
    assert_app_shell(bookings_response)


def test_transactions_balance_static_bundle_includes_print_styles():
    client = make_client()

    response = client.get("/transactions/balance?year=2025")
    assert_app_shell(response)

    css_match = re.search(r'href="(/static/app/assets/[^"]+\.css)"', response.text)
    js_match = re.search(r'src="(/static/app/assets/[^"]+\.js)"', response.text)
    assert css_match is not None
    assert js_match is not None

    css_response = client.get(css_match.group(1))
    js_response = client.get(js_match.group(1))
    assert css_response.status_code == 200
    assert js_response.status_code == 200

    css_text = css_response.text
    assert "@media print" in css_text
    assert ".tx-view-controls" in css_text
    assert ".audit-file-filter" in css_text
    assert ".balance-card-header-summary" in css_text
    assert ".balance-section-count" in css_text
    assert ".balance-section-totals" in css_text
    assert ".balance-equilibrium-badge" in css_text
    assert ".balance-footer-count" in css_text
    assert ".balance-columns" in css_text
    assert ".balance-col-code" in css_text
    assert ".balance-col-amount" in css_text
    assert "break-inside:avoid" in css_text or "break-inside: avoid" in css_text
    assert "break-before:page!important" in css_text or "break-before: page !important" in css_text
    assert "margin-top:0!important" in css_text or "margin-top: 0 !important" in css_text
    assert (
        '.balance-section[data-section=wenv] .balance-card{height:auto!important}' in css_text
        or '.balance-section[data-section="wenv"] .balance-card' in css_text
    )
    assert "2.75rem!important" in css_text or "2.75rem !important" in css_text
    assert "5.75rem!important" in css_text or "5.75rem !important" in css_text

    js_text = js_response.text
    assert "balance-col-code" in js_text
    assert "balance-col-amount" in js_text
    assert "balance-card-header-summary" in js_text
    assert "balance-section-count" in js_text
    assert "balance-section-totals" in js_text
    assert "balance-equilibrium-badge" in js_text
    assert "balance-footer-count" in js_text
    assert "d-print-none" in js_text


def test_audit_account_summaries_separate_opening_balance_and_compute_running_balance(tmp_path):
    audit_file = tmp_path / "auditlog-2026.xaf"
    audit_file.write_bytes(
        """<?xml version="1.0" encoding="ISO-8859-1"?>
<auditfile>
  <header><companyName>Test Vereniging €</companyName><fiscalYear>2026</fiscalYear></header>
  <generalLedger>
    <ledgerAccount><accountID>1020</accountID><accountDesc>Bank</accountDesc><accountType>Blns</accountType><leadCode>1020</leadCode></ledgerAccount>
    <ledgerAccount><accountID>900</accountID><accountDesc>Kas</accountDesc><accountType>Blns</accountType><leadCode>900</leadCode></ledgerAccount>
    <ledgerAccount><accountID>9999</accountID><accountDesc>Ongebruikt</accountDesc><accountType>WenV</accountType><leadCode>9999</leadCode></ledgerAccount>
  </generalLedger>
  <transactions>
    <numberEntries>3</numberEntries><totalDebit>150.00</totalDebit><totalCredit>50.00</totalCredit>
    <journal>
      <journalID>2100</journalID><description>Beginbalans</description>
      <transaction>
        <transactionID>1</transactionID><period>0</period><transactionDate>2026-01-01</transactionDate>
        <line><recordID>r0</recordID><accountID>1020</accountID><effectiveDate>2026-01-01</effectiveDate><description>Beginbalans</description><debitAmount>1000.00</debitAmount></line>
      </transaction>
    </journal>
    <journal>
      <journalID>1020</journalID><description>Bank</description>
      <transaction>
        <transactionID>3</transactionID><period>1</period><transactionDate>2026-01-10</transactionDate>
        <line><recordID>r2</recordID><accountID>1020</accountID><effectiveDate>2026-01-10</effectiveDate><description>Uitgave €50</description><creditAmount>50.00</creditAmount></line>
      </transaction>
      <transaction>
        <transactionID>2</transactionID><period>1</period><transactionDate>2026-01-05</transactionDate>
        <line><recordID>r1</recordID><accountID>1020</accountID><effectiveDate>2026-01-05</effectiveDate><description>Ontvangst</description><debitAmount>125.50</debitAmount></line>
        <line><recordID>r3</recordID><accountID>900</accountID><effectiveDate>2026-01-05</effectiveDate><description>Storting vanuit kas</description><creditAmount>125.50</creditAmount></line>
      </transaction>
    </journal>
  </transactions>
</auditfile>
""".encode("utf-8")
    )
    client = make_client(audit_file=audit_file)

    response = client.get("/api/audit/transactions")

    assert response.status_code == 200
    data = response.json()
    assert data["metadata"]["header"]["companyName"] == "Test Vereniging €"
    assert [tx["isOpeningBalance"] for tx in data["transactions"]] == [True, False, False]
    # Numeric sorting: 900 comes before 1020, and inactive 9999 is excluded from active accounts
    assert [acc["id"] for acc in data["accounts"]] == ["900", "1020"]
    assert [acc["id"] for acc in data["allAccounts"]] == ["900", "1020", "9999"]

    bank = next(acc for acc in data["accounts"] if acc["id"] == "1020")
    assert bank["openingDebit"] == 1000.0
    assert bank["openingCredit"] == 0.0
    assert bank["openingBalance"] == 1000.0
    assert bank["totalDebit"] == 125.5
    assert bank["totalCredit"] == 50.0
    assert bank["currentBalance"] == 1075.5
    assert bank["transactionCount"] == 2
    assert bank["isActive"] is True

    # Lines are sorted chronologically (2026-01-05 before 2026-01-10) with running cumulativeBalance
    assert [line["effectiveDate"] for line in bank["lines"]] == ["2026-01-05", "2026-01-10"]
    assert [line["debitAmount"] for line in bank["lines"]] == [125.5, 0.0]
    assert [line["creditAmount"] for line in bank["lines"]] == [0.0, 50.0]
    assert [line["cumulativeBalance"] for line in bank["lines"]] == [1125.5, 1075.5]
    assert bank["lines"][1]["description"] == "Uitgave €50"


def test_audit_account_lines_sort_same_day_numeric_transaction_ids_numerically(tmp_path):
    audit_file = tmp_path / "auditlog-2026.xaf"
    audit_file.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<auditfile>
  <header><companyName>Test Vereniging</companyName><fiscalYear>2026</fiscalYear></header>
  <generalLedger>
    <ledgerAccount><accountID>1020</accountID><accountDesc>Bank</accountDesc><accountType>Blns</accountType><leadCode>1020</leadCode></ledgerAccount>
  </generalLedger>
  <transactions>
    <numberEntries>3</numberEntries><totalDebit>150.00</totalDebit><totalCredit>30.00</totalCredit>
    <journal>
      <journalID>2100</journalID><description>Beginbalans</description>
      <transaction>
        <transactionID>1</transactionID><period>0</period><transactionDate>2026-01-01</transactionDate>
        <line><recordID>1</recordID><accountID>1020</accountID><effectiveDate>2026-01-01</effectiveDate><description>Beginbalans</description><debitAmount>100.00</debitAmount></line>
      </transaction>
    </journal>
    <journal>
      <journalID>1020</journalID><description>Bank</description>
      <transaction>
        <transactionID>10</transactionID><period>1</period><transactionDate>2026-01-05</transactionDate>
        <line><recordID>10</recordID><accountID>1020</accountID><effectiveDate>2026-01-05</effectiveDate><description>Tweede mutatie op dezelfde dag</description><creditAmount>30.00</creditAmount></line>
      </transaction>
      <transaction>
        <transactionID>2</transactionID><period>1</period><transactionDate>2026-01-05</transactionDate>
        <line><recordID>2</recordID><accountID>1020</accountID><effectiveDate>2026-01-05</effectiveDate><description>Eerste mutatie op dezelfde dag</description><debitAmount>50.00</debitAmount></line>
      </transaction>
    </journal>
  </transactions>
</auditfile>
""",
        encoding="utf-8",
    )
    client = make_client(audit_file=audit_file)

    response = client.get("/api/audit/transactions")

    assert response.status_code == 200
    data = response.json()
    assert [tx["transactionID"] for tx in data["transactions"]] == ["1", "2", "10"]
    bank = next(acc for acc in data["accounts"] if acc["id"] == "1020")
    assert [line["transactionID"] for line in bank["lines"]] == ["2", "10"]
    assert [line["cumulativeBalance"] for line in bank["lines"]] == [150.0, 120.0]


def test_audit_transactions_api_parses_configured_file(tmp_path):
    audit_file = write_audit_fixture(tmp_path)
    client = make_client(audit_file=audit_file)

    response = client.get("/api/audit/transactions")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["etag"]
    data = response.json()
    assert data["metadata"]["files"][0]["header"]["companyName"] == "Test Vereniging"
    assert data["metadata"]["years"] == ["2026"]
    assert data["yearOptions"][0]["year"] == "2026"
    assert data["supplierOptions"] == [{"id": "c1", "label": "Acme Supplies", "type": "Cred"}]
    assert data["journalOptions"][0]["label"] == "Crediteuren"
    transaction = data["transactions"][0]
    assert transaction["year"] == "2026"
    assert transaction["transactionKey"] == "2026:tx1"
    assert transaction["journalID"] == "1500"
    assert transaction["supplierNames"] == ["Acme Supplies"]
    assert transaction["debitTotal"] == 12.34
    assert transaction["creditTotal"] == 12.34
    assert transaction["transactionAmount"] == 12.34
    assert transaction["isOpeningBalance"] is False
    assert transaction["distinctDescriptions"] == ["Invoice Acme", "Invoice Acme extra"]
    assert transaction["lines"][0]["accountDescription"] == "Crediteuren"
    assert "acme supplies" in transaction["textSearch"]


def test_audit_transactions_api_skips_etag_when_stat_fails(tmp_path, monkeypatch):
    from boekhouding.audit_routes import Path as AuditPath

    audit_file = write_audit_fixture(tmp_path)
    client = make_client(audit_file=audit_file)
    original_stat = AuditPath.stat

    def failing_stat(self, *args, **kwargs):
        if self.name == "auditlog-2026.xaf":
            raise OSError("simulated stat failure")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(AuditPath, "is_dir", lambda self: False)
    monkeypatch.setattr(AuditPath, "exists", lambda self: True)
    monkeypatch.setattr(AuditPath, "stat", failing_stat)

    response = client.get("/api/audit/transactions", headers={"if-none-match": '"stale"'})

    monkeypatch.setattr(AuditPath, "stat", original_stat)
    # No usable ETag, so the client must not get a 304; the file is also
    # unreadable, so the request fails as a 404 rather than serving stale data.
    assert response.status_code == 404
    assert "etag" not in response.headers


def test_audit_years_api_skips_etag_when_stat_fails(tmp_path, monkeypatch):
    from boekhouding.audit_routes import Path as AuditPath

    audit_file = write_audit_fixture(tmp_path)
    client = make_client(audit_file=audit_file)
    original_stat = AuditPath.stat

    def failing_stat(self, *args, **kwargs):
        if self.name == "auditlog-2026.xaf":
            raise OSError("simulated stat failure")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(AuditPath, "is_dir", lambda self: False)
    monkeypatch.setattr(AuditPath, "exists", lambda self: True)
    monkeypatch.setattr(AuditPath, "stat", failing_stat)

    response = client.get("/api/audit/years", headers={"if-none-match": '"stale"'})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "etag" not in response.headers
    assert response.json()["years"]


def test_audit_transactions_api_serves_304_for_matching_etag(tmp_path):
    audit_file = write_audit_fixture(tmp_path)
    client = make_client(audit_file=audit_file)

    first = client.get("/api/audit/transactions")
    assert first.status_code == 200
    etag = first.headers["etag"]

    revalidated = client.get("/api/audit/transactions", headers={"if-none-match": etag})
    assert revalidated.status_code == 304
    assert revalidated.headers["cache-control"] == "no-cache"
    assert revalidated.headers["etag"] == etag
    assert revalidated.content == b""

    year_response = client.get("/api/audit/years")
    assert year_response.status_code == 200
    years_etag = year_response.headers["etag"]
    revalidated_years = client.get("/api/audit/years", headers={"if-none-match": years_etag})
    assert revalidated_years.status_code == 304
    assert revalidated_years.headers["etag"] == years_etag


def test_audit_transactions_api_changes_etag_when_audit_file_is_updated(tmp_path):
    audit_file = write_audit_fixture(tmp_path)
    client = make_client(audit_file=audit_file)

    first = client.get("/api/audit/transactions")
    assert first.status_code == 200
    old_etag = first.headers["etag"]
    assert first.json()["transactions"][0]["transactionKey"] == "2026:tx1"

    updated = audit_file.read_text(encoding="utf-8").replace("tx1", "tx9")
    audit_file.write_text(updated, encoding="utf-8")
    # force a distinct mtime so the stat-based etag cannot collide
    os.utime(audit_file, ns=(audit_file.stat().st_atime_ns + 1_000_000_000, audit_file.stat().st_mtime_ns + 1_000_000_000))

    second = client.get("/api/audit/transactions")
    assert second.status_code == 200
    assert second.headers["etag"] != old_etag
    assert second.json()["transactions"][0]["transactionKey"] == "2026:tx9"


def test_audit_years_etag_reflects_new_and_deleted_audit_files(tmp_path):
    first = write_audit_fixture(tmp_path)
    client = make_client(audit_file=tmp_path)

    initial = client.get("/api/audit/years")
    initial_etag = initial.headers["etag"]
    assert [option["year"] for option in initial.json()["years"]] == ["2026"]

    second = tmp_path / "auditlog-2024.xaf"
    second.write_text(first.read_text(encoding="utf-8").replace("2026", "2024").replace("tx1", "tx2"), encoding="utf-8")
    added = client.get("/api/audit/years")
    assert added.status_code == 200
    assert added.headers["etag"] != initial_etag
    assert [option["year"] for option in added.json()["years"]] == ["2024", "2026"]

    second.unlink()
    removed = client.get("/api/audit/years")
    assert removed.status_code == 200
    assert removed.headers["etag"] != added.headers["etag"]
    assert removed.headers["etag"] == initial_etag
    assert [option["year"] for option in removed.json()["years"]] == ["2026"]


def test_audit_years_api_lists_files_in_configured_directory(tmp_path):
    first = write_audit_fixture(tmp_path)
    second = tmp_path / "auditlog-2024.xaf"
    second.write_text(first.read_text(encoding="utf-8").replace("2026", "2024").replace("tx1", "tx2"), encoding="utf-8")
    client = make_client(audit_file=tmp_path)

    response = client.get("/api/audit/years")

    assert response.status_code == 200
    data = response.json()
    assert data["defaultYear"] == "2026"
    assert [option["year"] for option in data["years"]] == ["2024", "2026"]
    assert [option["fileName"] for option in data["years"]] == ["auditlog-2024.xaf", "auditlog-2026.xaf"]


def test_audit_transactions_api_loads_only_requested_year(tmp_path):
    first = write_audit_fixture(tmp_path)
    second = tmp_path / "auditlog-2024.xaf"
    second.write_text(first.read_text(encoding="utf-8").replace("2026", "2024").replace("tx1", "tx2"), encoding="utf-8")
    client = make_client(audit_file=tmp_path)

    response = client.get("/api/audit/transactions/2024")

    assert response.status_code == 200
    data = response.json()
    assert data["metadata"]["years"] == ["2024"]
    assert [transaction["year"] for transaction in data["transactions"]] == ["2024"]
    assert [transaction["transactionKey"] for transaction in data["transactions"]] == ["2024:tx2"]


def test_audit_transactions_api_reports_missing_file(tmp_path):
    client = make_client(audit_file=tmp_path / "missing.xaf")

    response = client.get("/api/audit/transactions")

    assert response.status_code == 404
    assert "Audit file not found" in response.text


