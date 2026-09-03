"""Tests for `yougile company|file|crm|config|alias|browse|status|version`.

The commands are mounted on a throwaway Typer app so that the module can be
exercised without depending on how `cli.py` wires everything together; the
``AppContext`` is built inside the callback, after ``CliRunner`` has replaced
``sys.stdout``.
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import respx
import typer
from typer.main import get_command
from typer.testing import CliRunner

from yougile_cli.client import YouGileClient
from yougile_cli.commands import misc
from yougile_cli.config import ResolvedAuth
from yougile_cli.context import AppContext
from yougile_cli.errors import ConfigError, ValidationError, YouGileError, exit_code_for

from .conftest import BASE_URL, HOST, TEST_KEY

# Доски открываются на веб-хосте, а не на хосте API.
WEB_URL = "https://yougile.com"

TASK_ID = "33333333-3333-4333-8333-333333333333"
BOARD_ID = "44444444-4444-4444-8444-444444444444"


def build_app() -> typer.Typer:
    app = typer.Typer()
    app.add_typer(misc.company_app, name="company")
    app.add_typer(misc.file_app, name="file")
    app.add_typer(misc.crm_app, name="crm")
    app.add_typer(misc.config_app, name="config")
    app.add_typer(misc.alias_app, name="alias")
    app.command("browse")(misc.browse_cmd)
    app.command("status")(misc.status_cmd)
    app.command("version")(misc.version_cmd)
    return app


@pytest.fixture
def invoke(runner: CliRunner, client: YouGileClient) -> Callable[..., Any]:
    app = build_app()

    @app.callback()
    def _root(ctx: typer.Context) -> None:
        app_ctx = AppContext(
            auth=ResolvedAuth(host=HOST, base_url=BASE_URL, api_key=TEST_KEY, source="flag")
        )
        app_ctx.set_client(client)
        ctx.obj = app_ctx

    def _invoke(args: str | list[str], *, input: str | None = None) -> Any:
        argv = shlex.split(args) if isinstance(args, str) else list(args)
        return runner.invoke(app, argv, input=input)

    return _invoke


def code(result: Any) -> int:
    """Exit code the global handler in `cli.py` would produce."""
    exc = result.exception
    if isinstance(exc, YouGileError):
        return exit_code_for(exc)
    return result.exit_code


def body_of(route: Any) -> Any:
    return json.loads(route.calls.last.request.content.decode())


# --------------------------------------------------------------------------- company


def test_company_view(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    api.get("/api-v2/companies").respond(json={"id": "c1", "title": "Моя компания"})
    result = invoke("company view")
    assert code(result) == 0
    assert "Моя компания" in result.stdout


def test_company_view_with_id(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    route = api.get("/api-v2/companies/c9").respond(json={"id": "c9", "title": "Другая"})
    assert code(invoke("company view --company-id c9")) == 0
    assert route.called


def test_company_id_cannot_escape_the_endpoint(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    """The option is interpolated into the path; httpx would normalise `..` away."""
    victim = api.get("/api-v2/users/11111111-1111-1111-1111-111111111111").respond(json={})
    result = invoke(
        ["company", "view", "--company-id", "x/../../users/11111111-1111-1111-1111-111111111111"]
    )
    assert code(result) == 2
    assert not victim.called


def test_company_edit_title(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    route = api.put("/api-v2/companies").respond(json={"id": "c1"})
    result = invoke("company edit --title Новое")
    assert code(result) == 0
    assert body_of(route) == {"title": "Новое"}


def test_company_edit_api_data(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    route = api.put("/api-v2/companies").respond(json={"id": "c1"})
    assert code(invoke("company edit -a crm=on -a plan=pro")) == 0
    assert body_of(route) == {"apiData": {"crm": "on", "plan": "pro"}}


def test_company_delete_is_put_deleted_true(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    """Компании не удаляются методом DELETE: удаление — PUT с deleted=true."""
    route = api.put("/api-v2/companies").respond(json={"id": "c1"})
    assert code(invoke("company edit --deleted --yes")) == 0
    assert body_of(route) == {"deleted": True}
    assert route.calls.last.request.method == "PUT"


def test_company_restore(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    route = api.put("/api-v2/companies").respond(json={"id": "c1"})
    assert code(invoke("company edit --restore")) == 0
    assert body_of(route) == {"deleted": False}


def test_company_edit_without_changes_fails(invoke: Callable[..., Any]) -> None:
    result = invoke("company edit")
    assert isinstance(result.exception, ValidationError)
    assert code(result) == 2


def test_company_delete_without_yes_needs_tty(invoke: Callable[..., Any]) -> None:
    result = invoke("company edit --deleted")
    assert isinstance(result.exception, ValidationError)
    assert code(result) == 2
    assert "--yes" in (result.exception.hint or "")


# --------------------------------------------------------------------------- file


def test_file_upload(invoke: Callable[..., Any], api: respx.MockRouter, tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("привет", encoding="utf-8")
    route = api.post("/api-v2/upload-file").respond(
        json={
            "result": "ok",
            "url": "/files/1",
            "fullUrl": "https://yougile.com/files/1",
        }
    )
    result = invoke(["file", "upload", str(target)])
    assert code(result) == 0
    assert route.called
    assert "https://yougile.com/files/1" in result.stdout


def test_file_upload_missing_file(invoke: Callable[..., Any], tmp_path: Path) -> None:
    result = invoke(["file", "upload", str(tmp_path / "нет.txt")])
    assert isinstance(result.exception, ValidationError)
    assert code(result) == 2


FILE_PATH = "/user-data/55555555-5555-4555-8555-555555555555/IMG_20260828.jpg"
FILE_BODY = b"\x89PNG\r\n\x1a\n original"
OLD_BODY = "старое".encode()


def test_file_download_strips_preview_by_default(
    invoke: Callable[..., Any],
    api: respx.MockRouter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    route = api.get(FILE_PATH).respond(content=FILE_BODY)
    result = invoke(["file", "download", f"{FILE_PATH}?previews[]=480x480"])
    assert code(result) == 0
    # Превью 480×480 вместо оригинала — ровно то, ради чего параметр вырезается.
    assert route.calls.last.request.url.query == b""
    saved = tmp_path / "IMG_20260828.jpg"
    assert saved.read_bytes() == FILE_BODY
    assert str(saved) in result.stdout
    assert str(len(FILE_BODY)) in result.stdout


def test_file_download_sends_bearer_and_resolves_host(
    invoke: Callable[..., Any],
    api: respx.MockRouter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    route = api.get(FILE_PATH).respond(content=FILE_BODY)
    assert code(invoke(["file", "download", FILE_PATH])) == 0
    request = route.calls.last.request
    assert str(request.url) == f"https://yougile.com{FILE_PATH}"
    assert request.headers["authorization"] == f"Bearer {TEST_KEY}"


def test_file_download_keeps_preview_with_flag(
    invoke: Callable[..., Any],
    api: respx.MockRouter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    route = api.get(FILE_PATH).respond(content=FILE_BODY)
    result = invoke(["file", "download", f"{FILE_PATH}?previews[]=480x480", "--preview"])
    assert code(result) == 0
    assert b"previews" in route.calls.last.request.url.query


def test_file_download_into_existing_directory(
    invoke: Callable[..., Any], api: respx.MockRouter, tmp_path: Path
) -> None:
    api.get(FILE_PATH).respond(content=FILE_BODY)
    target = tmp_path / "вложения"
    target.mkdir()
    assert code(invoke(["file", "download", FILE_PATH, "-o", str(target)])) == 0
    assert (target / "IMG_20260828.jpg").read_bytes() == FILE_BODY


def test_file_download_named_output(
    invoke: Callable[..., Any], api: respx.MockRouter, tmp_path: Path
) -> None:
    api.get(FILE_PATH).respond(content=FILE_BODY)
    target = tmp_path / "снимок.jpg"
    assert code(invoke(["file", "download", FILE_PATH, "-o", str(target)])) == 0
    assert target.read_bytes() == FILE_BODY


def test_file_download_refuses_to_overwrite(
    invoke: Callable[..., Any], api: respx.MockRouter, tmp_path: Path
) -> None:
    api.get(FILE_PATH).respond(content=FILE_BODY)
    target = tmp_path / "снимок.jpg"
    target.write_bytes(OLD_BODY)
    result = invoke(["file", "download", FILE_PATH, "-o", str(target)])
    assert isinstance(result.exception, ValidationError)
    assert code(result) == 2
    assert target.read_bytes() == OLD_BODY


def test_file_download_force_overwrites(
    invoke: Callable[..., Any], api: respx.MockRouter, tmp_path: Path
) -> None:
    api.get(FILE_PATH).respond(content=FILE_BODY)
    target = tmp_path / "снимок.jpg"
    target.write_bytes(OLD_BODY)
    assert code(invoke(["file", "download", FILE_PATH, "-o", str(target), "--force"])) == 0
    assert target.read_bytes() == FILE_BODY


def test_file_download_json(
    invoke: Callable[..., Any], api: respx.MockRouter, tmp_path: Path
) -> None:
    api.get(FILE_PATH).respond(content=FILE_BODY)
    target = tmp_path / "снимок.jpg"
    result = invoke(["file", "download", FILE_PATH, "-o", str(target), "--json", "path,size"])
    assert code(result) == 0
    payload = json.loads(result.stdout)
    row = payload[0] if isinstance(payload, list) else payload
    assert row["path"] == str(target)
    assert row["size"] == len(FILE_BODY)


# --------------------------------------------------------------------------- crm


def test_crm_contact_create_resolves_project_by_name(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., dict[str, Any]]
) -> None:
    api.get("/api-v2/projects").respond(json=paged([{"id": "p1", "title": "Продажи"}]))
    route = api.post("/api-v2/crm/contact-persons").respond(
        status_code=201, json={"id": "k1", "title": "Иван"}
    )
    result = invoke("crm contact create --title Иван --project Продажи --phone +79990000000")
    assert code(result) == 0
    assert body_of(route) == {
        "projectId": "p1",
        "title": "Иван",
        "fields": {"phone": "+79990000000"},
    }


def test_crm_contact_view_by_external_id(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    route = api.get("/api-v2/crm/contacts/by-external-id").respond(
        json={"id": "k1", "title": "Иван"}
    )
    result = invoke("crm contact view --external-id telegram:42")
    assert code(result) == 0
    assert dict(route.calls.last.request.url.params) == {"provider": "telegram", "chatId": "42"}
    assert "Иван" in result.stdout


def test_crm_contact_view_separate_flags(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    route = api.get("/api-v2/crm/contacts/by-external-id").respond(json={"id": "k1"})
    assert code(invoke("crm contact view --provider vk --chat-id 7")) == 0
    assert dict(route.calls.last.request.url.params) == {"provider": "vk", "chatId": "7"}


def test_crm_contact_view_requires_identifier(invoke: Callable[..., Any]) -> None:
    result = invoke("crm contact view")
    assert isinstance(result.exception, ValidationError)
    assert code(result) == 2


def test_crm_contact_view_bad_external_id(invoke: Callable[..., Any]) -> None:
    result = invoke("crm contact view --external-id telegram")
    assert isinstance(result.exception, ValidationError)
    assert code(result) == 2


# --------------------------------------------------------------------------- config


def test_config_set_and_get(invoke: Callable[..., Any]) -> None:
    assert code(invoke("config set output json")) == 0
    result = invoke("config get output")
    assert code(result) == 0
    assert result.stdout.strip() == "json"


def test_config_get_under_ids_prints_the_value(run: Any) -> None:
    """Формат ids печатал имя ключа вместо значения."""
    assert run(["config", "set", "output", "ids"]).exit_code == 0
    result = run(["config", "get", "output"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "ids"


def test_config_list_under_ids_warns_instead_of_printing_nothing(run: Any) -> None:
    assert run(["config", "set", "output", "ids"]).exit_code == 0
    result = run(["config", "list"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == ""
    assert "ids" in result.stderr


def test_config_get_unknown_key(invoke: Callable[..., Any]) -> None:
    result = invoke("config get nope")
    assert isinstance(result.exception, ValidationError)
    assert code(result) == 2


def test_config_set_rejects_bad_output(invoke: Callable[..., Any]) -> None:
    result = invoke("config set output мусор")
    assert isinstance(result.exception, ValidationError)
    assert code(result) == 2


def test_config_set_rejects_bad_prompt(invoke: Callable[..., Any]) -> None:
    assert code(invoke("config set prompt maybe")) == 2


def test_config_list(invoke: Callable[..., Any]) -> None:
    invoke("config set output json")
    result = invoke("config list")
    assert code(result) == 0
    assert "output" in result.stdout
    assert "json" in result.stdout
    assert "pager" not in result.stdout


def test_config_set_rejects_the_removed_pager_key(invoke: Callable[..., Any]) -> None:
    result = invoke("config set pager less")
    assert isinstance(result.exception, ValidationError)
    assert code(result) == 2
    assert "Неизвестная настройка" in str(result.exception)


def test_config_clear_cache(invoke: Callable[..., Any], isolated_config: Path) -> None:
    cache = isolated_config / "cache"
    cache.mkdir()
    (cache / "x.json").write_text("{}", encoding="utf-8")
    assert code(invoke("config clear-cache")) == 0
    assert not cache.exists()


def test_config_clear_cache_removes_task_code_cache(
    invoke: Callable[..., Any], isolated_config: Path
) -> None:
    from yougile_cli.resolve import task_cache_path

    cache = task_cache_path(HOST)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text('{"updated": 0, "codes": {}}', encoding="utf-8")
    (cache.parent / "tasks-other.json").write_text("{}", encoding="utf-8")
    result = invoke("config clear-cache")
    assert code(result) == 0
    assert not cache.parent.exists()
    assert "2" in result.stderr


def test_config_clear_cache_reports_entries_as_json(
    invoke: Callable[..., Any], isolated_config: Path
) -> None:
    cache = isolated_config / "cache"
    cache.mkdir()
    (cache / "tasks-yougile.com.json").write_text("{}", encoding="utf-8")
    result = invoke("config clear-cache --json path,removed,entries")
    assert code(result) == 0
    payload = json.loads(result.stdout)
    row = payload[0] if isinstance(payload, list) else payload
    assert row == {"path": str(cache), "removed": True, "entries": 1}


# --------------------------------------------------------------------------- alias


def test_alias_set_list_delete(invoke: Callable[..., Any]) -> None:
    assert code(invoke(["alias", "set", "mine", "task list --assignee @me"])) == 0
    listed = invoke("alias list")
    assert code(listed) == 0
    assert "mine" in listed.stdout
    assert "task list --assignee @me" in listed.stdout

    assert code(invoke("alias delete mine --yes")) == 0
    assert "mine" not in invoke("alias list").stdout


def test_alias_list_json_fields(invoke: Callable[..., Any]) -> None:
    invoke(["alias", "set", "mine", "task list"])
    invoke(["alias", "set", "co", "task view"])
    result = invoke("alias list --json name")
    assert code(result) == 0
    assert json.loads(result.stdout) == [{"name": "co"}, {"name": "mine"}]


def test_alias_list_unknown_json_field(invoke: Callable[..., Any]) -> None:
    invoke(["alias", "set", "mine", "task list"])
    result = invoke("alias list --json nope")
    assert isinstance(result.exception, YouGileError)
    assert code(result) == 1


def test_alias_set_rejects_core_command(invoke: Callable[..., Any]) -> None:
    result = invoke(["alias", "set", "status", "task list"])
    assert isinstance(result.exception, ValidationError)
    assert code(result) == 2


def test_alias_delete_unknown(invoke: Callable[..., Any]) -> None:
    result = invoke("alias delete nope --yes")
    assert isinstance(result.exception, ConfigError)
    assert code(result) == 1


def test_alias_delete_without_yes_needs_tty(invoke: Callable[..., Any]) -> None:
    invoke(["alias", "set", "mine", "task list"])
    result = invoke("alias delete mine")
    assert code(result) == 2


# --------------------------------------------------------------------------- expand_alias


def test_expand_alias_passthrough() -> None:
    assert misc.expand_alias(["task", "list"], {"mine": "task list"}) == ["task", "list"]


def test_expand_alias_simple() -> None:
    argv = misc.expand_alias(["mine", "--limit", "5"], {"mine": "task list --assignee @me"})
    assert argv == ["task", "list", "--assignee", "@me", "--limit", "5"]


def test_expand_alias_positional() -> None:
    aliases = {"open": "browse $1 --no-browser"}
    assert misc.expand_alias(["open", "ABC-1"], aliases) == ["browse", "ABC-1", "--no-browser"]


def test_expand_alias_positional_keeps_extra_args() -> None:
    aliases = {"open": "task view $1"}
    assert misc.expand_alias(["open", "ABC-1", "--web"], aliases) == [
        "task",
        "view",
        "ABC-1",
        "--web",
    ]


def test_expand_alias_all_args() -> None:
    aliases = {"mine": 'task list --assignee @me "$@"'}
    assert misc.expand_alias(["mine", "--limit", "5"], aliases) == [
        "task",
        "list",
        "--assignee",
        "@me",
        "--limit",
        "5",
    ]


def test_expand_alias_not_enough_arguments() -> None:
    with pytest.raises(ValidationError) as excinfo:
        misc.expand_alias(["open"], {"open": "task view $1"})
    assert excinfo.value.exit_code == 2


def test_expand_alias_empty_argv() -> None:
    assert misc.expand_alias([], {"mine": "task list"}) == []


# --------------------------------------------------------------------------- browse


def test_browse_root(invoke: Callable[..., Any]) -> None:
    result = invoke("browse --no-browser")
    assert code(result) == 0
    assert result.stdout.strip() == WEB_URL


def test_browse_board_by_name(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., dict[str, Any]]
) -> None:
    api.get("/api-v2/boards").respond(json=paged([{"id": "b1", "title": "Разработка"}]))
    result = invoke("browse Разработка --board --no-browser")
    assert code(result) == 0
    assert result.stdout.strip() == f"{WEB_URL}/board/b1"


def test_browse_task_url_keeps_code(invoke: Callable[..., Any]) -> None:
    result = invoke(f"browse https://ru.yougile.com/board/{BOARD_ID}#ABC-1 --no-browser")
    assert code(result) == 0
    assert result.stdout.strip() == f"{WEB_URL}/board/{BOARD_ID}#ABC-1"


def test_browse_task_by_id_walks_column(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(
        json={"id": TASK_ID, "title": "Задача", "columnId": "col1", "idTaskProject": "ABC-7"}
    )
    api.get("/api-v2/columns/col1").respond(
        json={"id": "col1", "title": "В работе", "boardId": "b1"}
    )
    result = invoke(["browse", "--task", TASK_ID, "--no-browser"])
    assert code(result) == 0
    assert result.stdout.strip() == f"{WEB_URL}/board/b1#ABC-7"


def test_browse_project_uses_first_board(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., dict[str, Any]]
) -> None:
    api.get("/api-v2/projects").respond(json=paged([{"id": "p1", "title": "Продажи"}]))
    api.get("/api-v2/boards").respond(json=paged([{"id": "b7", "title": "Сделки"}]))
    result = invoke("browse Продажи --project --no-browser")
    assert code(result) == 0
    assert result.stdout.strip() == f"{WEB_URL}/board/b7"


def test_browse_conflicting_kind_flags(invoke: Callable[..., Any]) -> None:
    result = invoke("browse x --task --board --no-browser")
    assert isinstance(result.exception, ValidationError)
    assert code(result) == 2


def test_browse_short_flags(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., dict[str, Any]]
) -> None:
    api.get("/api-v2/boards").respond(json=paged([{"id": "b1", "title": "Разработка"}]))
    result = invoke("browse Разработка -b -n")
    assert code(result) == 0
    assert result.stdout.strip() == f"{WEB_URL}/board/b1"


# --------------------------------------------------------------------------- status


def _status_routes(api: respx.MockRouter, paged: Callable[..., dict[str, Any]]) -> None:
    api.get("/api-v2/users/me").respond(json={"id": "u1", "email": "ivan@example.com"})
    api.get("/api-v2/task-list").respond(
        json=paged(
            [
                {
                    "id": "t1",
                    "title": "Починить логин",
                    "columnId": "col1",
                    "idTaskProject": "ABC-1",
                    "completed": False,
                },
                {
                    "id": "t2",
                    "title": "Старое",
                    "columnId": "col1",
                    "idTaskProject": "ABC-2",
                    "completed": True,
                },
            ]
        )
    )
    api.get("/api-v2/columns/col1").respond(
        json={"id": "col1", "title": "В работе", "boardId": "b1"}
    )
    api.get("/api-v2/boards/b1").respond(json={"id": "b1", "title": "Разработка"})


def test_status_groups_by_board(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., dict[str, Any]]
) -> None:
    _status_routes(api, paged)
    result = invoke("status")
    assert code(result) == 0
    assert "Разработка" in result.stdout
    assert "Починить логин" in result.stdout
    assert "Старое" not in result.stdout


def test_status_prints_titles_without_rich_markup(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., dict[str, Any]]
) -> None:
    """Square brackets in API data must not be parsed (or swallowed) as rich markup."""
    api.get("/api-v2/users/me").respond(json={"id": "u1", "email": "ivan@example.com"})
    api.get("/api-v2/task-list").respond(
        json=paged(
            [
                {
                    "id": "t1",
                    "title": "починить [/api/v2] роут",
                    "columnId": "col1",
                    "idTaskProject": "ABC-1",
                    "completed": False,
                }
            ]
        )
    )
    api.get("/api-v2/columns/col1").respond(
        json={"id": "col1", "title": "[QA] ревью", "boardId": "b1"}
    )
    api.get("/api-v2/boards/b1").respond(json={"id": "b1", "title": "[dev] Доска"})
    result = invoke("status")
    assert code(result) == 0, result.output
    assert "[dev] Доска" in result.stdout
    assert "починить [/api/v2] роут" in result.stdout
    assert "[QA] ревью" in result.stdout


def test_status_filters_by_me(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., dict[str, Any]]
) -> None:
    _status_routes(api, paged)
    invoke("status")
    listing = [call for call in api.calls if "task-list" in str(call.request.url)]
    assert listing
    assert dict(listing[0].request.url.params)["assignedTo"] == "u1"


def test_status_json_fields(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., dict[str, Any]]
) -> None:
    _status_routes(api, paged)
    result = invoke("status --json code,title,board")
    assert code(result) == 0
    assert json.loads(result.stdout) == [
        {"code": "ABC-1", "title": "Починить логин", "board": "Разработка"}
    ]


def test_status_empty(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., dict[str, Any]]
) -> None:
    api.get("/api-v2/users/me").respond(json={"id": "u1"})
    api.get("/api-v2/task-list").respond(json=paged([]))
    result = invoke("status")
    assert code(result) == 0
    assert "Нет незакрытых задач" in result.output


def test_status_requires_auth(runner: CliRunner) -> None:
    app = build_app()

    @app.callback()
    def _root(ctx: typer.Context) -> None:
        ctx.obj = AppContext(auth=ResolvedAuth(host=HOST, base_url=BASE_URL))

    result = runner.invoke(app, ["status"])
    assert code(result) == 4


# --------------------------------------------------------------------------- version


def test_version(invoke: Callable[..., Any]) -> None:
    from yougile_cli import __version__

    result = invoke("version")
    assert code(result) == 0
    assert f"yougile version {__version__}" in result.stdout
    assert "python" in result.stdout


def test_version_json(invoke: Callable[..., Any]) -> None:
    result = invoke("version --json version")
    assert code(result) == 2  # у version нет флагов вывода


# --------------------------------------------------------------------------- метавары

# ID и URL — латиница, но это общепринятые обозначения из спецификации, а не англицизмы.
ALLOWED_LATIN_METAVARS = {"ID", "URL"}
LATIN_RE = re.compile(r"[A-Za-z]+")


def iter_params(command: Any, path: str = "") -> Any:
    for param in getattr(command, "params", []):
        yield f"{path} {param.name}".strip(), param
    for name, sub in (getattr(command, "commands", None) or {}).items():
        yield from iter_params(sub, f"{path} {name}".strip())


def test_every_metavar_is_russian_and_uppercase() -> None:
    root = get_command(build_app())
    checked = 0
    for where, param in iter_params(root):
        if getattr(param, "is_flag", False) or param.name == "help":
            continue
        metavar = param.metavar
        assert metavar, f"{where}: метавар не задан, typer подставит латинский"
        assert metavar == metavar.upper(), f"{where}: метавар «{metavar}» не в верхнем регистре"
        for word in LATIN_RE.findall(metavar):
            assert word in ALLOWED_LATIN_METAVARS, f"{where}: латинский метавар «{metavar}»"
        checked += 1
    assert checked > 10


ESCAPE_ATTACK = "Имя\x1b]52;c;aGFjaw==\x1b\\\x1b[2J\x1b[31mFAKE"
# Ожидаемый результат очистки выписан руками, а не посчитан тем же кодом.
ESCAPE_CLEAN = "Имя�]52;c;aGFjaw==�\\�[2J�[31mFAKE"


def test_status_strips_escape_sequences_from_server_text(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., dict[str, Any]]
) -> None:
    """Название доски и заголовок задачи приходят с сервера (issue #1)."""
    api.get("/api-v2/users/me").respond(json={"id": "u1", "email": "ivan@example.com"})
    api.get("/api-v2/task-list").respond(
        json=paged(
            [
                {
                    "id": "t1",
                    "title": ESCAPE_ATTACK,
                    "columnId": "col1",
                    "idTaskProject": "ABC-1",
                    "completed": False,
                }
            ]
        )
    )
    api.get("/api-v2/columns/col1").respond(json={"id": "col1", "title": "Ревью", "boardId": "b1"})
    api.get("/api-v2/boards/b1").respond(json={"id": "b1", "title": ESCAPE_ATTACK})
    result = invoke("status")
    assert code(result) == 0, result.output
    assert "\x1b" not in result.output
    # Заголовок доски и строка задачи — каждая напечатана очищенной.
    assert result.stdout.count(ESCAPE_CLEAN) >= 2
