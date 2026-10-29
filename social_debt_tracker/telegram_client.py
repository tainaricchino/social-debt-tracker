"""Telethon user client restricted to dialog metadata.

Telegram's dialogs.list payload includes the latest message. This module copies
chat id, title, and last-activity timestamp, then drops the dialog object.
It does not subscribe to incoming updates.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.custom.dialog import Dialog
from telethon.tl.types import Channel, User

from .models import ChatMetadata


class SessionRequired(RuntimeError):
    """The local Telethon session has not been authorized on this machine."""


class MetadataClient:
    def __init__(self, api_id: int, api_hash: str, session_path: Path) -> None:
        session_path.parent.mkdir(parents=True, exist_ok=True)
        self._client = TelegramClient(
            str(session_path),
            api_id,
            api_hash,
            receive_updates=False,
        )

    async def connect(self) -> None:
        await self._client.connect()
        if not await self._client.is_user_authorized():
            await self._client.disconnect()
            raise SessionRequired(
                "Nenhuma sessão autorizada. Rode `python main.py login` neste computador."
            )

    async def login(self) -> str:
        await self._client.start()
        me = await self._client.get_me()
        first_name = getattr(me, "first_name", None)
        if isinstance(first_name, str) and first_name.strip():
            return first_name.strip()
        return "conta"

    async def fetch_metadata(self) -> list[ChatMetadata]:
        collected: list[ChatMetadata] = []
        async for dialog in self._client.iter_dialogs():
            metadata = metadata_from_dialog(dialog)
            if metadata is not None:
                collected.append(metadata)
        return collected

    async def disconnect(self) -> None:
        await self._client.disconnect()


def metadata_from_dialog(dialog: Dialog) -> ChatMetadata | None:
    if not _is_trackable(dialog):
        return None
    name = (dialog.name or "").strip()
    if not name:
        return None
    last_at = dialog.date if isinstance(dialog.date, datetime) else None
    if last_at is not None and last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)
    return ChatMetadata(
        chat_id=int(dialog.id),
        name=name,
        last_message_at=last_at,
        is_group=bool(dialog.is_group),
    )


def _is_trackable(dialog: Dialog) -> bool:
    entity = dialog.entity
    if isinstance(entity, User):
        return not bool(entity.bot)
    if isinstance(entity, Channel):
        return bool(entity.megagroup)
    return bool(dialog.is_user or dialog.is_group)
