"""Behavior of the saudade index, local storage, and the metadata boundary."""

from __future__ import annotations

import ast
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from social_debt_tracker.analyzer import GROUP_OPENERS, OPENERS, analyze, suggestion_for
from social_debt_tracker.config_store import (
    StorageError,
    load_config,
    load_metadata_cache,
    load_state,
    save_metadata_cache,
    save_state,
    set_manual_contact,
    set_snooze,
)
from social_debt_tracker.models import AppState, ChatMetadata, Circle, DebtStatus
from social_debt_tracker.names import contact_key, normalize_name
from social_debt_tracker.report import build_report_text, format_days, format_index
from social_debt_tracker.schedule import next_report_at
from social_debt_tracker.telegram_client import metadata_from_dialog

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)


def _chat(name: str, days_ago: float, chat_id: int = 1, group: bool = False) -> ChatMetadata:
    return ChatMetadata(
        chat_id=chat_id,
        name=name,
        last_message_at=NOW - timedelta(days=days_ago),
        is_group=group,
    )


def _circle(name: str, target: int, contacts: list[str]) -> Circle:
    return Circle(name=name, target_days=target, contacts=tuple(contacts))


class NameTests(unittest.TestCase):
    def test_normalize_ignores_case_and_accents(self) -> None:
        self.assertEqual(normalize_name("  Vovó   Teresa "), normalize_name("vovo teresa"))

    def test_contact_key_is_stable_and_short(self) -> None:
        self.assertEqual(contact_key("Mãe"), contact_key("mae"))
        self.assertEqual(len(contact_key("Ana Clara")), 12)
        self.assertTrue(contact_key("Ana Clara").isalnum())


class AnalyzerTests(unittest.TestCase):
    def test_overdue_due_and_on_track(self) -> None:
        items = analyze(
            [
                _chat("Mãe", 5, 1),
                _chat("Vovó Teresa", 1, 2),
                _chat("Ana Clara", 9, 3),
            ],
            [
                _circle("Círculo Íntimo", 3, ["Mãe", "Vovó Teresa"]),
                _circle("Amigos Próximos", 10, ["Ana Clara"]),
            ],
            AppState(),
            NOW,
        )
        by_name = {item.contact_name: item for item in items}
        self.assertEqual(by_name["Mãe"].status, DebtStatus.OVERDUE)
        self.assertAlmostEqual(by_name["Mãe"].saudade_index or 0, 5 / 3, places=5)
        self.assertEqual(by_name["Vovó Teresa"].status, DebtStatus.ON_TRACK)
        self.assertEqual(by_name["Ana Clara"].status, DebtStatus.DUE)
        self.assertIn(by_name["Mãe"].suggestion, OPENERS)
        self.assertIsNone(by_name["Vovó Teresa"].suggestion)

    def test_exact_name_wins_over_a_longer_title(self) -> None:
        items = analyze(
            [_chat("Ana Clara", 1, 1), _chat("Ana Clara Souza", 20, 2)],
            [_circle("Amigos", 10, ["Ana Clara"])],
            AppState(),
            NOW,
        )
        self.assertEqual(items[0].chat_id, 1)
        self.assertEqual(items[0].status, DebtStatus.ON_TRACK)

    def test_short_name_does_not_match_inside_another_word(self) -> None:
        items = analyze(
            [_chat("Maestro", 30, 1)],
            [_circle("Círculo Íntimo", 3, ["Mãe"])],
            AppState(),
            NOW,
        )
        self.assertEqual(items[0].status, DebtStatus.UNKNOWN)
        self.assertIsNone(items[0].chat_id)

    def test_unique_word_extension_matches(self) -> None:
        items = analyze(
            [_chat("Ana Clara Souza", 11, 4)],
            [_circle("Amigos", 10, ["Ana Clara"])],
            AppState(),
            NOW,
        )
        self.assertEqual(items[0].status, DebtStatus.OVERDUE)
        self.assertEqual(items[0].matched_name, "Ana Clara Souza")

    def test_two_extensions_are_ambiguous(self) -> None:
        items = analyze(
            [_chat("Ana Clara", 1, 1), _chat("Ana Beatriz", 1, 2)],
            [_circle("Amigos", 10, ["Ana"])],
            AppState(),
            NOW,
        )
        self.assertEqual(items[0].status, DebtStatus.AMBIGUOUS)
        self.assertIsNone(items[0].chat_id)

    def test_manual_contact_overrides_an_older_telegram_timestamp(self) -> None:
        state = AppState()
        set_manual_contact(state, "Mãe", NOW - timedelta(hours=2))
        items = analyze(
            [_chat("Mãe", 10, 1)],
            [_circle("Círculo Íntimo", 3, ["Mãe"])],
            state,
            NOW,
        )
        self.assertEqual(items[0].status, DebtStatus.ON_TRACK)
        self.assertLess(items[0].days_since or 0, 1)

    def test_active_snooze_keeps_the_number_and_changes_status(self) -> None:
        state = AppState()
        set_snooze(state, "Mãe", NOW + timedelta(days=1))
        items = analyze(
            [_chat("Mãe", 5, 1)],
            [_circle("Círculo Íntimo", 3, ["Mãe"])],
            state,
            NOW,
        )
        self.assertEqual(items[0].status, DebtStatus.SNOOZED)
        self.assertAlmostEqual(items[0].days_since or 0, 5, places=5)
        self.assertIsNone(items[0].suggestion)

    def test_future_timestamp_counts_as_today(self) -> None:
        items = analyze(
            [_chat("Mãe", -1, 1)],
            [_circle("Círculo Íntimo", 3, ["Mãe"])],
            AppState(),
            NOW,
        )
        self.assertEqual(items[0].days_since, 0)
        self.assertEqual(items[0].status, DebtStatus.ON_TRACK)

    def test_group_hook_is_not_a_person_hook(self) -> None:
        items = analyze(
            [_chat("Grupo do Futebol", 12, 3, group=True)],
            [_circle("Amigos", 10, ["Grupo do Futebol"])],
            AppState(),
            NOW,
        )
        self.assertIn(items[0].suggestion, GROUP_OPENERS)

    def test_suggestion_depends_on_the_day_not_on_message_text(self) -> None:
        first = suggestion_for("Mãe", NOW)
        second = suggestion_for("mãe", NOW)
        later = suggestion_for("Mãe", NOW + timedelta(days=3))
        self.assertEqual(first, second)
        self.assertIn(first, OPENERS)
        self.assertIn(later, OPENERS)

    def test_naive_clock_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            analyze([], [], AppState(), datetime(2026, 10, 29, 15, 0))


