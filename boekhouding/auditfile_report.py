"""Analyse van XAF (XML Auditfile Financieel) grootboekmutaties.

Dit hulpmiddel leest een XAF-auditfile (zoals ``data/auditlog-2025.xaf``),
selecteert alle ``line``-records van één grootboekrekening en schrijft die
naar CSV. Vervolgens worden de boekingen op die rekening op elkaar gematcht:
elke opboeking (credit; bij crediteuren een factuur) hoort een afboeking
(debet; een betaling) te hebben, en omgekeerd.

De matching werkt op *mutatierichting* (``credit - debit``) zodat negatieve
correcties automatisch de juiste kant op vallen. Regels worden gekoppeld op
basis van leverancier (afgeleid uit de omschrijving) en bedrag, met een
tolerantie voor kleine betalingsverschillen. Meerdere betalingen op één
factuur worden als groep gekoppeld.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from itertools import combinations
from pathlib import Path
from typing import Iterable, Sequence
from xml.etree import ElementTree

__all__ = [
    "AuditLine",
    "Match",
    "MatchResult",
    "AuditfileReport",
    "AuditfileError",
    "parse_auditfile",
    "load_auditfile_text",
    "supplier_tokens",
    "match_lines",
    "write_lines_csv",
    "write_account_csv",
    "write_unmatched_csv",
    "analyze_auditfile",
]

DEFAULT_OPENING_MARKERS = ("beginbalans",)
DEFAULT_TOLERANCE_PERCENT = Decimal("3.0")
DEFAULT_MAX_TOLERANCE = Decimal("10")
MIN_TOLERANCE = Decimal("0.05")

#: Omschrijving-tokens die geen leveranciersnaam zijn (factuurnummers,
#: administratieve termen, maandnamen, enz.).
STOPWORDS = frozenset(
    """
    factuur factuurnummer factuurnr fact fakt faktuurnr fakturen
    deb debiteurnummer debiteurennummer klantnr klantnummer
    kenmerk oms res inv nummer nr bv nv cv via van de het te op aan iom om
    bon periode per reservering monbiel mobiel belastig aanslag cookie
    jaarrekening deel januari februari maart april mei juni juli augustus
    september oktober november december
    """.split()
)

_XML_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>")
_BRACKETS = re.compile(r"\[[^\]]*\]")
_DIGITS = re.compile(r"[0-9]+")
_NON_ALPHA = re.compile(r"[^a-z]+")


class AuditfileError(Exception):
    """Fout bij het lezen of verwerken van een auditfile."""


@dataclass(frozen=True)
class AuditLine:
    """Eén ``line``-record op een grootboekrekening."""

    transaction_id: str
    record_id: str
    effective_date: str
    debit: Decimal
    credit: Decimal
    description: str
    document_id: str = ""

    @property
    def movement(self) -> Decimal:
        """Mutatierichting op de rekening.

        Positief = opboeking (credit), negatief = afboeking (debet). Door
        ``credit - debit`` te gebruiken vallen negatieve boekingen
        (correcties) automatisch aan de juiste kant.
        """
        return self.credit - self.debit

    @property
    def supplier_tokens(self) -> frozenset[str]:
        """Leverancier-achtige tokens uit de omschrijving."""
        return supplier_tokens(self.description)


@dataclass(frozen=True)
class Match:
    """Een opboeking met één of meer bijbehorende afboekingen."""

    opening: AuditLine
    closings: tuple[AuditLine, ...]
    #: Netto restpost: negatief betekent dat er te veel is afgeboekt.
    difference: Decimal


@dataclass
class MatchResult:
    """Uitkomst van het matchen van alle regels op een rekening."""

    matched: list[Match] = field(default_factory=list)
    unmatched_credits: list[AuditLine] = field(default_factory=list)
    unmatched_debits: list[AuditLine] = field(default_factory=list)
    opening_balance: list[AuditLine] = field(default_factory=list)

    @property
    def unmatched_credit_total(self) -> Decimal:
        """Som van opboekingen zonder afboeking (open posten)."""
        return sum((line.movement for line in self.unmatched_credits), Decimal("0"))

    @property
    def unmatched_debit_total(self) -> Decimal:
        """Som van afboekingen zonder opboeking (losse betalingen)."""
        return sum((-line.movement for line in self.unmatched_debits), Decimal("0"))


@dataclass
class AuditfileReport:
    """Samenvatting van een accountanalyse."""

    account: str
    line_count: int
    debit_total: Decimal
    credit_total: Decimal
    matched_count: int
    matched: list[Match]
    unmatched_credits: list[AuditLine]
    unmatched_debits: list[AuditLine]
    lines_path: Path
    unmatched_path: Path

    @property
    def movement(self) -> Decimal:
        """Mutatietotaal van de rekening (credit - debit)."""
        return self.credit_total - self.debit_total

    @property
    def unmatched_credit_total(self) -> Decimal:
        return sum((line.movement for line in self.unmatched_credits), Decimal("0"))

    @property
    def unmatched_debit_total(self) -> Decimal:
        return sum((-line.movement for line in self.unmatched_debits), Decimal("0"))


def _to_decimal(value: str | None) -> Decimal:
    """Zet een (mogelijk leeg) bedragveld om naar ``Decimal``."""
    if value is None:
        return Decimal("0")
    value = value.strip()
    if not value:
        return Decimal("0")
    try:
        return Decimal(value)
    except InvalidOperation as exc:  # pragma: no cover - defensief
        raise AuditfileError(f"Ongeldig bedrag in auditfile: {value!r}") from exc


def load_auditfile_text(path: Path | str) -> str:
    """Lees de auditfile als tekst.

    XAF-bestanden declareren vaak ISO-8859-1 terwijl ze feitelijk UTF-8 zijn.
    We proberen daarom UTF-8 en vallen terug op ISO-8859-1. De XML-declaratie
    wordt verwijderd zodat de tekst met ``ElementTree`` geparseerd kan worden.
    """
    raw = Path(path).read_bytes()
    text: str | None = None
    for encoding in ("utf-8", "iso-8859-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:  # pragma: no cover - beide decoderingen falen is zeldzaam
        raise AuditfileError(f"Kan {path} niet decoderen (geen UTF-8 of ISO-8859-1)")
    return _XML_DECLARATION.sub("", text, count=1)


def parse_auditfile(path: Path | str, account: str) -> list[AuditLine]:
    """Geef alle ``line``-records van ``account`` terug uit de auditfile."""
    text = load_auditfile_text(path)
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise AuditfileError(f"Kan auditfile {path} niet parsen: {exc}") from exc

    wanted = account.strip()
    lines: list[AuditLine] = []
    for transaction in root.iter("transaction"):
        transaction_id = (transaction.findtext("transactionID") or "").strip()
        for line in transaction.findall("line"):
            if (line.findtext("accountID") or "").strip() != wanted:
                continue
            lines.append(
                AuditLine(
                    transaction_id=transaction_id,
                    record_id=(line.findtext("recordID") or "").strip(),
                    effective_date=(line.findtext("effectiveDate") or "").strip(),
                    debit=_to_decimal(line.findtext("debitAmount")),
                    credit=_to_decimal(line.findtext("creditAmount")),
                    description=(line.findtext("description") or "").strip(),
                    document_id=(line.findtext("documentID") or "").strip(),
                )
            )
    return lines


def supplier_tokens(description: str) -> frozenset[str]:
    """Leid leverancier-achtige tokens af uit een omschrijving.

    Tussen haakjes staande toelichting (``[Dubbel betaald]``), cijfers en
    administratieve stopwoorden worden verwijderd, zodat bijvoorbeeld
    ``"KPN B.V. Mobiel mei"`` en ``"KPN  B.V."`` beide ``{"kpn"}`` opleveren.
    """
    lowered = _BRACKETS.sub(" ", description.lower())
    lowered = _DIGITS.sub(" ", lowered)
    lowered = _NON_ALPHA.sub(" ", lowered)
    return frozenset(
        token for token in lowered.split() if token not in STOPWORDS and len(token) > 1
    )


def _tolerance(
    movement: Decimal, tolerance_percent: Decimal, max_tolerance: Decimal
) -> Decimal:
    base = abs(movement) * tolerance_percent / Decimal("100")
    return max(MIN_TOLERANCE, min(max_tolerance, base))


def _same_supplier(left: AuditLine, right: AuditLine) -> bool:
    return bool(left.supplier_tokens & right.supplier_tokens)


def _is_opening(line: AuditLine, opening_markers: Sequence[str]) -> bool:
    description = line.description.lower()
    return any(marker in description for marker in opening_markers)


def match_lines(
    lines: Iterable[AuditLine],
    *,
    tolerance_percent: Decimal = DEFAULT_TOLERANCE_PERCENT,
    max_tolerance: Decimal = DEFAULT_MAX_TOLERANCE,
    opening_markers: Sequence[str] = DEFAULT_OPENING_MARKERS,
) -> MatchResult:
    """Match opboekingen en afboekingen op een grootboekrekening.

    Boekingen die als beginbalans gemarkeerd zijn, worden buiten de matching
    gehouden en apart teruggegeven. De matching gebeurt in vier passen:

    1. exact bedrag, zelfde leverancier;
    2. exact bedrag, willekeurige leverancier (andere omschrijving);
    3. meerdere afboekingen die samen één opboeking dekken (zelfde leverancier);
    4. bedrag binnen tolerantie, zelfde leverancier (betalingsverschil).
    """
    all_lines = list(lines)
    opening = [line for line in all_lines if _is_opening(line, opening_markers)]
    opening_ids = {id(line) for line in opening}
    candidates = [line for line in all_lines if id(line) not in opening_ids]

    positives = sorted(
        (line for line in candidates if line.movement > 0),
        key=lambda line: line.effective_date,
    )
    negatives = [line for line in candidates if line.movement < 0]

    used: set[int] = set()
    matched_ids: set[int] = set()
    result = MatchResult(opening_balance=opening)

    def available() -> list[AuditLine]:
        return [line for line in negatives if id(line) not in used]

    def record(opening_line: AuditLine, closings: Sequence[AuditLine]) -> None:
        for closing in closings:
            used.add(id(closing))
        matched_ids.add(id(opening_line))
        difference = (
            sum((closing.movement for closing in closings), Decimal("0"))
            + opening_line.movement
        )
        result.matched.append(
            Match(opening=opening_line, closings=tuple(closings), difference=difference)
        )

    # Pas 1: exact, zelfde leverancier.
    for opening_line in positives:
        found = [
            line
            for line in available()
            if _same_supplier(opening_line, line)
            and abs(line.movement) == abs(opening_line.movement)
        ]
        if found:
            record(opening_line, [found[0]])

    # Pas 2: exact, willekeurige leverancier.
    for opening_line in positives:
        if id(opening_line) in matched_ids:
            continue
        found = [
            line for line in available() if abs(line.movement) == abs(opening_line.movement)
        ]
        if found:
            record(opening_line, [found[0]])

    # Pas 3: meerdere afboekingen dekken samen één opboeking.
    for opening_line in positives:
        if id(opening_line) in matched_ids:
            continue
        pool = [line for line in available() if _same_supplier(opening_line, line)]
        tolerance = _tolerance(opening_line.movement, tolerance_percent, max_tolerance)
        group: tuple[AuditLine, ...] | None = None
        for size in (2, 3):
            if size > len(pool):
                break
            for combo in combinations(pool, size):
                total = sum((line.movement for line in combo), Decimal("0"))
                if abs(total + opening_line.movement) <= tolerance:
                    group = combo
                    break
            if group:
                break
        if group:
            record(opening_line, group)

    # Pas 4: bedrag binnen tolerantie, zelfde leverancier.
    for opening_line in positives:
        if id(opening_line) in matched_ids:
            continue
        tolerance = _tolerance(opening_line.movement, tolerance_percent, max_tolerance)
        found = [
            line
            for line in available()
            if _same_supplier(opening_line, line)
            and abs(abs(line.movement) - abs(opening_line.movement)) <= tolerance
        ]
        if found:
            closest = min(
                found, key=lambda line: abs(abs(line.movement) - abs(opening_line.movement))
            )
            record(opening_line, [closest])

    result.unmatched_credits = sorted(
        (line for line in positives if id(line) not in matched_ids), key=_sort_key
    )
    result.unmatched_debits = sorted(
        (line for line in negatives if id(line) not in used), key=_sort_key
    )
    return result


def _sort_key(line: AuditLine) -> tuple[str, int, int]:
    return (
        line.effective_date,
        _int_or_zero(line.transaction_id),
        _int_or_zero(line.record_id),
    )


def _int_or_zero(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _format_amount(amount: Decimal) -> str:
    return f"{amount:.2f}"


def write_lines_csv(lines: Iterable[AuditLine], path: Path | str) -> Path:
    """Schrijf alle regels naar CSV met de gevraagde kolommen."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["effectiveDate", "debitAmount", "creditAmount", "description"])
        for line in sorted(lines, key=_sort_key):
            writer.writerow(
                [
                    line.effective_date,
                    _format_amount(line.debit) if line.debit != 0 else "",
                    _format_amount(line.credit) if line.credit != 0 else "",
                    line.description,
                ]
            )
    return target


