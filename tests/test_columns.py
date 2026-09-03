"""Tests for `yougile column`.

The sub-app is invoked directly with a prepared :class:`AppContext` so that these
tests do not depend on the root CLI wiring; exit codes are checked through
``exit_code_for``, which is exactly what the global handler in ``cli.py`` uses.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import pytest
import respx
from rich.console import Console
from typer.testing import CliRunner

from yougile_cli.client import YouGileClient
from yougile_cli.commands import columns as columns_module
from yougile_cli.commands.columns import app as column_app
from yougile_cli.config import ResolvedAuth
from yougile_cli.context import AppContext
from yougile_cli.errors import exit_code_for

from .conftest import BASE_URL, HOST, TEST_KEY

COLUMN_ID = "33333333-3333-4333-8333-333333333333"
BOARD_ID = "44444444-4444-4444-8444-444444444444"
OTHER_BOARD_ID = "55555555-5555-4555-8555-555555555555"

COLUMN = {"id": COLUMN_ID, "title": "В работе", "color": 3, "boardId": BOARD_ID}
OTHER = {
    "id": "66666666-6666-4666-8666-666666666666",
    "title": "Готово",
    "color": 5,
    "boardId": BOARD_ID,
}


@pytest.fixture
def app_ctx(client: YouGileClient) -> AppContext:
    ctx = AppContext(
        auth=ResolvedAuth(host=HOST, base_url=BASE_URL, api_key=TEST_KEY, source="flag"),
        console=Console(no_color=True, highlight=False, soft_wrap=True, width=200),
    )
    ctx.set_client(client)
    return ctx


@pytest.fixture
def invoke(runner: CliRunner, app_ctx: AppContext) -> Callable[..., Any]:
    def _invoke(args: list[str] | str, *, input: str | None = None) -> Any:
        argv = args.split() if isinstance(args, str) else list(args)
        return runner.invoke(column_app, argv, obj=app_ctx, input=input)

    return _invoke


def code(result: Any) -> int:
    """The exit code the root CLI would produce for this result."""
    exc = result.exception
    if exc is not None and not isinstance(exc, SystemExit):
        return exit_code_for(exc)
    return result.exit_code


def body(route: Any) -> Any:
    return json.loads(route.calls.last.request.content)


def params(route: Any) -> dict[str, str]:
    return dict(route.calls.last.request.url.params)


# --------------------------------------------------------------------------- list


def test_list_prints_columns(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    route = api.get("/api-v2/columns").respond(json=paged([COLUMN, OTHER]))
    result = invoke("list")
    assert code(result) == 0, result.output
    assert "В работе" in result.output
    assert "Готово" in result.output
    assert params(route)["limit"] == "30"


def test_list_limit_trims_rows(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    api.get("/api-v2/columns").respond(json=paged([COLUMN, OTHER]))
    result = invoke("list -L 1")
    assert code(result) == 0
    assert "В работе" in result.output
    assert "Готово" not in result.output


def test_list_resolves_board_name(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    api.get("/api-v2/boards").respond(json=paged([{"id": BOARD_ID, "title": "Спринт"}]))
    columns = api.get("/api-v2/columns").respond(json=paged([COLUMN]))
    result = invoke(["list", "--board", "Спринт"])
    assert code(result) == 0, result.output
    assert params(columns)["boardId"] == BOARD_ID


def test_list_search_and_include_deleted(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    route = api.get("/api-v2/columns").respond(json=paged([COLUMN]))
    result = invoke(["list", "--search", "В работе", "--include-deleted"])
    assert code(result) == 0
    query = params(route)
    assert query["title"] == "В работе"
    assert query["includeDeleted"] == "true"


def test_list_json_field_selection(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    api.get("/api-v2/columns").respond(json=paged([COLUMN]))
    result = invoke("list --json id,title")
    assert code(result) == 0, result.output
    assert json.loads(result.stdout) == [{"id": COLUMN_ID, "title": "В работе"}]


def test_list_json_without_fields_lists_them(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    api.get("/api-v2/columns").respond(json=paged([COLUMN]))
    result = invoke(["list", "--json", ""])
    assert code(result) == 1
    assert "boardId" in (result.exception.hint or "")


def test_list_unknown_json_field_fails(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    api.get("/api-v2/columns").respond(json=paged([COLUMN]))
    result = invoke("list --json id,nope")
    assert code(result) == 1


# --------------------------------------------------------------------------- view


def test_view_by_id(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    api.get(f"/api-v2/columns/{COLUMN_ID}").respond(json=COLUMN)
    result = invoke(["view", COLUMN_ID])
    assert code(result) == 0, result.output
    assert "В работе" in result.output


def test_view_resolves_column_name(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    listing = api.get("/api-v2/columns").respond(json=paged([COLUMN]))
    api.get(f"/api-v2/columns/{COLUMN_ID}").respond(json=COLUMN)
    result = invoke(["view", "В работе"])
    assert code(result) == 0, result.output
    assert params(listing)["title"] == "В работе"


# --------------------------------------------------------------------------- create


def test_create_posts_payload(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    route = api.post("/api-v2/columns").respond(201, json={"id": COLUMN_ID})
    result = invoke(["create", "В работе", "--board", BOARD_ID, "--color", "3"])
    assert code(result) == 0, result.output
    assert body(route) == {"title": "В работе", "boardId": BOARD_ID, "color": 3}
    assert COLUMN_ID[:8] in result.output


def test_create_rejects_color_out_of_palette(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    result = invoke(["create", "X", "--board", BOARD_ID, "--color", "17"])
    assert code(result) == 2


# --------------------------------------------------------------------------- edit


def test_edit_puts_changed_fields(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    route = api.put(f"/api-v2/columns/{COLUMN_ID}").respond(json={"id": COLUMN_ID})
    result = invoke(["edit", COLUMN_ID, "--title", "Готово", "--color", "5"])
    assert code(result) == 0, result.output
    assert body(route) == {"title": "Готово", "color": 5}


def test_edit_without_changes_is_usage_error(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    route = api.put(f"/api-v2/columns/{COLUMN_ID}")
    result = invoke(["edit", COLUMN_ID])
    assert code(result) == 2
    assert not route.called


# --------------------------------------------------------------------------- delete


def test_delete_is_a_put_with_deleted_true(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    route = api.put(f"/api-v2/columns/{COLUMN_ID}").respond(json={"id": COLUMN_ID})
    result = invoke(["delete", COLUMN_ID, "--yes"])
    assert code(result) == 0, result.output
    assert body(route) == {"deleted": True}


def test_delete_without_yes_and_without_tty_fails(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    route = api.put(f"/api-v2/columns/{COLUMN_ID}")
    result = invoke(["delete", COLUMN_ID])
    assert code(result) == 2
    assert not route.called


def test_interactive_survives_closed_stdin(
    app_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """При закрытом дескрипторе 0 sys.stdin равен None — это не должно ронять команду."""
    monkeypatch.setattr("sys.stdin", None)
    assert app_ctx.prompt_enabled is True
    assert columns_module._interactive(app_ctx) is False


def test_delete_declined_at_the_prompt(
    invoke: Callable[..., Any],
    api: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("yougile_cli.commands.columns._interactive", lambda _ctx: True)
    route = api.put(f"/api-v2/columns/{COLUMN_ID}")
    result = invoke(["delete", COLUMN_ID], input="n\n")
    assert code(result) == 1
    assert not route.called


def test_delete_prompt_names_the_target(
    invoke: Callable[..., Any],
    api: respx.MockRouter,
    paged: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Подтверждение должно называть то, что ввёл пользователь, а не обрывок UUID."""
    monkeypatch.setattr("yougile_cli.commands.columns._interactive", lambda _ctx: True)
    api.get("/api-v2/columns").respond(json=paged([OTHER]))
    route = api.put(f"/api-v2/columns/{OTHER['id']}")
    result = invoke(["delete", "Готово"], input="n\n")
    assert code(result) == 1
    assert "«Готово»" in result.output
    assert not route.called


