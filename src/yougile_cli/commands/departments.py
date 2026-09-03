"""`yougile department` — отделы компании (gh-стиль: list/view/create/edit/delete/tree)."""

from __future__ import annotations

import sys
from typing import Annotated, Any

import typer
from rich.text import Text
from rich.tree import Tree

from ..client import YouGileClient
from ..context import AppContext, get_ctx
from ..errors import CancelledError, ResolveError, ValidationError, single_name
from ..output import OutputFormat, is_tty, shorten_id, target_label
from ..resolve import parse_kv_options, resolve_one, resolve_user_id

__all__ = ["app", "resolve_department_id"]

PATH = "/api-v2/departments"
LIST_COLUMNS = ["id", "title", "parentId", "deleted"]

app = typer.Typer(
    no_args_is_help=True,
    help="Отделы компании: список, просмотр, создание, изменение, удаление, дерево.",
)

JsonFields = Annotated[
    str | None,
    typer.Option(
        "--json",
        metavar="ПОЛЯ",
        help="Вывести JSON только с перечисленными через запятую полями.",
    ),
]
JqExpr = Annotated[
    str | None,
    typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Прогнать JSON через выражение jq."),
]
LimitOpt = Annotated[
    int,
    typer.Option(
        "--limit", "-L", metavar="ЧИСЛО", min=0, help="Сколько отделов показать (0 — все)."
    ),
]
ParentOpt = Annotated[
    str | None,
    typer.Option("--parent", "-p", metavar="ОТДЕЛ", help="Родительский отдел: ID или название."),
]
UserOpt = Annotated[
    list[str] | None,
    typer.Option("--user", "-u", metavar="КТО=РОЛЬ", help="Сотрудник и его роль, можно повторять."),
]
IncludeDeletedOpt = Annotated[
    bool,
    typer.Option("--include-deleted", help="Показывать удалённые отделы."),
]
YesOpt = Annotated[bool, typer.Option("--yes", "-y", help="Не спрашивать подтверждение.")]
TitleArg = Annotated[
    str | None,
    typer.Argument(metavar="НАЗВАНИЕ", help="Название нового отдела."),
]
TitleOpt = Annotated[
    str | None,
    typer.Option("--title", "-t", metavar="НАЗВАНИЕ", help="То же название, но флагом."),
]


def resolve_department_id(client: YouGileClient, value: str) -> str:
    return resolve_one(client, path=PATH, value=value, kind="отдел")


def _prepare(
    ctx: typer.Context,
    json_fields: str | None = None,
    jq: str | None = None,
) -> AppContext:
    """Apply the per-command output flags on top of the global ones, like gh does."""
    app_ctx = get_ctx(ctx)
    if json_fields is not None:
        # An empty `--json` makes output.select_fields list the available fields (exit 1).
        app_ctx.out.json_fields = [name.strip() for name in json_fields.split(",") if name.strip()]
        app_ctx.out.fmt = OutputFormat.JSON
    if jq:
        app_ctx.out.jq = jq
    return app_ctx


def _confirm(app_ctx: AppContext, message: str, yes: bool) -> None:
    if yes:
        return
    if not app_ctx.prompt_enabled or app_ctx.out.machine_readable or not is_tty(sys.stdin):
        raise ValidationError(
            "Требуется подтверждение, а ввод не интерактивный.",
            hint="Добавьте --yes, чтобы подтвердить без вопроса.",
        )
    if not typer.confirm(message):
        raise CancelledError()


def _users_payload(client: YouGileClient, values: list[str] | None) -> dict[str, str] | None:
    """Turn repeated `--user КТО=РОЛЬ` flags into the API `users` object."""
    parsed = parse_kv_options(list(values or []))
    if not parsed:
        return None
    return {
        resolve_user_id(client, key): "" if role is None else str(role)
        for key, role in parsed.items()
    }


def _label(item: dict[str, Any], *, full_ids: bool) -> Text:
    text = Text(str(item.get("title") or "(без названия)"), style="bold")
    item_id = str(item.get("id") or "")
    if item_id:
        text.append(f"  {shorten_id(item_id, full=full_ids)}", style="dim")
    if item.get("deleted"):
        text.append(" (удалён)", style="red")
    return text


def _build_tree(items: list[dict[str, Any]], root_id: str | None, *, full_ids: bool) -> Tree:
    by_id = {str(i.get("id")): i for i in items if i.get("id")}
    children: dict[str | None, list[dict[str, Any]]] = {}
    for item in items:
        parent = str(item.get("parentId") or "") or None
        # A parent outside the fetched set (or a self-reference) is a root here.
        if parent not in by_id or parent == str(item.get("id") or ""):
            parent = None
        children.setdefault(parent, []).append(item)
    for bucket in children.values():
        bucket.sort(key=lambda i: str(i.get("title") or "").casefold())

    seen: set[str] = set()

    def attach(node: Tree, item: dict[str, Any]) -> None:
        item_id = str(item.get("id") or "")
        if item_id in seen:
            return
        seen.add(item_id)
        branch = node.add(_label(item, full_ids=full_ids))
        for child in children.get(item_id, []):
            attach(branch, child)

    if root_id is not None:
        root_item = by_id.get(root_id)
        if root_item is None:
            raise ResolveError(f"Отдел {root_id} не найден среди полученных отделов.")
        tree = Tree(_label(root_item, full_ids=full_ids))
        seen.add(root_id)
        for child in children.get(root_id, []):
            attach(tree, child)
        return tree

    tree = Tree(Text("Отделы", style="bold"))
    for item in children.get(None, []):
        attach(tree, item)
    # A parentId cycle would leave nodes unreachable from the root, so surface them anyway.
    for item in items:
        attach(tree, item)
    return tree


