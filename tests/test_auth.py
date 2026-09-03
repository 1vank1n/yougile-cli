"""Tests for `yougile auth` (login, logout, status, token, switch, refresh, keys).

The commands are mounted on a throw-away root Typer app that builds the
``AppContext`` exactly like ``cli.py`` does, so this module never depends on the
root CLI wiring. ``exit_code`` mirrors the global handler in ``cli.py``:
a ``YouGileError`` escaping a command becomes its ``exit_code``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from yougile_cli.commands import auth as auth_cmd
from yougile_cli.config import (
    Host,
    Hosts,
    HostUser,
    Settings,
    load_hosts,
    resolve_auth,
    save_hosts,
)
from yougile_cli.context import AppContext
from yougile_cli.errors import YouGileError, exit_code_for, format_error
from yougile_cli.output import OutputFormat, OutputOptions

HOST = "yougile.com"
TEST_EMAIL = "ivan@example.com"
TEST_KEY = "test-key"
COMPANY_ID = "22222222-2222-4222-8222-222222222222"

ME = {"id": "u-1", "email": TEST_EMAIL, "realName": "Иван Лукьянец"}
COMPANY = {"id": COMPANY_ID, "title": "Моя компания"}


# --------------------------------------------------------------------------- harness


def exit_code(result: Any) -> int:
    exc = result.exception
    if exc is not None and not isinstance(exc, SystemExit):
        return exit_code_for(exc)
    return result.exit_code


def message(result: Any) -> str:
    exc = result.exception
    extra = format_error(exc) if isinstance(exc, YouGileError) else ""
    return f"{result.output}\n{extra}"


def json_payload(result: Any) -> Any:
    text = result.stdout
    start = min((text.index(ch) for ch in "[{" if ch in text), default=-1)
    assert start >= 0, text
    return json.loads(text[start:])


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> Callable[..., Any]:
    """Run an `auth` subcommand with a freshly built AppContext."""

    def _invoke(
        args: list[str] | str,
        *,
        input: str | None = None,
        output: str = "table",
        prompt: bool = True,
        tty: bool = True,
        token: str | None = None,
    ) -> Any:
        monkeypatch.setattr(auth_cmd, "is_tty", lambda *_a, **_k: tty)
        root = typer.Typer()

        @root.callback()
        def _root(ctx: typer.Context) -> None:
            ctx.obj = AppContext(
                auth=resolve_auth(token=token),
                out=OutputOptions(fmt=OutputFormat(output)),
                settings=Settings(prompt="enabled" if prompt else "disabled"),
                prompt_enabled=prompt,
            )

        root.add_typer(auth_cmd.app, name="auth")
        argv = args.split() if isinstance(args, str) else list(args)
        return runner.invoke(root, argv, input=input)

    return _invoke


@pytest.fixture
def two_accounts() -> None:
    save_hosts(
        Hosts(
            {
                HOST: Host(
                    active_user=TEST_EMAIL,
                    users={
                        TEST_EMAIL: HostUser(api_key=TEST_KEY, email=TEST_EMAIL),
                        "anna@example.com": HostUser(api_key="anna-key", email="anna@example.com"),
                    },
                )
            }
        )
    )


@pytest.fixture
def three_accounts() -> None:
    save_hosts(
        Hosts(
            {
                HOST: Host(
                    active_user=TEST_EMAIL,
                    users={
                        TEST_EMAIL: HostUser(api_key=TEST_KEY, email=TEST_EMAIL),
                        "anna@example.com": HostUser(api_key="anna-key", email="anna@example.com"),
                        "petr@example.com": HostUser(api_key="petr-key", email="petr@example.com"),
                    },
                )
            }
        )
    )


# --------------------------------------------------------------------------- login


def test_login_with_token_validates_and_saves(cli: Any, api: Any) -> None:
    me = api.get("/api-v2/users/me").respond(json=ME)
    api.get("/api-v2/companies").respond(json=COMPANY)

    result = cli("auth login --with-token", input="fresh-token-value\n")

    assert exit_code(result) == 0, message(result)
    assert me.called
    stored = load_hosts()[HOST].users[TEST_EMAIL]
    assert stored.api_key == "fresh-token-value"
    assert stored.company_name == "Моя компания"
    assert "Вход выполнен как Иван Лукьянец" in result.output


def test_login_with_token_rejects_bad_key(cli: Any, api: Any) -> None:
    api.get("/api-v2/users/me").respond(401, json={"message": "unauthorized"})

    result = cli("auth login --with-token", input="nope\n")

    assert exit_code(result) == 4, message(result)
    assert HOST not in load_hosts()


def test_login_reuses_existing_key(cli: Any, api: Any, paged: Any) -> None:
    api.post("/api-v2/auth/companies").respond(
        json=paged([{"id": COMPANY_ID, "name": "Моя компания", "isAdmin": True}])
    )
    keys_get = api.post("/api-v2/auth/keys/get").respond(
        json=[{"key": "reused-key", "companyId": COMPANY_ID, "timestamp": 1, "deleted": False}]
    )
    created = api.post("/api-v2/auth/keys").respond(201, json={"key": "brand-new"})
    api.get("/api-v2/users/me").respond(json=ME)

    result = cli(
        ["auth", "login", "--user", TEST_EMAIL, "--company", "Моя компания"],
        input="secret\n",
    )

    assert exit_code(result) == 0, message(result)
    assert keys_get.called
    assert not created.called
    stored = load_hosts()[HOST].users[TEST_EMAIL]
    assert stored.api_key == "reused-key"
    assert stored.company_id == COMPANY_ID


def test_login_new_key_skips_reuse(cli: Any, api: Any, paged: Any) -> None:
    api.post("/api-v2/auth/companies").respond(
        json=paged([{"id": COMPANY_ID, "name": "Моя компания", "isAdmin": True}])
    )
    keys_get = api.post("/api-v2/auth/keys/get").respond(json=[])
    api.post("/api-v2/auth/keys").respond(201, json={"key": "brand-new"})
    api.get("/api-v2/users/me").respond(json=ME)

    result = cli(
        ["auth", "login", "--user", TEST_EMAIL, "--company", COMPANY_ID, "--new-key"],
        input="secret\n",
    )

    assert exit_code(result) == 0, message(result)
    assert not keys_get.called
    assert load_hosts()[HOST].users[TEST_EMAIL].api_key == "brand-new"


def test_login_resolves_company_by_name(cli: Any, api: Any, paged: Any) -> None:
    """A company is addressable by name, not only by id."""
    api.post("/api-v2/auth/companies").respond(
        json=paged(
            [
                {"id": "c-other", "name": "Другая компания", "isAdmin": False},
                {"id": COMPANY_ID, "name": "Моя компания", "isAdmin": True},
            ]
        )
    )
    create = api.post("/api-v2/auth/keys").respond(201, json={"key": "brand-new"})
    api.get("/api-v2/users/me").respond(json=ME)

    result = cli(
        ["auth", "login", "--user", TEST_EMAIL, "--company", "моя компания", "--new-key"],
        input="secret\n",
    )

    assert exit_code(result) == 0, message(result)
    assert json.loads(create.calls[0].request.content)["companyId"] == COMPANY_ID


def test_login_ambiguous_company_is_usage_error(cli: Any, api: Any, paged: Any) -> None:
    api.post("/api-v2/auth/companies").respond(
        json=paged(
            [
                {"id": "c-1", "name": "Первая компания", "isAdmin": True},
                {"id": "c-2", "name": "Вторая компания", "isAdmin": True},
            ]
        )
    )

    result = cli(
        ["auth", "login", "--user", TEST_EMAIL, "--company", "компания", "--new-key"],
        input="secret\n",
    )

    assert exit_code(result) == 2, message(result)
    assert "несколько компаний" in message(result)


def test_login_interactive_accepts_pasted_key(cli: Any, api: Any) -> None:
    """Ответ «2» в интерактивном входе: ключ вставляют руками."""
    me = api.get("/api-v2/users/me").respond(json=ME)
    api.get("/api-v2/companies").respond(json=COMPANY)

    result = cli("auth login", input="\n2\npasted-key\n")

    assert exit_code(result) == 0, message(result)
    assert me.called
    assert load_hosts()[HOST].users[TEST_EMAIL].api_key == "pasted-key"


def test_login_interactive_rejects_empty_pasted_key(cli: Any) -> None:
    result = cli("auth login", input="\n2\n   \n")

    assert exit_code(result) == 2, message(result)
    assert "API-ключ" in message(result)


def test_login_company_picker(cli: Any, api: Any, paged: Any) -> None:
    api.post("/api-v2/auth/companies").respond(
        json=paged(
            [
                {"id": "c-1", "name": "Первая", "isAdmin": True},
                {"id": COMPANY_ID, "name": "Вторая", "isAdmin": True},
            ]
        )
    )
    api.post("/api-v2/auth/keys/get").respond(
        json=[{"key": "picked-key", "companyId": COMPANY_ID, "timestamp": 1, "deleted": False}]
    )
    api.get("/api-v2/users/me").respond(json=ME)

    result = cli(["auth", "login", "--user", TEST_EMAIL], input="secret\n2\n")

    assert exit_code(result) == 0, message(result)
    stored = load_hosts()[HOST].users[TEST_EMAIL]
    assert (stored.api_key, stored.company_id) == ("picked-key", COMPANY_ID)


def test_login_company_picker_out_of_range(cli: Any, api: Any, paged: Any) -> None:
    api.post("/api-v2/auth/companies").respond(
        json=paged(
            [
                {"id": "c-1", "name": "Первая", "isAdmin": True},
                {"id": COMPANY_ID, "name": "Вторая", "isAdmin": True},
            ]
        )
    )

    result = cli(["auth", "login", "--user", TEST_EMAIL], input="secret\n9\n")

    assert exit_code(result) == 2, message(result)
    assert "номером 9" in message(result)


def test_login_without_prompt_requires_with_token(cli: Any) -> None:
    result = cli("auth login", tty=False)

    assert exit_code(result) == 2, message(result)
    assert "--with-token" in message(result)


def test_login_prompt_disabled_by_settings(cli: Any) -> None:
    result = cli("auth login", prompt=False)

    assert exit_code(result) == 2, message(result)


# --------------------------------------------------------------------------- status


def test_status_prints_gh_block(cli: Any, logged_in: Any) -> None:
    result = cli("auth status")

    assert exit_code(result) == 0, message(result)
    out = result.output
    assert HOST in out
    assert "Вход выполнен как Иван Лукьянец (ivan@example.com)" in out
    assert "Активная учётная запись: да" in out
    assert "Моя компания" in out
    assert "Хранилище:" in out
    assert TEST_KEY not in out


def test_status_show_token(cli: Any, logged_in: Any) -> None:
    result = cli("auth status --show-token")

    assert exit_code(result) == 0, message(result)
    assert TEST_KEY in result.output


def test_status_logged_out_exits_4(cli: Any) -> None:
    result = cli("auth status")

    assert exit_code(result) == 4, message(result)
    assert "Вход не выполнен" in message(result)


def test_status_checks_a_key_from_the_environment(cli: Any, api: Any) -> None:
    """Ключ из YOUGILE_TOKEN не хранит ни имени, ни компании — их называет сервер."""
    api.get("/api-v2/users/me").respond(json=ME)
    api.get("/api-v2/companies").respond(json=COMPANY)

    result = cli("auth status", token="env-key")

    assert exit_code(result) == 0, message(result)
    assert "Иван Лукьянец" in result.output
    assert "Моя компания" in result.output


def test_status_rejects_a_bad_key_from_the_environment(cli: Any, api: Any) -> None:
    api.get("/api-v2/users/me").respond(401, json={"message": "unauthorized"})

    result = cli("auth status", token="garbage")

    assert exit_code(result) == 4, message(result)
    assert "ключ" in message(result).lower()


def test_status_json_output(cli: Any, logged_in: Any) -> None:
    result = cli("auth status", output="json")

    assert exit_code(result) == 0, message(result)
    rows = json_payload(result)
    assert rows[0]["email"] == TEST_EMAIL
    assert rows[0]["api_key"] != TEST_KEY


# --------------------------------------------------------------------------- token


def test_token_prints_only_the_key(cli: Any, logged_in: Any) -> None:
    result = cli("auth token")

    assert exit_code(result) == 0, message(result)
    assert result.stdout.strip() == TEST_KEY


def test_token_logged_out_exits_4(cli: Any) -> None:
    result = cli("auth token")

    assert exit_code(result) == 4, message(result)


# --------------------------------------------------------------------------- switch


def test_switch_changes_active_account(cli: Any, two_accounts: None) -> None:
    result = cli("auth switch --user anna@example.com")

    assert exit_code(result) == 0, message(result)
    assert load_hosts()[HOST].active_user == "anna@example.com"


def test_switch_picks_the_only_alternative(cli: Any, two_accounts: None) -> None:
    result = cli("auth switch")

    assert exit_code(result) == 0, message(result)
    assert load_hosts()[HOST].active_user == "anna@example.com"


def test_switch_account_picker(cli: Any, three_accounts: None) -> None:
    result = cli("auth switch", input="2\n")

    assert exit_code(result) == 0, message(result)
    assert load_hosts()[HOST].active_user == "petr@example.com"


def test_switch_account_picker_out_of_range(cli: Any, three_accounts: None) -> None:
    result = cli("auth switch", input="9\n")

    assert exit_code(result) == 2, message(result)
    assert load_hosts()[HOST].active_user == TEST_EMAIL


def test_switch_unknown_account(cli: Any, logged_in: Any) -> None:
    result = cli("auth switch --user nobody@example.com")

    assert exit_code(result) == 1, message(result)


# --------------------------------------------------------------------------- logout


def test_logout_removes_the_account(cli: Any, logged_in: Any) -> None:
    result = cli("auth logout --yes")

    assert exit_code(result) == 0, message(result)
    assert HOST not in load_hosts()


def test_logout_without_prompt_requires_yes(cli: Any, logged_in: Any) -> None:
    result = cli("auth logout", tty=False)

    assert exit_code(result) == 2, message(result)
    assert HOST in load_hosts()


def test_logout_declined_keeps_the_account(cli: Any, logged_in: Any) -> None:
    result = cli("auth logout", input="n\n")

    assert exit_code(result) == 1, message(result)
    assert HOST in load_hosts()


def test_logout_unknown_host(cli: Any) -> None:
    result = cli("auth logout --yes")

    assert exit_code(result) == 1, message(result)


# --------------------------------------------------------------------------- refresh


def test_refresh_reissues_and_revokes_the_old_key(cli: Any, api: Any, logged_in: Any) -> None:
    create = api.post("/api-v2/auth/keys").respond(201, json={"key": "fresh-key"})
    api.get("/api-v2/users/me").respond(json=ME)
    api.get("/api-v2/companies").respond(json=COMPANY)
    revoke = api.delete(f"/api-v2/auth/keys/{TEST_KEY}").respond(200, json={})

    result = cli("auth refresh", input="secret\n")

    assert exit_code(result) == 0, message(result)
    assert json.loads(create.calls[0].request.content)["companyId"] == COMPANY_ID
    assert revoke.called
    assert load_hosts()[HOST].users[TEST_EMAIL].api_key == "fresh-key"


def test_refresh_logged_out_exits_4(cli: Any) -> None:
    result = cli("auth refresh", input="secret\n")

    assert exit_code(result) == 4, message(result)


# --------------------------------------------------------------------------- keys


def _keys_body() -> list[dict[str, Any]]:
    return [
        {"key": "alpha-key-0001", "companyId": COMPANY_ID, "timestamp": 1, "deleted": False},
        {"key": "beta-key-0002", "companyId": COMPANY_ID, "timestamp": 2, "deleted": True},
    ]


def test_keys_list_hides_deleted_and_masks(cli: Any, api: Any, logged_in: Any) -> None:
    route = api.post("/api-v2/auth/keys/get").respond(json=_keys_body())

    result = cli("auth keys list", input="secret\n")

    assert exit_code(result) == 0, message(result)
    assert json.loads(route.calls[0].request.content)["companyId"] == COMPANY_ID
    assert "alp…0001" in result.output
    assert "alpha-key-0001" not in result.output
    assert "0002" not in result.output


def test_keys_list_include_deleted_and_show_token(cli: Any, api: Any, logged_in: Any) -> None:
    api.post("/api-v2/auth/keys/get").respond(json=_keys_body())

    result = cli("auth keys list --include-deleted --show-token", input="secret\n")

    assert exit_code(result) == 0, message(result)
    assert "alpha-key-0001" in result.output
    assert "beta-key-0002" in result.output


def test_keys_list_json_field_selection(cli: Any, api: Any, logged_in: Any) -> None:
    api.post("/api-v2/auth/keys/get").respond(json=_keys_body())

    result = cli(["auth", "keys", "list", "--json", "companyId,deleted"], input="secret\n")

    assert exit_code(result) == 0, message(result)
    assert json_payload(result) == [{"companyId": COMPANY_ID, "deleted": False}]


def test_keys_list_unknown_json_field(cli: Any, api: Any, logged_in: Any) -> None:
    api.post("/api-v2/auth/keys/get").respond(json=_keys_body())

    result = cli(["auth", "keys", "list", "--json", "nope"], input="secret\n")

    assert exit_code(result) == 1, message(result)
    assert "nope" in message(result)


def test_keys_list_limit(cli: Any, api: Any, logged_in: Any) -> None:
    body = [
        {"key": f"key-{index:04d}-tail", "companyId": COMPANY_ID, "deleted": False}
        for index in range(5)
    ]
    api.post("/api-v2/auth/keys/get").respond(json=body)

    result = cli(["auth", "keys", "list", "--limit", "2", "--json", "companyId"], input="secret\n")

    assert exit_code(result) == 0, message(result)
    assert len(json_payload(result)) == 2


def test_keys_create(cli: Any, api: Any, paged: Any, logged_in: Any) -> None:
    api.post("/api-v2/auth/companies").respond(
        json=paged([{"id": COMPANY_ID, "name": "Моя компания", "isAdmin": True}])
    )
    create = api.post("/api-v2/auth/keys").respond(201, json={"key": "brand-new-key"})

    result = cli(["auth", "keys", "create", "--company", COMPANY_ID], input="secret\n")

    assert exit_code(result) == 0, message(result)
    assert create.called
    assert "brand-new-key" in result.output


def test_keys_delete_uses_a_real_delete(cli: Any, api: Any, logged_in: Any) -> None:
    """Auth keys are one of the three endpoints with a real DELETE method."""
    route = api.delete("/api-v2/auth/keys/some-other-key").respond(200, json={})
    put = api.put("/api-v2/auth/keys/some-other-key").respond(200, json={})

    result = cli("auth keys delete some-other-key --yes")

    assert exit_code(result) == 0, message(result)
    assert route.called
    assert route.calls[0].request.method == "DELETE"
    assert not put.called
    # An unrelated key must not touch the stored account.
    assert HOST in load_hosts()


def test_keys_delete_forgets_the_stored_account(cli: Any, api: Any, logged_in: Any) -> None:
    api.delete(f"/api-v2/auth/keys/{TEST_KEY}").respond(200, json={})

    result = cli(f"auth keys delete {TEST_KEY} --yes")

    assert exit_code(result) == 0, message(result)
    assert HOST not in load_hosts()


def test_keys_delete_without_prompt_requires_yes(cli: Any, api: Any, logged_in: Any) -> None:
    route = api.delete("/api-v2/auth/keys/some-key").respond(200, json={})

    result = cli("auth keys delete some-key", tty=False)

    assert exit_code(result) == 2, message(result)
    assert not route.called


def test_keys_delete_refuses_a_path_escaping_key(cli: Any, api: Any, logged_in: Any) -> None:
    """httpx normalises `..`, so an unquoted segment could delete a company employee."""
    victim = api.delete("/api-v2/users/11111111-1111-1111-1111-111111111111").respond(200, json={})

    result = cli(
        ["auth", "keys", "delete", "x/../../../users/11111111-1111-1111-1111-111111111111", "-y"]
    )

    assert exit_code(result) == 2, message(result)
    assert not victim.called


def test_keys_delete_refuses_a_fragment_in_the_key(cli: Any, api: Any, logged_in: Any) -> None:
    route = api.delete("/api-v2/auth/keys/abc").respond(200, json={})

    result = cli(["auth", "keys", "delete", "abc#frag", "-y"])

    assert exit_code(result) == 2, message(result)
    assert not route.called


def test_keys_delete_needs_authentication(cli: Any) -> None:
    result = cli("auth keys delete some-key --yes")

    assert exit_code(result) == 4, message(result)


# ------------------------------------------------------- defect 1: russian metavars


def test_auth_metavars_are_russian(cli: Callable[..., Any]) -> None:
    for args, expected in (
        ("auth login --help", "ПОЧТА"),
        ("auth keys list --help", "ЧИСЛО"),
        ("auth keys delete --help", "КЛЮЧ"),
    ):
        output = cli(args).output
        assert expected in output
        assert "EMAIL" not in output
        assert "TEXT" not in output
        assert "INTEGER" not in output
