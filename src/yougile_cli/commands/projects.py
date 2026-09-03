"""`yougile project` — projects and their roles, shaped after `gh`.

Projects have no DELETE method in the API: removing one is a ``PUT`` with
``{"deleted": true}``, and ``project edit --undelete`` is the way back. Project
roles are one of the three objects with a real DELETE.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from ..client import YouGileClient
from ..context import AppContext, ctx_client, emit, get_ctx
from ..errors import CancelledError, ValidationError, single_name
from ..output import apply_json_fields, is_tty, target_label
from ..resolve import parse_kv_options, resolve_one, resolve_project_id, resolve_user_id

__all__ = ["app", "role_app"]

PROJECTS_PATH = "/api-v2/projects"
PROJECT_COLUMNS = ["id", "title", "timestamp"]
ROLE_COLUMNS = ["id", "name", "description"]

app = typer.Typer(no_args_is_help=True, help="Проекты: список, просмотр, создание, изменение.")
role_app = typer.Typer(no_args_is_help=True, help="Роли проекта и их права доступа.")
app.add_typer(role_app, name="role")

JSON_OPT = typer.Option(
    None, "--json", metavar="ПОЛЯ", help="Вывести JSON только с перечисленными через запятую полями"
)
JQ_OPT = typer.Option(None, "--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq для JSON-вывода")
FULL_IDS_OPT = typer.Option(False, "--full-ids", help="Показывать идентификаторы целиком")
LIMIT_OPT = typer.Option(
    30, "--limit", "-L", min=0, metavar="ЧИСЛО", help="Сколько записей вернуть; 0 — все"
)
YES_OPT = typer.Option(False, "--yes", "-y", help="Не спрашивать подтверждение")

TITLE_ARG_HELP = "Название (можно передать и флагом --title)"
TITLE_OPT_HELP = "Название; синоним позиционного аргумента НАЗВАНИЕ"


def _apply_output(
    app_ctx: AppContext,
    *,
    json_fields: str | None = None,
    jq: str | None = None,
    full_ids: bool = False,
    resource: str | None = "project",
) -> None:
    """Fold the per-command output flags into the context's output options.

    `-o/--output` stays a root flag: cli.hoist_root_flags lets it trail any
    subcommand, so redeclaring it here would only split the help text.
    """
    apply_json_fields(app_ctx.out, json_fields, resource)
    if jq:
        app_ctx.out.jq = jq
    if full_ids:
        app_ctx.out.full_ids = True


def _max_items(limit: int) -> int | None:
    return None if limit <= 0 else limit


def _emit_result(app_ctx: AppContext, data: Any) -> None:
    """Identifiers of just-changed objects must stay copy-pasteable."""
    app_ctx.out.full_ids = True
    emit(app_ctx, data)


def _confirm(app_ctx: AppContext, question: str, yes: bool) -> None:
    if yes:
        return
    if not app_ctx.prompt_enabled or not is_tty(sys.stdin):
        raise ValidationError(
            "Требуется подтверждение, но ввод не интерактивный.",
            hint="Повторите команду с флагом --yes.",
        )
    if not typer.confirm(question):
        raise CancelledError()


def _roles_path(project_id: str) -> str:
    return f"{PROJECTS_PATH}/{project_id}/roles"


def _resolve_role_id(client: YouGileClient, project_id: str, value: str) -> str:
    return resolve_one(
        client,
        path=_roles_path(project_id),
        value=value,
        name_field="name",
        kind="роль",
    )


def _resolve_department_id(client: YouGileClient, value: str) -> str:
    return resolve_one(client, path="/api-v2/departments", value=value, kind="отдел")


def _members(
    client: YouGileClient,
    values: list[str] | None,
    *,
    departments: bool = False,
) -> dict[str, str] | None:
    """Turn repeated `id=role` flags into the {id: role} object the API expects."""
    raw = parse_kv_options(list(values or []))
    if not raw:
        return None
    result: dict[str, str] = {}
    for key, role in raw.items():
        ident = _resolve_department_id(client, key) if departments else resolve_user_id(client, key)
        value = role[-1] if isinstance(role, list) else role
        result[ident] = "" if value is None else str(value)
    return result


def _load_permissions(source: str) -> dict[str, Any]:
    """Read the permission tree from a JSON file or from stdin when source is `-`."""
    try:
        text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(f"Не удалось прочитать файл прав доступа «{source}»: {exc}") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValidationError(f"Файл прав доступа «{source}» не является корректным JSON.") from exc
    if not isinstance(data, dict):
        raise ValidationError("Права доступа должны быть JSON-объектом.")
    return data


USER_OPT_HELP = "Участник в формате id=роль (можно повторять); вместо ID можно указать email"
DEPT_OPT_HELP = "Отдел в формате id=роль (можно повторять); вместо ID можно указать название"
PROJECT_ARG_HELP = "ID, ссылка или название проекта"
ROLE_ARG_HELP = "ID или название роли"
PERMISSIONS_HELP = "JSON-файл с деревом прав доступа; «-» — читать из stdin"

PROJECT_ARG = typer.Argument(..., metavar="ПРОЕКТ", help=PROJECT_ARG_HELP)
ROLE_ARG = typer.Argument(..., metavar="РОЛЬ", help=ROLE_ARG_HELP)


@app.command("list")
def list_projects(
    ctx: typer.Context,
    search: str | None = typer.Option(
        None, "--search", "-S", metavar="ТЕКСТ", help="Фильтр по названию проекта"
    ),
    include_deleted: bool = typer.Option(
        False, "--include-deleted", help="Показывать в том числе удалённые проекты"
    ),
    limit: int = LIMIT_OPT,
    json_fields: str | None = JSON_OPT,
    jq: str | None = JQ_OPT,
    full_ids: bool = FULL_IDS_OPT,
) -> None:
    """Список проектов."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq, full_ids=full_ids)
    params = {"title": search, "includeDeleted": True if include_deleted else None}
    items = ctx_client(ctx).collect(PROJECTS_PATH, params, max_items=_max_items(limit))
    columns = [*PROJECT_COLUMNS, "deleted"] if include_deleted else PROJECT_COLUMNS
    emit(app_ctx, items, columns=columns)


