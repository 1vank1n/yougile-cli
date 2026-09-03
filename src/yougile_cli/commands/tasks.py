"""`yougile task …` — списки, просмотр, создание и изменение задач.

Две особенности API, из-за которых код выглядит именно так:

* удаление задачи — это ``PUT /api-v2/tasks/{id}`` с телом ``{"deleted": true}``;
  метода DELETE для задач не существует;
* список задач фильтруется только по ``columnId``, поэтому ``--board`` и
  ``--project`` разворачиваются в набор колонок перед запросом ``/api-v2/task-list``
  (сам ``/api-v2/tasks`` объявлен устаревшим и здесь не используется).
"""

from __future__ import annotations

import html
import re
import sys
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer

from ..attachments import (
    Attachment,
    download,
    from_description,
    from_message,
    strip_preview,
)
from ..client import YouGileClient
from ..config import host_to_web_url
from ..context import AppContext, emit, get_ctx
from ..editor import open_editor
from ..errors import CancelledError, ValidationError, YouGileError, not_specified_message
from ..htmltext import html_to_text
from ..output import apply_json_fields, sanitize_terminal_text, shorten_id, target_label
from ..output import is_tty as _is_tty
from ..resolve import (
    parse_kv_options,
    resolve_board_id,
    resolve_column_id,
    resolve_project_id,
    resolve_task_id,
    resolve_user_id,
)

__all__ = [
    "TASK_COLORS",
    "AttachmentSource",
    "TaskState",
    "app",
    "datetime_has_time",
    "format_ms",
    "parse_datetime_to_ms",
    "subscribers_app",
]

TASKS_PATH = "/api-v2/tasks"
TASK_LIST_PATH = "/api-v2/task-list"
COLUMNS_PATH = "/api-v2/columns"
BOARDS_PATH = "/api-v2/boards"
CHATS_PATH = "/api-v2/chats"

TASK_COLORS = (
    "task-primary",
    "task-gray",
    "task-red",
    "task-pink",
    "task-yellow",
    "task-green",
    "task-turquoise",
    "task-blue",
    "task-violet",
)

LIST_COLUMNS = ["id", "title", "state", "assignees", "deadline"]
COMMENT_COLUMNS = ["id", "fromUserId", "text"]
ATTACHMENT_COLUMNS = ["источник", "имя", "тип", "url"]

TASK_ARG_HELP = "Задача: код, ID, ссылка или заголовок"

# One page of chat history is enough to find what is attached to a task.
CHAT_SCAN_LIMIT = 200


class TaskState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    ALL = "all"


class AttachmentSource(StrEnum):
    """Where `task attachments` looks for files."""

    DESCRIPTION = "описание"
    CHAT = "чат"
    ALL = "все"


# --------------------------------------------------------------------------- dates

_DATE_FORMATS: tuple[tuple[str, bool], ...] = (
    ("%Y-%m-%d %H:%M:%S", True),
    ("%Y-%m-%d %H:%M", True),
    ("%Y-%m-%dT%H:%M:%S", True),
    ("%Y-%m-%dT%H:%M", True),
    ("%Y-%m-%d", False),
    ("%d.%m.%Y %H:%M", True),
    ("%d.%m.%Y", False),
)