# --------------------------------------------------------------------------- move


def test_move_changes_board_id(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    api.get("/api-v2/boards").respond(json=paged([{"id": OTHER_BOARD_ID, "title": "Архив"}]))
    route = api.put(f"/api-v2/columns/{COLUMN_ID}").respond(json={"id": COLUMN_ID})
    result = invoke(["move", COLUMN_ID, "--board", "Архив"])
    assert code(result) == 0, result.output
    assert body(route) == {"boardId": OTHER_BOARD_ID}


# --------------------------------------------------------------------------- errors


def test_api_error_exit_code(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    api.get(f"/api-v2/columns/{COLUMN_ID}").respond(404, json={"message": "not found"})
    result = invoke(["view", COLUMN_ID])
    assert code(result) == 1


# ------------------------------------------------------- defect 1: НАЗВАНИЕ и единые метавары


def latin_metavars(app: Any) -> list[str]:
    """Every metavar of every leaf command that still contains Latin letters."""
    from typer.main import get_command

    found: list[str] = []

    def walk(command: Any, path: str) -> None:
        subcommands = getattr(command, "commands", None)
        if subcommands:
            for name, child in subcommands.items():
                walk(child, f"{path} {name}".strip())
            return
        for param in command.params:
            if param.name in {"ctx", "help"} or getattr(param, "is_flag", False):
                continue
            metavar = param.metavar or ""
            # ID is an accepted metavar even though it is spelled with Latin letters.
            if not metavar or re.search(r"[A-Za-z]", metavar.replace("ID", "")):
                found.append(f"{path}: {param.name} -> {metavar!r}")

    walk(get_command(app), "column")
    return found


def test_column_commands_have_no_latin_metavars() -> None:
    assert latin_metavars(column_app) == []


def test_create_title_argument_uses_russian_metavar(invoke: Callable[..., Any]) -> None:
    result = invoke(["create", "--help"])
    assert "НАЗВАНИЕ" in result.output
    assert "ИМЯ " not in result.output


def test_create_accepts_title_flag(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    route = api.post("/api-v2/columns").respond(201, json=COLUMN)
    result = invoke(["create", "--title", "В работе", "--board", BOARD_ID])
    assert code(result) == 0, result.output
    assert body(route)["title"] == "В работе"


def test_create_accepts_positional_and_matching_flag(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    route = api.post("/api-v2/columns").respond(201, json=COLUMN)
    result = invoke(["create", "В работе", "--title", "В работе", "--board", BOARD_ID])
    assert code(result) == 0, result.output
    assert body(route)["title"] == "В работе"


def test_create_rejects_conflicting_titles(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    route = api.post("/api-v2/columns").respond(201, json=COLUMN)
    result = invoke(["create", "В работе", "--title", "Готово", "--board", BOARD_ID])
    assert code(result) == 2
    assert "дважды" in str(result.exception)
    assert not route.called


def test_create_without_title_is_usage_error(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    route = api.post("/api-v2/columns").respond(201, json=COLUMN)
    result = invoke(["create", "--board", BOARD_ID])
    assert code(result) == 2
    assert "Не указано название колонки." in str(result.exception)
    assert not route.called


# ------------------------------------------------------- defect 3: род и число в сообщениях


def test_missing_column_name_is_feminine(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    api.get("/api-v2/columns").respond(json=paged([]))
    result = invoke(["view", "нет-такой-колонки"])
    assert code(result) == 1
    assert str(result.exception) == "Колонка «нет-такой-колонки» не найдена."


def test_ambiguous_column_name_uses_plural_genitive(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    api.get("/api-v2/columns").respond(json=paged([COLUMN, {**COLUMN, "id": OTHER_BOARD_ID}]))
    result = invoke(["view", "В работе"])
    assert code(result) == 1
    assert "Найдено несколько (2) колонок с именем «В работе»." in str(result.exception)
