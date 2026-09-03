"""`yougile column` — колонки досок в стиле gh.

Колонка живёт на доске, поэтому `--board` везде означает доску: у `list`, `view`,
`edit` и `delete` она сужает поиск по имени, у `create` и `move` — задаёт доску
назначения.
"""

from __future__ import annotations

import sys
from typing import Annotated, Any

import typer

from ..client import YouGileClient
from ..context import AppContext, get_ctx
from ..errors import CancelledError, ValidationError, single_name
from ..output import apply_json_fields, is_tty, target_label
from ..resolve import resolve_board_id, resolve_column_id

__all__ = ["app"]

app = typer.Typer(
    no_args_is_help=True,
    help="Колонки досок: список, просмотр, создание, изменение, перенос и удаление.",
)

COLUMNS_PATH = "/api-v2/columns"
LIST_COLUMNS = ["id", "title", "color", "boardId"]

ColumnArg = Annotated[str, typer.Argument(metavar="КОЛОНКА", help="Колонка: ID, имя или ссылка")]
ScopeBoardOpt = Annotated[
    str | None,
    typer.Option(
        "--board",
        "-b",
        metavar="ДОСКА",
        help="Доска для поиска колонки по имени: ID, имя или ссылка",
    ),
]
TitleArg = Annotated[
    str | None,
    typer.Argument(metavar="НАЗВАНИЕ", help="Название новой колонки (можно передать и --title)"),
]
TitleOpt = Annotated[
    str | None,
    typer.Option(
        "--title", "-t", metavar="НАЗВАНИЕ", help="Название колонки; синоним аргумента НАЗВАНИЕ"
    ),
]
SearchOpt = Annotated[
    str | None, typer.Option("--search", "-S", metavar="ТЕКСТ", help="Фильтр по имени колонки")
]
IncludeDeletedOpt = Annotated[
    bool, typer.Option("--include-deleted", help="Показывать удалённые колонки")
]
ColorOpt = Annotated[
    int | None,
    typer.Option(
        "--color",
        "-c",
        min=1,
        max=16,
        metavar="ЧИСЛО",
        help="Цвет колонки: индекс палитры от 1 до 16",
    ),
]
LimitOpt = Annotated[
    int,
    typer.Option("--limit", "-L", min=0, metavar="ЧИСЛО", help="Сколько колонок показать; 0 — все"),
]
JsonOpt = Annotated[
    str | None,
    typer.Option(
        "--json",
        metavar="ПОЛЯ",
        help='JSON только с этими полями через запятую; --json "" печатает список полей',
    ),
]
JqOpt = Annotated[
    str | None,
    typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Прогнать JSON через фильтр jq"),
]
YesOpt = Annotated[bool, typer.Option("--yes", "-y", help="Не спрашивать подтверждение")]


def _prepare(
    ctx: typer.Context,
    *,
    json_fields: str | None = None,
    jq: str | None = None,
    limit: int | None = None,
    resource: str | None = "column",
) -> AppContext:
    """Fold the per-command output flags into the shared output options."""
    app_ctx = get_ctx(ctx)
    apply_json_fields(app_ctx.out, json_fields, resource)
    if jq:
        app_ctx.out.jq = jq
    if limit is not None:
        app_ctx.out.limit = limit
    return app_ctx


def _emit(app_ctx: AppContext, data: Any, columns: list[str] | None = None) -> None:
    app_ctx.emit(data, columns)


def _interactive(app_ctx: AppContext) -> bool:
    return app_ctx.prompt_enabled and is_tty(sys.stdin)


def _confirm(app_ctx: AppContext, message: str, yes: bool) -> None:
    if yes:
        return
    if not _interactive(app_ctx):
        raise ValidationError(
            "Требуется подтверждение, но задать вопрос некому.",
            hint="Повторите команду с флагом --yes.",
        )
    if not typer.confirm(message):
        raise CancelledError()


def _scope(client: YouGileClient, board: str | None) -> str | None:
    return resolve_board_id(client, board) if board else None