def _parse_datetime(value: str | int | float) -> tuple[int, bool]:
    """Return (epoch milliseconds, whether a time of day was given)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value), True
    text = str(value).strip()
    if not text:
        raise ValidationError("Пустое значение даты.")
    if re.fullmatch(r"-?\d+", text):
        return int(text), True
    for fmt, with_time in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return int(parsed.timestamp() * 1000), with_time
    raise ValidationError(
        f"Не удалось разобрать дату «{text}». "
        "Ожидается «ГГГГ-ММ-ДД», «ГГГГ-ММ-ДД ЧЧ:ММ» или число (миллисекунды)."
    )


def parse_datetime_to_ms(value: str | int | float) -> int:
    """Local date/time (or a raw millisecond number) -> epoch milliseconds."""
    return _parse_datetime(value)[0]


def datetime_has_time(value: str | int | float) -> bool:
    return _parse_datetime(value)[1]


def format_ms(value: Any, with_time: bool = True) -> str:
    """Epoch milliseconds -> a human readable local timestamp."""
    if value is None or isinstance(value, bool):
        return ""
    try:
        moment = datetime.fromtimestamp(float(value) / 1000)
    except (TypeError, ValueError, OSError, OverflowError):
        return ""
    return moment.strftime("%Y-%m-%d %H:%M" if with_time else "%Y-%m-%d")


# --------------------------------------------------------------------------- helpers


def _flag(value: bool) -> bool | None:
    """Send a boolean query flag only when it is switched on."""
    return True if value else None


def _apply_output(
    app_ctx: AppContext,
    *,
    json_fields: str | None = None,
    jq: str | None = None,
    limit: int | None = None,
    full_ids: bool = False,
    resource: str | None = "task",
) -> None:
    """Per-command output flags win over the global ones set in `cli.py`."""
    apply_json_fields(app_ctx.out, json_fields, resource)
    if jq:
        app_ctx.out.jq = jq
    if limit is not None:
        app_ctx.out.limit = limit
    if full_ids:
        app_ctx.out.full_ids = True


def _report(app_ctx: AppContext, task_id: str, message: str) -> None:
    """gh-style: a short confirmation for humans, the object id for machines."""
    if app_ctx.out.machine_readable:
        emit(app_ctx, {"id": task_id})
        return
    if not app_ctx.quiet:
        app_ctx.err_console.print(f"✓ {message}", markup=False, highlight=False)


def _confirm(app_ctx: AppContext, question: str, *, yes: bool) -> None:
    if yes:
        return
    if not app_ctx.prompt_enabled or not _is_tty(sys.stdin):
        raise ValidationError(
            "Требуется подтверждение, но ввод неинтерактивный.",
            hint="Повторите с флагом --yes.",
        )
    typer.confirm(question, abort=True)


def _resolve_users(client: YouGileClient, values: list[str] | None) -> list[str]:
    return [resolve_user_id(client, item) for item in values or []]


def _require_values(values: list[str] | None, message: str) -> list[str]:
    items = [item for item in values or [] if item]
    if not items:
        raise ValidationError(message)
    return items


def _merge_values(*groups: list[str] | None) -> list[str]:
    """Positional values and their `--flag` synonym are one list, order kept."""
    merged: list[str] = []
    for group in groups:
        for item in group or []:
            text = item.strip()
            if text and text not in merged:
                merged.append(text)
    return merged


def _single_value(
    positional: str | None,
    option: str | None,
    *,
    conflict: str,
) -> str | None:
    """A value given both as an argument and as its flag must not disagree."""
    left = (positional or "").strip()
    right = (option or "").strip()
    if left and right and left != right:
        raise ValidationError(conflict)
    return left or right or None


def _parse_checklists(values: list[str] | None) -> list[dict[str, Any]]:
    checklists: list[dict[str, Any]] = []
    for raw in values or []:
        title, sep, items = raw.partition(":")
        title = title.strip()
        if not sep or not title:
            raise ValidationError(f"Ожидался формат «Название:пункт1,пункт2», получено «{raw}».")
        entries = [item.strip() for item in items.split(",") if item.strip()]
        checklists.append(
            {
                "title": title,
                "items": [{"title": item, "isCompleted": False} for item in entries],
            }
        )
    return checklists


def _parse_color(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    candidate = text if text.startswith("task-") else f"task-{text}"
    if candidate not in TASK_COLORS:
        raise ValidationError(f"Неизвестный цвет «{value}». Доступны: {', '.join(TASK_COLORS)}.")
    return candidate


def _deadline_payload(
    deadline: str | None,
    start_date: str | None,
    *,
    require_deadline: bool,
) -> dict[str, Any] | None:
    if deadline is None and start_date is None:
        return None
    # The API declares blockedPoints and links required inside the deadline object.
    payload: dict[str, Any] = {"blockedPoints": [], "links": []}
    if deadline is not None:
        moment, with_time = _parse_datetime(deadline)
        payload["deadline"] = moment
        payload["withTime"] = with_time
    elif require_deadline:
        raise ValidationError("Для --start-date нужно указать и --deadline.")
    if start_date is not None:
        payload["startDate"] = parse_datetime_to_ms(start_date)
    return payload


def _merge_deadline(client: YouGileClient, task_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """PUT replaces the whole deadline object, so keep the keys the task already has."""
    current = client.get(f"{TASKS_PATH}/{task_id}")
    existing = current.get("deadline") if isinstance(current, dict) else None
    if not isinstance(existing, dict) or existing.get("deleted"):
        return updates
    merged = {**existing, **updates}
    merged.pop("deleted", None)
    return merged


def _require_editor(app_ctx: AppContext | None) -> None:
    """$EDITOR is the most interactive prompt there is — refuse it when prompts are off."""
    if app_ctx is not None and app_ctx.prompt_enabled and _is_tty(sys.stdin):
        return
    raise ValidationError(
        "Отключены интерактивные вопросы, редактор открыть нельзя.",
        hint="Передайте текст через --body или --body-file.",
    )


def _open_editor(initial: str = "") -> str | None:
    """Split out so tests can drive `--editor` without a real $EDITOR."""
    return open_editor(initial)


def _read_body_file(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        raise ValidationError(f"Не удалось прочитать файл «{path}»: {exc}") from exc


def _body_text(
    body: str | None,
    body_file: str | None,
    editor: bool,
    *,
    app_ctx: AppContext | None = None,
    initial: str = "",
) -> str | None:
    """`--body` / `--body-file` / `--editor` — ровно один источник текста."""
    given = (
        ("--body", body is not None),
        ("--body-file", bool(body_file)),
        ("--editor", editor),
    )
    sources = [name for name, used in given if used]
    if len(sources) > 1:
        raise ValidationError(f"Флаги {' и '.join(sources)} нельзя использовать вместе.")
    if body is not None:
        return body
    if body_file:
        return _read_body_file(body_file)
    if editor:
        _require_editor(app_ctx)
        text = _open_editor(initial)
        if text is None:
            raise CancelledError("Текст не сохранён — отменено.")
        return text.strip("\n")
    return None


def _deadline_text(task: dict[str, Any]) -> str:
    deadline = task.get("deadline")
    if not isinstance(deadline, dict):
        return ""
    return format_ms(deadline.get("deadline"), bool(deadline.get("withTime")))


def _display_row(task: dict[str, Any], full_ids: bool) -> dict[str, Any]:
    assigned = [shorten_id(str(item), full=full_ids) for item in task.get("assigned") or []]
    return {
        "id": shorten_id(str(task.get("id") or ""), full=full_ids),
        "title": task.get("title") or "",
        "state": "closed" if task.get("completed") else "open",
        "assignees": ", ".join(assigned),
        "deadline": _deadline_text(task),
    }


def _summary(task: dict[str, Any], full_ids: bool = False) -> dict[str, Any]:
    raw_deadline = task.get("deadline")
    deadline: dict[str, Any] = raw_deadline if isinstance(raw_deadline, dict) else {}
    raw_tracking = task.get("timeTracking")
    tracking: dict[str, Any] = raw_tracking if isinstance(raw_tracking, dict) else {}
    code = task.get("idTaskProject") or task.get("idTaskCommon") or ""
    summary: dict[str, Any] = {
        "id": task.get("id", ""),
        "code": str(code),
        "title": task.get("title", ""),
        "state": "closed" if task.get("completed") else "open",
        "columnId": task.get("columnId", ""),
        "archived": bool(task.get("archived")),
        "deleted": bool(task.get("deleted")),
        "assigned": ", ".join(
            shorten_id(str(item), full=full_ids) for item in task.get("assigned") or []
        ),
        "deadline": _deadline_text(task),
        "startDate": format_ms(deadline.get("startDate"), bool(deadline.get("withTime"))),
        "planHours": tracking.get("plan", ""),
        "workHours": tracking.get("work", ""),
        "color": task.get("color", ""),
        "createdBy": task.get("createdBy", ""),
        "created": format_ms(task.get("timestamp")),
    }
    if not code:
        summary.pop("code")
    stickers = task.get("stickers")
    if stickers:
        summary["stickers"] = stickers
    return summary


def _fetch_task(client: YouGileClient, task: str, column_id: str | None = None) -> dict[str, Any]:
    task_id = resolve_task_id(client, task, column_id)
    data = client.get(f"{TASKS_PATH}/{task_id}")
    return data if isinstance(data, dict) else {"id": task_id}


def _web_base(app_ctx: AppContext) -> str:
    return host_to_web_url(app_ctx.host)


def _task_url(client: YouGileClient, app_ctx: AppContext, task: dict[str, Any]) -> str | None:
    """Board id for the link comes from the task's column."""
    column_id = task.get("columnId")
    if not column_id:
        return None
    column = client.get(f"{COLUMNS_PATH}/{column_id}")
    board_id = column.get("boardId") if isinstance(column, dict) else None
    if not board_id:
        return None
    code = task.get("idTaskProject") or task.get("idTaskCommon") or task.get("id")
    return f"{_web_base(app_ctx)}/board/{board_id}#{code}"


