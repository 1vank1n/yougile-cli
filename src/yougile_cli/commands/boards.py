"""`yougile board` — доски проекта: list / view / create / edit / delete / tree."""

from __future__ import annotations

import sys
from typing import Any

import typer
from rich.markup import escape
from rich.tree import Tree

from ..client import YouGileClient
from ..context import AppContext, get_ctx
from ..errors import CancelledError, ValidationError, single_name
from ..output import (
    OutputFormat,
    apply_json_fields,
    is_tty,
    sanitize_terminal_text,
    shorten_id,
    target_label,
)
from ..resolve import resolve_board_id, resolve_project_id

__all__ = ["app"]

app = typer.Typer(
    no_args_is_help=True,
    help="Доски: список, просмотр, создание, изменение, удаление и дерево доски.",
)

BOARDS_PATH = "/api-v2/boards"
COLUMNS_PATH = "/api-v2/columns"
TASKS_PATH = "/api-v2/task-list"

DEFAULT_LIMIT = 30
LIST_COLUMNS = ["id", "title", "projectId"]

_STICKER_HELP = "Стикер «{name}» на карточках доски"

# --------------------------------------------------------------------------- shared flags

_BOARD_ARG = typer.Argument(..., metavar="ДОСКА", help="Доска: ID, имя или ссылка")
_PROJECT_OPT = typer.Option(
    None, "--project", "-p", metavar="ПРОЕКТ", help="Проект: ID, имя или ссылка"
)
_JSON_OPT = typer.Option(
    None,
    "--json",
    metavar="ПОЛЯ",
    help="Вывести JSON только с этими полями (через запятую)",
)
_JQ_OPT = typer.Option(None, "--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq для JSON")
_LIMIT_OPT = typer.Option(
    DEFAULT_LIMIT,
    "--limit",
    "-L",
    min=0,
    metavar="ЧИСЛО",
    help="Сколько элементов показать; 0 — все",
)
_INCLUDE_DELETED_OPT = typer.Option(False, "--include-deleted", help="Показывать удалённые")
_YES_OPT = typer.Option(False, "--yes", "-y", help="Не спрашивать подтверждение")


def _apply_output(
    app_ctx: AppContext,
    json_fields: str | None,
    jq: str | None,
    resource: str | None = "board",
) -> None:
    """`--json ПОЛЯ` и `--jq` живут на команде, а не на корневом приложении."""
    apply_json_fields(app_ctx.out, json_fields, resource)
    if jq:
        app_ctx.out.jq = jq


def _max_items(limit: int) -> int | None:
    return None if limit <= 0 else limit


def _stdin_is_tty() -> bool:
    return is_tty(sys.stdin)


def _confirm(app_ctx: AppContext, message: str, yes: bool) -> None:
    if yes:
        return
    if not app_ctx.prompt_enabled or app_ctx.out.machine_readable or not _stdin_is_tty():
        raise ValidationError(
            "Требуется подтверждение, но задать вопрос некому.",
            hint="Повторите команду с флагом --yes.",
        )
    if not typer.confirm(message):
        raise CancelledError()


def _stickers(
    timer: bool | None,
    deadline: bool | None,
    stopwatch: bool | None,
    time_tracking: bool | None,
    assignee: bool | None,
    repeat: bool | None,
) -> dict[str, bool] | None:
    values = {
        "timer": timer,
        "deadline": deadline,
        "stopwatch": stopwatch,
        "timeTracking": time_tracking,
        "assignee": assignee,
        "repeat": repeat,
    }
    chosen = {key: value for key, value in values.items() if value is not None}
    return chosen or None


def _board_id(client: YouGileClient, board: str, project: str | None) -> str:
    project_id = resolve_project_id(client, project) if project else None
    return resolve_board_id(client, board, project_id)


# --------------------------------------------------------------------------- commands


