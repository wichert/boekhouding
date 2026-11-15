"""Parser for Dutch XML audit files used by the transaction explorer."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


from boekhouding.auditfile_report import load_auditfile_text


def clean_text(value: str | None) -> str:
    """Return stripped XML text, treating missing values as empty strings."""

    return (value or "").strip()


def child_text(element: ET.Element | None, name: str) -> str:
    """Return stripped text for a direct child element."""

    if element is None:
        return ""
    child = element.find(name)
    return clean_text(child.text if child is not None else None)


def amount_value(value: str) -> float:
    """Convert an audit amount to a JSON number."""

    if not value:
        return 0.0
    try:
        return float(Decimal(value))
    except (InvalidOperation, ValueError):
        return 0.0


def year_from_path(path: str | Path) -> str:
    """Return a year found in an audit filename, if present."""

    match = re.search(r"auditlog-(\d{4})\.xaf$", Path(path).name)
    return match.group(1) if match else ""


def parse_address(element: ET.Element) -> dict[str, str]:
    """Parse a streetAddress-like node."""

    return {
        "address": child_text(element, "address"),
        "postalCode": child_text(element, "postalCode"),
        "city": child_text(element, "city"),
        "country": child_text(element, "country"),
    }


def parse_suppliers(root: ET.Element) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    suppliers_by_id: dict[str, dict[str, Any]] = {}
    for supplier in root.findall("./customersSuppliers/customerSupplier"):
        supplier_id = child_text(supplier, "custSupID")
        if not supplier_id:
            continue
        address = supplier.find("streetAddress")
        parsed = {
            "id": supplier_id,
            "type": child_text(supplier, "type"),
            "companyName": child_text(supplier, "companyName"),
            "address": parse_address(address) if address is not None else {},
        }
        suppliers_by_id[supplier_id] = parsed
    supplier_options = sorted(
        (
            {"id": sid, "label": supplier.get("companyName") or sid, "type": supplier.get("type", "")}
            for sid, supplier in suppliers_by_id.items()
        ),
        key=lambda item: str(item["label"]).lower(),
    )
    return suppliers_by_id, supplier_options


def account_sort_key(account_id: str) -> tuple[int, int, str]:
    """Sort numeric account IDs numerically before non-numeric IDs."""

    aid = str(account_id).strip()
    return (0, int(aid), aid) if aid.isdigit() else (1, 0, aid)


def transaction_sort_key(tx: dict[str, Any]) -> tuple[str, tuple[int, int, str]]:
    """Sort transactions chronologically by date, then numerically by transactionID."""

    tx_date = (
        str(tx.get("transactionDate") or "")
        or str(tx.get("minEffectiveDate") or "")
        or str(tx.get("maxEffectiveDate") or "")
    )
    return (tx_date, account_sort_key(str(tx.get("transactionID") or "")))


def is_opening_line(line: dict[str, Any]) -> bool:
    """Return True when a transaction line represents an opening balance (Beginbalans)."""

    description = str(line.get("description") or "").lower()
    return "beginbalans" in description


def parse_accounts(root: ET.Element) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    accounts_by_id: dict[str, dict[str, Any]] = {}
    for account in root.findall("./generalLedger/ledgerAccount"):
        account_id = child_text(account, "accountID")
        if not account_id:
            continue
        parsed = {
            "id": account_id,
            "description": child_text(account, "accountDesc"),
            "type": child_text(account, "accountType"),
            "leadCode": child_text(account, "leadCode"),
        }
        accounts_by_id[account_id] = parsed
    account_options = sorted(
        (
            {"id": aid, "label": account.get("description") or aid, "type": account.get("type", "")}
            for aid, account in accounts_by_id.items()
        ),
        key=lambda item: account_sort_key(str(item["id"])),
    )
    return accounts_by_id, account_options


def build_account_summaries(
    accounts_by_id: dict[str, dict[str, Any]],
    flat_transactions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate opening balance, totals, and chronological lines with running balance per account."""

    all_accounts_meta: dict[str, dict[str, Any]] = {
        aid: {
            "id": aid,
            "description": account.get("description", ""),
            "type": account.get("type", ""),
            "leadCode": account.get("leadCode", ""),
        }
        for aid, account in accounts_by_id.items()
    }

    opening_by_account: dict[str, list[dict[str, Any]]] = defaultdict(list)
    regular_by_account: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)

    for tx in flat_transactions:
        for line in tx.get("lines") or []:
            account_id = str(line.get("accountID") or "").strip()
            if not account_id:
                continue
            if account_id not in all_accounts_meta:
                all_accounts_meta[account_id] = {
                    "id": account_id,
                    "description": str(line.get("accountDescription") or ""),
                    "type": "",
                    "leadCode": "",
                }
            if is_opening_line(line):
                opening_by_account[account_id].append(line)
            else:
                regular_by_account[account_id].append((tx, line))

    summaries: list[dict[str, Any]] = []
    for account_id in sorted(all_accounts_meta.keys(), key=account_sort_key):
        meta = all_accounts_meta[account_id]
        opening_lines = opening_by_account.get(account_id, [])
        regular_pairs = regular_by_account.get(account_id, [])

        opening_debit = round(sum(float(line.get("debitAmount") or 0.0) for line in opening_lines), 2)
        opening_credit = round(sum(float(line.get("creditAmount") or 0.0) for line in opening_lines), 2)
        opening_balance = round(opening_debit - opening_credit, 2)

        sorted_pairs = sorted(
            regular_pairs,
            key=lambda pair: (
                pair[1].get("effectiveDate") or pair[0].get("transactionDate") or "",
                account_sort_key(str(pair[0].get("transactionID") or "")),
                account_sort_key(str(pair[1].get("recordID") or "")),
            ),
        )

        total_debit = round(sum(float(line.get("debitAmount") or 0.0) for _, line in sorted_pairs), 2)
        total_credit = round(sum(float(line.get("creditAmount") or 0.0) for _, line in sorted_pairs), 2)
        current_balance = round(opening_balance + total_debit - total_credit, 2)
        transaction_count = len(sorted_pairs)

        running = opening_balance
        account_lines: list[dict[str, Any]] = []
        for tx, line in sorted_pairs:
            debit = round(float(line.get("debitAmount") or 0.0), 2)
            credit = round(float(line.get("creditAmount") or 0.0), 2)
            running = round(running + debit - credit, 2)
            account_lines.append(
                {
                    "recordID": line.get("recordID", ""),
                    "transactionID": tx.get("transactionID", ""),
                    "transactionKey": tx.get("transactionKey", ""),
                    "transactionDate": tx.get("transactionDate", ""),
                    "effectiveDate": line.get("effectiveDate") or tx.get("transactionDate") or "",
                    "period": tx.get("period", ""),
                    "journalID": tx.get("journalID", ""),
                    "journalDescription": tx.get("journalDescription", ""),
                    "documentID": line.get("documentID", ""),
                    "custSupID": line.get("custSupID", ""),
                    "supplierName": line.get("supplierName", ""),
                    "description": line.get("description", ""),
                    "debitAmount": debit,
                    "creditAmount": credit,
                    "netAmount": round(debit - credit, 2),
                    "impactAmount": round(max(abs(debit), abs(credit)), 2),
                    "cumulativeBalance": running,
                    "vat": line.get("vat") or {"vatCode": "", "vatPercentage": ""},
                }
            )

        is_active = bool(
            opening_balance != 0
            or opening_debit != 0
            or opening_credit != 0
            or total_debit != 0
            or total_credit != 0
            or transaction_count > 0
        )

        summaries.append(
            {
                "id": account_id,
                "description": meta["description"],
                "type": meta["type"],
                "leadCode": meta["leadCode"],
                "openingDebit": opening_debit,
                "openingCredit": opening_credit,
                "openingBalance": opening_balance,
                "totalDebit": total_debit,
                "totalCredit": total_credit,
                "currentBalance": current_balance,
                "transactionCount": transaction_count,
                "isActive": is_active,
                "lines": account_lines,
            }
        )

    return summaries