def _safe_task_url(client: YouGileClient, app_ctx: AppContext, task: dict[str, Any]) -> str | None:
    try:
        return _task_url(client, app_ctx, task)
    except YouGileError:
        return None


def _column_ids_for_boards(
    client: YouGileClient, board_ids: list[str], include_deleted: bool
) -> list[str]:
    ids: list[str] = []
    for board_id in board_ids:
        columns = client.collect(
            COLUMNS_PATH,
            {"boardId": board_id, "includeDeleted": _flag(include_deleted)},
        )
        ids.extend(str(item["id"]) for item in columns if item.get("id"))
    return ids


def _target_columns(
    client: YouGileClient,
    *,
    column: str | None,
    board: str | None,
    project: str | None,
    include_deleted: bool,
) -> list[str] | None:
    """Column ids to query; None means "no columnId filter at all"."""
    project_id = resolve_project_id(client, project) if project else None
    if column:
        board_id = resolve_board_id(client, board, project_id) if board else None
        return [resolve_column_id(client, column, board_id)]
    if board:
        board_id = resolve_board_id(client, board, project_id)
        return _column_ids_for_boards(client, [board_id], include_deleted)
    if project_id:
        boards = client.collect(
            BOARDS_PATH,
            {"projectId": project_id, "includeDeleted": _flag(include_deleted)},
        )
        board_ids = [str(item["id"]) for item in boards if item.get("id")]
        return _column_ids_for_boards(client, board_ids, include_deleted)
    return None


def _state_matches(task: dict[str, Any], state: TaskState) -> bool:
    if state is TaskState.ALL:
        return True
    return bool(task.get("completed")) is (state is TaskState.CLOSED)


# --------------------------------------------------------------------------- attachments


def _unique(items: list[Attachment]) -> list[Attachment]:
    seen: set[str] = set()
    result: list[Attachment] = []
    for item in items:
        if item.url in seen:
            continue
        seen.add(item.url)
        result.append(item)
    return result


def _chat_messages(client: YouGileClient, task_id: str) -> list[dict[str, Any]]:
    """A task chat that cannot be read must not break the view."""
    if not task_id:
        return []
    try:
        return client.collect(f"{CHATS_PATH}/{task_id}/messages", max_items=CHAT_SCAN_LIMIT)
    except YouGileError:
        return []


def _chat_attachments(
    client: YouGileClient,
    task_id: str,
    messages: list[dict[str, Any]] | None = None,
) -> list[Attachment]:
    items = _chat_messages(client, task_id) if messages is None else messages
    found: list[Attachment] = []
    for message in items:
        if not isinstance(message, dict):
            continue
        # The service form lives in `text`, real markup in `textHtml`.
        for key in ("textHtml", "text"):
            found.extend(from_message(str(message.get(key) or ""), client.host))
    return found


def _collect_attachments(
    client: YouGileClient,
    task: dict[str, Any],
    *,
    source: AttachmentSource = AttachmentSource.ALL,
    messages: list[dict[str, Any]] | None = None,
) -> list[Attachment]:
    found: list[Attachment] = []
    if source in (AttachmentSource.ALL, AttachmentSource.DESCRIPTION):
        found.extend(from_description(str(task.get("description") or ""), client.host))
    if source in (AttachmentSource.ALL, AttachmentSource.CHAT):
        found.extend(_chat_attachments(client, str(task.get("id") or ""), messages))
    return _unique(found)


def _description_text(task: dict[str, Any], *, raw: bool) -> str:
    description = str(task.get("description") or "")
    if raw:
        return description.strip()
    return html_to_text(description)


