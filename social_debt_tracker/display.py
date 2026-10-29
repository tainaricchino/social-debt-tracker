"""Terminal table for a local run."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from .models import DebtItem, DebtStatus
from .report import attention_items, format_days, format_index, status_label

_STATUS_STYLE = {
    DebtStatus.ON_TRACK: "green",
    DebtStatus.DUE: "yellow",
    DebtStatus.OVERDUE: "bold red",
    DebtStatus.SNOOZED: "cyan",
    DebtStatus.UNKNOWN: "dim",
    DebtStatus.AMBIGUOUS: "magenta",
}


def render_report(items: Sequence[DebtItem], generated_at: datetime, console: Console | None = None) -> None:
    out = console or Console()
    table = Table(
        title="Índice de Saudade",
        caption=generated_at.strftime("%d/%m/%Y %H:%M") + "  ·  índice = dias / meta",
        header_style="bold",
        title_style="bold",
    )
    table.add_column("Contato", overflow="fold")
    table.add_column("Círculo", overflow="fold")
    table.add_column("Dias", justify="right")
    table.add_column("Meta", justify="right")
    table.add_column("Índice", justify="right")
    table.add_column("Status")

    for item in items:
        style = _STATUS_STYLE[item.status]
        table.add_row(
            escape(item.contact_name),
            escape(item.circle_name),
            format_days(item.days_since),
            str(item.target_days),
            format_index(item.saudade_index),
            f"[{style}]{status_label(item.status)}[/{style}]",
        )
    out.print(table)

    hooks = attention_items(items)
    if hooks:
        body = "\n".join(
            f"[bold]{escape(item.contact_name)}[/bold]: {escape(item.suggestion or '')}"
            for item in hooks
        )
        out.print(Panel(body, title="Ganchos para retomar", border_style="yellow"))

    notes = [item for item in items if item.note]
    if notes:
        body = "\n".join(f"[bold]{escape(item.contact_name)}[/bold]: {escape(item.note or '')}" for item in notes)
        out.print(Panel(body, title="Notas", border_style="dim"))

    counts = {status: 0 for status in DebtStatus}
    for item in items:
        counts[item.status] += 1
    out.print(
        "Em atraso: {overdue}   Quase: {due}   Em dia: {ok}   "
        "Adiados: {snoozed}   Sem match: {missing}".format(
            overdue=counts[DebtStatus.OVERDUE],
            due=counts[DebtStatus.DUE],
            ok=counts[DebtStatus.ON_TRACK],
            snoozed=counts[DebtStatus.SNOOZED],
            missing=counts[DebtStatus.UNKNOWN] + counts[DebtStatus.AMBIGUOUS],
        )
    )