def parse_vat(line: ET.Element) -> dict[str, str]:
    vat = line.find("vat")
    if vat is None:
        return {"vatCode": "", "vatPercentage": ""}
    return {"vatCode": child_text(vat, "vatCode"), "vatPercentage": child_text(vat, "vatPercentage")}


def parse_line(
    line: ET.Element,
    *,
    suppliers_by_id: dict[str, dict[str, Any]],
    accounts_by_id: dict[str, dict[str, Any]],
    year: str,
) -> dict[str, Any]:
    account_id = child_text(line, "accountID")
    supplier_id = child_text(line, "custSupID")
    debit_text = child_text(line, "debitAmount")
    credit_text = child_text(line, "creditAmount")
    account = accounts_by_id.get(account_id, {})
    supplier = suppliers_by_id.get(supplier_id, {}) if supplier_id else {}
    return {
        "year": year,
        "recordID": child_text(line, "recordID"),
        "accountID": account_id,
        "accountDescription": account.get("description", ""),
        "custSupID": supplier_id,
        "supplierName": supplier.get("companyName", ""),
        "documentID": child_text(line, "documentID"),
        "effectiveDate": child_text(line, "effectiveDate"),
        "description": child_text(line, "description"),
        "debitAmount": amount_value(debit_text),
        "creditAmount": amount_value(credit_text),
        "debitAmountRaw": debit_text,
        "creditAmountRaw": credit_text,
        "costDesc": child_text(line, "costDesc"),
        "vat": parse_vat(line),
    }