def _put(app_ctx: AppContext, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = app_ctx.client().put(f"{TASKS_PATH}/{task_id}", payload)
    return result if isinstance(result, dict) else {"id": task_id}


app = typer.Typer(no_args_is_help=True, help="Задачи: поиск, создание, изменение, перемещение.")
subscribers_app = typer.Typer(no_args_is_help=True, help="Участники чата задачи.")
app.add_typer(subscribers_app, name="subscribers")


# --------------------------------------------------------------------------- list


@app.command("list")
def list_tasks(
    ctx: typer.Context,
    assignee: Annotated[
        list[str] | None,
        typer.Option(
            "--assignee", "-a", metavar="ИСПОЛНИТЕЛЬ", help="Исполнитель: @me, почта, имя или ID"
        ),
    ] = None,
    state: Annotated[
        TaskState, typer.Option("--state", "-s", help="Состояние: open, closed или all")
    ] = TaskState.OPEN,
    column: Annotated[
        str | None,
        typer.Option("--column", "-c", metavar="КОЛОНКА", help="Колонка (ID или название)"),
    ] = None,
    board: Annotated[
        str | None,
        typer.Option("--board", "-b", metavar="ДОСКА", help="Доска: опрашиваются все её колонки"),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option(
            "--project", "-p", metavar="ПРОЕКТ", help="Проект: все доски и колонки проекта"
        ),
    ] = None,
    search: Annotated[
        str | None,
        typer.Option("--search", "-S", metavar="ТЕКСТ", help="Поиск по заголовку задачи"),
    ] = None,
    sticker: Annotated[
        str | None, typer.Option("--sticker", metavar="СТИКЕР", help="ID стикера")
    ] = None,
    sticker_state: Annotated[
        str | None, typer.Option("--sticker-state", metavar="ID", help="ID состояния стикера")
    ] = None,
    include_deleted: Annotated[
        bool, typer.Option("--include-deleted", help="Показывать удалённые задачи")
    ] = False,
    archived: Annotated[
        bool | None,
        typer.Option("--archived/--no-archived", help="Только архивные / только неархивные"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(
            "--limit", "-L", metavar="ЧИСЛО", min=0, help="Сколько задач показать, 0 — все"
        ),
    ] = 30,
    json_fields: Annotated[
        str | None,
        typer.Option("--json", metavar="ПОЛЯ", help="Вывести JSON с перечисленными полями"),
    ] = None,
    jq: Annotated[
        str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq по JSON-выводу")
    ] = None,
    full_ids: Annotated[bool, typer.Option("--full-ids", help="Показывать ID целиком")] = False,
) -> None:
    """Список задач с фильтрами по исполнителю, состоянию и месту."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq, limit=limit, full_ids=full_ids)
    client = app_ctx.client()

    column_ids = _target_columns(
        client,
        column=column,
        board=board,
        project=project,
        include_deleted=include_deleted,
    )

    params: dict[str, Any] = {
        "title": search,
        "stickerId": sticker,
        "stickerStateId": sticker_state,
        "includeDeleted": _flag(include_deleted),
    }
    user_ids = _resolve_users(client, assignee)
    if user_ids:
        params["assignedTo"] = ",".join(user_ids)

    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for column_id in column_ids if column_ids is not None else [None]:
        query = dict(params)
        query["columnId"] = column_id
        for task in client.paginate(TASK_LIST_PATH, query):
            key = str(task.get("id") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            if not _state_matches(task, state):
                continue
            if archived is not None and bool(task.get("archived")) is not archived:
                continue
            tasks.append(task)
            if limit and len(tasks) >= limit:
                break
        if limit and len(tasks) >= limit:
            break

    if app_ctx.out.machine_readable:
        emit(app_ctx, tasks)
        return
    emit(app_ctx, [_display_row(task, full_ids) for task in tasks], columns=LIST_COLUMNS)


# --------------------------------------------------------------------------- view


@app.command("view")
def view_task(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(metavar="ЗАДАЧА", help=TASK_ARG_HELP)],
    comments: Annotated[bool, typer.Option("--comments", help="Показать чат задачи")] = False,
    raw_description: Annotated[
        bool, typer.Option("--raw-description", help="Печатать описание исходным HTML")
    ] = False,
    limit: Annotated[
        int,
        typer.Option(
            "--limit", "-L", metavar="ЧИСЛО", min=0, help="Сколько комментариев показать, 0 — все"
        ),
    ] = 30,
    web: Annotated[bool, typer.Option("--web", "-w", help="Открыть задачу в браузере")] = False,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Напечатать ссылку вместо открытия браузера")
    ] = False,
    json_fields: Annotated[
        str | None,
        typer.Option("--json", metavar="ПОЛЯ", help="Вывести JSON с перечисленными полями"),
    ] = None,
    jq: Annotated[
        str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq по JSON-выводу")
    ] = None,
    full_ids: Annotated[bool, typer.Option("--full-ids", help="Показывать ID целиком")] = False,
) -> None:
    """Подробности задачи: поля, чек-листы, подзадачи и, по флагу, чат."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq, limit=limit, full_ids=full_ids)
    client = app_ctx.client()
    data = _fetch_task(client, task)

    if web or no_browser:
        url = _task_url(client, app_ctx, data)
        if not url:
            raise YouGileError(
                "Не удалось собрать ссылку: у задачи нет колонки.",
                hint="Переместите задачу в колонку: yougile task move …",
            )
        if no_browser:
            app_ctx.console.print(url, markup=False, highlight=False)
            return
        app_ctx.err_console.print(f"Открываю {url}", markup=False, highlight=False)
        typer.launch(url)
        return

    messages: list[dict[str, Any]] | None = None
    if comments:
        task_id = str(data.get("id") or "")
        messages = client.collect(
            f"{CHATS_PATH}/{task_id}/messages", max_items=app_ctx.out.limit or None
        )

    if app_ctx.out.machine_readable:
        payload = dict(data)
        if messages is not None:
            payload["comments"] = messages
        emit(app_ctx, payload)
        return

    emit(app_ctx, _summary(data, app_ctx.out.full_ids))
    _print_description(app_ctx, data, raw=raw_description)
    _print_checklists(app_ctx, data)
    _print_subtasks(app_ctx, data)
    if not app_ctx.quiet:
        _print_attachments(app_ctx, _collect_attachments(client, data, messages=messages))
    if messages is not None:
        app_ctx.console.print("")
        emit(app_ctx, messages, columns=COMMENT_COLUMNS)


def _print_description(app_ctx: AppContext, task: dict[str, Any], *, raw: bool) -> None:
    """Descriptions arrive as HTML; a human gets text unless --raw-description."""
    text = _description_text(task, raw=raw)
    if not text or app_ctx.quiet:
        return
    app_ctx.console.print("\nОПИСАНИЕ", style="bold", markup=False, highlight=False)
    for line in sanitize_terminal_text(text).split("\n"):
        app_ctx.console.print(f"  {line}".rstrip(), markup=False, highlight=False)


def _print_attachments(app_ctx: AppContext, attachments: list[Attachment]) -> None:
    if not attachments:
        return
    app_ctx.console.print("\nВЛОЖЕНИЯ", style="bold", markup=False, highlight=False)
    width = max(len(item.source) for item in attachments)
    for item in attachments:
        app_ctx.console.print(
            sanitize_terminal_text(
                f"  {item.source.ljust(width)}  {item.name}  {strip_preview(item.url)}"
            ),
            markup=False,
            highlight=False,
        )


def _print_checklists(app_ctx: AppContext, task: dict[str, Any]) -> None:
    checklists = [item for item in task.get("checklists") or [] if isinstance(item, dict)]
    if not checklists or app_ctx.quiet:
        return
    app_ctx.console.print("\nЧЕК-ЛИСТЫ", style="bold", markup=False, highlight=False)
    for checklist in checklists:
        app_ctx.console.print(
            sanitize_terminal_text(f"  {checklist.get('title') or ''}"),
            markup=False,
            highlight=False,
        )
        items = checklist.get("items")
        entries = items if isinstance(items, list) else [items] if items else []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            mark = "x" if entry.get("isCompleted") else " "
            app_ctx.console.print(
                sanitize_terminal_text(f"    [{mark}] {entry.get('title') or ''}"),
                markup=False,
                highlight=False,
            )


def _print_subtasks(app_ctx: AppContext, task: dict[str, Any]) -> None:
    subtasks = [str(item) for item in task.get("subtasks") or [] if item]
    if not subtasks or app_ctx.quiet:
        return
    app_ctx.console.print("\nПОДЗАДАЧИ", style="bold", markup=False, highlight=False)
    for subtask_id in subtasks:
        title = subtask_id
        completed = False
        try:
            child = app_ctx.client().get(f"{TASKS_PATH}/{subtask_id}")
        except YouGileError:  # a missing subtask must not break the whole view
            child = None
        if isinstance(child, dict):
            title = str(child.get("title") or subtask_id)
            completed = bool(child.get("completed"))
        mark = "x" if completed else " "
        app_ctx.console.print(
            sanitize_terminal_text(
                f"  [{mark}] {shorten_id(subtask_id, full=app_ctx.out.full_ids)}  {title}"
            ),
            markup=False,
            highlight=False,
        )


# --------------------------------------------------------------------------- attachments


def _download_dir(value: str | None) -> Path:
    path = Path(value).expanduser() if value else Path.cwd()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise YouGileError(f"Не удалось создать каталог «{path}»: {exc}") from exc
    return path


@app.command("attachments")
def task_attachments(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(metavar="ЗАДАЧА", help=TASK_ARG_HELP)],
    download_files: Annotated[
        bool, typer.Option("--download", help="Скачать все найденные файлы")
    ] = False,
    directory: Annotated[
        str | None,
        typer.Option("--dir", metavar="КАТАЛОГ", help="Куда скачивать; по умолчанию текущий"),
    ] = None,
    source: Annotated[
        AttachmentSource,
        typer.Option("--source", help="Где искать вложения"),
    ] = AttachmentSource.ALL,
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Перезаписывать существующие файлы")
    ] = False,
    json_fields: Annotated[
        str | None,
        typer.Option("--json", metavar="ПОЛЯ", help="Вывести JSON с перечисленными полями"),
    ] = None,
    jq: Annotated[
        str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq по JSON-выводу")
    ] = None,
) -> None:
    """Файлы, приложенные к задаче в описании и в чате."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq, resource="task-attachment")
    client = app_ctx.client()
    data = _fetch_task(client, task)
    items = _collect_attachments(client, data, source=source)

    target_dir = _download_dir(directory) if download_files else None
    saved: list[tuple[Path, int]] = []
    rows: list[dict[str, Any]] = []
    for item in items:
        row: dict[str, Any] = {
            "source": item.source,
            "name": item.name,
            "kind": item.kind,
            "url": strip_preview(item.url),
        }
        if target_dir is not None:
            path = download(client, item.url, target_dir, force=force)
            size = path.stat().st_size
            saved.append((path, size))
            row["path"] = str(path)
            row["size"] = size
        rows.append(row)

    if app_ctx.out.machine_readable:
        emit(app_ctx, rows)
        return
    emit(
        app_ctx,
        [
            {"источник": row["source"], "имя": row["name"], "тип": row["kind"], "url": row["url"]}
            for row in rows
        ],
        columns=ATTACHMENT_COLUMNS,
    )
    if app_ctx.quiet:
        return
    for path, size in saved:
        app_ctx.err_console.print(f"✓ {path} ({size} Б)", markup=False, highlight=False)


# --------------------------------------------------------------------------- create


@app.command("create")
def create_task(
    ctx: typer.Context,
    title_arg: Annotated[
        str | None, typer.Argument(metavar="[ЗАГОЛОВОК]", help="Заголовок задачи")
    ] = None,
    title: Annotated[
        str | None, typer.Option("--title", "-t", metavar="ЗАГОЛОВОК", help="Заголовок задачи")
    ] = None,
    column: Annotated[
        str | None,
        typer.Option("--column", "-c", metavar="КОЛОНКА", help="Колонка (ID или название)"),
    ] = None,
    board: Annotated[
        str | None,
        typer.Option(
            "--board", "-b", metavar="ДОСКА", help="Доска для уточнения колонки по названию"
        ),
    ] = None,
    body: Annotated[
        str | None, typer.Option("--body", metavar="ТЕКСТ", help="Описание задачи")
    ] = None,
    body_file: Annotated[
        str | None,
        typer.Option("--body-file", "-F", metavar="ФАЙЛ", help="Файл с описанием, «-» — stdin"),
    ] = None,
    editor: Annotated[
        bool, typer.Option("--editor", "-e", help="Написать описание в $EDITOR")
    ] = False,
    assignee: Annotated[
        list[str] | None,
        typer.Option(
            "--assignee", "-a", metavar="ИСПОЛНИТЕЛЬ", help="Исполнитель: @me, почта, имя или ID"
        ),
    ] = None,
    subtask: Annotated[
        list[str] | None,
        typer.Option("--subtask", metavar="ЗАДАЧА", help="Подзадача: ID, ссылка или заголовок"),
    ] = None,
    deadline: Annotated[
        str | None, typer.Option("--deadline", metavar="ДАТА", help="Дедлайн «ГГГГ-ММ-ДД[ ЧЧ:ММ]»")
    ] = None,
    start_date: Annotated[
        str | None,
        typer.Option("--start-date", metavar="ДАТА", help="Дата начала «ГГГГ-ММ-ДД[ ЧЧ:ММ]»"),
    ] = None,
    color: Annotated[
        str | None, typer.Option("--color", metavar="ЦВЕТ", help=f"Цвет: {', '.join(TASK_COLORS)}")
    ] = None,
    plan_hours: Annotated[
        float | None,
        typer.Option("--plan-hours", metavar="ЧИСЛО", help="Плановые трудозатраты в часах"),
    ] = None,
    checklist: Annotated[
        list[str] | None,
        typer.Option("--checklist", metavar="ЧЕК-ЛИСТ", help="Чек-лист «Название:пункт1,пункт2»"),
    ] = None,
    sticker: Annotated[
        list[str] | None,
        typer.Option("--sticker", metavar="СТИКЕР", help="Стикер в формате ID=СОСТОЯНИЕ"),
    ] = None,
    archived: Annotated[bool, typer.Option("--archived", help="Создать сразу в архиве")] = False,
    completed: Annotated[
        bool, typer.Option("--completed", help="Создать сразу выполненной")
    ] = False,
    idempotency_key: Annotated[
        str | None, typer.Option("--idempotency-key", metavar="КЛЮЧ", help="Ключ идемпотентности")
    ] = None,
    json_fields: Annotated[
        str | None,
        typer.Option("--json", metavar="ПОЛЯ", help="Вывести JSON с перечисленными полями"),
    ] = None,
    jq: Annotated[
        str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq по JSON-выводу")
    ] = None,
) -> None:
    """Создать задачу и напечатать ссылку на неё."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    client = app_ctx.client()

    heading = (
        _single_value(
            title_arg,
            title,
            conflict="Заголовок задан дважды: аргументом и флагом --title.",
        )
        or ""
    )
    if not heading:
        if not app_ctx.prompt_enabled or not _is_tty(sys.stdin):
            raise ValidationError(
                "Не указан заголовок задачи.", hint="Укажите его аргументом или флагом --title."
            )
        heading = typer.prompt("Заголовок задачи").strip()
        if not heading:
            raise ValidationError("Не указан заголовок задачи.")

    description = _body_text(body, body_file, editor, app_ctx=app_ctx)

    column_id = None
    if column:
        board_id = resolve_board_id(client, board) if board else None
        column_id = resolve_column_id(client, column, board_id)

    payload: dict[str, Any] = {
        "title": heading,
        "columnId": column_id,
        "description": description,
        "color": _parse_color(color),
        "idempotencyKey": idempotency_key,
    }
    if completed:
        payload["completed"] = True
    if archived:
        payload["archived"] = True
    assigned = _resolve_users(client, assignee)
    if assigned:
        payload["assigned"] = assigned
    if subtask:
        payload["subtasks"] = [resolve_task_id(client, item) for item in subtask]
    deadline_payload = _deadline_payload(deadline, start_date, require_deadline=True)
    if deadline_payload:
        payload["deadline"] = deadline_payload
    if plan_hours is not None:
        payload["timeTracking"] = {"plan": plan_hours, "work": 0}
    checklists = _parse_checklists(checklist)
    if checklists:
        payload["checklists"] = checklists
    stickers = parse_kv_options(sticker)
    if stickers:
        payload["stickers"] = stickers

    created = client.post(TASKS_PATH, payload)
    task_id = str(created.get("id") or "") if isinstance(created, dict) else ""

    url = None
    if task_id:
        fresh = client.get(f"{TASKS_PATH}/{task_id}")
        if isinstance(fresh, dict):
            url = _safe_task_url(client, app_ctx, fresh)

    if app_ctx.out.machine_readable:
        emit(app_ctx, {"id": task_id, "title": heading, "url": url or ""})
        return
    if not app_ctx.quiet:
        app_ctx.console.print(url or task_id, markup=False, highlight=False)


