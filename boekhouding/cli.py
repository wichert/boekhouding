"""XAF auditfile, CAMT.053 and web explorer commands."""

from decimal import Decimal
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from boekhouding.auditfile_report import (
    AuditfileError,
    analyze_auditfile,
    parse_auditfile,
    write_account_csv,
)
from boekhouding.audit_routes import AUDIT_FILE_ENV
from boekhouding.app import HOST_ENV, PORT_ENV
from boekhouding.camt053 import parse_camt053, write_csv

app = typer.Typer(name="boekhouding", help="XAF auditfile and CAMT.053 tools")
console = Console()


@app.command("auditfile-account-report")
def auditfile_account_report(
    auditfile: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="XAF auditfile, bijvoorbeeld data/auditlog-2025.xaf",
    ),
    account: str = typer.Option(
        "1500", "-a", "--account", help="Grootboekrekening om te analyseren"
    ),
    output_dir: Path = typer.Option(
        Path("output"), "-o", "--output-dir", help="Map voor de CSV-bestanden"
    ),
    tolerance_percent: float = typer.Option(
        3.0,
        "--tolerance-percent",
        help="Tolerantie voor betalingsverschillen (% van het factuurbedrag)",
    ),
    verbose: bool = typer.Option(
        False, "-v", "--verbose", help="Toon alle ongematchte posten in de console"
    ),
):
    """Analyseer één grootboekrekening uit een XAF auditfile.

    Schrijft alle ``line``-records van de rekening naar CSV en spoort
    boekingen op waarvoor geen tegenboeking bestaat: opboekingen (credit)
    zonder afboeking en afboekingen (debet) zonder opboeking. Boekingen
    worden gekoppeld op leverancier en bedrag, met tolerantie voor
    betalingsverschillen.

    Voorbeeld:

        boekhouding auditfile-account-report data/auditlog-2025.xaf -a 1500 -o output
    """
    try:
        report = analyze_auditfile(
            auditfile,
            account,
            output_dir,
            tolerance_percent=Decimal(str(tolerance_percent)),
        )
    except AuditfileError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    if report.line_count == 0:
        console.print(
            f"[yellow]Geen boekingen gevonden op rekening {account} in {auditfile}.[/yellow]"
        )
        raise typer.Exit(code=1)

    summary = Table(title=f"Auditfile-rekening {account}")
    summary.add_column("Omschrijving", style="cyan")
    summary.add_column("Waarde", justify="right", style="magenta")
    summary.add_row("Regels", str(report.line_count))
    summary.add_row("Totaal debet", f"{report.debit_total:.2f}")
    summary.add_row("Totaal credit", f"{report.credit_total:.2f}")
    summary.add_row("Mutatie (credit - debet)", f"{report.movement:.2f}")
    summary.add_row("Gematchte paren", str(report.matched_count))
    summary.add_row(
        "Credit zonder debet",
        f"{len(report.unmatched_credits)} ({report.unmatched_credit_total:.2f})",
    )
    summary.add_row(
        "Debet zonder credit",
        f"{len(report.unmatched_debits)} ({report.unmatched_debit_total:.2f})",
    )
    console.print(summary)

    if report.unmatched_credits or report.unmatched_debits:
        details = Table(title="Boekingen zonder tegenboeking")
        details.add_column("Richting", style="cyan")
        details.add_column("Datum")
        details.add_column("Debet", justify="right")
        details.add_column("Credit", justify="right")
        details.add_column("Omschrijving")
        for line in report.unmatched_credits:
            details.add_row(
                "CREDIT zonder debet",
                line.effective_date,
                f"{line.debit:.2f}" if line.debit != 0 else "",
                f"{line.credit:.2f}" if line.credit != 0 else "",
                line.description,
            )
        for line in report.unmatched_debits:
            details.add_row(
                "DEBET zonder credit",
                line.effective_date,
                f"{line.debit:.2f}" if line.debit != 0 else "",
                f"{line.credit:.2f}" if line.credit != 0 else "",
                line.description,
            )
        console.print(details)

    if verbose and report.matched:
        matches = Table(title="Gematchte paren")
        matches.add_column("Datum")
        matches.add_column("Opboeking", justify="right")
        matches.add_column("Afboeking(en)", justify="right")
        matches.add_column("Verschil", justify="right")
        matches.add_column("Omschrijving")
        for match in report.matched:
            matches.add_row(
                match.opening.effective_date,
                f"{match.opening.movement:.2f}",
                f"{sum((c.movement for c in match.closings), Decimal('0')):.2f}",
                f"{match.difference:.2f}",
                match.opening.description,
            )
        console.print(matches)

    console.print(f"[green]Regels geschreven naar:[/green] {report.lines_path}")
    console.print(f"[green]Afwijkingen geschreven naar:[/green] {report.unmatched_path}")


@app.command("account-to-csv")
def account_to_csv(
    auditfile: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="XAF auditfile, bijvoorbeeld data/auditlog-2025.xaf",
    ),
    account: str = typer.Argument(
        ..., help="Grootboekrekening om te exporteren, bijvoorbeeld 1500"
    ),
    output: Path = typer.Option(
        None,
        "-o",
        "--output",
        help="CSV-bestand om naar te schrijven (standaard output/account-<account>.csv)",
    ),
):
    """Exporteer de regels van één grootboekrekening naar CSV.

    Schrijft de kolommen ``date``, ``description``, ``debit``, ``credit`` en
    ``factuur``. De kolom ``factuur`` bevat het ``documentID`` van de regel
    met alle witruimte verwijderd.

    Voorbeeld:

        boekhouding account-to-csv data/auditlog-2025.xaf 1500 -o output/account-1500.csv
    """
    target = output if output is not None else Path("output") / f"account-{account}.csv"
    try:
        lines = parse_auditfile(auditfile, account)
        write_account_csv(lines, target)
    except AuditfileError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    if not lines:
        console.print(
            f"[yellow]Geen boekingen gevonden op rekening {account} in {auditfile}.[/yellow]"
        )
        raise typer.Exit(code=1)

    console.print(
        f"[green]{len(lines)} regels geschreven naar:[/green] {target}"
    )


@app.command("camt053-to-csv")
def camt053_to_csv(
    xml: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True, help="CAMT.053 XML-bestand"),
    output: Path = typer.Option(Path("output/camt053.csv"), "-o", "--output", help="CSV-uitvoerbestand"),
):
    """Converteer een CAMT.053 bankafschrift naar CSV (één regel per Ntry)."""
    try:
        rows = parse_camt053(xml)
        target = write_csv(rows, output)
    except (OSError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]{len(rows)} boekingen geschreven naar:[/green] {target}")


@app.command()
def serve(
    host: str = typer.Option(None, envvar=HOST_ENV, help=f"Host interface (or {HOST_ENV})"),
    port: int = typer.Option(None, envvar=PORT_ENV, help=f"TCP port (or {PORT_ENV})"),
    audit_file: str = typer.Option(None, "--audit-file", envvar=AUDIT_FILE_ENV, help=f"XAF file, directory, or glob (or {AUDIT_FILE_ENV})"),
    reload: bool = typer.Option(False, help="Reload when source files change"),
):
    """Start the Boekhouding web explorer."""
    from boekhouding.app import serve as run_server

    try:
        run_server(host=host, port=port, audit_file=audit_file, reload=reload)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