def parse_transaction(
    transaction: ET.Element,
    *,
    journal_id: str,
    journal_description: str,
    suppliers_by_id: dict[str, dict[str, Any]],
    accounts_by_id: dict[str, dict[str, Any]],
    year: str,
) -> dict[str, Any]:
    transaction_id = child_text(transaction, "transactionID")
    lines = [
        parse_line(line, suppliers_by_id=suppliers_by_id, accounts_by_id=accounts_by_id, year=year)
        for line in transaction.findall("line")
    ]
    supplier_ids = sorted({line["custSupID"] for line in lines if line.get("custSupID")})
    supplier_names = sorted({line["supplierName"] for line in lines if line.get("supplierName")})
    effective_dates = sorted({line["effectiveDate"] for line in lines if line.get("effectiveDate")})
    descriptions = [line["description"] for line in lines if line.get("description")]
    distinct_descriptions: list[str] = []
    seen_descriptions: set[str] = set()
    for raw_desc in descriptions:
        desc = raw_desc.strip()
        key = " ".join(desc.lower().split())
        if desc and key not in seen_descriptions:
            seen_descriptions.add(key)
            distinct_descriptions.append(desc)
    document_ids = list(dict.fromkeys(line["documentID"] for line in lines if line.get("documentID")))
    account_ids = list(dict.fromkeys(line["accountID"] for line in lines if line.get("accountID")))
    account_descriptions = list(
        dict.fromkeys(line["accountDescription"] for line in lines if line.get("accountDescription"))
    )
    text_search = " ".join(
        [
            transaction_id,
            journal_id,
            journal_description,
            *supplier_names,
            *supplier_ids,
            *document_ids,
            *account_ids,
            *account_descriptions,
            *distinct_descriptions,
        ]
    ).lower()
    debit_total = round(sum(float(line["debitAmount"]) for line in lines), 2)
    credit_total = round(sum(float(line["creditAmount"]) for line in lines), 2)
    transaction_amount = round(max(abs(debit_total), abs(credit_total)), 2)
    is_opening_balance = bool(any(is_opening_line(line) for line in lines))
    return {
        "year": year,
        "transactionKey": f"{year}:{transaction_id}" if year else transaction_id,
        "transactionID": transaction_id,
        "period": child_text(transaction, "period"),
        "transactionDate": child_text(transaction, "transactionDate"),
        "journalID": journal_id,
        "journalDescription": journal_description,
        "lines": lines,
        "lineCount": len(lines),
        "debitTotal": debit_total,
        "creditTotal": credit_total,
        "transactionAmount": transaction_amount,
        "isOpeningBalance": is_opening_balance,
        "supplierIDs": supplier_ids,
        "supplierNames": supplier_names,
        "minEffectiveDate": effective_dates[0] if effective_dates else "",
        "maxEffectiveDate": effective_dates[-1] if effective_dates else "",
        "descriptionSummary": distinct_descriptions[0] if distinct_descriptions else "",
        "descriptions": distinct_descriptions,
        "distinctDescriptions": distinct_descriptions,
        "textSearch": text_search,
    }


def parse_header(root: ET.Element) -> dict[str, str]:
    header = root.find("header")
    if header is None:
        return {}
    return {child.tag: clean_text(child.text) for child in header}


def parse_audit_file(path: str | Path) -> dict[str, Any]:
    """Parse one XML audit file into JSON-friendly transaction explorer data."""

    audit_path = Path(path)
    root = ET.fromstring(load_auditfile_text(audit_path))
    if root.tag != "auditfile":
        raise ValueError(f"Expected auditfile root element, got {root.tag!r}")

    header = parse_header(root)
    year = header.get("fiscalYear") or year_from_path(audit_path)
    suppliers_by_id, supplier_options = parse_suppliers(root)
    accounts_by_id, account_options = parse_accounts(root)
    transactions_node = root.find("transactions")
    metadata = {
        "filePath": str(audit_path),
        "fileName": audit_path.name,
        "year": year,
        "header": header,
        "numberEntries": child_text(transactions_node, "numberEntries"),
        "totalDebit": amount_value(child_text(transactions_node, "totalDebit")),
        "totalCredit": amount_value(child_text(transactions_node, "totalCredit")),
    }

    journals: list[dict[str, Any]] = []
    flat_transactions: list[dict[str, Any]] = []
    if transactions_node is not None:
        for journal in transactions_node.findall("journal"):
            journal_id = child_text(journal, "journalID")
            journal_description = child_text(journal, "description")
            transactions = [
                parse_transaction(
                    transaction,
                    journal_id=journal_id,
                    journal_description=journal_description,
                    suppliers_by_id=suppliers_by_id,
                    accounts_by_id=accounts_by_id,
                    year=year,
                )
                for transaction in journal.findall("transaction")
            ]
            flat_transactions.extend(transactions)
            journals.append(
                {
                    "year": year,
                    "journalID": journal_id,
                    "description": journal_description,
                    "transactionCount": len(transactions),
                    "transactions": transactions,
                }
            )

    journal_options = [
        {
            "id": journal["journalID"],
            "label": journal["description"] or journal["journalID"],
            "transactionCount": journal["transactionCount"],
        }
        for journal in journals
    ]

    flat_transactions.sort(key=transaction_sort_key)
    all_accounts = build_account_summaries(accounts_by_id, flat_transactions)
    active_accounts = [account for account in all_accounts if account["isActive"]]

    return {
        "metadata": metadata,
        "suppliersById": suppliers_by_id,
        "supplierOptions": supplier_options,
        "accountsById": accounts_by_id,
        "accountOptions": account_options,
        "accounts": active_accounts,
        "allAccounts": all_accounts,
        "journalOptions": journal_options,
        "journals": journals,
        "transactions": flat_transactions,
    }