# --------------------------------------------------------------------------- edit


@app.command("edit")
def edit_task(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(metavar="ЗАДАЧА", help=TASK_ARG_HELP)],
    title: Annotated[
        str | None, typer.Option("--title", "-t", metavar="ЗАГОЛОВОК", help="Новый заголовок")
    ] = None,
    column: Annotated[
        str | None, typer.Option("--column", "-c", metavar="КОЛОНКА", help="Переместить в колонку")
    ] = None,
    board: Annotated[
        str | None,
        typer.Option(
            "--board", "-b", metavar="ДОСКА", help="Доска для уточнения колонки по названию"
        ),
    ] = None,
    body: Annotated[
        str | None, typer.Option("--body", metavar="ТЕКСТ", help="Новое описание")
    ] = None,
    body_file: Annotated[
        str | None,
        typer.Option("--body-file", "-F", metavar="ФАЙЛ", help="Файл с описанием, «-» — stdin"),
    ] = None,
    editor: Annotated[
        bool, typer.Option("--editor", "-e", help="Править описание в $EDITOR")
    ] = False,
    assignee: Annotated[
        list[str] | None,
        typer.Option(
            "--assignee", "-a", metavar="ИСПОЛНИТЕЛЬ", help="Заменить список исполнителей"
        ),
    ] = None,
    subtask: Annotated[
        list[str] | None,
        typer.Option("--subtask", metavar="ЗАДАЧА", help="Заменить список подзадач"),
    ] = None,
    deadline: Annotated[
        str | None, typer.Option("--deadline", metavar="ДАТА", help="Дедлайн «ГГГГ-ММ-ДД[ ЧЧ:ММ]»")
    ] = None,
    start_date: Annotated[
        str | None,
        typer.Option("--start-date", metavar="ДАТА", help="Дата начала «ГГГГ-ММ-ДД[ ЧЧ:ММ]»"),
    ] = None,
    clear_deadline: Annotated[
        bool, typer.Option("--clear-deadline", help="Убрать дедлайн")
    ] = False,
    color: Annotated[
        str | None, typer.Option("--color", metavar="ЦВЕТ", help=f"Цвет: {', '.join(TASK_COLORS)}")
    ] = None,
    plan_hours: Annotated[
        float | None,
        typer.Option("--plan-hours", metavar="ЧИСЛО", help="Плановые трудозатраты в часах"),
    ] = None,
    checklist: Annotated[
        list[str] | None, typer.Option("--checklist", metavar="ЧЕК-ЛИСТ", help="Заменить чек-листы")
    ] = None,
    sticker: Annotated[
        list[str] | None,
        typer.Option("--sticker", metavar="СТИКЕР", help="Стикер в формате ID=СОСТОЯНИЕ"),
    ] = None,
    archived: Annotated[
        bool | None, typer.Option("--archived/--no-archived", help="В архив / из архива")
    ] = None,
    completed: Annotated[
        bool | None, typer.Option("--completed/--no-completed", help="Выполнена / не выполнена")
    ] = None,
    undelete: Annotated[
        bool, typer.Option("--undelete", help="Восстановить удалённую задачу")
    ] = False,
    json_fields: Annotated[
        str | None,
        typer.Option("--json", metavar="ПОЛЯ", help="Вывести JSON с перечисленными полями"),
    ] = None,
    jq: Annotated[
        str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq по JSON-выводу")
    ] = None,
) -> None:
    """Изменить поля задачи."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    client = app_ctx.client()
    task_id = resolve_task_id(client, task)

    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if column:
        board_id = resolve_board_id(client, board) if board else None
        payload["columnId"] = resolve_column_id(client, column, board_id)
    description = _body_text(body, body_file, editor, app_ctx=app_ctx)
    if description is not None:
        payload["description"] = description
    if assignee:
        payload["assigned"] = _resolve_users(client, assignee)
    if subtask:
        payload["subtasks"] = [resolve_task_id(client, item) for item in subtask]
    if clear_deadline:
        if deadline is not None or start_date is not None:
            raise ValidationError("--clear-deadline нельзя сочетать с --deadline/--start-date.")
        payload["deadline"] = {"deleted": True}
    else:
        deadline_payload = _deadline_payload(deadline, start_date, require_deadline=False)
        if deadline_payload:
            payload["deadline"] = _merge_deadline(client, task_id, deadline_payload)
    parsed_color = _parse_color(color)
    if parsed_color:
        payload["color"] = parsed_color
    if plan_hours is not None:
        payload["timeTracking"] = {"plan": plan_hours}
    checklists = _parse_checklists(checklist)
    if checklists:
        payload["checklists"] = checklists
    stickers = parse_kv_options(sticker)
    if stickers:
        payload["stickers"] = stickers
    if archived is not None:
        payload["archived"] = archived
    if completed is not None:
        payload["completed"] = completed
    if undelete:
        payload["deleted"] = False

    if not payload:
        raise ValidationError("Не указано ни одного поля для изменения.")

    _put(app_ctx, task_id, payload)
    _report(app_ctx, task_id, f"Задача {shorten_id(task_id)} изменена")


# --------------------------------------------------------------------------- state


@app.command("close")
def close_task(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(metavar="ЗАДАЧА", help=TASK_ARG_HELP)],
    json_fields: Annotated[
        str | None,
        typer.Option("--json", metavar="ПОЛЯ", help="Вывести JSON с перечисленными полями"),
    ] = None,
    jq: Annotated[
        str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq по JSON-выводу")
    ] = None,
) -> None:
    """Отметить задачу выполненной."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    task_id = resolve_task_id(app_ctx.client(), task)
    _put(app_ctx, task_id, {"completed": True})
    _report(app_ctx, task_id, f"Задача {shorten_id(task_id)} закрыта")


