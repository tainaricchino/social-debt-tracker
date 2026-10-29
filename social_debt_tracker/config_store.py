"""Load and store local JSON: circles, feedback, and the metadata cache."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import (
    AppConfig,
    AppState,
    ChatMetadata,
    Circle,
    ContactOverride,
    UserSettings,
)
from .names import contact_key
from .schedule import parse_hour_minute


class StorageError(ValueError):
    """config.json or state.json cannot be used as-is."""


def load_config(path: Path) -> AppConfig:
    raw = _read_object(path, "config.json")
    settings_raw = raw.get("user_settings", {})
    circles_raw = raw.get("circles", [])
    if not isinstance(settings_raw, dict):
        raise StorageError("user_settings precisa ser um objeto.")
    if not isinstance(circles_raw, list) or not circles_raw:
        raise StorageError("circles precisa ser uma lista com pelo menos um círculo.")

    privacy_mode = settings_raw.get("privacy_mode", None)
    if privacy_mode is not True:
        raise StorageError(
            "privacy_mode precisa ser true. Este projeto só roda em modo de metadados."
        )

    hour = settings_raw.get("daily_report_hour", "10:00")
    if not isinstance(hour, str):
        raise StorageError("daily_report_hour precisa ser uma string HH:MM.")
    try:
        parse_hour_minute(hour)
    except ValueError as exc:
        raise StorageError(str(exc)) from exc

    timezone_name = settings_raw.get("timezone", "America/Sao_Paulo")
    if not isinstance(timezone_name, str):
        raise StorageError("timezone precisa ser um nome IANA, por exemplo America/Sao_Paulo.")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise StorageError(f"Fuso desconhecido: {timezone_name}.") from exc

    interval = settings_raw.get("report_interval_days", 1)
    if isinstance(interval, bool) or not isinstance(interval, int) or interval < 1:
        raise StorageError("report_interval_days precisa ser um inteiro maior ou igual a 1.")

    circles: list[Circle] = []
    for entry in circles_raw:
        circles.append(_parse_circle(entry))

    settings = UserSettings(
        daily_report_hour=hour,
        privacy_mode=True,
        timezone=timezone_name,
        report_interval_days=interval,
    )
    return AppConfig(user_settings=settings, circles=tuple(circles))


def load_state(path: Path) -> AppState:
    if not path.exists():
        return AppState()
    raw = _read_object(path, "state.json")
    chat_id = raw.get("report_chat_id")
    if chat_id is not None and not isinstance(chat_id, int):
        raise StorageError("report_chat_id em state.json precisa ser um inteiro.")
    contacts_raw = raw.get("contacts", {})
    if not isinstance(contacts_raw, dict):
        raise StorageError("contacts em state.json precisa ser um objeto.")

    contacts: dict[str, ContactOverride] = {}
    for key, entry in contacts_raw.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            raise StorageError("Cada contato em state.json precisa ser um objeto.")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise StorageError("Cada contato em state.json precisa de um nome.")
        contacts[key] = ContactOverride(
            name=name.strip(),
            snooze_until=_parse_datetime(entry.get("snooze_until"), "snooze_until"),
            manual_last_contact=_parse_datetime(
                entry.get("manual_last_contact"),
                "manual_last_contact",
            ),
        )

    return AppState(
        report_chat_id=chat_id,
        last_report_sent_at=_parse_datetime(raw.get("last_report_sent_at"), "last_report_sent_at"),
        contacts=contacts,
    )


def save_state(path: Path, state: AppState) -> None:
    contacts_payload = {
        key: {
            "name": record.name,
            "snooze_until": _dump_datetime(record.snooze_until),
            "manual_last_contact": _dump_datetime(record.manual_last_contact),
        }
        for key, record in sorted(state.contact_map.items())
    }
    payload = {
        "version": 1,
        "report_chat_id": state.report_chat_id,
        "last_report_sent_at": _dump_datetime(state.last_report_sent_at),
        "contacts": contacts_payload,
    }
    _write_json(path, payload)


def remember_chat(state: AppState, chat_id: int) -> None:
    state.report_chat_id = chat_id


def set_manual_contact(state: AppState, name: str, when: datetime) -> None:
    record = _record(state, name)
    record.manual_last_contact = when
    record.snooze_until = None


def set_snooze(state: AppState, name: str, until: datetime) -> None:
    record = _record(state, name)
    record.snooze_until = until


def name_for_key(config: AppConfig, state: AppState, key: str) -> str | None:
    for circle in config.circles:
        for contact in circle.contacts:
            if contact_key(contact) == key:
                return contact
    record = state.contact_map.get(key)
    if record is not None:
        return record.name
    return None


def load_metadata_cache(path: Path) -> list[ChatMetadata]:
    if not path.exists():
        return []
    raw = _read_object(path, "metadata.json")
    chats_raw = raw.get("chats", [])
    if not isinstance(chats_raw, list):
        raise StorageError("cache de metadados inválido.")
    chats: list[ChatMetadata] = []
    for entry in chats_raw:
        if not isinstance(entry, dict):
            raise StorageError("cada conversa no cache precisa ser um objeto.")
        name = entry.get("name")
        chat_id = entry.get("chat_id")
        if not isinstance(name, str) or not isinstance(chat_id, int):
            raise StorageError("cache de metadados sem nome ou chat_id.")
        chats.append(
            ChatMetadata(
                chat_id=chat_id,
                name=name,
                last_message_at=_parse_datetime(entry.get("last_message_at"), "last_message_at"),
                is_group=bool(entry.get("is_group", False)),
            )
        )
    return chats


def save_metadata_cache(path: Path, chats: list[ChatMetadata], fetched_at: datetime) -> None:
    payload = {
        "fetched_at": _dump_datetime(fetched_at),
        "chats": [
            {
                "chat_id": chat.chat_id,
                "name": chat.name,
                "last_message_at": _dump_datetime(chat.last_message_at),
                "is_group": chat.is_group,
            }
            for chat in chats
        ],
    }
    _write_json(path, payload)


def _record(state: AppState, name: str) -> ContactOverride:
    key = contact_key(name)
    record = state.contact_map.get(key)
    if record is None:
        record = ContactOverride(name=name)
        state.contact_map[key] = record
    else:
        record.name = name
    return record


def _parse_circle(entry: object) -> Circle:
    if not isinstance(entry, dict):
        raise StorageError("Cada círculo precisa ser um objeto.")
    name = entry.get("name")
    target_days = entry.get("target_days")
    contacts = entry.get("contacts")
    if not isinstance(name, str) or not name.strip():
        raise StorageError("Cada círculo precisa de um nome.")
    if isinstance(target_days, bool) or not isinstance(target_days, int) or target_days < 1:
        raise StorageError(f"target_days de {name!r} precisa ser um inteiro maior ou igual a 1.")
    if not isinstance(contacts, list) or not contacts:
        raise StorageError(f"O círculo {name!r} precisa de uma lista de contatos.")
    cleaned: list[str] = []
    for contact in contacts:
        if not isinstance(contact, str) or not contact.strip():
            raise StorageError(f"Contato inválido no círculo {name!r}.")
        cleaned.append(contact.strip())
    return Circle(name=name.strip(), target_days=target_days, contacts=tuple(cleaned))


def _read_object(path: Path, label: str) -> dict[str, object]:
    if not path.exists():
        raise StorageError(f"Arquivo não encontrado: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StorageError(f"{label} não é JSON válido: {exc}") from exc
    if not isinstance(raw, dict):
        raise StorageError(f"{label} precisa ser um objeto JSON.")
    return raw


def _parse_datetime(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise StorageError(f"{field} precisa ser uma data ISO-8601.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise StorageError(f"{field} não é uma data ISO-8601.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _dump_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
