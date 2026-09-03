"""Tests for `yougile user`: list, view, invite, edit, delete."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner

from yougile_cli.client import YouGileClient
from yougile_cli.commands import users
from yougile_cli.context import AppContext
from yougile_cli.errors import exit_code_for
from yougile_cli.output import OutputFormat, OutputOptions, humanize_timestamp

USER_ID = "33333333-3333-4333-8333-333333333333"
OTHER_ID = "44444444-4444-4444-8444-444444444444"
PROJECT_ID = "55555555-5555-4555-8555-555555555555"

IVAN = {
    "id": USER_ID,
    "email": "ivan@example.com",
    "realName": "Иван Лукьянец",
    "isAdmin": True,
    "messengerOnly": False,
    "status": "active",
    "lastActivity": 1710000000000,
}
ANNA = {
    "id": OTHER_ID,
    "email": "anna@example.com",
    "realName": "Анна Петрова",
    "isAdmin": False,
    "messengerOnly": True,
    "status": "active",
    "lastActivity": 1710000600000,
}


@pytest.fixture
def invoke(runner: CliRunner, client: YouGileClient) -> Callable[..., Any]:
    """Run `user ...` against a root app that builds the AppContext inside the runner."""

    def _invoke(
        args: list[str],
        *,
        input: str | None = None,
        output: str = "table",
        prompt: bool = True,
    ) -> Any:
        root = typer.Typer()
        root.add_typer(users.app, name="user")

        @root.callback()
        def _root(ctx: typer.Context) -> None:
            app_ctx = AppContext(out=OutputOptions(fmt=OutputFormat(output)), prompt_enabled=prompt)
            app_ctx.set_client(client)
            ctx.obj = app_ctx

        return runner.invoke(root, ["user", *args], input=input)

    return _invoke


def code(result: Any) -> int:
    """What cli.py's global handler would exit with."""
    if result.exception is not None and not isinstance(result.exception, SystemExit):
        return exit_code_for(result.exception)
    return result.exit_code


# --------------------------------------------------------------------------- list