@app.command("reopen")
def reopen_task(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(metavar="ЗАДАЧА", help=TASK_ARG_HELP)],
    json_fields: Annotated[
        str | None,
        typer.Option("--json", metavar="ПОЛЯ", help="Вывести JSON с перечисленными полями"),
    ] = None,
    jq: Annotated[
        str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq по JSON-выводу")
    ] = None,
) -> None:
    """Вернуть задачу в работу."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    task_id = resolve_task_id(app_ctx.client(), task)
    _put(app_ctx, task_id, {"completed": False})
    _report(app_ctx, task_id, f"Задача {shorten_id(task_id)} снова в работе")


@app.command("archive")
def archive_task(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(metavar="ЗАДАЧА", help=TASK_ARG_HELP)],
    json_fields: Annotated[
        str | None,
        typer.Option("--json", metavar="ПОЛЯ", help="Вывести JSON с перечисленными полями"),
    ] = None,
    jq: Annotated[
        str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq по JSON-выводу")
    ] = None,
) -> None:
    """Убрать задачу в архив."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    task_id = resolve_task_id(app_ctx.client(), task)
    _put(app_ctx, task_id, {"archived": True})
    _report(app_ctx, task_id, f"Задача {shorten_id(task_id)} в архиве")


@app.command("unarchive")
def unarchive_task(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(metavar="ЗАДАЧА", help=TASK_ARG_HELP)],
    json_fields: Annotated[
        str | None,
        typer.Option("--json", metavar="ПОЛЯ", help="Вывести JSON с перечисленными полями"),
    ] = None,
    jq: Annotated[
        str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq по JSON-выводу")
    ] = None,
) -> None:
    """Достать задачу из архива."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    task_id = resolve_task_id(app_ctx.client(), task)
    _put(app_ctx, task_id, {"archived": False})
    _report(app_ctx, task_id, f"Задача {shorten_id(task_id)} возвращена из архива")


@app.command("delete")
def delete_task(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(metavar="ЗАДАЧА", help=TASK_ARG_HELP)],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Не спрашивать подтверждение")] = False,
    json_fields: Annotated[
        str | None,
        typer.Option("--json", metavar="ПОЛЯ", help="Вывести JSON с перечисленными полями"),
    ] = None,
    jq: Annotated[
        str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq по JSON-выводу")
    ] = None,
) -> None:
    """Удалить задачу."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    task_id = resolve_task_id(app_ctx.client(), task)
    _confirm(app_ctx, f"Удалить задачу {target_label(task, task_id)}?", yes=yes)
    # There is no DELETE for tasks: deletion is a PUT with deleted=true.
    _put(app_ctx, task_id, {"deleted": True})
    _report(app_ctx, task_id, f"Задача {shorten_id(task_id)} удалена")