@app.command("view")
def view_project(
    ctx: typer.Context,
    project: str = PROJECT_ARG,
    json_fields: str | None = JSON_OPT,
    jq: str | None = JQ_OPT,
    full_ids: bool = FULL_IDS_OPT,
) -> None:
    """Показать проект."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq, full_ids=full_ids)
    client = ctx_client(ctx)
    project_id = resolve_project_id(client, project)
    emit(app_ctx, client.get(f"{PROJECTS_PATH}/{project_id}"))


@app.command("create")
def create_project(
    ctx: typer.Context,
    title_arg: Annotated[
        str | None, typer.Argument(metavar="НАЗВАНИЕ", help=TITLE_ARG_HELP)
    ] = None,
    title: Annotated[
        str | None, typer.Option("--title", "-t", metavar="НАЗВАНИЕ", help=TITLE_OPT_HELP)
    ] = None,
    users: Annotated[
        list[str] | None,
        typer.Option("--user", "-u", metavar="СОТРУДНИК=РОЛЬ", help=USER_OPT_HELP),
    ] = None,
    departments: Annotated[
        list[str] | None,
        typer.Option("--department", "-d", metavar="ОТДЕЛ=РОЛЬ", help=DEPT_OPT_HELP),
    ] = None,
    idempotency_key: str | None = typer.Option(
        None,
        "--idempotency-key",
        metavar="КЛЮЧ",
        help="Ключ идемпотентности: повторный запрос с тем же ключом не создаст дубликат",
    ),
    json_fields: str | None = JSON_OPT,
    jq: str | None = JQ_OPT,
) -> None:
    """Создать проект."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    client = ctx_client(ctx)
    body = {
        "title": single_name(title_arg, title, genitive="проекта"),
        "users": _members(client, users),
        "departments": _members(client, departments, departments=True),
        "idempotencyKey": idempotency_key,
    }
    _emit_result(app_ctx, client.post(PROJECTS_PATH, body))


@app.command("edit")
def edit_project(
    ctx: typer.Context,
    project: str = PROJECT_ARG,
    title: str | None = typer.Option(
        None, "--title", "-t", metavar="НАЗВАНИЕ", help="Новое название проекта"
    ),
    users: Annotated[
        list[str] | None,
        typer.Option("--user", "-u", metavar="СОТРУДНИК=РОЛЬ", help=USER_OPT_HELP),
    ] = None,
    departments: Annotated[
        list[str] | None,
        typer.Option("--department", "-d", metavar="ОТДЕЛ=РОЛЬ", help=DEPT_OPT_HELP),
    ] = None,
    undelete: bool = typer.Option(False, "--undelete", help="Восстановить удалённый проект"),
    json_fields: str | None = JSON_OPT,
    jq: str | None = JQ_OPT,
) -> None:
    """Изменить проект."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    client = ctx_client(ctx)
    project_id = resolve_project_id(client, project)
    body: dict[str, Any] = {
        "title": title,
        "users": _members(client, users),
        "departments": _members(client, departments, departments=True),
    }
    if undelete:
        body["deleted"] = False
    if all(value is None for value in body.values()):
        raise ValidationError(
            "Нечего менять.",
            hint="Укажите --title, --user, --department или --undelete.",
        )
    _emit_result(app_ctx, client.put(f"{PROJECTS_PATH}/{project_id}", body))


@app.command("delete")
def delete_project(
    ctx: typer.Context,
    project: str = PROJECT_ARG,
    yes: bool = YES_OPT,
    json_fields: str | None = JSON_OPT,
    jq: str | None = JQ_OPT,
) -> None:
    """Удалить проект (пометить удалённым)."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    client = ctx_client(ctx)
    project_id = resolve_project_id(client, project)
    _confirm(app_ctx, f"Удалить проект {target_label(project, project_id)}?", yes)
    # The API has no DELETE for projects: deleting is a PUT with deleted=true.
    _emit_result(app_ctx, client.put(f"{PROJECTS_PATH}/{project_id}", {"deleted": True}))


