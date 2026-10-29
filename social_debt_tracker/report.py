"""Text of the private report. Names and elapsed days only."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from .models import DebtItem, DebtStatus

_ATTENTION = {DebtStatus.OVERDUE, DebtStatus.DUE}
_UNMATCHED = {DebtStatus.UNKNOWN, DebtStatus.AMBIGUOUS}
_TELEGRAM_LIMIT = 4000


def format_days(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}".replace(".", ",")


def format_index(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}×".replace(".", ",")


def status_label(status: DebtStatus) -> str:
    labels = {
        DebtStatus.ON_TRACK: "em dia",
        DebtStatus.DUE: "quase",
        DebtStatus.OVERDUE: "em atraso",
        DebtStatus.SNOOZED: "adiado",
        DebtStatus.UNKNOWN: "sem registro",
        DebtStatus.AMBIGUOUS: "ambíguo",
    }
    return labels[status]


def attention_items(items: Sequence[DebtItem]) -> list[DebtItem]:
    return [item for item in items if item.status in _ATTENTION]


def build_report_text(items: Sequence[DebtItem], generated_at: datetime) -> str:
    full = _render(items, generated_at, include_suggestions=True)
    if len(full) <= _TELEGRAM_LIMIT:
        return full
    compact = _render(items, generated_at, include_suggestions=False)
    if len(compact) <= _TELEGRAM_LIMIT:
        return compact
    return compact[: _TELEGRAM_LIMIT - 1] + "…"


def _render(items: Sequence[DebtItem], generated_at: datetime, include_suggestions: bool) -> str:
    lines = [
        "<b>Social Debt Tracker</b>",
        html_escape(generated_at.strftime("%d/%m/%Y %H:%M")),
        "",
    ]
    needing = attention_items(items)
    if not needing:
        lines.append("Nenhum contato passou da meta. Os vínculos acompanhados estão em dia.")
    else:
        lines.append("<b>Hora de retomar o contato</b>")
        for item in needing:
            lines.append(
                "• <b>{name}</b> — {circle} — {days} dias "
                "({label}, meta {target}, índice {index})".format(
                    name=html_escape(item.contact_name),
                    circle=html_escape(item.circle_name),
                    days=format_days(item.days_since),
                    label=status_label(item.status),
                    target=item.target_days,
                    index=format_index(item.saudade_index),
                )
            )
            if include_suggestions and item.suggestion:
                lines.append(f"  <i>{html_escape(item.suggestion)}</i>")
        lines.append("")

    on_track = sum(1 for item in items if item.status is DebtStatus.ON_TRACK)
    snoozed = sum(1 for item in items if item.status is DebtStatus.SNOOZED)
    lines.append(f"Em dia: {on_track}. Adiados: {snoozed}.")

    unmatched = [item for item in items if item.status in _UNMATCHED]
    if unmatched:
        lines.append("")
        lines.append("<b>Sem correspondência segura</b>")
        for item in unmatched:
            detail = item.note or status_label(item.status)
            lines.append(f"• {html_escape(item.contact_name)} — {html_escape(detail)}")

    lines.append("")
    lines.append("Os ganchos são genéricos. O texto das conversas não entra neste relatório.")
    return "\n".join(lines)


def html_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