@app.command("list", help="Список досок.")
def list_boards(
    ctx: typer.Context,
    project: str | None = _PROJECT_OPT,
    search: str | None = typer.Option(
        None, "--search", "-S", metavar="ТЕКСТ", help="Искать по имени доски"
    ),
    limit: int = _LIMIT_OPT,
    include_deleted: bool = _INCLUDE_DELETED_OPT,
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    client = app_ctx.client()

    params: dict[str, Any] = {"title": search}
    if project:
        params["projectId"] = resolve_project_id(client, project)
    if include_deleted:
        params["includeDeleted"] = True

    items = client.collect(BOARDS_PATH, params, max_items=_max_items(limit))
    columns = [*LIST_COLUMNS, "deleted"] if include_deleted else LIST_COLUMNS
    app_ctx.emit(items, columns=columns)


@app.command("view", help="Показать доску.")
def view_board(
    ctx: typer.Context,
    board: str = _BOARD_ARG,
    project: str | None = _PROJECT_OPT,
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    client = app_ctx.client()
    board_id = _board_id(client, board, project)
    app_ctx.emit(client.get(f"{BOARDS_PATH}/{board_id}"))


@app.command("create", help="Создать доску.")
def create_board(
    ctx: typer.Context,
    title_arg: str | None = typer.Argument(
        None, metavar="НАЗВАНИЕ", help="Название новой доски (можно передать и флагом --title)"
    ),
    project: str = typer.Option(
        ..., "--project", "-p", metavar="ПРОЕКТ", help="Проект: ID, имя или ссылка"
    ),
    title: str | None = typer.Option(
        None,
        "--title",
        "-t",
        metavar="НАЗВАНИЕ",
        help="Название доски; синоним позиционного аргумента НАЗВАНИЕ",
    ),
    timer: bool | None = typer.Option(
        None, "--timer/--no-timer", help=_STICKER_HELP.format(name="таймер")
    ),
    deadline: bool | None = typer.Option(
        None, "--deadline/--no-deadline", help=_STICKER_HELP.format(name="дедлайн")
    ),
    stopwatch: bool | None = typer.Option(
        None, "--stopwatch/--no-stopwatch", help=_STICKER_HELP.format(name="секундомер")
    ),
    time_tracking: bool | None = typer.Option(
        None, "--time-tracking/--no-time-tracking", help=_STICKER_HELP.format(name="таймтрекинг")
    ),
    assignee: bool | None = typer.Option(
        None, "--assignee/--no-assignee", help=_STICKER_HELP.format(name="исполнитель")
    ),
    repeat: bool | None = typer.Option(
        None, "--repeat/--no-repeat", help=_STICKER_HELP.format(name="повтор")
    ),
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    name = single_name(title_arg, title, genitive="доски")
    client = app_ctx.client()
    payload: dict[str, Any] = {
        "title": name,
        "projectId": resolve_project_id(client, project),
        "stickers": _stickers(timer, deadline, stopwatch, time_tracking, assignee, repeat),
    }
    app_ctx.emit(client.post(BOARDS_PATH, payload))


@app.command("edit", help="Изменить доску.")
def edit_board(
    ctx: typer.Context,
    board: str = _BOARD_ARG,
    title: str | None = typer.Option(
        None, "--title", "-t", metavar="НАЗВАНИЕ", help="Новое название доски"
    ),
    project: str | None = typer.Option(
        None, "--project", "-p", metavar="ПРОЕКТ", help="Перенести доску в другой проект"
    ),
    timer: bool | None = typer.Option(
        None, "--timer/--no-timer", help=_STICKER_HELP.format(name="таймер")
    ),
    deadline: bool | None = typer.Option(
        None, "--deadline/--no-deadline", help=_STICKER_HELP.format(name="дедлайн")
    ),
    stopwatch: bool | None = typer.Option(
        None, "--stopwatch/--no-stopwatch", help=_STICKER_HELP.format(name="секундомер")
    ),
    time_tracking: bool | None = typer.Option(
        None, "--time-tracking/--no-time-tracking", help=_STICKER_HELP.format(name="таймтрекинг")
    ),
    assignee: bool | None = typer.Option(
        None, "--assignee/--no-assignee", help=_STICKER_HELP.format(name="исполнитель")
    ),
    repeat: bool | None = typer.Option(
        None, "--repeat/--no-repeat", help=_STICKER_HELP.format(name="повтор")
    ),
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    stickers = _stickers(timer, deadline, stopwatch, time_tracking, assignee, repeat)
    if title is None and project is None and stickers is None:
        raise ValidationError(
            "Нечего менять.",
            hint="Укажите --title, --project или флаги стикеров.",
        )

    client = app_ctx.client()
    board_id = resolve_board_id(client, board)
    payload: dict[str, Any] = {
        "title": title,
        "projectId": resolve_project_id(client, project) if project else None,
        "stickers": stickers,
    }
    app_ctx.emit(client.put(f"{BOARDS_PATH}/{board_id}", payload))


@app.command("delete", help="Удалить доску.")
def delete_board(
    ctx: typer.Context,
    board: str = _BOARD_ARG,
    project: str | None = _PROJECT_OPT,
    yes: bool = _YES_OPT,
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    client = app_ctx.client()
    board_id = _board_id(client, board, project)
    _confirm(app_ctx, f"Удалить доску {target_label(board, board_id)}?", yes)
    # API has no DELETE for boards: deleting is a PUT with deleted=true.
    app_ctx.emit(client.put(f"{BOARDS_PATH}/{board_id}", {"deleted": True}))


@app.command("tree", help="Дерево доски: колонки и задачи в них.")
def board_tree(
    ctx: typer.Context,
    board: str = _BOARD_ARG,
    project: str | None = _PROJECT_OPT,
    limit: int = typer.Option(
        DEFAULT_LIMIT,
        "--limit",
        "-L",
        min=0,
        metavar="ЧИСЛО",
        help="Сколько задач показать в колонке; 0 — все",
    ),
    include_deleted: bool = _INCLUDE_DELETED_OPT,
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    client = app_ctx.client()
    board_id = _board_id(client, board, project)
    data = _collect_tree(
        client,
        board_id,
        include_deleted=include_deleted,
        task_limit=_max_items(limit),
    )

    if app_ctx.out.fmt is not OutputFormat.TABLE or app_ctx.out.json_fields or app_ctx.out.jq:
        app_ctx.emit(data)
        return
    if app_ctx.quiet:
        return
    app_ctx.console.print(_render_tree(data, full_ids=app_ctx.out.full_ids))


def _collect_tree(
    client: YouGileClient,
    board_id: str,
    *,
    include_deleted: bool,
    task_limit: int | None,
) -> dict[str, Any]:
    """Whole board = board + its columns + the tasks of every column (no boardId filter)."""
    board_data = client.get(f"{BOARDS_PATH}/{board_id}")
    if not isinstance(board_data, dict):
        board_data = {"id": board_id}

    shared: dict[str, Any] = {"includeDeleted": True} if include_deleted else {}
    columns: list[dict[str, Any]] = []
    for column in client.collect(COLUMNS_PATH, {**shared, "boardId": board_id}):
        column_id = column.get("id")
        tasks = client.collect(
            TASKS_PATH,
            {**shared, "columnId": column_id},
            max_items=task_limit,
        )
        columns.append(
            {
                "id": column_id,
                "title": column.get("title"),
                "tasks": [
                    {
                        "id": task.get("id"),
                        "title": task.get("title"),
                        "completed": bool(task.get("completed")),
                    }
                    for task in tasks
                ],
            }
        )

    return {
        "id": board_data.get("id", board_id),
        "title": board_data.get("title"),
        "projectId": board_data.get("projectId"),
        "columns": columns,
    }


def _render_tree(data: dict[str, Any], *, full_ids: bool = False) -> Tree:
    def tag(value: Any) -> str:
        return shorten_id(str(value or ""), full=full_ids)

    def title_of(item: dict[str, Any]) -> str:
        # Titles come from the API: a bracket in one would otherwise be read as rich markup.
        return escape(sanitize_terminal_text(str(item.get("title") or "")))

    root = Tree(f"[bold]{title_of(data)}[/bold] [dim]{tag(data.get('id'))}[/dim]")
    for column in data.get("columns", []):
        branch = root.add(f"[cyan]{title_of(column)}[/cyan] [dim]{tag(column.get('id'))}[/dim]")
        tasks = column.get("tasks") or []
        if not tasks:
            branch.add("[dim]нет задач[/dim]")
            continue
        for task in tasks:
            mark = "[green]✓[/green] " if task.get("completed") else ""
            branch.add(f"{mark}{title_of(task)} [dim]{tag(task.get('id'))}[/dim]")
    return root
