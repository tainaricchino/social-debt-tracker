"""Índice de Saudade: days since the last contact, compared with the circle target."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from .models import AppState, ChatMetadata, Circle, DebtItem, DebtStatus
from .names import contact_key, normalize_name

# A contact enters the "quase" band in the last 20% of the target window.
APPROACHING_RATIO = 0.8
_MIN_PREFIX_LENGTH = 3

_STATUS_ORDER = {
    DebtStatus.OVERDUE: 0,
    DebtStatus.DUE: 1,
    DebtStatus.SNOOZED: 2,
    DebtStatus.AMBIGUOUS: 3,
    DebtStatus.UNKNOWN: 4,
    DebtStatus.ON_TRACK: 5,
}

logger = logging.getLogger(__name__)

OPENERS: tuple[str, ...] = (
    "Manda um oi curto dizendo que lembrou da pessoa.",
    "Pergunta como foi a semana, sem cobrar uma resposta longa.",
    "Relembra um plano antigo e pergunta se ainda faz sentido.",
    "Conta uma novidade pequena da sua vida e devolve a pergunta.",
    "Sugere um encontro curto: um café ou uma ligação de dez minutos.",
)

GROUP_OPENERS: tuple[str, ...] = (
    "Manda um oi no grupo perguntando quando é o próximo encontro.",
    "Pergunta se algum plano antigo do grupo ainda está de pé.",
    "Propõe um horário curto para o pessoal se ver.",
    "Pergunta como a semana foi para a turma, sem cobrar resposta longa.",
    "Lembra um momento do grupo e chama todo mundo para repetir.",
)


def analyze(
    chats: Sequence[ChatMetadata],
    circles: Sequence[Circle],
    state: AppState,
    now: datetime,
) -> list[DebtItem]:
    if now.tzinfo is None:
        raise ValueError("now precisa ter fuso horário.")

    seen: dict[str, str] = {}
    items: list[DebtItem] = []
    for circle in circles:
        for contact in circle.contacts:
            key = normalize_name(contact)
            previous = seen.get(key)
            if previous is not None:
                logger.warning("Contato repetido em %r e %r.", previous, circle.name)
            else:
                seen[key] = circle.name
            items.append(_evaluate(contact, circle, chats, state, now))
    return sorted(items, key=_sort_key)


def suggestion_for(contact_name: str, day: datetime, *, group: bool = False) -> str:
    pool = GROUP_OPENERS if group else OPENERS
    material = f"{normalize_name(contact_name)}:{day.date().isoformat()}:{'g' if group else 'p'}".encode()
    digest = hashlib.sha256(material).digest()
    return pool[digest[0] % len(pool)]


def _evaluate(
    contact: str,
    circle: Circle,
    chats: Sequence[ChatMetadata],
    state: AppState,
    now: datetime,
) -> DebtItem:
    chat, problem = _match_chat(contact, chats)
    override = state.contact_map.get(contact_key(contact))
    manual_at = _as_aware(override.manual_last_contact) if override else None
    telegram_at = _as_aware(chat.last_message_at) if chat is not None else None
    if problem is DebtStatus.AMBIGUOUS:
        telegram_at = None

    if telegram_at is not None and manual_at is not None:
        effective = max(telegram_at, manual_at)
    else:
        effective = telegram_at or manual_at

    notes: list[str] = []
    if problem is DebtStatus.AMBIGUOUS:
        notes.append("Mais de uma conversa corresponde a esse nome.")
    elif problem is DebtStatus.UNKNOWN and effective is None:
        notes.append("Nenhuma conversa encontrada com esse nome.")
    elif chat is not None and normalize_name(chat.name) != normalize_name(contact):
        notes.append(f"Nome no Telegram: {chat.name}.")

    if manual_at is not None and (telegram_at is None or manual_at >= telegram_at):
        notes.append("Último contato informado por você.")

    if effective is None:
        status = problem or DebtStatus.UNKNOWN
        days_since = None
        index = None
    else:
        days_since, index, status = _measure(effective, circle.target_days, now)

    snooze_until = _as_aware(override.snooze_until) if override else None
    if snooze_until is not None and snooze_until > now:
        status = DebtStatus.SNOOZED
        notes.append(f"Adiado até {_format_local(snooze_until, now)}.")

    suggestion = None
    if status in {DebtStatus.OVERDUE, DebtStatus.DUE}:
        suggestion = suggestion_for(contact, now, group=bool(chat and chat.is_group))

    return DebtItem(
        contact_name=contact,
        circle_name=circle.name,
        target_days=circle.target_days,
        chat_id=chat.chat_id if chat is not None else None,
        matched_name=chat.name if chat is not None else None,
        last_contact_at=effective,
        days_since=days_since,
        saudade_index=index,
        status=status,
        suggestion=suggestion,
        note=" ".join(notes) or None,
    )


def _match_chat(
    contact: str,
    chats: Sequence[ChatMetadata],
) -> tuple[ChatMetadata | None, DebtStatus | None]:
    target = normalize_name(contact)
    if not target:
        return None, DebtStatus.UNKNOWN

    exact = [chat for chat in chats if normalize_name(chat.name) == target]
    if len(exact) == 1:
        return exact[0], None
    if len(exact) > 1:
        return None, DebtStatus.AMBIGUOUS

    if len(target) < _MIN_PREFIX_LENGTH:
        return None, DebtStatus.UNKNOWN

    extensions: list[ChatMetadata] = []
    for chat in chats:
        candidate = normalize_name(chat.name)
        if _extends(target, candidate):
            extensions.append(chat)
    if len(extensions) == 1:
        return extensions[0], None
    if len(extensions) > 1:
        return None, DebtStatus.AMBIGUOUS
    return None, DebtStatus.UNKNOWN


def _extends(left: str, right: str) -> bool:
    """True when one name continues the other on a word boundary."""

    if len(left) < _MIN_PREFIX_LENGTH or len(right) < _MIN_PREFIX_LENGTH:
        return False
    if left == right:
        return False
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    if len(shorter) < _MIN_PREFIX_LENGTH:
        return False
    return longer.startswith(shorter) and longer[len(shorter)] == " "


def _measure(last_contact: datetime, target_days: int, now: datetime) -> tuple[float, float, DebtStatus]:
    elapsed = (now - last_contact).total_seconds() / timedelta(days=1).total_seconds()
    if elapsed < 0:
        elapsed = 0.0
    index = elapsed / target_days
    if elapsed >= target_days:
        status = DebtStatus.OVERDUE
    elif index >= APPROACHING_RATIO:
        status = DebtStatus.DUE
    else:
        status = DebtStatus.ON_TRACK
    return elapsed, index, status


def _sort_key(item: DebtItem) -> tuple[int, int, float, str]:
    missing = 0 if item.saudade_index is not None else 1
    magnitude = -(item.saudade_index or 0.0)
    return (_STATUS_ORDER[item.status], missing, magnitude, item.contact_name.casefold())


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _format_local(moment: datetime, now: datetime) -> str:
    local = moment.astimezone(now.tzinfo)
    return local.strftime("%d/%m %H:%M")