@app.command("move")
def move_task(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(metavar="ЗАДАЧА", help=TASK_ARG_HELP)],
    column_arg: Annotated[
        str | None,
        typer.Argument(metavar="[КОЛОНКА]", help="Колонка назначения: ID или название"),
    ] = None,
    column: Annotated[
        str | None,
        typer.Option("--column", "-c", metavar="КОЛОНКА", help="То же, что позиционный аргумент"),
    ] = None,
    board: Annotated[
        str | None,
        typer.Option("--board", "-b", metavar="ДОСКА", help="Доска для уточнения колонки"),
    ] = None,
    json_fields: Annotated[
        str | None,
        typer.Option("--json", metavar="ПОЛЯ", help="Вывести JSON с перечисленными полями"),
    ] = None,
    jq: Annotated[
        str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq по JSON-выводу")
    ] = None,
) -> None:
    """Перенести задачу в другую колонку."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    client = app_ctx.client()
    target = _single_value(
        column_arg,
        column,
        conflict="Колонка задана дважды: аргументом и флагом --column.",
    )
    if not target:
        raise ValidationError(
            not_specified_message("колонка"),
            hint="Укажите её аргументом или флагом --column.",
        )
    task_id = resolve_task_id(client, task)
    board_id = resolve_board_id(client, board) if board else None
    column_id = resolve_column_id(client, target, board_id)
    _put(app_ctx, task_id, {"columnId": column_id})
    _report(app_ctx, task_id, f"Задача {shorten_id(task_id)} перемещена")


# --------------------------------------------------------------------------- assignees


def _current_assigned(client: YouGileClient, task_id: str) -> list[str]:
    data = client.get(f"{TASKS_PATH}/{task_id}")
    assigned = data.get("assigned") if isinstance(data, dict) else None
    return [str(item) for item in assigned or []]


@app.command("assign")
def assign_task(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(metavar="ЗАДАЧА", help=TASK_ARG_HELP)],
    users: Annotated[
        list[str] | None, typer.Argument(metavar="ИСПОЛНИТЕЛЬ...", help="@me, почта, имя или ID")
    ] = None,
    assignee: Annotated[
        list[str] | None,
        typer.Option(
            "--assignee", "-a", metavar="ИСПОЛНИТЕЛЬ", help="То же, что позиционный аргумент"
        ),
    ] = None,
    json_fields: Annotated[
        str | None,
        typer.Option("--json", metavar="ПОЛЯ", help="Вывести JSON с перечисленными полями"),
    ] = None,
    jq: Annotated[
        str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq по JSON-выводу")
    ] = None,
) -> None:
    """Добавить исполнителей к задаче."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    client = app_ctx.client()
    wanted = _require_values(_merge_values(users, assignee), "Не указан ни один исполнитель.")
    task_id = resolve_task_id(client, task)
    assigned = _current_assigned(client, task_id)
    for user_id in _resolve_users(client, wanted):
        if user_id not in assigned:
            assigned.append(user_id)
    _put(app_ctx, task_id, {"assigned": assigned})
    _report(app_ctx, task_id, f"Исполнители задачи {shorten_id(task_id)} обновлены")