@app.command("list")
def list_departments(
    ctx: typer.Context,
    parent: ParentOpt = None,
    search: Annotated[
        str | None,
        typer.Option("--search", "-S", metavar="ТЕКСТ", help="Искать по названию отдела."),
    ] = None,
    include_deleted: IncludeDeletedOpt = False,
    limit: LimitOpt = 30,
    json_fields: JsonFields = None,
    jq: JqExpr = None,
) -> None:
    """Список отделов."""
    app_ctx = _prepare(ctx, json_fields, jq)
    client = app_ctx.client()
    params: dict[str, Any] = {}
    if search:
        params["title"] = search
    if parent:
        params["parentId"] = resolve_department_id(client, parent)
    if include_deleted:
        params["includeDeleted"] = True
    items = client.collect(PATH, params or None, max_items=limit or None)
    app_ctx.emit(items, LIST_COLUMNS)


@app.command("view")
def view_department(
    ctx: typer.Context,
    department: Annotated[str, typer.Argument(metavar="ОТДЕЛ", help="ID или название отдела.")],
    json_fields: JsonFields = None,
    jq: JqExpr = None,
) -> None:
    """Показать отдел."""
    app_ctx = _prepare(ctx, json_fields, jq)
    client = app_ctx.client()
    department_id = resolve_department_id(client, department)
    app_ctx.emit(client.get(f"{PATH}/{department_id}"))


@app.command("create")
def create_department(
    ctx: typer.Context,
    name: TitleArg = None,
    title: TitleOpt = None,
    parent: ParentOpt = None,
    user: UserOpt = None,
    json_fields: JsonFields = None,
    jq: JqExpr = None,
) -> None:
    """Создать отдел."""
    app_ctx = _prepare(ctx, json_fields, jq)
    client = app_ctx.client()
    body: dict[str, Any] = {
        "title": single_name(
            name,
            title,
            genitive="отдела",
            hint="Например: yougile department create «Отдел продаж».",
        )
    }
    if parent:
        body["parentId"] = resolve_department_id(client, parent)
    users = _users_payload(client, user)
    if users is not None:
        body["users"] = users
    app_ctx.emit(client.post(PATH, body))


@app.command("edit")
def edit_department(
    ctx: typer.Context,
    department: Annotated[str, typer.Argument(metavar="ОТДЕЛ", help="ID или название отдела.")],
    title: Annotated[
        str | None, typer.Option("--title", "-t", metavar="НАЗВАНИЕ", help="Новое название.")
    ] = None,
    parent: ParentOpt = None,
    user: UserOpt = None,
    json_fields: JsonFields = None,
    jq: JqExpr = None,
) -> None:
    """Изменить отдел."""
    app_ctx = _prepare(ctx, json_fields, jq)
    client = app_ctx.client()
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if parent:
        body["parentId"] = resolve_department_id(client, parent)
    users = _users_payload(client, user)
    if users is not None:
        body["users"] = users
    if not body:
        raise ValidationError("Нечего менять: укажите --title, --parent или --user.")
    department_id = resolve_department_id(client, department)
    app_ctx.emit(client.put(f"{PATH}/{department_id}", body))


@app.command("delete")
def delete_department(
    ctx: typer.Context,
    department: Annotated[str, typer.Argument(metavar="ОТДЕЛ", help="ID или название отдела.")],
    yes: YesOpt = False,
    json_fields: JsonFields = None,
    jq: JqExpr = None,
) -> None:
    """Удалить отдел."""
    app_ctx = _prepare(ctx, json_fields, jq)
    client = app_ctx.client()
    department_id = resolve_department_id(client, department)
    _confirm(app_ctx, f"Удалить отдел {target_label(department, department_id)}?", yes)
    # The API has no DELETE for departments: deleting is PUT with deleted=true.
    app_ctx.emit(client.put(f"{PATH}/{department_id}", {"deleted": True}))


@app.command("tree")
def department_tree(
    ctx: typer.Context,
    department: Annotated[
        str | None,
        typer.Argument(
            metavar="ОТДЕЛ", help="Корневой отдел (ID или название). По умолчанию — все."
        ),
    ] = None,
    include_deleted: IncludeDeletedOpt = False,
    limit: LimitOpt = 0,
    json_fields: JsonFields = None,
    jq: JqExpr = None,
) -> None:
    """Дерево отделов по parentId."""
    app_ctx = _prepare(ctx, json_fields, jq)
    client = app_ctx.client()
    root_id = resolve_department_id(client, department) if department else None
    params: dict[str, Any] = {"includeDeleted": True} if include_deleted else {}
    items = client.collect(PATH, params or None, max_items=limit or None)
    if app_ctx.out.machine_readable:
        app_ctx.emit(items, LIST_COLUMNS)
        return
    if app_ctx.quiet:
        return
    app_ctx.console.print(_build_tree(items, root_id, full_ids=app_ctx.out.full_ids))
