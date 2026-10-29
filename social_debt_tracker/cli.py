"""Social Debt Tracker — local runner.

Commands:
    python -m social_debt_tracker login
    python -m social_debt_tracker run [--demo] [--notify]
    python -m social_debt_tracker serve
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import NoReturn

from dotenv import load_dotenv
from rich.console import Console
from telegram.ext import Application
from zoneinfo import ZoneInfo

from .analyzer import analyze
from .config_store import StorageError, load_config, load_state, save_metadata_cache, save_state
from .display import render_report
from .models import AppConfig, ChatMetadata
from .notifier import NotifyError, register_handlers, send_report
from .schedule import seconds_until_next_report
from .telegram_client import MetadataClient, SessionRequired

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
CACHE_PATH = ROOT / "cache" / "metadata.json"
SESSION_PATH = ROOT / "social_debt.session"

console = Console()
logger = logging.getLogger("social_debt")

_RETRY_SECONDS = 15 * 60


@dataclass(frozen=True, slots=True)
class Credentials:
    api_id: int | None
    api_hash: str | None
    bot_token: str | None
    report_chat_id: int | None


def main() -> None:
    _configure_logging()
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(
        description="Acompanha o tempo desde o último contato com as pessoas que importam.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="Autentica a sua conta no Telethon (uma vez neste computador).")

    run = sub.add_parser("run", help="Calcula o índice e mostra a tabela.")
    run.add_argument("--demo", action="store_true", help="Usa conversas de exemplo, sem Telegram.")
    run.add_argument("--notify", action="store_true", help="Envia o relatório pelo bot.")

    sub.add_parser("serve", help="Fica em execução: relatório no horário e botões de feedback.")

    args = parser.parse_args()
    try:
        asyncio.run(_dispatch(args))
    except KeyboardInterrupt:
        console.print("\nEncerrado.")


async def _dispatch(args: argparse.Namespace) -> None:
    if args.command == "login":
        await _login()
    elif args.command == "run":
        await _run(demo=args.demo, notify=args.notify)
    elif args.command == "serve":
        await _serve()


async def _login() -> None:
    credentials = _credentials()
    api_id, api_hash = _require_user_api(credentials)
    client = MetadataClient(api_id, api_hash, SESSION_PATH)
    try:
        first_name = await client.login()
    finally:
        await client.disconnect()
    console.print(f"Sessão pronta para [bold]{first_name}[/bold].")


async def _run(*, demo: bool, notify: bool) -> None:
    config = _load_config()
    state = load_state(STATE_PATH)
    now = datetime.now(ZoneInfo(config.user_settings.timezone))
    if demo:
        chats = _demo_chats(now)
    else:
        chats = await _fetch(now)

    items = analyze(chats, config.circles, state, now)
    render_report(items, now, console)

    if not notify:
        return

    credentials = _credentials()
    token, chat_id = _require_bot(credentials, state.report_chat_id)
    try:
        await send_report(token, chat_id, items, now)
    except NotifyError as exc:
        _fail(str(exc))
    console.print("Relatório enviado.")


async def _serve() -> None:
    config = _load_config()
    credentials = _credentials()
    api_id, api_hash = _require_user_api(credentials)
    token = credentials.bot_token
    if token is None:
        _fail("Defina TELEGRAM_BOT_TOKEN no .env para o modo serve.")

    application = Application.builder().token(token).build()
    register_handlers(
        application,
        config_path=CONFIG_PATH,
        state_path=STATE_PATH,
        cache_path=CACHE_PATH,
        session_path=SESSION_PATH,
        api_id=api_id,
        api_hash=api_hash,
    )
    initialized = False
    started = False
    polling = False
    try:
        await application.initialize()
        initialized = True
        await application.start()
        started = True
        updater = application.updater
        if updater is None:
            _fail("O bot não iniciou o receptor de comandos.")
        await updater.start_polling()
        polling = True
        console.print(
            f"Bot ouvindo. Relatório às {config.user_settings.daily_report_hour} "
            f"({config.user_settings.timezone}), a cada {config.user_settings.report_interval_days} dia(s)."
        )
        while True:
            state = load_state(STATE_PATH)
            now = datetime.now(ZoneInfo(config.user_settings.timezone))
            delay = seconds_until_next_report(
                now,
                config.user_settings.daily_report_hour,
                config.user_settings.timezone,
                config.user_settings.report_interval_days,
                state.last_report_sent_at,
            )
            if delay > 0:
                logger.info("Próximo relatório em %.0f minutos.", delay / 60)
                await asyncio.sleep(delay)
            try:
                await _send_scheduled(config, token)
            except (NotifyError, SessionRequired, StorageError) as exc:
                logger.error("%s", exc)
                await asyncio.sleep(_RETRY_SECONDS)
            except Exception:
                logger.exception("Falha ao enviar o relatório agendado.")
                await asyncio.sleep(_RETRY_SECONDS)
    finally:
        if polling and application.updater is not None:
            await application.updater.stop()
        if started:
            await application.stop()
        if initialized:
            await application.shutdown()


async def _send_scheduled(config: AppConfig, token: str) -> None:
    now = datetime.now(ZoneInfo(config.user_settings.timezone))
    chats = await _fetch(now)
    state = load_state(STATE_PATH)
    items = analyze(chats, config.circles, state, now)
    render_report(items, now, console)
    chat_id = _resolve_chat_id(_credentials(), state.report_chat_id)
    await send_report(token, chat_id, items, now)
    state = load_state(STATE_PATH)
    state.last_report_sent_at = now
    save_state(STATE_PATH, state)
    console.print("Relatório agendado enviado.")


async def _fetch(now: datetime) -> list[ChatMetadata]:
    credentials = _credentials()
    api_id, api_hash = _require_user_api(credentials)
    client = MetadataClient(api_id, api_hash, SESSION_PATH)
    await client.connect()
    try:
        chats = await client.fetch_metadata()
    finally:
        await client.disconnect()
    save_metadata_cache(CACHE_PATH, chats, now)
    logger.info("Metadados coletados de %s conversas.", len(chats))
    return chats


def _demo_chats(now: datetime) -> list[ChatMetadata]:
    return [
        ChatMetadata(101, "Mãe", now - timedelta(days=5), False),
        ChatMetadata(102, "Vovó Teresa", now - timedelta(days=1), False),
        ChatMetadata(103, "Grupo do Futebol", now - timedelta(days=12, hours=3), True),
        ChatMetadata(104, "Ana Clara", now - timedelta(days=9), False),
        ChatMetadata(105, "Ana Clara Souza", now - timedelta(days=1), False),
        ChatMetadata(106, "Maestro", now - timedelta(days=40), False),
    ]


def _load_config() -> AppConfig:
    try:
        return load_config(CONFIG_PATH)
    except StorageError as exc:
        _fail(str(exc))


def _credentials() -> Credentials:
    api_id_raw = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip() or None
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or None
    chat_raw = os.getenv("TELEGRAM_REPORT_CHAT_ID", "").strip()
    api_id = int(api_id_raw) if api_id_raw.isdigit() else None
    chat_id = int(chat_raw) if chat_raw.lstrip("-").isdigit() else None
    return Credentials(api_id=api_id, api_hash=api_hash, bot_token=token, report_chat_id=chat_id)


def _require_user_api(credentials: Credentials) -> tuple[int, str]:
    if credentials.api_id is None or not credentials.api_hash:
        _fail("Defina TELEGRAM_API_ID e TELEGRAM_API_HASH no .env.")
    return credentials.api_id, credentials.api_hash


def _require_bot(credentials: Credentials, state_chat_id: int | None) -> tuple[str, int]:
    if not credentials.bot_token:
        _fail("Defina TELEGRAM_BOT_TOKEN no .env para enviar o relatório.")
    return credentials.bot_token, _resolve_chat_id(credentials, state_chat_id)


def _resolve_chat_id(credentials: Credentials, state_chat_id: int | None) -> int:
    chat_id = credentials.report_chat_id or state_chat_id
    if chat_id is None:
        _fail("Envie /start para o bot, ou defina TELEGRAM_REPORT_CHAT_ID no .env.")
    return chat_id


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for name in ("telethon", "telegram", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _fail(message: str) -> NoReturn:
    console.print(f"[red]{message}[/red]")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