class ScheduleTests(unittest.TestCase):
    def test_waits_for_todays_slot_on_first_run(self) -> None:
        now = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)
        target = next_report_at(now, "10:00", "UTC", 1, None)
        self.assertEqual(target.timestamp(), datetime(2026, 10, 29, 10, 0, tzinfo=timezone.utc).timestamp())

    def test_sends_immediately_when_the_slot_was_missed(self) -> None:
        now = datetime(2026, 10, 29, 11, 0, tzinfo=timezone.utc)
        target = next_report_at(now, "10:00", "UTC", 1, None)
        self.assertEqual(target.timestamp(), now.timestamp())

    def test_daily_interval_moves_to_tomorrow_after_a_send(self) -> None:
        now = datetime(2026, 10, 29, 11, 0, tzinfo=timezone.utc)
        last = datetime(2026, 10, 29, 10, 0, tzinfo=timezone.utc)
        target = next_report_at(now, "10:00", "UTC", 1, last)
        self.assertEqual(target.timestamp(), datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc).timestamp())

    def test_weekly_interval_waits_out_the_gap(self) -> None:
        now = datetime(2026, 10, 29, 11, 0, tzinfo=timezone.utc)
        last = datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc)
        target = next_report_at(now, "10:00", "UTC", 7, last)
        self.assertEqual(target.timestamp(), datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc).timestamp())


class ReportTests(unittest.TestCase):
    def test_formats_with_decimal_comma(self) -> None:
        self.assertEqual(format_days(5), "5,0")
        self.assertEqual(format_index(5 / 3), "1,67×")
        self.assertEqual(format_days(None), "—")

    def test_report_escapes_names_and_states_the_privacy_limit(self) -> None:
        items = analyze(
            [_chat("Mãe <3", 5, 1)],
            [_circle("Círculo & Íntimo", 3, ["Mãe <3"])],
            AppState(),
            NOW,
        )
        text = build_report_text(items, NOW)
        self.assertIn("Mãe &lt;3", text)
        self.assertIn("Círculo &amp; Íntimo", text)
        self.assertIn("O texto das conversas não entra neste relatório.", text)
        self.assertNotIn("<3", text.replace("&lt;3", ""))


