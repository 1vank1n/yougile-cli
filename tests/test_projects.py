"""Tests for `yougile project` and `yougile project role`."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from yougile_cli.commands.projects import app
from yougile_cli.context import AppContext
from yougile_cli.errors import YouGileError, exit_code_for
from yougile_cli.output import OutputFormat, OutputOptions

PROJECT_ID = "11111111-1111-4111-8111-111111111111"
ROLE_ID = "22222222-2222-4222-8222-222222222222"
USER_ID = "33333333-3333-4333-8333-333333333333"

PROJECT = {"id": PROJECT_ID, "title": "Ремонт", "timestamp": 1700000000000, "deleted": False}
ROLE = {"id": ROLE_ID, "name": "Менеджер", "description": "", "permissions": {"editTitle": True}}
PERMISSIONS = {"editTitle": True, "delete": False}


@pytest.fixture
def run(client: Any, runner: Any) -> Any:
    """Invoke the project sub-app with a ready AppContext, the way cli.py does."""

    def _run(
        args: list[str],
        *,
        fmt: str = "json",
        input: str | None = None,
    ) -> tuple[int, str, BaseException | None]:
        app_ctx = AppContext(out=OutputOptions(fmt=OutputFormat(fmt)))
        app_ctx.set_client(client)
        result = runner.invoke(app, args, input=input, obj=app_ctx)
        exc = result.exception
        code = exit_code_for(exc) if isinstance(exc, YouGileError) else result.exit_code
        return code, result.output, exc

    return _run


def body_of(route: Any, index: int = 0) -> Any:
    return json.loads(route.calls[index].request.content)


# --------------------------------------------------------------------------- list


def test_list_projects(run: Any, api: Any, paged: Any) -> None:
    route = api.get("/api-v2/projects").respond(json=paged([PROJECT]))
    code, out, _ = run(["list"])
    assert code == 0
    assert json.loads(out)[0]["id"] == PROJECT_ID
    assert route.calls[0].request.url.params["limit"] == "30"


def test_list_projects_search_and_deleted(run: Any, api: Any, paged: Any) -> None:
    route = api.get("/api-v2/projects").respond(json=paged([PROJECT]))
    code, _, _ = run(["list", "--search", "Ремонт", "--include-deleted", "--limit", "0"])
    assert code == 0
    params = route.calls[0].request.url.params
    assert params["title"] == "Ремонт"
    assert params["includeDeleted"] == "true"
    # limit 0 means "everything": the client falls back to its maximum page size.
    assert params["limit"] == "1000"


def test_list_projects_json_fields(run: Any, api: Any, paged: Any) -> None:
    api.get("/api-v2/projects").respond(json=paged([PROJECT]))
    code, out, _ = run(["list", "--json", "id,title"], fmt="table")
    assert code == 0
    assert json.loads(out) == [{"id": PROJECT_ID, "title": "Ремонт"}]


def test_list_projects_json_without_fields_lists_them(run: Any, api: Any, paged: Any) -> None:
    api.get("/api-v2/projects").respond(json=paged([PROJECT]))
    code, _, exc = run(["list", "--json", ""], fmt="table")
    assert code == 1
    assert "доступные поля" in str(getattr(exc, "hint", ""))


def test_list_projects_json_unknown_field(run: Any, api: Any, paged: Any) -> None:
    api.get("/api-v2/projects").respond(json=paged([PROJECT]))
    code, _, exc = run(["list", "--json", "nope"], fmt="table")
    assert code == 1
    assert "nope" in str(exc)


def test_list_projects_ids_format(run: Any, api: Any, paged: Any) -> None:
    api.get("/api-v2/projects").respond(json=paged([PROJECT]))
    code, out, _ = run(["list"], fmt="ids")
    assert code == 0
    assert out.strip() == PROJECT_ID


# --------------------------------------------------------------------------- view


def test_view_project_by_id(run: Any, api: Any) -> None:
    api.get(f"/api-v2/projects/{PROJECT_ID}").respond(json=PROJECT)
    code, out, _ = run(["view", PROJECT_ID])
    assert code == 0
    assert json.loads(out)["title"] == "Ремонт"


def test_view_project_resolves_name(run: Any, api: Any, paged: Any) -> None:
    listing = api.get("/api-v2/projects").respond(json=paged([PROJECT]))
    detail = api.get(f"/api-v2/projects/{PROJECT_ID}").respond(json=PROJECT)
    code, out, _ = run(["view", "Ремонт"])
    assert code == 0
    assert listing.calls[0].request.url.params["title"] == "Ремонт"
    assert detail.called
    assert json.loads(out)["id"] == PROJECT_ID


def test_view_project_not_found(run: Any, api: Any) -> None:
    api.get(f"/api-v2/projects/{PROJECT_ID}").respond(404, json={"message": "нет такого"})
    code, _, exc = run(["view", PROJECT_ID])
    assert code == 1
    assert "не найден" in str(exc).lower()


def test_view_project_unauthorized(run: Any, api: Any) -> None:
    api.get(f"/api-v2/projects/{PROJECT_ID}").respond(401, json={"message": "no"})
    code, _, _ = run(["view", PROJECT_ID])
    assert code == 4


# --------------------------------------------------------------------------- create


def test_create_project(run: Any, api: Any) -> None:
    route = api.post("/api-v2/projects").respond(201, json={"id": PROJECT_ID})
    code, out, _ = run(["create", "--title", "Ремонт", "--idempotency-key", "k1"])
    assert code == 0
    assert body_of(route) == {"title": "Ремонт", "idempotencyKey": "k1"}
    assert json.loads(out)["id"] == PROJECT_ID


def test_create_project_with_members(run: Any, api: Any) -> None:
    route = api.post("/api-v2/projects").respond(201, json={"id": PROJECT_ID})
    code, _, _ = run(["create", "--title", "Ремонт", "--user", f"{USER_ID}=admin"])
    assert code == 0
    assert body_of(route)["users"] == {USER_ID: "admin"}


# --------------------------------------------------------------------------- edit


def test_edit_project_title(run: Any, api: Any) -> None:
    route = api.put(f"/api-v2/projects/{PROJECT_ID}").respond(json={"id": PROJECT_ID})
    code, _, _ = run(["edit", PROJECT_ID, "--title", "Новый"])
    assert code == 0
    assert body_of(route) == {"title": "Новый"}


def test_edit_project_undelete(run: Any, api: Any) -> None:
    route = api.put(f"/api-v2/projects/{PROJECT_ID}").respond(json={"id": PROJECT_ID})
    code, _, _ = run(["edit", PROJECT_ID, "--undelete"])
    assert code == 0
    assert body_of(route) == {"deleted": False}


def test_edit_project_nothing_to_change(run: Any, api: Any) -> None:
    route = api.put(f"/api-v2/projects/{PROJECT_ID}").respond(json={"id": PROJECT_ID})
    code, _, exc = run(["edit", PROJECT_ID])
    assert code == 2
    assert "Нечего менять" in str(exc)
    assert not route.called


# --------------------------------------------------------------------------- delete


def test_delete_project_is_put_deleted_true(run: Any, api: Any) -> None:
    route = api.put(f"/api-v2/projects/{PROJECT_ID}").respond(json={"id": PROJECT_ID})
    code, out, _ = run(["delete", PROJECT_ID, "--yes"])
    assert code == 0
    assert route.calls[0].request.method == "PUT"
    assert body_of(route) == {"deleted": True}
    assert json.loads(out)["id"] == PROJECT_ID


def test_delete_project_needs_yes_without_tty(run: Any, api: Any) -> None:
    route = api.put(f"/api-v2/projects/{PROJECT_ID}").respond(json={"id": PROJECT_ID})
    code, _, exc = run(["delete", PROJECT_ID])
    assert code == 2
    assert "--yes" in str(getattr(exc, "hint", ""))
    assert not route.called


def test_delete_project_confirmed(run: Any, api: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yougile_cli.commands.projects.is_tty", lambda *_a, **_k: True)
    route = api.put(f"/api-v2/projects/{PROJECT_ID}").respond(json={"id": PROJECT_ID})
    code, _, _ = run(["delete", PROJECT_ID], input="y\n")
    assert code == 0
    assert body_of(route) == {"deleted": True}


def test_delete_project_declined(run: Any, api: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yougile_cli.commands.projects.is_tty", lambda *_a, **_k: True)
    route = api.put(f"/api-v2/projects/{PROJECT_ID}").respond(json={"id": PROJECT_ID})
    code, _, _ = run(["delete", PROJECT_ID], input="n\n")
    assert code == 1
    assert not route.called


# --------------------------------------------------------------------------- roles


def test_role_list(run: Any, api: Any, paged: Any) -> None:
    route = api.get(f"/api-v2/projects/{PROJECT_ID}/roles").respond(json=paged([ROLE]))
    code, out, _ = run(["role", "list", PROJECT_ID, "--search", "Менеджер", "--limit", "5"])
    assert code == 0
    params = route.calls[0].request.url.params
    assert params["name"] == "Менеджер"
    assert params["limit"] == "5"
    assert json.loads(out)[0]["id"] == ROLE_ID


def test_role_view_resolves_name(run: Any, api: Any, paged: Any) -> None:
    listing = api.get(f"/api-v2/projects/{PROJECT_ID}/roles").respond(json=paged([ROLE]))
    detail = api.get(f"/api-v2/projects/{PROJECT_ID}/roles/{ROLE_ID}").respond(json=ROLE)
    code, out, _ = run(["role", "view", PROJECT_ID, "Менеджер"])
    assert code == 0
    assert listing.calls[0].request.url.params["name"] == "Менеджер"
    assert detail.called
    assert json.loads(out)["permissions"] == {"editTitle": True}


def test_role_create_from_file(run: Any, api: Any, tmp_path: Path) -> None:
    permissions = tmp_path / "perm.json"
    permissions.write_text(json.dumps(PERMISSIONS), encoding="utf-8")
    route = api.post(f"/api-v2/projects/{PROJECT_ID}/roles").respond(201, json={"id": ROLE_ID})
    code, out, _ = run(["role", "create", PROJECT_ID, "--name", "Менеджер", "-p", str(permissions)])
    assert code == 0
    assert body_of(route) == {"name": "Менеджер", "permissions": PERMISSIONS}
    assert json.loads(out)["id"] == ROLE_ID


def test_role_create_permissions_from_stdin(run: Any, api: Any) -> None:
    route = api.post(f"/api-v2/projects/{PROJECT_ID}/roles").respond(201, json={"id": ROLE_ID})
    code, _, _ = run(
        ["role", "create", PROJECT_ID, "--name", "Менеджер", "-p", "-"],
        input=json.dumps(PERMISSIONS),
    )
    assert code == 0
    assert body_of(route)["permissions"] == PERMISSIONS


def test_role_create_rejects_broken_json(run: Any, api: Any, tmp_path: Path) -> None:
    permissions = tmp_path / "perm.json"
    permissions.write_text("{не json", encoding="utf-8")
    route = api.post(f"/api-v2/projects/{PROJECT_ID}/roles").respond(201, json={"id": ROLE_ID})
    code, _, exc = run(["role", "create", PROJECT_ID, "--name", "Менеджер", "-p", str(permissions)])
    assert code == 2
    assert "JSON" in str(exc)
    assert not route.called


def test_role_edit(run: Any, api: Any) -> None:
    route = api.put(f"/api-v2/projects/{PROJECT_ID}/roles/{ROLE_ID}").respond(json={"id": ROLE_ID})
    code, _, _ = run(["role", "edit", PROJECT_ID, ROLE_ID, "--description", "Ведёт проект"])
    assert code == 0
    assert body_of(route) == {"description": "Ведёт проект"}


def test_role_edit_nothing_to_change(run: Any, api: Any) -> None:
    route = api.put(f"/api-v2/projects/{PROJECT_ID}/roles/{ROLE_ID}").respond(json={"id": ROLE_ID})
    code, _, _ = run(["role", "edit", PROJECT_ID, ROLE_ID])
    assert code == 2
    assert not route.called


def test_role_delete_uses_real_delete(run: Any, api: Any) -> None:
    route = api.delete(f"/api-v2/projects/{PROJECT_ID}/roles/{ROLE_ID}").respond(
        json={"id": ROLE_ID, "name": "Менеджер"}
    )
    code, out, _ = run(["role", "delete", PROJECT_ID, ROLE_ID, "--yes"])
    assert code == 0
    assert route.calls[0].request.method == "DELETE"
    assert json.loads(out)["id"] == ROLE_ID


def test_role_delete_needs_yes_without_tty(run: Any, api: Any) -> None:
    route = api.delete(f"/api-v2/projects/{PROJECT_ID}/roles/{ROLE_ID}").respond(json={})
    code, _, _ = run(["role", "delete", PROJECT_ID, ROLE_ID])
    assert code == 2
    assert not route.called


# ------------------------------------------------------- defect 1: НАЗВАНИЕ и единые метавары


def latin_metavars(sub_app: Any) -> list[str]:
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

    walk(get_command(sub_app), "project")
    return found


def test_project_commands_have_no_latin_metavars() -> None:
    assert latin_metavars(app) == []


def test_create_project_positional_title(run: Any, api: Any) -> None:
    route = api.post("/api-v2/projects").respond(201, json=PROJECT)
    code, _, _ = run(["create", "Ремонт"])
    assert code == 0
    assert body_of(route)["title"] == "Ремонт"


def test_create_project_positional_and_matching_flag(run: Any, api: Any) -> None:
    route = api.post("/api-v2/projects").respond(201, json=PROJECT)
    code, _, _ = run(["create", "Ремонт", "--title", "Ремонт"])
    assert code == 0
    assert body_of(route)["title"] == "Ремонт"


def test_create_project_rejects_conflicting_titles(run: Any, api: Any) -> None:
    route = api.post("/api-v2/projects").respond(201, json=PROJECT)
    code, _, exc = run(["create", "Ремонт", "--title", "Другой"])
    assert code == 2
    assert "дважды" in str(exc)
    assert not route.called


def test_create_project_without_title_is_usage_error(run: Any, api: Any) -> None:
    route = api.post("/api-v2/projects").respond(201, json=PROJECT)
    code, _, exc = run(["create"])
    assert code == 2
    assert "Не указано название проекта." in str(exc)
    assert not route.called


def test_role_create_accepts_positional_name(run: Any, api: Any, tmp_path: Path) -> None:
    permissions = tmp_path / "perm.json"
    permissions.write_text(json.dumps(PERMISSIONS), encoding="utf-8")
    route = api.post(f"/api-v2/projects/{PROJECT_ID}/roles").respond(201, json=ROLE)
    code, _, _ = run(["role", "create", PROJECT_ID, "Менеджер", "-p", str(permissions)])
    assert code == 0
    assert body_of(route)["name"] == "Менеджер"


def test_role_create_rejects_conflicting_names(run: Any, api: Any, tmp_path: Path) -> None:
    permissions = tmp_path / "perm.json"
    permissions.write_text(json.dumps(PERMISSIONS), encoding="utf-8")
    route = api.post(f"/api-v2/projects/{PROJECT_ID}/roles").respond(201, json=ROLE)
    code, _, exc = run(
        ["role", "create", PROJECT_ID, "Менеджер", "--name", "Другая", "-p", str(permissions)]
    )
    assert code == 2
    assert "дважды" in str(exc)
    assert not route.called


# ------------------------------------------------------- defect 3: род и число в сообщениях


def test_missing_project_name_is_masculine(run: Any, api: Any, paged: Any) -> None:
    api.get("/api-v2/projects").respond(json=paged([]))
    code, _, exc = run(["view", "нет-такого-проекта"])
    assert code == 1
    assert str(exc) == "Проект «нет-такого-проекта» не найден."


def test_ambiguous_project_name_uses_plural_genitive(run: Any, api: Any, paged: Any) -> None:
    api.get("/api-v2/projects").respond(json=paged([PROJECT, {**PROJECT, "id": USER_ID}]))
    code, _, exc = run(["view", "Ремонт"])
    assert code == 1
    assert "Найдено несколько (2) проектов с именем «Ремонт»." in str(exc)


def test_missing_role_name_is_feminine(run: Any, api: Any, paged: Any) -> None:
    api.get(f"/api-v2/projects/{PROJECT_ID}/roles").respond(json=paged([]))
    code, _, exc = run(["role", "view", PROJECT_ID, "Нет-такой-роли"])
    assert code == 1
    assert str(exc) == "Роль «Нет-такой-роли» не найдена."