def test_list_prints_table(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    route = api.get("/api-v2/users").respond(json=paged([IVAN, ANNA]))
    result = invoke(["list"])

    assert code(result) == 0, result.output
    assert "Иван Лукьянец" in result.stdout
    assert "anna@example.com" in result.stdout
    assert dict(route.calls.last.request.url.params)["limit"] == "30"


def test_list_humanizes_last_activity(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    api.get("/api-v2/users").respond(json=paged([IVAN]))
    result = invoke(["list"])

    assert code(result) == 0, result.output
    assert humanize_timestamp(IVAN["lastActivity"]) in result.stdout
    assert "1710000000000" not in result.stdout


def test_list_limit_zero_fetches_everything(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    route = api.get("/api-v2/users").respond(json=paged([IVAN]))
    result = invoke(["list", "--limit", "0"])

    assert code(result) == 0, result.output
    assert dict(route.calls.last.request.url.params)["limit"] == "1000"


def test_list_by_email_passes_filter(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    route = api.get("/api-v2/users").respond(json=paged([ANNA]))
    result = invoke(["list", "--email", "anna@example.com"])

    assert code(result) == 0, result.output
    assert dict(route.calls.last.request.url.params)["email"] == "anna@example.com"


def test_list_resolves_project_name_to_id(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    api.get("/api-v2/projects").respond(json=paged([{"id": PROJECT_ID, "title": "Мой проект"}]))
    users_route = api.get("/api-v2/users").respond(json=paged([IVAN]))
    result = invoke(["list", "--project", "Мой проект"])

    assert code(result) == 0, result.output
    assert dict(users_route.calls.last.request.url.params)["projectId"] == PROJECT_ID


def test_list_search_filters_locally(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    api.get("/api-v2/users").respond(json=paged([IVAN, ANNA]))
    result = invoke(["list", "--search", "анна"])

    assert code(result) == 0, result.output
    assert "Анна Петрова" in result.stdout
    assert "Иван" not in result.stdout


def test_list_search_short_flag(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    api.get("/api-v2/users").respond(json=paged([IVAN, ANNA]))
    result = invoke(["list", "-S", "анна"])
    assert code(result) == 0, result.output
    assert "Анна Петрова" in result.stdout
    assert "Иван" not in result.stdout


def test_list_json_selects_fields(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    api.get("/api-v2/users").respond(json=paged([IVAN, ANNA]))
    result = invoke(["list", "--json", "id,email"])

    assert code(result) == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == [
        {"id": USER_ID, "email": "ivan@example.com"},
        {"id": OTHER_ID, "email": "anna@example.com"},
    ]


def test_list_json_without_fields_lists_them(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    api.get("/api-v2/users").respond(json=paged([IVAN]))
    result = invoke(["list", "--json", ""])

    assert code(result) == 1
    assert "realName" in str(result.exception.hint or "")


# --------------------------------------------------------------------------- view


def test_view_me(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    route = api.get("/api-v2/users/me").respond(json=IVAN)
    result = invoke(["view"])

    assert code(result) == 0, result.output
    assert route.called
    assert "Иван Лукьянец" in result.stdout


def test_view_resolves_email(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    api.get("/api-v2/users").respond(json=paged([ANNA]))
    card = api.get(f"/api-v2/users/{OTHER_ID}").respond(json=ANNA)
    result = invoke(["view", "anna@example.com"])

    assert code(result) == 0, result.output
    assert card.called
    assert "Анна Петрова" in result.stdout


def test_view_unknown_user_fails(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., Any]
) -> None:
    api.get("/api-v2/users").respond(json=paged([]))
    result = invoke(["view", "Никого Нет"])

    assert code(result) == 1
    assert str(result.exception) == "Сотрудник «Никого Нет» не найден."


# --------------------------------------------------------------------------- invite


def test_invite_posts_body(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    route = api.post("/api-v2/users").respond(201, json={"id": OTHER_ID})
    result = invoke(["invite", "--email", "new@example.com", "--admin"])

    assert code(result) == 0, result.output
    assert json.loads(route.calls.last.request.content) == {
        "email": "new@example.com",
        "isAdmin": True,
        "messengerOnly": False,
    }


def test_invite_supports_json_field_selection(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    """gh-spec §4: every data-returning command carries --json and --jq."""
    api.post("/api-v2/users").respond(201, json={"id": OTHER_ID, "email": "new@example.com"})
    result = invoke(["invite", "--email", "new@example.com", "--json", "id"])
    assert code(result) == 0, result.output
    assert json.loads(result.stdout) == [{"id": OTHER_ID}]


def test_delete_supports_jq(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    api.delete(f"/api-v2/users/{USER_ID}").respond(json={"id": USER_ID})
    result = invoke(["delete", USER_ID, "--yes", "--jq", ".id"])
    assert code(result) == 0, result.output
    assert USER_ID in result.stdout


# --------------------------------------------------------------------------- edit


def test_edit_puts_only_given_flags(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    route = api.put(f"/api-v2/users/{USER_ID}").respond(json={"id": USER_ID})
    result = invoke(["edit", USER_ID, "--no-admin"])

    assert code(result) == 0, result.output
    assert json.loads(route.calls.last.request.content) == {"isAdmin": False}


def test_edit_without_flags_is_usage_error(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    result = invoke(["edit", USER_ID])

    assert code(result) == 2
    assert not api.calls


# --------------------------------------------------------------------------- delete


def test_delete_uses_real_delete_method(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    """Users are one of the three resources with a real DELETE, not a PUT deleted=true."""
    put_route = api.put(f"/api-v2/users/{USER_ID}").respond(json={"id": USER_ID})
    delete_route = api.delete(f"/api-v2/users/{USER_ID}").respond(json={"id": USER_ID})
    result = invoke(["delete", USER_ID, "--yes"])

    assert code(result) == 0, result.output
    assert delete_route.called
    assert not put_route.called
    assert delete_route.calls.last.request.method == "DELETE"
    assert not delete_route.calls.last.request.content


def test_delete_confirms_when_interactive(
    invoke: Callable[..., Any],
    api: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "is_tty", lambda *_a, **_k: True)
    delete_route = api.delete(f"/api-v2/users/{USER_ID}").respond(json={"id": USER_ID})
    result = invoke(["delete", USER_ID], input="y\n")

    assert code(result) == 0, result.output
    assert delete_route.called


def test_delete_aborted_by_user(
    invoke: Callable[..., Any],
    api: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "is_tty", lambda *_a, **_k: True)
    delete_route = api.delete(f"/api-v2/users/{USER_ID}").respond(json={"id": USER_ID})
    result = invoke(["delete", USER_ID], input="n\n")

    assert code(result) == 1
    assert not delete_route.called


def test_delete_without_tty_requires_yes(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    delete_route = api.delete(f"/api-v2/users/{USER_ID}").respond(json={"id": USER_ID})
    result = invoke(["delete", USER_ID])

    assert code(result) == 2
    assert not delete_route.called
    assert "--yes" in str(result.exception.hint or "")


def test_delete_api_error_propagates(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    api.delete(f"/api-v2/users/{USER_ID}").mock(
        return_value=httpx.Response(404, json={"message": "user not found"})
    )
    result = invoke(["delete", USER_ID, "--yes"])

    assert code(result) == 1
    assert "user not found" in str(result.exception)


# ------------------------------------------------------- defect 1: email argument


def test_invite_accepts_positional_email(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    route = api.post("/api-v2/users").respond(201, json={"id": OTHER_ID})
    result = invoke(["invite", "new@example.com"])

    assert code(result) == 0, result.output
    assert json.loads(route.calls.last.request.content) == {
        "email": "new@example.com",
        "isAdmin": False,
        "messengerOnly": False,
    }


def test_invite_with_conflicting_emails_is_usage_error(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    route = api.post("/api-v2/users").respond(201, json={"id": OTHER_ID})
    result = invoke(["invite", "new@example.com", "--email", "other@example.com"])

    assert code(result) == 2
    assert not route.called


def test_invite_without_email_is_usage_error(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    route = api.post("/api-v2/users").respond(201, json={"id": OTHER_ID})
    assert code(invoke(["invite"])) == 2
    assert not route.called


def test_user_metavars_are_russian(invoke: Callable[..., Any]) -> None:
    for args, expected in (
        (["invite", "--help"], "ПОЧТА"),
        (["view", "--help"], "СОТРУДНИК"),
        (["list", "--help"], "ЧИСЛО"),
    ):
        output = invoke(args).output
        assert expected in output
        assert "TEXT" not in output
        assert "INTEGER" not in output