class StorageTests(unittest.TestCase):
    def test_spec_document_uses_safe_defaults(self) -> None:
        spec = {
            "user_settings": {"daily_report_hour": "10:00", "privacy_mode": True},
            "circles": [
                {"name": "Círculo Íntimo", "target_days": 3, "contacts": ["Mãe", "Vovó Teresa"]},
                {"name": "Amigos Próximos", "target_days": 10, "contacts": ["Grupo do Futebol", "Ana Clara"]},
            ],
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            config = load_config(path)
        self.assertEqual(config.user_settings.timezone, "America/Sao_Paulo")
        self.assertEqual(config.user_settings.report_interval_days, 1)
        self.assertTrue(config.user_settings.privacy_mode)
        self.assertEqual(config.circles[0].contacts, ("Mãe", "Vovó Teresa"))

    def test_shipped_config_loads(self) -> None:
        config = load_config(ROOT / "config.json")
        self.assertEqual(config.user_settings.daily_report_hour, "10:00")

    def test_privacy_mode_cannot_be_disabled(self) -> None:
        raw = {
            "user_settings": {"daily_report_hour": "10:00", "privacy_mode": False},
            "circles": [{"name": "A", "target_days": 3, "contacts": ["Mãe"]}],
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(StorageError):
                load_config(path)

    def test_state_and_cache_roundtrip_keep_metadata_only(self) -> None:
        state = AppState(report_chat_id=42)
        set_manual_contact(state, "Mãe", NOW)
        set_snooze(state, "Ana Clara", NOW + timedelta(days=1))
        state.last_report_sent_at = NOW
        chats = [_chat("Mãe", 2, 9)]
        with tempfile.TemporaryDirectory() as folder:
            folder_path = Path(folder)
            save_state(folder_path / "state.json", state)
            restored = load_state(folder_path / "state.json")
            save_metadata_cache(folder_path / "metadata.json", chats, NOW)
            cached = load_metadata_cache(folder_path / "metadata.json")
            payload = json.loads((folder_path / "metadata.json").read_text(encoding="utf-8"))

        self.assertEqual(restored.report_chat_id, 42)
        self.assertIsNotNone(restored.contact_map[contact_key("Mãe")].manual_last_contact)
        self.assertEqual(cached[0].name, "Mãe")
        self.assertEqual(set(payload["chats"][0]), {"chat_id", "name", "last_message_at", "is_group"})


class PrivacyBoundaryTests(unittest.TestCase):
    def test_extractor_never_reads_the_message_payload(self) -> None:
        class Dialog:
            name = "Mãe"
            id = 15
            date = NOW
            is_group = False
            is_user = True
            entity = object()

            @property
            def message(self) -> object:
                raise AssertionError("payload da mensagem foi lido")

            @property
            def text(self) -> str:
                raise AssertionError("texto foi lido")

            @property
            def raw_text(self) -> str:
                raise AssertionError("texto foi lido")

        metadata = metadata_from_dialog(Dialog())  # type: ignore[arg-type]
        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual(metadata.chat_id, 15)
        self.assertEqual(metadata.name, "Mãe")
        self.assertEqual(metadata.last_message_at, NOW)

    def test_client_source_does_not_touch_message_attributes(self) -> None:
        source = (ROOT / "social_debt_tracker" / "telegram_client.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = {"message", "raw_text", "text", "message_text"}
        found = [
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in forbidden
        ]
        self.assertEqual(found, [])
        self.assertIn("receive_updates=False", source)
        self.assertNotIn("NewMessage", source)
        self.assertNotIn("iter_messages", source)

    def test_bots_and_broadcast_channels_are_skipped(self) -> None:
        from telethon.tl.types import Channel, User

        class FakeUser(User):
            def __init__(self, bot: bool) -> None:
                self.bot = bot

        class FakeChannel(Channel):
            def __init__(self, megagroup: bool) -> None:
                self.megagroup = megagroup

        class Dialog:
            def __init__(self, entity: object, group: bool = False, user: bool = False) -> None:
                self.name = "Algo"
                self.id = 1
                self.date = NOW
                self.entity = entity
                self.is_group = group
                self.is_user = user

        self.assertIsNone(metadata_from_dialog(Dialog(FakeUser(bot=True), user=True)))  # type: ignore[arg-type]
        self.assertIsNotNone(metadata_from_dialog(Dialog(FakeUser(bot=False), user=True)))  # type: ignore[arg-type]
        self.assertIsNone(metadata_from_dialog(Dialog(FakeChannel(megagroup=False))))  # type: ignore[arg-type]
        self.assertIsNotNone(metadata_from_dialog(Dialog(FakeChannel(megagroup=True), group=True)))  # type: ignore[arg-type]


class KeyboardTests(unittest.TestCase):
    def test_callback_data_fits_telegram_limit(self) -> None:
        from social_debt_tracker.notifier import build_keyboard

        items = analyze(
            [_chat("Vovó Teresa", 5, 1), _chat("Ana Clara", 9, 2)],
            [
                _circle("Círculo Íntimo", 3, ["Vovó Teresa"]),
                _circle("Amigos Próximos", 10, ["Ana Clara"]),
            ],
            AppState(),
            NOW,
        )
        keyboard = build_keyboard(items)
        self.assertIsNotNone(keyboard)
        assert keyboard is not None
        callbacks = [button.callback_data or "" for row in keyboard.inline_keyboard for button in row]
        self.assertTrue(callbacks)
        self.assertTrue(all(len(data.encode("utf-8")) <= 64 for data in callbacks))
        self.assertTrue(any(data.endswith(":ok") for data in callbacks))
        self.assertTrue(all(len(button.text) <= 64 for row in keyboard.inline_keyboard for button in row))


if __name__ == "__main__":
    unittest.main()
