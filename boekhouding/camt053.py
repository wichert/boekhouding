"""Minimal CAMT.053 (ISO 20022 bank statement) to CSV conversion."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree

NS = {"c": "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"}

COLUMNS = [
    "account_iban",
    "account_name",
    "entry_ref",
    "booking_date",
    "value_date",
    "amount",
    "direction",
    "counterparty_name",
    "counterparty_iban",
    "counterparty_account",
    "transaction_code",
    "description",
]


def _text(node: ElementTree.Element | None, path: str) -> str:
    """Geef de tekst van ``path`` onder ``node`` terug, of een lege string."""
    if node is None:
        return ""
    found = node.find(path, NS)
    return (found.text or "").strip() if found is not None else ""


def parse_camt053(path: Path | str) -> list[dict[str, str]]:
    """Zet een CAMT.053-bestand om naar een lijst CSV-rijen (dicts)."""
    root = ElementTree.parse(path).getroot()
    rows: list[dict[str, str]] = []
    for stmt in root.findall(".//c:Stmt", NS):
        account_iban = _text(stmt, "c:Acct/c:Id/c:IBAN")
        account_name = _text(stmt, "c:Acct/c:Nm")
        for entry in stmt.findall("c:Ntry", NS):
            tx = entry.find("c:NtryDtls/c:TxDtls", NS)
            parties = tx.find("c:RltdPties", NS) if tx is not None else None
            # Bij een creditboeking is de tegenpartij de debiteur, anders de crediteur.
            debit_side = _text(entry, "c:CdtDbtInd") == "DBIT"
            name = _text(parties, "c:Cdtr/c:Nm" if debit_side else "c:Dbtr/c:Nm")
            iban = _text(
                parties, "c:CdtrAcct/c:Id/c:IBAN" if debit_side else "c:DbtrAcct/c:Id/c:IBAN"
            )
            other = _text(
                parties,
                "c:CdtrAcct/c:Id/c:Othr/c:Id" if debit_side else "c:DbtrAcct/c:Id/c:Othr/c:Id",
            )
            description = " ".join(
                (u.text or "").strip()
                for u in (tx.findall("c:RmtInf/c:Ustrd", NS) if tx is not None else [])
                if (u.text or "").strip()
            )
            rows.append(
                {
                    "account_iban": account_iban,
                    "account_name": account_name,
                    "entry_ref": _text(entry, "c:NtryRef"),
                    "booking_date": _text(entry, "c:BookgDt/c:Dt"),
                    "value_date": _text(entry, "c:ValDt/c:Dt"),
                    "amount": _text(entry, "c:Amt"),
                    "direction": _text(entry, "c:CdtDbtInd"),
                    "counterparty_name": name,
                    "counterparty_iban": iban,
                    "counterparty_account": other,
                    "transaction_code": _text(entry, "c:BkTxCd/c:Prtry/c:Cd"),
                    "description": description,
                }
            )
    rows.sort(key=lambda r: (r["booking_date"], r["account_iban"], r["entry_ref"]))
    return rows


def write_csv(rows: Iterable[dict[str, str]], path: Path | str) -> Path:
    """Schrijf de rijen als UTF-8 CSV (met header) naar ``path``."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return target
