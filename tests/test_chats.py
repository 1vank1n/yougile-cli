"""Tests for the `chat` sub-app (src/yougile_cli/commands/chats.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner, Result

from yougile_cli.commands import chats as chats_module
from yougile_cli.commands.chats import app as chat_app
from yougile_cli.context import AppContext
from yougile_cli.errors import exit_code_for
from yougile_cli.output import OutputFormat, OutputOptions

CHAT_ID = "11111111-1111-4111-8111-111111111111"
OTHER_CHAT_ID = "22222222-2222-4222-8222-222222222222"
USER_ID = "33333333-3333-4333-8333-333333333333"
TASK_ID = "44444444-4444-4444-8444-444444444444"
BOARD_ID = "55555555-5555-4555-8555-555555555555"

CHAT = {"id": CHAT_ID, "title": "Общий"}
USER = {"id": USER_ID, "email": "ivan@example.com", "realName": "Иван"}
MESSAGE_OLD = {
    "id": 1,
    "fromUserId": USER_ID,
    "text": "первое",
    "textHtml": "<p>первое</p>",
    "label": "",
    "editTimestamp": 1700000000000,
}
MESSAGE_NEW = {
    "id": 2,
    "fromUserId": USER_ID,
    "text": "второе",
    "textHtml": "<p>второе</p>",
    "label": "",
    "editTimestamp": 1700000100000,
}

MESSAGES_PATH = f"/api-v2/chats/{CHAT_ID}/messages"


@pytest.fixture
def run(client: Any, runner: CliRunner) -> Any:
    """Run the chat sub-app with an AppContext wired to the mocked client."""

    def _run(args: list[str], fmt: str = "table", input: str | None = None) -> Result:
        root = typer.Typer()

        @root.callback()
        def _callback(ctx: typer.Context) -> None:
            app_ctx = AppContext(out=OutputOptions(fmt=OutputFormat(fmt)))
            app_ctx.set_client(client)
            ctx.obj = app_ctx

        root.add_typer(chat_app, name="chat")
        return runner.invoke(root, ["chat", *args], input=input)

    return _run


def code(result: Result) -> int:
    """The exit code the real CLI would produce (cli.py maps our errors)."""
    if result.exception is not None and not isinstance(result.exception, SystemExit):
        return exit_code_for(result.exception)
    return result.exit_code


def body(route: Any) -> dict[str, Any]:
    return json.loads(route.calls.last.request.content)


# --------------------------------------------------------------------------- list / view


def test_list_default_limit(api: Any, paged: Any, run: Any) -> None:
    route = api.get("/api-v2/group-chats").respond(json=paged([CHAT]))
    result = run(["list"])
    assert code(result) == 0, result.output
    assert "Общий" in result.output
    params = route.calls.last.request.url.params
    assert params["limit"] == "30"
    assert "includeDeleted" not in params


def test_list_search_and_include_deleted(api: Any, paged: Any, run: Any) -> None:
    route = api.get("/api-v2/group-chats").respond(json=paged([CHAT]))
    result = run(["list", "--search", "Общий", "--include-deleted", "--limit", "0"])
    assert code(result) == 0, result.output
    params = route.calls.last.request.url.params
    assert params["title"] == "Общий"
    assert params["includeDeleted"] == "true"
    assert params["limit"] == "1000"


def test_list_json_fields(api: Any, paged: Any, run: Any) -> None:
    api.get("/api-v2/group-chats").respond(json=paged([CHAT]))
    result = run(["list", "--json", "id,title"])
    assert code(result) == 0, result.output
    assert json.loads(result.stdout) == [{"id": CHAT_ID, "title": "Общий"}]


def test_list_json_without_fields_lists_them(api: Any, paged: Any, run: Any) -> None:
    api.get("/api-v2/group-chats").respond(json=paged([CHAT]))
    result = run(["list", "--json", ""])
    assert code(result) == 1


def test_view_resolves_name_to_id(api: Any, paged: Any, run: Any) -> None:
    lookup = api.get("/api-v2/group-chats").respond(json=paged([CHAT]))
    api.get(f"/api-v2/group-chats/{CHAT_ID}").respond(json=CHAT)
    result = run(["view", "Общий"])
    assert code(result) == 0, result.output
    assert lookup.calls.last.request.url.params["title"] == "Общий"
    assert "Общий" in result.output


def test_view_unknown_name_fails(api: Any, paged: Any, run: Any) -> None:
    api.get("/api-v2/group-chats").respond(json=paged([]))
    result = run(["view", "Нет такого"])
    assert code(result) == 1
    assert "Нет такого" in str(result.exception)


def test_view_not_found_exit_code(api: Any, run: Any) -> None:
    api.get(f"/api-v2/group-chats/{CHAT_ID}").respond(404, json={"message": "нет"})
    result = run(["view", CHAT_ID])
    assert code(result) == 1
    assert "не найден" in str(result.exception).lower()


# --------------------------------------------------------------------------- create / edit


def test_create_builds_membership(api: Any, paged: Any, run: Any) -> None:
    api.get("/api-v2/users").respond(json=paged([USER]))
    route = api.post("/api-v2/group-chats").respond(201, json={"id": CHAT_ID})
    result = run(["create", "Общий", "--user", "ivan@example.com=admin"])
    assert code(result) == 0, result.output
    sent = body(route)
    assert sent["title"] == "Общий"
    assert sent["users"] == {USER_ID: {"notified": True}}
    assert sent["userRoleMap"] == {USER_ID: "admin"}
    assert sent["roleConfigMap"]["admin"]["sendMessages"] is True


def test_create_without_users_is_usage_error(run: Any) -> None:
    """Domain errors take the `ошибка:`/`подсказка:` shape, not a click usage panel."""
    from yougile_cli.errors import ValidationError

    result = run(["create", "Общий"])
    assert code(result) == 2
    assert isinstance(result.exception, ValidationError)
    assert result.exception.hint


def test_edit_title(api: Any, run: Any) -> None:
    route = api.put(f"/api-v2/group-chats/{CHAT_ID}").respond(json={"id": CHAT_ID})
    result = run(["edit", CHAT_ID, "--title", "Новый"])
    assert code(result) == 0, result.output
    assert body(route) == {"title": "Новый"}


def test_edit_user_merges_current_membership(api: Any, paged: Any, run: Any) -> None:
    """PUT replaces the membership objects, so existing members must survive `--user`."""
    api.get("/api-v2/users").respond(json=paged([USER]))
    api.get(f"/api-v2/group-chats/{CHAT_ID}").respond(
        json={
            "id": CHAT_ID,
            "users": {"old-user": {"notified": False}},
            "userRoleMap": {"old-user": "owner"},
            "roleConfigMap": {"owner": {"sendMessages": True}},
        }
    )
    route = api.put(f"/api-v2/group-chats/{CHAT_ID}").respond(json={"id": CHAT_ID})
    result = run(["edit", CHAT_ID, "--user", "ivan@example.com"])
    assert code(result) == 0, result.output
    sent = body(route)
    assert sent["users"] == {"old-user": {"notified": False}, USER_ID: {"notified": True}}
    assert sent["userRoleMap"] == {"old-user": "owner", USER_ID: "user"}
    assert sent["roleConfigMap"]["owner"] == {"sendMessages": True}
    assert "user" in sent["roleConfigMap"]


def test_edit_without_changes_is_usage_error(run: Any) -> None:
    result = run(["edit", CHAT_ID])
    assert code(result) == 2


# --------------------------------------------------------------------------- delete


def test_delete_is_put_with_deleted_true(api: Any, run: Any) -> None:
    route = api.put(f"/api-v2/group-chats/{CHAT_ID}").respond(json={"id": CHAT_ID})
    result = run(["delete", CHAT_ID, "--yes"])
    assert code(result) == 0, result.output
    assert route.calls.last.request.method == "PUT"
    assert body(route) == {"deleted": True}


def test_delete_without_yes_needs_a_tty(api: Any, run: Any) -> None:
    api.put(f"/api-v2/group-chats/{CHAT_ID}").respond(json={"id": CHAT_ID})
    result = run(["delete", CHAT_ID])
    assert code(result) == 2
    assert "--yes" in (result.exception.hint or "")  # type: ignore[union-attr]


# --------------------------------------------------------------------------- send


def test_send_wraps_body_in_html(api: Any, run: Any) -> None:
    route = api.post(MESSAGES_PATH).respond(201, json={"id": 7})
    result = run(["send", CHAT_ID, "привет & пока"])
    assert code(result) == 0, result.output
    assert body(route) == {
        "text": "привет & пока",
        "textHtml": "<p>привет &amp; пока</p>",
        "label": "",
    }


def test_send_html_and_label_override(api: Any, run: Any) -> None:
    route = api.post(MESSAGES_PATH).respond(201, json={"id": 7})
    result = run(["send", CHAT_ID, "текст", "--html", "<b>текст</b>", "--label", "релиз"])
    assert code(result) == 0, result.output
    assert body(route) == {"text": "текст", "textHtml": "<b>текст</b>", "label": "релиз"}


def test_send_body_file(api: Any, run: Any, tmp_path: Path) -> None:
    note = tmp_path / "note.txt"
    note.write_text("из файла\n", encoding="utf-8")
    route = api.post(MESSAGES_PATH).respond(201, json={"id": 7})
    result = run(["send", CHAT_ID, "--body-file", str(note)])
    assert code(result) == 0, result.output
    assert body(route)["text"] == "из файла"


def test_send_without_body_is_usage_error(run: Any) -> None:
    result = run(["send", CHAT_ID])
    assert code(result) == 2


def test_send_to_task_url(api: Any, run: Any) -> None:
    """A task id is a valid chatId, so a task link addresses the task chat."""
    route = api.post(f"/api-v2/chats/{TASK_ID}/messages").respond(201, json={"id": 7})
    result = run(["send", f"https://ru.yougile.com/board/{BOARD_ID}#{TASK_ID}", "привет"])
    assert code(result) == 0, result.output
    assert body(route)["text"] == "привет"


def test_send_falls_back_to_task_lookup(api: Any, paged: Any, run: Any) -> None:
    api.get("/api-v2/group-chats").respond(json=paged([]))
    api.get("/api-v2/task-list").respond(json=paged([{"id": TASK_ID, "title": "Починить"}]))
    route = api.post(f"/api-v2/chats/{TASK_ID}/messages").respond(201, json={"id": 7})
    result = run(["send", "Починить", "готово"])
    assert code(result) == 0, result.output
    assert body(route)["text"] == "готово"


# --------------------------------------------------------------------------- messages


def test_messages_newest_last_in_table(api: Any, paged: Any, run: Any) -> None:
    api.get(MESSAGES_PATH).respond(json=paged([MESSAGE_NEW, MESSAGE_OLD]))
    result = run(["messages", CHAT_ID])
    assert code(result) == 0, result.output
    assert result.stdout.index("первое") < result.stdout.index("второе")


def test_messages_keep_api_order_in_json(api: Any, paged: Any, run: Any) -> None:
    api.get(MESSAGES_PATH).respond(json=paged([MESSAGE_NEW, MESSAGE_OLD]))
    result = run(["messages", CHAT_ID, "--json", "id,text"])
    assert code(result) == 0, result.output
    assert json.loads(result.stdout) == [
        {"id": 2, "text": "второе"},
        {"id": 1, "text": "первое"},
    ]


def test_messages_filters(api: Any, paged: Any, run: Any) -> None:
    api.get("/api-v2/users").respond(json=paged([USER]))
    route = api.get(MESSAGES_PATH).respond(json=paged([MESSAGE_OLD]))
    result = run(
        [
            "messages",
            CHAT_ID,
            "--from-user",
            "ivan@example.com",
            "--search",
            "релиз",
            "--label",
            "rel",
            "--since",
            "1700000000000",
            "--include-system",
            "--include-deleted",
            "--limit",
            "5",
        ]
    )
    assert code(result) == 0, result.output
    params = route.calls.last.request.url.params
    assert params["fromUserId"] == USER_ID
    assert params["text"] == "релиз"
    assert params["label"] == "rel"
    assert params["since"] == "1700000000000"
    assert params["includeSystem"] == "true"
    assert params["includeDeleted"] == "true"
    assert params["limit"] == "5"


def test_messages_since_accepts_iso_date(api: Any, paged: Any, run: Any) -> None:
    route = api.get(MESSAGES_PATH).respond(json=paged([MESSAGE_OLD]))
    result = run(["messages", CHAT_ID, "--since", "2024-05-01"])
    assert code(result) == 0, result.output
    assert int(route.calls.last.request.url.params["since"]) > 0


def test_messages_since_rejects_garbage(run: Any) -> None:
    result = run(["messages", CHAT_ID, "--since", "вчера"])
    assert code(result) == 2


# --------------------------------------------------------------------------- typing


def test_typing(api: Any, run: Any) -> None:
    route = api.post(f"/api-v2/chats/{CHAT_ID}/typing").respond(
        json={"chatId": CHAT_ID, "typedAt": 1700000000000}
    )
    result = run(["typing", CHAT_ID])
    assert code(result) == 0, result.output
    assert route.called


# --------------------------------------------------------------------------- message sub-app


def test_message_view(api: Any, run: Any) -> None:
    api.get(f"{MESSAGES_PATH}/2").respond(json=MESSAGE_NEW)
    result = run(["message", "view", CHAT_ID, "2"])
    assert code(result) == 0, result.output
    assert "второе" in result.output


def test_message_edit_react(api: Any, run: Any) -> None:
    route = api.put(f"{MESSAGES_PATH}/2").respond(json={"id": 2})
    result = run(["message", "edit", CHAT_ID, "2", "--react", "👍"])
    assert code(result) == 0, result.output
    assert body(route) == {"react": "👍"}


def test_message_edit_label(api: Any, run: Any) -> None:
    route = api.put(f"{MESSAGES_PATH}/2").respond(json={"id": 2})
    result = run(["message", "edit", CHAT_ID, "2", "--label", "итог"])
    assert code(result) == 0, result.output
    assert body(route) == {"label": "итог"}


def test_message_edit_rejects_unknown_reaction(run: Any) -> None:
    result = run(["message", "edit", CHAT_ID, "2", "--react", "🥑"])
    assert code(result) == 2


def test_message_edit_without_changes_is_usage_error(run: Any) -> None:
    result = run(["message", "edit", CHAT_ID, "2"])
    assert code(result) == 2


def test_message_delete_is_put_with_deleted_true(api: Any, run: Any) -> None:
    route = api.put(f"{MESSAGES_PATH}/2").respond(json={"id": 2})
    result = run(["message", "delete", CHAT_ID, "2", "--yes"])
    assert code(result) == 0, result.output
    assert route.calls.last.request.method == "PUT"
    assert body(route) == {"deleted": True}


def test_message_delete_without_yes_needs_a_tty(api: Any, run: Any) -> None:
    api.put(f"{MESSAGES_PATH}/2").respond(json={"id": 2})
    result = run(["message", "delete", CHAT_ID, "2"])
    assert code(result) == 2


def test_message_ambiguous_chat_name(api: Any, paged: Any, run: Any) -> None:
    """Неоднозначное имя — ошибка выполнения, а не вызова: код 1 (issue #9)."""
    api.get("/api-v2/group-chats").respond(
        json=paged([CHAT, {"id": OTHER_CHAT_ID, "title": "Общий чат"}])
    )
    result = run(["messages", "Общ"])
    assert code(result) == 1


def test_send_editor_refused_without_prompts(
    api: Any, run: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    launched: list[str] = []
    monkeypatch.setattr(chats_module, "open_editor", lambda text: launched.append(text))
    result = run(["send", CHAT_ID, "--editor"])
    assert code(result) == 2, result.output
    assert not launched


def test_send_editor(api: Any, run: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chats_module, "is_tty", lambda *_a: True)
    monkeypatch.setattr(chats_module, "open_editor", lambda text: "из редактора")
    route = api.post(MESSAGES_PATH).respond(201, json={"id": 7})
    result = run(["send", CHAT_ID, "--editor"])
    assert code(result) == 0, result.output
    assert body(route)["text"] == "из редактора"


# --------------------------------------------------------------------------- defect 1: аргументы


def test_create_accepts_title_option(api: Any, paged: Any, run: Any) -> None:
    """`--title` — синоним позиционного НАЗВАНИЕ (для скриптов)."""
    api.get("/api-v2/users").respond(json=paged([USER]))
    route = api.post("/api-v2/group-chats").respond(201, json={"id": CHAT_ID})
    result = run(["create", "--title", "Общий", "--user", "ivan@example.com"])
    assert code(result) == 0, result.output
    assert body(route)["title"] == "Общий"


def test_create_positional_and_option_must_agree(run: Any) -> None:
    result = run(["create", "Общий", "--title", "Другой", "--user", "ivan@example.com"])
    assert code(result) == 2
    assert "по-разному" in str(result.exception)


def test_create_without_title_is_usage_error(run: Any) -> None:
    result = run(["create", "--user", "ivan@example.com"])
    assert code(result) == 2
    assert "Не указано название чата" in str(result.exception)


def test_all_metavars_are_russian() -> None:
    """Ни одного латинского метавара: только слова из общего списка (плюс ID и URL)."""
    from typer.main import get_command

    latin_ok = {"ID", "URL"}
    seen: list[tuple[str, str, str | None]] = []

    def walk(command: Any, path: str) -> None:
        for param in command.params:
            if param.name == "help" or getattr(param, "is_flag", False):
                continue
            seen.append((path, str(param.name), param.metavar))
        for name, sub in getattr(command, "commands", {}).items():
            walk(sub, f"{path} {name}")

    walk(get_command(chats_module.app), "chat")
    assert seen
    for path, name, metavar in seen:
        assert metavar, f"{path} {name}: метавар не задан"
        assert metavar in latin_ok or not any("a" <= ch.lower() <= "z" for ch in metavar), (
            f"{path} {name}: латинский метавар {metavar}"
        )


# --------------------------------------------------------------------------- defect 10: вложения

FILE_UUID = "66666666-6666-4666-8666-666666666666"
FILE_NAME = "IMG_20260828_173932.jpg"
FILE_URL = f"https://yougile.com/user-data/{FILE_UUID}/{FILE_NAME}"
MESSAGE_FILE = {
    "id": 3,
    "fromUserId": USER_ID,
    "text": f"/root/#file:/user-data/{FILE_UUID}/{FILE_NAME}%3Fpreviews%5B%5D%3D480x480",
    "label": "",
    "editTimestamp": 1700000200000,
}
MESSAGE_HTML = {
    "id": 4,
    "fromUserId": USER_ID,
    "text": "<p>привет</p><p>мир</p>",
    "label": "",
    "editTimestamp": 1700000300000,
}


def test_messages_table_decodes_file_form(api: Any, paged: Any, run: Any) -> None:
    api.get(MESSAGES_PATH).respond(json=paged([MESSAGE_FILE]))
    result = run(["messages", CHAT_ID])
    assert code(result) == 0, result.output
    assert f"📎 {FILE_NAME}" in result.stdout
    assert "#file:" not in result.stdout
    assert "ВЛОЖЕНИЯ" in result.stdout
    assert FILE_URL in result.stdout
    assert "previews" not in result.stdout


def test_messages_table_strips_html(api: Any, paged: Any, run: Any) -> None:
    api.get(MESSAGES_PATH).respond(json=paged([MESSAGE_HTML]))
    result = run(["messages", CHAT_ID])
    assert code(result) == 0, result.output
    assert "<p>" not in result.stdout
    assert "привет" in result.stdout and "мир" in result.stdout


def test_messages_json_keeps_raw_message(api: Any, paged: Any, run: Any) -> None:
    """В машинных форматах ничего не преобразуется."""
    api.get(MESSAGES_PATH).respond(json=paged([MESSAGE_FILE, MESSAGE_HTML]))
    result = run(["messages", CHAT_ID], fmt="json")
    assert code(result) == 0, result.output
    payload = json.loads(result.stdout)
    assert payload[0]["text"] == MESSAGE_FILE["text"]
    assert payload[1]["text"] == MESSAGE_HTML["text"]
    assert "ВЛОЖЕНИЯ" not in result.stdout


# --------------------------------------------------------------------------- defect 8: адресация


def test_messages_by_task_link_with_code(api: Any, paged: Any, run: Any) -> None:
    """`…/team/<id>/#ILS-343` — код задачи, а не идентификатор чата."""
    api.get("/api-v2/task-list").respond(
        json=paged([{"id": TASK_ID, "title": "Починить", "idTaskProject": "ILS-343"}])
    )
    route = api.get(f"/api-v2/chats/{TASK_ID}/messages").respond(json=paged([MESSAGE_OLD]))
    result = run(["messages", "https://ru.yougile.com/team/a1b2c3d4e5f6/#ILS-343"])
    assert code(result) == 0, result.output
    assert route.called


def test_messages_by_bare_task_code(api: Any, paged: Any, run: Any) -> None:
    api.get("/api-v2/group-chats").respond(json=paged([]))
    api.get("/api-v2/task-list").respond(
        json=paged([{"id": TASK_ID, "title": "Починить", "idTaskProject": "ILS-343"}])
    )
    route = api.get(f"/api-v2/chats/{TASK_ID}/messages").respond(json=paged([MESSAGE_OLD]))
    result = run(["messages", "ILS-343"])
    assert code(result) == 0, result.output
    assert route.called


def test_not_found_chat_message_is_gendered(api: Any, paged: Any, run: Any) -> None:
    api.get("/api-v2/group-chats").respond(json=paged([]))
    result = run(["view", "нет-такого-чата"])
    assert code(result) == 1
    assert "Чат «нет-такого-чата» не найден." in str(result.exception)


def test_empty_chat_target_uses_the_shared_wording(run: Any) -> None:
    """Фразы про ресурсы берутся из errors.RESOURCES, а не пишутся руками."""
    from yougile_cli.errors import not_specified_message

    result = run(["messages", ""])
    assert code(result) == 1
    assert str(result.exception) == not_specified_message("чат")


ESCAPE_ATTACK = "Задача\x1b]52;c;aGFjaw==\x1b\\\x1b[2J\x1b[31mFAKE"
# Ожидаемый результат очистки выписан руками, а не посчитан тем же кодом.
ESCAPE_CLEAN = "Задача\ufffd]52;c;aGFjaw==\ufffd\\\ufffd[2J\ufffd[31mFAKE"


def test_messages_strip_escape_sequences(api: Any, paged: Any, run: Any) -> None:
    """Текст сообщения пишет кто угодно с доступом к чату (issue #1)."""
    api.get(MESSAGES_PATH).respond(
        json=paged([{**MESSAGE_OLD, "text": ESCAPE_ATTACK, "textHtml": f"<p>{ESCAPE_ATTACK}</p>"}])
    )
    result = run(["messages", CHAT_ID])
    assert code(result) == 0, result.output
    assert "\x1b" not in result.output
    assert ESCAPE_CLEAN in result.stdout


def test_chat_view_strips_escape_sequences(api: Any, paged: Any, run: Any) -> None:
    api.get(f"/api-v2/group-chats/{CHAT_ID}").respond(json={**CHAT, "title": ESCAPE_ATTACK})
    result = run(["view", CHAT_ID])
    assert code(result) == 0, result.output
    assert "\x1b" not in result.output
    assert ESCAPE_CLEAN in result.stdout


def test_attachment_block_strips_escape_sequences(api: Any, paged: Any, run: Any) -> None:
    """Имя вложения приходит из ссылки: %1b раскодируется в ESC до печати."""
    api.get(MESSAGES_PATH).respond(
        json=paged(
            [
                {
                    **MESSAGE_FILE,
                    "text": f"/root/#file:/user-data/{FILE_UUID}/a%1B%5B31mfake.jpg",
                }
            ]
        )
    )
    result = run(["messages", CHAT_ID])
    assert code(result) == 0, result.output
    assert "ВЛОЖЕНИЯ" in result.stdout
    assert "\x1b" not in result.output
    assert "a\ufffd[31mfake.jpg" in result.stdout