@app.command("list")
def list_columns(
    ctx: typer.Context,
    board: ScopeBoardOpt = None,
    search: SearchOpt = None,
    include_deleted: IncludeDeletedOpt = False,
    limit: LimitOpt = 30,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Показать колонки, при необходимости только одной доски."""
    app_ctx = _prepare(ctx, json_fields=json_fields, jq=jq, limit=limit)
    client = app_ctx.client()
    params: dict[str, Any] = {
        "boardId": _scope(client, board),
        "title": search,
        "includeDeleted": True if include_deleted else None,
    }
    rows = client.collect(COLUMNS_PATH, params, max_items=limit or None)
    _emit(app_ctx, rows, LIST_COLUMNS)


@app.command("view")
def view_column(
    ctx: typer.Context,
    column: ColumnArg,
    board: ScopeBoardOpt = None,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Показать одну колонку."""
    app_ctx = _prepare(ctx, json_fields=json_fields, jq=jq)
    client = app_ctx.client()
    column_id = resolve_column_id(client, column, _scope(client, board))
    _emit(app_ctx, client.get(f"{COLUMNS_PATH}/{column_id}"))


@app.command("create")
def create_column(
    ctx: typer.Context,
    board: Annotated[
        str, typer.Option("--board", "-b", metavar="ДОСКА", help="Доска: ID, имя или ссылка")
    ],
    title_arg: TitleArg = None,
    title: TitleOpt = None,
    color: ColorOpt = None,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Создать колонку на доске."""
    app_ctx = _prepare(ctx, json_fields=json_fields, jq=jq)
    name = single_name(title_arg, title, genitive="колонки")
    client = app_ctx.client()
    payload: dict[str, Any] = {
        "title": name,
        "boardId": resolve_board_id(client, board),
        "color": color,
    }
    _emit(app_ctx, client.post(COLUMNS_PATH, payload))


@app.command("edit")
def edit_column(
    ctx: typer.Context,
    column: ColumnArg,
    title: Annotated[
        str | None,
        typer.Option("--title", "-t", metavar="НАЗВАНИЕ", help="Новое название колонки"),
    ] = None,
    color: ColorOpt = None,
    board: ScopeBoardOpt = None,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Переименовать колонку или сменить её цвет."""
    app_ctx = _prepare(ctx, json_fields=json_fields, jq=jq)
    payload: dict[str, Any] = {"title": title, "color": color}
    payload = {key: value for key, value in payload.items() if value is not None}
    if not payload:
        raise ValidationError(
            "Нечего менять: укажите --title или --color.",
            hint="Перенос на другую доску — это `yougile column move`.",
        )
    client = app_ctx.client()
    column_id = resolve_column_id(client, column, _scope(client, board))
    _emit(app_ctx, client.put(f"{COLUMNS_PATH}/{column_id}", payload))


@app.command("delete")
def delete_column(
    ctx: typer.Context,
    column: ColumnArg,
    board: ScopeBoardOpt = None,
    yes: YesOpt = False,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Удалить колонку."""
    app_ctx = _prepare(ctx, json_fields=json_fields, jq=jq)
    client = app_ctx.client()
    column_id = resolve_column_id(client, column, _scope(client, board))
    _confirm(app_ctx, f"Удалить колонку {target_label(column, column_id)}?", yes)
    # There is no DELETE for columns: deleting is a PUT with deleted=true.
    _emit(app_ctx, client.put(f"{COLUMNS_PATH}/{column_id}", {"deleted": True}))


@app.command("move")
def move_column(
    ctx: typer.Context,
    column: ColumnArg,
    board: Annotated[
        str,
        typer.Option("--board", "-b", metavar="ДОСКА", help="Доска назначения: ID, имя или ссылка"),
    ],
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Перенести колонку на другую доску."""
    app_ctx = _prepare(ctx, json_fields=json_fields, jq=jq)
    client = app_ctx.client()
    column_id = resolve_column_id(client, column)
    board_id = resolve_board_id(client, board)
    _emit(app_ctx, client.put(f"{COLUMNS_PATH}/{column_id}", {"boardId": board_id}))
