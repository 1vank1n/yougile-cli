"""Tests for `yougile department` (list/view/create/edit/delete/tree)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import respx
import typer
from rich.console import Console
from typer.testing import CliRunner

from yougile_cli.client import YouGileClient
from yougile_cli.commands.departments import app as department_app
from yougile_cli.context import AppContext
from yougile_cli.errors import YouGileError, exit_code_for
from yougile_cli.output import OutputFormat, OutputOptions

PATH = "/api-v2/departments"
SALES_ID = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
DEV_ID = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
QA_ID = "cccccccc-3333-4333-8333-cccccccccccc"
USER_ID = "dddddddd-4444-4444-8444-dddddddddddd"

SALES = {"id": SALES_ID, "title": "Продажи", "parentId": "", "deleted": False}
DEV = {"id": DEV_ID, "title": "Разработка", "parentId": "", "deleted": False}
QA = {"id": QA_ID, "title": "Тестирование", "parentId": DEV_ID, "deleted": False}


@pytest.fixture
def dept(runner: CliRunner, client: YouGileClient, api: respx.MockRouter) -> Callable[..., Any]:
    """Run `department …` against an AppContext holding the mocked client."""

    def _run(
        args: list[str] | str,
        *,
        input: str | None = None,
        fmt: OutputFormat = OutputFormat.TABLE,
    ) -> Any:
        app_ctx = AppContext(
            out=OutputOptions(fmt=fmt),
            console=Console(width=200, no_color=True, highlight=False),
        )
        app_ctx.set_client(client)

        cli = typer.Typer()
        cli.add_typer(department_app, name="department")

        @cli.callback()
        def _root(ctx: typer.Context) -> None:
            ctx.obj = app_ctx

        argv = args.split() if isinstance(args, str) else list(args)
        result = runner.invoke(cli, ["department", *argv], input=input)
        # cli.py owns the global handler; mirror its exit-code mapping here.
        if isinstance(result.exception, YouGileError):
            result.code = exit_code_for(result.exception)
        else:
            result.code = result.exit_code
        return result

    return _run


# --------------------------------------------------------------------------- list


def test_list_prints_departments(dept, api, paged) -> None:
    route = api.get(PATH).respond(json=paged([SALES, DEV]))
    result = dept("list")
    assert result.code == 0, result.output
    assert "Продажи" in result.stdout
    assert "Разработка" in result.stdout
    assert route.calls.last.request.url.params["limit"] == "30"


def test_list_search_and_include_deleted(dept, api, paged) -> None:
    route = api.get(PATH).respond(json=paged([SALES]))
    result = dept(["list", "--search", "Прод", "--include-deleted", "-L", "5"])
    assert result.code == 0, result.output
    params = route.calls.last.request.url.params
    assert params["title"] == "Прод"
    assert params["includeDeleted"] == "true"
    assert params["limit"] == "5"


def test_list_resolves_parent_name_to_id(dept, api, paged) -> None:
    """`--parent Разработка` is looked up by title before filtering."""
    lookup = api.get(PATH, params={"title": "Разработка"}).respond(json=paged([DEV]))
    listing = api.get(PATH, params={"parentId": DEV_ID}).respond(json=paged([QA]))
    result = dept(["list", "--parent", "Разработка"])
    assert result.code == 0, result.output
    assert lookup.called and listing.called
    assert "Тестирование" in result.stdout


def test_list_limit_zero_fetches_everything(dept, api, paged) -> None:
    route = api.get(PATH).respond(json=paged([SALES]))
    result = dept(["list", "--limit", "0"])
    assert result.code == 0, result.output
    assert route.calls.last.request.url.params["limit"] == "1000"


# --------------------------------------------------------------------------- view


def test_view_by_id(dept, api) -> None:
    route = api.get(f"{PATH}/{SALES_ID}").respond(json=SALES)
    result = dept(["view", SALES_ID])
    assert result.code == 0, result.output
    assert route.called
    assert "Продажи" in result.stdout


# --------------------------------------------------------------------------- create


def test_create_with_parent_and_user(dept, api, paged) -> None:
    api.get(PATH, params={"title": "Разработка"}).respond(json=paged([DEV]))
    api.get("/api-v2/users").respond(
        json=paged([{"id": USER_ID, "email": "ivan@example.com", "realName": "Иван"}])
    )
    created = api.post(PATH).respond(201, json={"id": QA_ID})
    result = dept(
        ["create", "Тестирование", "--parent", "Разработка", "--user", "ivan@example.com=admin"]
    )
    assert result.code == 0, result.output
    body = json.loads(created.calls.last.request.content)
    assert body == {
        "title": "Тестирование",
        "parentId": DEV_ID,
        "users": {USER_ID: "admin"},
    }


def test_create_minimal(dept, api) -> None:
    created = api.post(PATH).respond(201, json={"id": SALES_ID})
    result = dept(["create", "Продажи"])
    assert result.code == 0, result.output
    assert json.loads(created.calls.last.request.content) == {"title": "Продажи"}


# --------------------------------------------------------------------------- edit


def test_edit_sends_put(dept, api) -> None:
    route = api.put(f"{PATH}/{SALES_ID}").respond(json={"id": SALES_ID})
    result = dept(["edit", SALES_ID, "--title", "Продажи РФ"])
    assert result.code == 0, result.output
    assert json.loads(route.calls.last.request.content) == {"title": "Продажи РФ"}


def test_edit_without_changes_is_usage_error(dept, api) -> None:
    result = dept(["edit", SALES_ID])
    assert result.code == 2
    assert "Нечего менять" in str(result.exception)


# --------------------------------------------------------------------------- delete


def test_delete_is_put_with_deleted_true(dept, api) -> None:
    route = api.put(f"{PATH}/{SALES_ID}").respond(json={"id": SALES_ID})
    result = dept(["delete", SALES_ID, "--yes"])
    assert result.code == 0, result.output
    request = route.calls.last.request
    assert request.method == "PUT"
    assert json.loads(request.content) == {"deleted": True}


def test_delete_without_yes_and_without_tty_is_usage_error(dept, api) -> None:
    route = api.put(f"{PATH}/{SALES_ID}").respond(json={"id": SALES_ID})
    result = dept(["delete", SALES_ID])
    assert result.code == 2
    assert not route.called


def test_delete_resolves_name(dept, api, paged) -> None:
    api.get(PATH, params={"title": "Продажи"}).respond(json=paged([SALES]))
    route = api.put(f"{PATH}/{SALES_ID}").respond(json={"id": SALES_ID})
    result = dept(["delete", "Продажи", "-y"])
    assert result.code == 0, result.output
    assert route.called


# --------------------------------------------------------------------------- tree


def test_tree_renders_hierarchy(dept, api, paged) -> None:
    api.get(PATH).respond(json=paged([QA, DEV, SALES]))
    result = dept("tree")
    assert result.code == 0, result.output
    out = result.stdout
    assert "Отделы" in out
    assert "Разработка" in out and "Тестирование" in out
    # The child must be printed after its parent and indented under it.
    assert out.index("Разработка") < out.index("Тестирование")
    assert "└──" in out or "├──" in out


def test_tree_with_root_shows_only_subtree(dept, api, paged) -> None:
    api.get(PATH).respond(json=paged([QA, DEV, SALES]))
    result = dept(["tree", DEV_ID])
    assert result.code == 0, result.output
    assert "Тестирование" in result.stdout
    assert "Продажи" not in result.stdout


def test_tree_json_emits_rows(dept, api, paged) -> None:
    api.get(PATH).respond(json=paged([DEV, QA]))
    result = dept(["tree", "--json", "id,title"])
    assert result.code == 0, result.output
    assert json.loads(result.stdout) == [
        {"id": DEV_ID, "title": "Разработка"},
        {"id": QA_ID, "title": "Тестирование"},
    ]


# ------------------------------------------------------------------- output flags


def test_json_field_selection(dept, api, paged) -> None:
    api.get(PATH).respond(json=paged([SALES, DEV]))
    result = dept(["list", "--json", "id,title"])
    assert result.code == 0, result.output
    assert json.loads(result.stdout) == [
        {"id": SALES_ID, "title": "Продажи"},
        {"id": DEV_ID, "title": "Разработка"},
    ]


def test_json_without_fields_lists_available_fields(dept, api, paged) -> None:
    api.get(PATH).respond(json=paged([SALES]))
    result = dept(["list", "--json", ""])
    assert result.code == 1
    assert "parentId" in str(result.exception.hint)


# --------------------------------------------------------------------------- errors


def test_view_missing_department_exits_1(dept, api) -> None:
    api.get(f"{PATH}/{SALES_ID}").mock(
        return_value=httpx.Response(404, json={"message": "Не найдено"})
    )
    result = dept(["view", SALES_ID])
    assert result.code == 1
    assert isinstance(result.exception, YouGileError)


# ------------------------------------------------------- defect 1: name argument


def test_create_accepts_title_flag(dept, api) -> None:
    """`--title` is the scripting synonym of the positional НАЗВАНИЕ."""
    created = api.post(PATH).respond(201, json={"id": SALES_ID})
    result = dept(["create", "--title", "Продажи"])
    assert result.code == 0, result.output
    assert json.loads(created.calls.last.request.content) == {"title": "Продажи"}


def test_create_accepts_matching_positional_and_flag(dept, api) -> None:
    created = api.post(PATH).respond(201, json={"id": SALES_ID})
    result = dept(["create", "Продажи", "--title", "Продажи"])
    assert result.code == 0, result.output
    assert json.loads(created.calls.last.request.content) == {"title": "Продажи"}


def test_create_with_conflicting_names_is_usage_error(dept, api) -> None:
    created = api.post(PATH).respond(201, json={"id": SALES_ID})
    result = dept(["create", "Продажи", "--title", "Закупки"])
    assert result.code == 2
    assert not created.called


def test_create_without_any_name_is_usage_error(dept, api) -> None:
    created = api.post(PATH).respond(201, json={"id": SALES_ID})
    result = dept(["create"])
    assert result.code == 2
    assert not created.called


def test_metavars_are_russian(dept) -> None:
    for args, expected in (
        (["create", "--help"], "НАЗВАНИЕ"),
        (["view", "--help"], "ОТДЕЛ"),
        (["list", "--help"], "ЧИСЛО"),
    ):
        output = dept(args).output
        assert expected in output
        assert "TEXT" not in output
        assert "INTEGER" not in output


# ------------------------------------------------------- defect 3: gendered wording


def test_missing_department_says_ne_najden(dept, api, paged) -> None:
    api.get(PATH).respond(json=paged([]))
    result = dept(["view", "нет-такого-отдела"])
    assert result.code == 1
    assert str(result.exception) == "Отдел «нет-такого-отдела» не найден."


# ------------------------------------------------------- defect 4: server 400 is exit 1


def test_server_400_is_runtime_error_not_usage(dept, api) -> None:
    """A refusal from the server is a runtime failure (1), not our usage error (2)."""
    api.put(f"{PATH}/{SALES_ID}").mock(
        return_value=httpx.Response(400, json={"message": "Нельзя удалить последний отдел"})
    )
    result = dept(["delete", SALES_ID, "--yes"])
    assert result.code == 1
    assert "Нельзя удалить последний отдел" in str(result.exception)