def write_account_csv(lines: Iterable[AuditLine], path: Path | str) -> Path:
    """Schrijf grootboekregels naar CSV met datum, omschrijving, bedrag en factuur.

    De kolom ``factuur`` bevat het ``documentID`` van de regel, met alle
    witruimte verwijderd (document-ID's worden soms met spaties opgevuld).
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "description", "debit", "credit", "factuur"])
        for line in sorted(lines, key=_sort_key):
            writer.writerow(
                [
                    line.effective_date,
                    line.description,
                    _format_amount(line.debit) if line.debit != 0 else "",
                    _format_amount(line.credit) if line.credit != 0 else "",
                    re.sub(r"\s+", "", line.document_id),
                ]
            )
    return target


def _cause(line: AuditLine, is_invoice: bool) -> str:
    description = line.description.lower()
    if "dubbel betaald" in description:
        return "dubbele betaling"
    if "teveel" in description:
        return "betalingsverschil / te veel betaald"
    if is_invoice:
        return "openstaand / betaling in ander jaar of via andere rekening"
    return "betaling zonder factuur (ander jaar / andere rekening)"


def write_unmatched_csv(result: MatchResult, path: Path | str) -> Path:
    """Schrijf ongematchte opboekingen en afboekingen naar CSV."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "richting",
                "effectiveDate",
                "debitAmount",
                "creditAmount",
                "description",
                "transactionID",
                "mogelijke_oorzaak",
            ]
        )
        for line in sorted(result.unmatched_credits, key=_sort_key):
            writer.writerow(
                [
                    "CREDIT zonder debet (factuur zonder betaling)",
                    line.effective_date,
                    _format_amount(line.debit) if line.debit != 0 else "",
                    _format_amount(line.credit) if line.credit != 0 else "",
                    line.description,
                    line.transaction_id,
                    _cause(line, is_invoice=True),
                ]
            )
        for line in sorted(result.unmatched_debits, key=_sort_key):
            writer.writerow(
                [
                    "DEBET zonder credit (betaling zonder factuur)",
                    line.effective_date,
                    _format_amount(line.debit) if line.debit != 0 else "",
                    _format_amount(line.credit) if line.credit != 0 else "",
                    line.description,
                    line.transaction_id,
                    _cause(line, is_invoice=False),
                ]
            )
    return target


def analyze_auditfile(
    auditfile: Path | str,
    account: str,
    output_dir: Path | str,
    *,
    tolerance_percent: Decimal = DEFAULT_TOLERANCE_PERCENT,
    max_tolerance: Decimal = DEFAULT_MAX_TOLERANCE,
) -> AuditfileReport:
    """Analyseer één grootboekrekening en schrijf beide CSV-bestanden."""
    lines = parse_auditfile(auditfile, account)
    result = match_lines(
        lines, tolerance_percent=tolerance_percent, max_tolerance=max_tolerance
    )

    directory = Path(output_dir)
    lines_path = directory / f"account-{account}-lines.csv"
    unmatched_path = directory / f"account-{account}-unmatched.csv"
    write_lines_csv(lines, lines_path)
    write_unmatched_csv(result, unmatched_path)

    return AuditfileReport(
        account=account,
        line_count=len(lines),
        debit_total=sum((line.debit for line in lines), Decimal("0")),
        credit_total=sum((line.credit for line in lines), Decimal("0")),
        matched_count=len(result.matched),
        matched=result.matched,
        unmatched_credits=result.unmatched_credits,
        unmatched_debits=result.unmatched_debits,
        lines_path=lines_path,
        unmatched_path=unmatched_path,
    )