@app.command("unassign")
def unassign_task(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(metavar="ЗАДАЧА", help=TASK_ARG_HELP)],
    users: Annotated[
        list[str] | None, typer.Argument(metavar="ИСПОЛНИТЕЛЬ...", help="@me, почта, имя или ID")
    ] = None,
    assignee: Annotated[
        list[str] | None,
        typer.Option(
            "--assignee", "-a", metavar="ИСПОЛНИТЕЛЬ", help="То же, что позиционный аргумент"
        ),
    ] = None,
    json_fields: Annotated[
        str | None,
        typer.Option("--json", metavar="ПОЛЯ", help="Вывести JSON с перечисленными полями"),
    ] = None,
    jq: Annotated[
        str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq по JSON-выводу")
    ] = None,
) -> None:
    """Убрать исполнителей из задачи."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    client = app_ctx.client()
    wanted = _require_values(_merge_values(users, assignee), "Не указан ни один исполнитель.")
    task_id = resolve_task_id(client, task)
    remove = set(_resolve_users(client, wanted))
    assigned = [item for item in _current_assigned(client, task_id) if item not in remove]
    _put(app_ctx, task_id, {"assigned": assigned})
    _report(app_ctx, task_id, f"Исполнители задачи {shorten_id(task_id)} обновлены")


# --------------------------------------------------------------------------- comment


@app.command("comment")
def comment_task(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(metavar="ЗАДАЧА", help=TASK_ARG_HELP)],
    body_arg: Annotated[str | None, typer.Argument(metavar="[ТЕКСТ]", help="Текст")] = None,
    body: Annotated[
        str | None, typer.Option("--body", metavar="ТЕКСТ", help="Текст комментария")
    ] = None,
    body_file: Annotated[
        str | None,
        typer.Option("--body-file", "-F", metavar="ФАЙЛ", help="Файл с текстом, «-» — stdin"),
    ] = None,
    editor: Annotated[
        bool, typer.Option("--editor", "-e", help="Написать комментарий в $EDITOR")
    ] = False,
    json_fields: Annotated[
        str | None,
        typer.Option("--json", metavar="ПОЛЯ", help="Вывести JSON с перечисленными полями"),
    ] = None,
    jq: Annotated[
        str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq по JSON-выводу")
    ] = None,
) -> None:
    """Написать в чат задачи."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq, resource="chat-message")
    client = app_ctx.client()
    task_id = resolve_task_id(client, task)

    text = body_arg
    if text is None:
        text = _body_text(body, body_file, editor, app_ctx=app_ctx)
    if text is None:
        if not app_ctx.prompt_enabled or not _is_tty(sys.stdin):
            raise ValidationError(
                "Не указан текст комментария.",
                hint="Передайте его аргументом, через --body, --body-file или --editor.",
            )
        text = typer.prompt("Текст комментария")
    text = text.strip()
    if not text:
        raise ValidationError("Пустой комментарий не отправляется.")

    payload = {"text": text, "textHtml": html.escape(text), "label": ""}
    created = client.post(f"{CHATS_PATH}/{task_id}/messages", payload)
    message_id = str(created.get("id") or "") if isinstance(created, dict) else ""
    if app_ctx.out.machine_readable:
        emit(app_ctx, {"id": message_id, "taskId": task_id})
        return
    if not app_ctx.quiet:
        app_ctx.err_console.print(
            f"✓ Комментарий добавлен к задаче {shorten_id(task_id)}",
            markup=False,
            highlight=False,
        )


# --------------------------------------------------------------------------- subscribers


def _subscribers_path(task_id: str) -> str:
    return f"{TASKS_PATH}/{task_id}/chat-subscribers"


def _current_subscribers(client: YouGileClient, task_id: str) -> list[str]:
    data = client.get(_subscribers_path(task_id))
    if isinstance(data, dict):
        data = data.get("content")
    return [str(item) for item in data or []]


@subscribers_app.command("list")
def list_subscribers(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(metavar="ЗАДАЧА", help=TASK_ARG_HELP)],
    json_fields: Annotated[
        str | None,
        typer.Option("--json", metavar="ПОЛЯ", help="Вывести JSON с перечисленными полями"),
    ] = None,
    jq: Annotated[
        str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq по JSON-выводу")
    ] = None,
    full_ids: Annotated[bool, typer.Option("--full-ids", help="Показывать ID целиком")] = False,
) -> None:
    """Показать участников чата задачи."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq, full_ids=full_ids, resource=None)
    client = app_ctx.client()
    task_id = resolve_task_id(client, task)
    emit(app_ctx, [{"id": item} for item in _current_subscribers(client, task_id)], ["id"])


def _set_subscribers(app_ctx: AppContext, task_id: str, ids: list[str]) -> None:
    app_ctx.client().put(_subscribers_path(task_id), {"content": ids})
    _report(app_ctx, task_id, f"Участники чата задачи {shorten_id(task_id)} обновлены")


@subscribers_app.command("add")
def add_subscribers(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(metavar="ЗАДАЧА", help=TASK_ARG_HELP)],
    users: Annotated[
        list[str] | None, typer.Argument(metavar="СОТРУДНИК...", help="@me, почта, имя или ID")
    ] = None,
    json_fields: Annotated[
        str | None,
        typer.Option("--json", metavar="ПОЛЯ", help="Вывести JSON с перечисленными полями"),
    ] = None,
    jq: Annotated[
        str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq по JSON-выводу")
    ] = None,
) -> None:
    """Добавить участников в чат задачи."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    client = app_ctx.client()
    wanted = _require_values(users, "Не указан ни один участник.")
    task_id = resolve_task_id(client, task)
    current = _current_subscribers(client, task_id)
    for user_id in _resolve_users(client, wanted):
        if user_id not in current:
            current.append(user_id)
    _set_subscribers(app_ctx, task_id, current)


@subscribers_app.command("remove")
def remove_subscribers(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(metavar="ЗАДАЧА", help=TASK_ARG_HELP)],
    users: Annotated[
        list[str] | None, typer.Argument(metavar="СОТРУДНИК...", help="@me, почта, имя или ID")
    ] = None,
    json_fields: Annotated[
        str | None,
        typer.Option("--json", metavar="ПОЛЯ", help="Вывести JSON с перечисленными полями"),
    ] = None,
    jq: Annotated[
        str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq по JSON-выводу")
    ] = None,
) -> None:
    """Убрать участников из чата задачи."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    client = app_ctx.client()
    wanted = _require_values(users, "Не указан ни один участник.")
    task_id = resolve_task_id(client, task)
    drop = set(_resolve_users(client, wanted))
    current = [item for item in _current_subscribers(client, task_id) if item not in drop]
    _set_subscribers(app_ctx, task_id, current)


@subscribers_app.command("set")
def set_subscribers(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(metavar="ЗАДАЧА", help=TASK_ARG_HELP)],
    users: Annotated[
        list[str] | None, typer.Argument(metavar="СОТРУДНИК...", help="@me, почта, имя или ID")
    ] = None,
    json_fields: Annotated[
        str | None,
        typer.Option("--json", metavar="ПОЛЯ", help="Вывести JSON с перечисленными полями"),
    ] = None,
    jq: Annotated[
        str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq по JSON-выводу")
    ] = None,
) -> None:
    """Заменить список участников чата задачи."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    client = app_ctx.client()
    wanted = _require_values(users, "Не указан ни один участник.")
    task_id = resolve_task_id(client, task)
    _set_subscribers(app_ctx, task_id, _resolve_users(client, wanted))