def merge_options_by_id(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for option in options:
        option_id = str(option.get("id", ""))
        if not option_id:
            continue
        existing = merged.setdefault(option_id, {**option, "transactionCount": 0})
        existing["transactionCount"] = int(existing.get("transactionCount") or 0) + int(option.get("transactionCount") or 0)
        if not existing.get("label") and option.get("label"):
            existing["label"] = option["label"]
    return sorted(merged.values(), key=lambda item: str(item.get("label") or item.get("id", "")).lower())


def merge_dicts_by_id(parsed_files: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for parsed in parsed_files:
        for item_id, item in parsed.get(key, {}).items():
            merged.setdefault(item_id, item)
    return merged


def parse_audit_files(paths: list[str | Path]) -> dict[str, Any]:
    """Parse multiple XML audit files and return one combined explorer payload."""

    parsed_files = [parse_audit_file(path) for path in paths]
    transactions = sorted(
        (transaction for parsed in parsed_files for transaction in parsed["transactions"]),
        key=transaction_sort_key,
    )
    journals = [journal for parsed in parsed_files for journal in parsed["journals"]]
    files = [parsed["metadata"] for parsed in parsed_files]
    years = sorted({str(metadata.get("year", "")) for metadata in files if metadata.get("year")}, reverse=True)

    transactions_by_year: dict[str, int] = defaultdict(int)
    entries_by_year: dict[str, float] = defaultdict(float)
    debit_by_year: dict[str, float] = defaultdict(float)
    credit_by_year: dict[str, float] = defaultdict(float)
    for metadata in files:
        year = str(metadata.get("year") or "")
        transactions_by_year[year] += sum(1 for transaction in transactions if transaction.get("year") == year)
        entries_by_year[year] += amount_value(str(metadata.get("numberEntries") or "0"))
        debit_by_year[year] += float(metadata.get("totalDebit") or 0)
        credit_by_year[year] += float(metadata.get("totalCredit") or 0)

    year_options = [
        {
            "year": year,
            "transactionCount": transactions_by_year[year],
            "numberEntries": int(entries_by_year[year]),
            "totalDebit": round(debit_by_year[year], 2),
            "totalCredit": round(credit_by_year[year], 2),
        }
        for year in years
    ]

    suppliers_by_id = merge_dicts_by_id(parsed_files, "suppliersById")
    accounts_by_id = merge_dicts_by_id(parsed_files, "accountsById")
    supplier_options = sorted(
        (
            {"id": sid, "label": supplier.get("companyName") or sid, "type": supplier.get("type", "")}
            for sid, supplier in suppliers_by_id.items()
        ),
        key=lambda item: str(item["label"]).lower(),
    )
    account_options = sorted(
        (
            {"id": aid, "label": account.get("description") or aid, "type": account.get("type", "")}
            for aid, account in accounts_by_id.items()
        ),
        key=lambda item: account_sort_key(str(item["id"])),
    )
    all_accounts = build_account_summaries(accounts_by_id, transactions)
    active_accounts = [account for account in all_accounts if account["isActive"]]

    return {
        "metadata": {
            "files": files,
            "years": years,
            "yearOptions": year_options,
            "numberEntries": int(sum(entries_by_year.values())),
            "totalDebit": round(sum(debit_by_year.values()), 2),
            "totalCredit": round(sum(credit_by_year.values()), 2),
        },
        "suppliersById": suppliers_by_id,
        "supplierOptions": supplier_options,
        "accountsById": accounts_by_id,
        "accountOptions": account_options,
        "accounts": active_accounts,
        "allAccounts": all_accounts,
        "journalOptions": merge_options_by_id([option for parsed in parsed_files for option in parsed["journalOptions"]]),
        "yearOptions": year_options,
        "journals": journals,
        "transactions": transactions,
    }