@role_app.command("list")
def list_roles(
    ctx: typer.Context,
    project: str = PROJECT_ARG,
    search: str | None = typer.Option(
        None, "--search", "-S", metavar="ТЕКСТ", help="Фильтр по названию роли"
    ),
    limit: int = LIMIT_OPT,
    json_fields: str | None = JSON_OPT,
    jq: str | None = JQ_OPT,
    full_ids: bool = FULL_IDS_OPT,
) -> None:
    """Список ролей проекта."""
    app_ctx = get_ctx(ctx)
    _apply_output(
        app_ctx, json_fields=json_fields, jq=jq, full_ids=full_ids, resource="project-role"
    )
    client = ctx_client(ctx)
    project_id = resolve_project_id(client, project)
    items = client.collect(_roles_path(project_id), {"name": search}, max_items=_max_items(limit))
    emit(app_ctx, items, columns=ROLE_COLUMNS)


@role_app.command("view")
def view_role(
    ctx: typer.Context,
    project: str = PROJECT_ARG,
    role: str = ROLE_ARG,
    json_fields: str | None = JSON_OPT,
    jq: str | None = JQ_OPT,
    full_ids: bool = FULL_IDS_OPT,
) -> None:
    """Показать роль вместе с деревом прав."""
    app_ctx = get_ctx(ctx)
    _apply_output(
        app_ctx, json_fields=json_fields, jq=jq, full_ids=full_ids, resource="project-role"
    )
    client = ctx_client(ctx)
    project_id = resolve_project_id(client, project)
    role_id = _resolve_role_id(client, project_id, role)
    emit(app_ctx, client.get(f"{_roles_path(project_id)}/{role_id}"))


@role_app.command("create")
def create_role(
    ctx: typer.Context,
    project: str = PROJECT_ARG,
    name_arg: Annotated[
        str | None, typer.Argument(metavar="НАЗВАНИЕ", help="Название роли (синоним --name)")
    ] = None,
    name: Annotated[
        str | None,
        typer.Option("--name", "-n", metavar="НАЗВАНИЕ", help="Название роли; синоним НАЗВАНИЕ"),
    ] = None,
    permissions_file: str = typer.Option(
        ..., "--permissions-file", "-p", metavar="ФАЙЛ", help=PERMISSIONS_HELP
    ),
    description: str | None = typer.Option(
        None, "--description", metavar="ТЕКСТ", help="Описание роли"
    ),
    json_fields: str | None = JSON_OPT,
    jq: str | None = JQ_OPT,
) -> None:
    """Создать роль проекта."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq, resource="project-role")
    client = ctx_client(ctx)
    project_id = resolve_project_id(client, project)
    body = {
        "name": single_name(name_arg, name, genitive="роли", flag="--name"),
        "description": description,
        "permissions": _load_permissions(permissions_file),
    }
    _emit_result(app_ctx, client.post(_roles_path(project_id), body))


@role_app.command("edit")
def edit_role(
    ctx: typer.Context,
    project: str = PROJECT_ARG,
    role: str = ROLE_ARG,
    name: str | None = typer.Option(
        None, "--name", "-n", metavar="НАЗВАНИЕ", help="Новое название роли"
    ),
    description: str | None = typer.Option(
        None, "--description", metavar="ТЕКСТ", help="Новое описание роли"
    ),
    permissions_file: str | None = typer.Option(
        None, "--permissions-file", "-p", metavar="ФАЙЛ", help=PERMISSIONS_HELP
    ),
    json_fields: str | None = JSON_OPT,
    jq: str | None = JQ_OPT,
) -> None:
    """Изменить роль проекта."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq, resource="project-role")
    client = ctx_client(ctx)
    project_id = resolve_project_id(client, project)
    role_id = _resolve_role_id(client, project_id, role)
    body = {
        "name": name,
        "description": description,
        "permissions": _load_permissions(permissions_file) if permissions_file else None,
    }
    if all(value is None for value in body.values()):
        raise ValidationError(
            "Нечего менять.",
            hint="Укажите --name, --description или --permissions-file.",
        )
    _emit_result(app_ctx, client.put(f"{_roles_path(project_id)}/{role_id}", body))


@role_app.command("delete")
def delete_role(
    ctx: typer.Context,
    project: str = PROJECT_ARG,
    role: str = ROLE_ARG,
    yes: bool = YES_OPT,
    json_fields: str | None = JSON_OPT,
    jq: str | None = JQ_OPT,
) -> None:
    """Удалить роль проекта."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq, resource="project-role")
    client = ctx_client(ctx)
    project_id = resolve_project_id(client, project)
    role_id = _resolve_role_id(client, project_id, role)
    _confirm(app_ctx, f"Удалить роль {role_id} из проекта {project_id}?", yes)
    # Project roles are one of the three objects with a real DELETE method.
    _emit_result(app_ctx, client.delete(f"{_roles_path(project_id)}/{role_id}"))
