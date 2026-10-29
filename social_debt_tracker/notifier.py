"""Private report via a Bot API bot, with inline buttons for feedback.

The bot receives commands and button presses. It does not read the account's chats.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from .analyzer import analyze
from .config_store import (
    StorageError,
    load_config,
    load_state,
    name_for_key,
    save_metadata_cache,
    save_state,
    set_manual_contact,
    set_snooze,
)
from .models import DebtItem
from .names import contact_key
from .report import attention_items, build_report_text
from .telegram_client import MetadataClient, SessionRequired

logger = logging.getLogger(__name__)

_BUTTON_LIMIT = 64


class NotifyError(RuntimeError):
    """The report could not be delivered to the user's bot chat."""


async def send_report(
    token: str,
    chat_id: int,
    items: Sequence[DebtItem],
    generated_at: datetime,
) -> None:
    text = build_report_text(items, generated_at)
    keyboard = build_keyboard(items)
    bot = Bot(token)
    try:
        async with bot:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
    except TelegramError as exc:
        raise NotifyError(f"O bot não conseguiu enviar o relatório: {exc}") from exc


def build_keyboard(items: Sequence[DebtItem]) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    for item in attention_items(items):
        key = contact_key(item.contact_name)
        rows.append(
            [
                InlineKeyboardButton(
                    _fit(item.contact_name, "falei"),
                    callback_data=f"{key}:ok",
                ),
                InlineKeyboardButton("1d", callback_data=f"{key}:d1"),
                InlineKeyboardButton("7d", callback_data=f"{key}:d7"),
            ]
        )
    if not rows:
        return None
    return InlineKeyboardMarkup(rows)


def register_handlers(
    application: Application[object, object, object, object],
    *,
    config_path: Path,
    state_path: Path,
    cache_path: Path,
    session_path: Path,
    api_id: int,
    api_hash: str,
) -> None:
    application.bot_data["paths"] = {
        "config": config_path,
        "state": state_path,
        "cache": cache_path,
        "session": session_path,
        "api_id": api_id,
        "api_hash": api_hash,
    }
    application.add_handler(CommandHandler("start", on_start))
    application.add_handler(CommandHandler("report", on_report))
    application.add_handler(CallbackQueryHandler(on_feedback))


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None:
        return
    if chat.type != "private":
        await message.reply_text("Abre uma conversa privada comigo e envia /start.")
        return
    paths = _paths(context)
    state = load_state(paths["state"])
    state.report_chat_id = chat.id
    save_state(paths["state"], state)
    await message.reply_text(
        "Social Debt Tracker\n\n"
        "Os relatórios passam a chegar aqui. Este bot recebe comandos e os botões "
        "de feedback. Ele não lê o texto das suas conversas.\n\n"
        "/report — gera o relatório agora"
    )


async def on_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    paths = _paths(context)
    try:
        config = load_config(paths["config"])
        state = load_state(paths["state"])
    except StorageError as exc:
        await message.reply_text(str(exc))
        return

    try:
        now = datetime.now(ZoneInfo(config.user_settings.timezone))
        client = MetadataClient(paths["api_id"], paths["api_hash"], paths["session"])
        await client.connect()
        try:
            chats = await client.fetch_metadata()
        finally:
            await client.disconnect()
    except SessionRequired as exc:
        await message.reply_text(str(exc))
        return
    except Exception:
        logger.exception("Falha ao ler metadados para /report.")
        await message.reply_text("Não consegui ler os metadados do Telegram. Veja o terminal.")
        return

    save_metadata_cache(paths["cache"], chats, now)
    items = analyze(chats, config.circles, state, now)
    try:
        await send_report(context.bot.token, message.chat_id, items, now)
    except NotifyError as exc:
        await message.reply_text(str(exc))


async def on_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not query.data:
        return
    parts = query.data.split(":")
    if len(parts) != 2:
        await query.answer()
        return
    key, action = parts
    paths = _paths(context)
    try:
        config = load_config(paths["config"])
        state = load_state(paths["state"])
    except StorageError:
        await query.answer("Configuração inválida.")
        return

    name = name_for_key(config, state, key)
    if name is None:
        await query.answer("Contato não encontrado.")
        return

    now = datetime.now(timezone.utc)
    if action == "ok":
        set_manual_contact(state, name, now)
        confirmation = "Registrado como contato de agora."
        button = _fit(name, "anotado")
    elif action == "d1":
        set_snooze(state, name, now + timedelta(days=1))
        confirmation = "Adiado por 1 dia."
        button = _fit(name, "adiado 1d")
    elif action == "d7":
        set_snooze(state, name, now + timedelta(days=7))
        confirmation = "Adiado por 7 dias."
        button = _fit(name, "adiado 7d")
    elif action == "noop":
        await query.answer("Já anotado.")
        return
    else:
        await query.answer()
        return

    save_state(paths["state"], state)
    await query.answer(confirmation)
    if query.message is not None and query.message.reply_markup is not None:
        updated = _replace_contact_row(query.message.reply_markup, key, button)
        try:
            await query.edit_message_reply_markup(reply_markup=updated)
        except TelegramError:
            logger.info("O relatório foi anotado, mas o botão não pôde ser atualizado.")


def _replace_contact_row(
    markup: InlineKeyboardMarkup,
    key: str,
    label: str,
) -> InlineKeyboardMarkup:
    prefix = f"{key}:"
    rows: list[list[InlineKeyboardButton]] = []
    for row in markup.inline_keyboard:
        owned = any((button.callback_data or "").startswith(prefix) for button in row)
        if owned:
            rows.append([InlineKeyboardButton(label, callback_data=f"{key}:noop")])
        else:
            rows.append(list(row))
    return InlineKeyboardMarkup(rows)


def _fit(name: str, action: str) -> str:
    suffix = f" · {action}"
    room = _BUTTON_LIMIT - len(suffix)
    if room < 1:
        return action[:_BUTTON_LIMIT]
    if len(name) <= room:
        return f"{name}{suffix}"
    trimmed = name[: room - 1].rstrip() + "…"
    return f"{trimmed}{suffix}"


def _paths(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Path | int | str]:
    raw = context.application.bot_data.get("paths")
    if not isinstance(raw, dict):
        raise RuntimeError("Handlers registrados sem os caminhos do projeto.")
    return raw
