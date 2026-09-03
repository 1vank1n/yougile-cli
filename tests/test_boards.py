"""Tests for the `board` sub-app (src/yougile_cli/commands/boards.py)."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest
import typer
from typer.testing import CliRunner, Result

from yougile_cli.commands import boards as boards_module
from yougile_cli.commands.boards import app as board_app
from yougile_cli.context import AppContext
from yougile_cli.errors import NotFoundError, ResolveError, ValidationError, exit_code_for
from yougile_cli.output import OutputFormat, OutputOptions

BOARD_ID = "11111111-1111-4111-8111-111111111111"
OTHER_BOARD_ID = "22222222-2222-4222-8222-222222222222"
PROJECT_ID = "33333333-3333-4333-8333-333333333333"
COLUMN_A = "44444444-4444-4444-8444-444444444444"
COLUMN_B = "55555555-5555-4555-8555-555555555555"
TASK_A = "66666666-6666-4666-8666-666666666666"
TASK_B = "77777777-7777-4777-8777-777777777777"

BOARD = {"id": BOARD_ID, "title": "Спринт", "projectId": PROJECT_ID}
PROJECT = {"id": PROJECT_ID, "title": "Разработка"}


@pytest.fixture
def run(client: Any, runner: CliRunner) -> Any:
    """Run the board sub-app with an AppContext wired to the mocked client."""

    def _run(args: list[str], fmt: str = "table", input: str | None = None) -> Result:
        root = typer.Typer()

        @root.callback()
        def _callback(ctx: typer.Context) -> None:
            app_ctx = AppContext(out=OutputOptions(fmt=OutputFormat(fmt)))
            app_ctx.set_client(client)
            ctx.obj = app_ctx

        root.add_typer(board_app, name="board")
        return runner.invoke(root, ["board", *args], input=input)

    return _run


def code(result: Result) -> int:
    """The exit code the real CLI would produce (cli.py maps our errors)."""
    if result.exception is not None and not isinstance(result.exception, SystemExit):
        return exit_code_for(result.exception)
    return result.exit_code


def body(route: Any) -> dict[str, Any]:
    return json.loads(route.calls.last.request.content)


# --------------------------------------------------------------------------- list


def test_list_default_limit(api: Any, paged: Any, run: Any) -> None:
    route = api.get("/api-v2/boards").respond(json=paged([BOARD]))
    result = run(["list"])
    assert code(result) == 0, result.output
    assert "Спринт" in result.output
    params = route.calls.last.request.url.params
    assert params["limit"] == "30"
    assert "includeDeleted" not in params


def test_list_limit_zero_pulls_everything(api: Any, paged: Any, run: Any) -> None:
    route = api.get("/api-v2/boards").respond(json=paged([BOARD]))
    result = run(["list", "--limit", "0"])
    assert code(result) == 0, result.output
    assert route.calls.last.request.url.params["limit"] == "1000"


def test_list_search_and_include_deleted(api: Any, paged: Any, run: Any) -> None:
    route = api.get("/api-v2/boards").respond(json=paged([{**BOARD, "deleted": True}]))
    result = run(["list", "--search", "Спринт", "--include-deleted"])
    assert code(result) == 0, result.output
    params = route.calls.last.request.url.params
    assert params["title"] == "Спринт"
    assert params["includeDeleted"] == "true"
    assert "DELETED" in result.output


def test_list_resolves_project_name_to_id(api: Any, paged: Any, run: Any) -> None:
    projects = api.get("/api-v2/projects").respond(json=paged([PROJECT]))
    boards = api.get("/api-v2/boards").respond(json=paged([BOARD]))
    result = run(["list", "--project", "Разработка"], fmt="ids")
    assert code(result) == 0, result.output
    assert result.stdout.strip() == BOARD_ID
    assert projects.called
    assert boards.calls.last.request.url.params["projectId"] == PROJECT_ID


def test_list_json_field_selection(api: Any, paged: Any, run: Any) -> None:
    api.get("/api-v2/boards").respond(json=paged([BOARD]))
    result = run(["list", "--json", "id,title"])
    assert code(result) == 0, result.output
    assert json.loads(result.stdout) == [{"id": BOARD_ID, "title": "Спринт"}]


def test_list_json_without_fields_lists_them(api: Any, paged: Any, run: Any) -> None:
    api.get("/api-v2/boards").respond(json=paged([BOARD]))
    result = run(["list", "--json", ""])
    assert code(result) == 1
    assert "projectId" in (getattr(result.exception, "hint", "") or "")


def test_list_unknown_json_field_fails(api: Any, paged: Any, run: Any) -> None:
    api.get("/api-v2/boards").respond(json=paged([BOARD]))
    result = run(["list", "--json", "nope"])
    assert code(result) == 1
    assert "nope" in str(result.exception)


# --------------------------------------------------------------------------- view


def test_view_by_id(api: Any, run: Any) -> None:
    api.get(f"/api-v2/boards/{BOARD_ID}").respond(json=BOARD)
    result = run(["view", BOARD_ID], fmt="json")
    assert code(result) == 0, result.output
    assert json.loads(result.stdout)["title"] == "Спринт"


def test_view_resolves_name_to_id(api: Any, paged: Any, run: Any) -> None:
    listing = api.get("/api-v2/boards").respond(json=paged([BOARD]))
    single = api.get(f"/api-v2/boards/{BOARD_ID}").respond(json=BOARD)
    result = run(["view", "Спринт"])
    assert code(result) == 0, result.output
    assert listing.calls.last.request.url.params["title"] == "Спринт"
    assert single.called


def test_view_ambiguous_name_fails(api: Any, paged: Any, run: Any) -> None:
    api.get("/api-v2/boards").respond(json=paged([BOARD, {**BOARD, "id": OTHER_BOARD_ID}]))
    result = run(["view", "Спринт"])
    assert isinstance(result.exception, ResolveError)
    assert code(result) == 2


def test_view_missing_board_is_not_found(api: Any, run: Any) -> None:
    api.get(f"/api-v2/boards/{BOARD_ID}").respond(404, json={"message": "not found"})
    result = run(["view", BOARD_ID])
    assert isinstance(result.exception, NotFoundError)
    assert code(result) == 1


# --------------------------------------------------------------------------- create


def test_create_sends_project_and_stickers(api: Any, paged: Any, run: Any) -> None:
    api.get("/api-v2/projects").respond(json=paged([PROJECT]))
    route = api.post("/api-v2/boards").respond(201, json={"id": BOARD_ID})
    result = run(["create", "Спринт", "--project", "Разработка", "--timer", "--no-assignee"])
    assert code(result) == 0, result.output
    assert body(route) == {
        "title": "Спринт",
        "projectId": PROJECT_ID,
        "stickers": {"timer": True, "assignee": False},
    }


def test_create_without_stickers_omits_them(api: Any, run: Any) -> None:
    route = api.post("/api-v2/boards").respond(201, json={"id": BOARD_ID})
    result = run(["create", "Спринт", "--project", PROJECT_ID])
    assert code(result) == 0, result.output
    assert body(route) == {"title": "Спринт", "projectId": PROJECT_ID}


# --------------------------------------------------------------------------- edit


def test_edit_title_and_sticker(api: Any, run: Any) -> None:
    route = api.put(f"/api-v2/boards/{BOARD_ID}").respond(json={"id": BOARD_ID})
    result = run(["edit", BOARD_ID, "--title", "Новая", "--no-timer", "--time-tracking"])
    assert code(result) == 0, result.output
    assert body(route) == {
        "title": "Новая",
        "stickers": {"timer": False, "timeTracking": True},
    }


def test_edit_moves_board_to_resolved_project(api: Any, paged: Any, run: Any) -> None:
    api.get("/api-v2/projects").respond(json=paged([PROJECT]))
    route = api.put(f"/api-v2/boards/{BOARD_ID}").respond(json={"id": BOARD_ID})
    result = run(["edit", BOARD_ID, "--project", "Разработка"])
    assert code(result) == 0, result.output
    assert body(route) == {"projectId": PROJECT_ID}


def test_edit_without_changes_is_usage_error(api: Any, run: Any) -> None:
    route = api.put(f"/api-v2/boards/{BOARD_ID}")
    result = run(["edit", BOARD_ID])
    assert code(result) == 2
    assert not route.called
    # gh-spec §8: a domain error, not a click usage panel.
    assert isinstance(result.exception, ValidationError)


# --------------------------------------------------------------------------- delete


def test_delete_is_put_with_deleted_true(api: Any, run: Any) -> None:
    route = api.put(f"/api-v2/boards/{BOARD_ID}").respond(json={"id": BOARD_ID})
    result = run(["delete", BOARD_ID, "--yes"])
    assert code(result) == 0, result.output
    assert route.calls.last.request.method == "PUT"
    assert body(route) == {"deleted": True}


def test_delete_without_tty_requires_yes(api: Any, run: Any) -> None:
    route = api.put(f"/api-v2/boards/{BOARD_ID}").respond(json={"id": BOARD_ID})
    result = run(["delete", BOARD_ID])
    assert isinstance(result.exception, ValidationError)
    assert code(result) == 2
    assert not route.called


def test_list_rejects_negative_limit(run: Any) -> None:
    """A negative -L used to mean "download everything"."""
    assert run(["list", "-L", "-1"]).exit_code == 2


def test_delete_confirmed_interactively(
    api: Any, run: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(boards_module, "_stdin_is_tty", lambda: True)
    route = api.put(f"/api-v2/boards/{BOARD_ID}").respond(json={"id": BOARD_ID})
    result = run(["delete", BOARD_ID], input="y\n")
    assert code(result) == 0, result.output
    assert body(route) == {"deleted": True}


def test_delete_declined_interactively(api: Any, run: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(boards_module, "_stdin_is_tty", lambda: True)
    route = api.put(f"/api-v2/boards/{BOARD_ID}").respond(json={"id": BOARD_ID})
    result = run(["delete", BOARD_ID], input="n\n")
    assert code(result) == 1
    assert not route.called


# --------------------------------------------------------------------------- tree


def _mock_tree(api: Any, paged: Any) -> None:
    api.get(f"/api-v2/boards/{BOARD_ID}").respond(json=BOARD)
    api.get("/api-v2/columns").respond(
        json=paged(
            [
                {"id": COLUMN_A, "title": "Todo", "boardId": BOARD_ID},
                {"id": COLUMN_B, "title": "Done", "boardId": BOARD_ID},
            ]
        )
    )
    tasks = {
        COLUMN_A: [{"id": TASK_A, "title": "Задача A", "completed": False}],
        COLUMN_B: [{"id": TASK_B, "title": "Задача B", "completed": True}],
    }

    def _tasks(request: httpx.Request) -> httpx.Response:
        column_id = request.url.params.get("columnId", "")
        return httpx.Response(200, json=paged(tasks.get(column_id, [])))

    api.get("/api-v2/task-list").mock(side_effect=_tasks)


def test_tree_table_output(api: Any, paged: Any, run: Any) -> None:
    _mock_tree(api, paged)
    result = run(["tree", BOARD_ID])
    assert code(result) == 0, result.output
    for text in ("Спринт", "Todo", "Done", "Задача A"):
        assert text in result.output
    assert "✓ Задача B" in result.output


def test_tree_json_is_nested(api: Any, paged: Any, run: Any) -> None:
    _mock_tree(api, paged)
    result = run(["tree", BOARD_ID], fmt="json")
    assert code(result) == 0, result.output
    data = json.loads(result.stdout)
    assert data["id"] == BOARD_ID
    assert [c["title"] for c in data["columns"]] == ["Todo", "Done"]
    assert data["columns"][1]["tasks"] == [{"id": TASK_B, "title": "Задача B", "completed": True}]


def test_tree_limits_tasks_per_column(api: Any, paged: Any, run: Any) -> None:
    _mock_tree(api, paged)
    tasks = api.get("/api-v2/task-list")
    result = run(["tree", BOARD_ID, "--limit", "5", "--include-deleted"], fmt="json")
    assert code(result) == 0, result.output
    params = tasks.calls.last.request.url.params
    assert params["limit"] == "5"
    assert params["includeDeleted"] == "true"


def test_tree_titles_with_brackets_are_not_markup(api: Any, paged: Any, run: Any) -> None:
    """Заголовки приходят с сервера: скобки в них не должны разбираться как разметка rich."""
    api.get(f"/api-v2/boards/{BOARD_ID}").respond(json=BOARD)
    api.get("/api-v2/columns").respond(
        json=paged([{"id": COLUMN_A, "title": "Todo", "boardId": BOARD_ID}])
    )
    api.get("/api-v2/task-list").respond(
        json=paged(
            [
                {"id": TASK_A, "title": "починить [/b] логин", "completed": False},
                {"id": TASK_B, "title": "[wip] релиз", "completed": False},
            ]
        )
    )
    result = run(["tree", BOARD_ID])
    assert code(result) == 0, result.output
    assert "починить [/b] логин" in result.output
    assert "[wip] релиз" in result.output


def test_tree_empty_column(api: Any, paged: Any, run: Any) -> None:
    api.get(f"/api-v2/boards/{BOARD_ID}").respond(json=BOARD)
    api.get("/api-v2/columns").respond(
        json=paged([{"id": COLUMN_A, "title": "Todo", "boardId": BOARD_ID}])
    )
    api.get("/api-v2/task-list").respond(json=paged([]))
    result = run(["tree", BOARD_ID])
    assert code(result) == 0, result.output
    assert "нет задач" in result.output


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

    walk(get_command(app), "board")
    return found


def test_board_commands_have_no_latin_metavars() -> None:
    assert latin_metavars(board_app) == []


def test_create_title_argument_uses_russian_metavar(run: Any) -> None:
    result = run(["create", "--help"])
    assert "НАЗВАНИЕ" in result.output
    assert "TITLE" not in result.output


def test_create_accepts_title_flag(api: Any, run: Any) -> None:
    route = api.post("/api-v2/boards").respond(201, json={"id": BOARD_ID})
    result = run(["create", "--title", "Спринт", "--project", PROJECT_ID])
    assert code(result) == 0, result.output
    assert body(route)["title"] == "Спринт"


def test_create_accepts_positional_and_matching_flag(api: Any, run: Any) -> None:
    route = api.post("/api-v2/boards").respond(201, json={"id": BOARD_ID})
    result = run(["create", "Спринт", "--title", "Спринт", "--project", PROJECT_ID])
    assert code(result) == 0, result.output
    assert body(route)["title"] == "Спринт"


def test_create_rejects_conflicting_titles(api: Any, run: Any) -> None:
    route = api.post("/api-v2/boards").respond(201, json={"id": BOARD_ID})
    result = run(["create", "Спринт", "--title", "Другая", "--project", PROJECT_ID])
    assert code(result) == 2
    assert isinstance(result.exception, ValidationError)
    assert not route.called


def test_create_without_title_is_usage_error(api: Any, run: Any) -> None:
    route = api.post("/api-v2/boards").respond(201, json={"id": BOARD_ID})
    result = run(["create", "--project", PROJECT_ID])
    assert code(result) == 2
    assert "Не указано название доски." in str(result.exception)
    assert not route.called


# ------------------------------------------------------- defect 3: род и число в сообщениях


def test_missing_board_name_is_feminine(api: Any, paged: Any, run: Any) -> None:
    api.get("/api-v2/boards").respond(json=paged([]))
    result = run(["view", "нет-такой-доски"])
    assert code(result) == 1
    assert str(result.exception) == "Доска «нет-такой-доски» не найдена."


def test_ambiguous_board_name_uses_plural_genitive(api: Any, paged: Any, run: Any) -> None:
    api.get("/api-v2/boards").respond(json=paged([BOARD, {**BOARD, "id": OTHER_BOARD_ID}]))
    result = run(["view", "Спринт"])
    assert code(result) == 2
    assert "Найдено несколько (2) досок с именем «Спринт»." in str(result.exception)
