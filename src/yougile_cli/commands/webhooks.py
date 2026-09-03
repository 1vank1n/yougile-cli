"""`yougile webhook` — company event subscriptions, shaped after `gh`.

Webhooks have no DELETE method and no per-id GET: removing one is a ``PUT``
with ``{"deleted": true}``, and ``webhook view`` picks the subscription out of
the full listing. ``GET /api-v2/webhooks`` is documented as a single object but
answers with a bare list (and, on some deployments, a paged envelope), so every
shape is normalised here.
"""

from __future__ import annotations

import sys
from typing import Annotated, Any

import typer

from ..client import YouGileClient
from ..context import AppContext, ctx_client, emit, get_ctx
from ..errors import (
    AmbiguousNameError,
    CancelledError,
    ResolveError,
    ValidationError,
    ambiguous_error,
    not_found_error,
    not_specified_message,
    resource_words,
)
from ..output import is_tty, shorten_id
from ..resolve import is_uuid, resolve_board_id, resolve_column_id, resolve_project_id

__all__ = ["app"]

WEBHOOKS_PATH = "/api-v2/webhooks"
KIND = "вебхук"
LIST_COLUMNS = ["id", "url", "event", "disabled", "failuresSinceLastSuccess", "filters"]

app = typer.Typer(
    no_args_is_help=True,
    help="Вебхуки — подписки на события компании: список, создание, изменение, удаление.",
)

JSON_OPT = typer.Option(
    None, "--json", metavar="ПОЛЯ", help="Вывести JSON только с перечисленными через запятую полями"
)
JQ_OPT = typer.Option(None, "--jq", "-q", metavar="ВЫРАЖЕНИЕ", help="Фильтр jq для JSON-вывода")
FULL_IDS_OPT = typer.Option(False, "--full-ids", help="Показывать идентификаторы целиком")
LIMIT_OPT = typer.Option(
    30, "--limit", "-L", metavar="ЧИСЛО", min=0, help="Сколько записей вернуть; 0 — все"
)
YES_OPT = typer.Option(False, "--yes", "-y", help="Не спрашивать подтверждение")

WEBHOOK_ARG_HELP = "Вебхук: ID или его URL"
FILTER_OPT_HELP = (
    "Фильтр вида имя=значение: location=<проект/доска/колонка>, "
    "title=<regexp>, chat_message=<regexp>. Можно повторять"
)

# Filter names and their value shapes come from the API description:
# location is a UUID (or a list of them), title and chat_message are regexps.
FILTER_NAMES = ("location", "title", "chat_message")
LIST_VALUE_FILTERS = ("location",)

OBJECT_ACTIONS = ("created", "deleted", "restored", "moved", "renamed", "updated")
USER_ACTIONS = ("added", "removed")
EVENT_OBJECTS = (
    "project",
    "board",
    "column",
    "task",
    "sticker",
    "department",
    "group_chat",
    "chat_message",
)

ACTION_LABELS = {
    "created": "создан",
    "deleted": "удалён",
    "restored": "восстановлен",
    "moved": "перемещён",
    "renamed": "переименован",
    "updated": "изменён",
    "added": "добавлен",
    "removed": "исключён",
}

EVENTS_NOTE = (
    "Событие — свободная строка формата <тип_объекта>-<действие>; "
    "поддерживается javascript regexp, где «*» означает «любое»: "
    "«task-*» — все события задач, «.*» — все события компании. "
    "Подписаться можно только на события компании: личные чаты недоступны."
)


def _event_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = [{"event": ".*", "description": "все события компании"}]
    for name in EVENT_OBJECTS:
        rows.append({"event": f"{name}-*", "description": f"все события: {name}"})
        rows.extend(
            {"event": f"{name}-{action}", "description": f"{name}: {ACTION_LABELS[action]}"}
            for action in OBJECT_ACTIONS
        )
    rows.append({"event": "user-*", "description": "все события: user"})
    rows.extend(
        {"event": f"user-{action}", "description": f"user: {ACTION_LABELS[action]}"}
        for action in USER_ACTIONS
    )
    return rows


EVENT_ROWS = _event_rows()


def single_url(positional: str | None, option: str | None) -> str:
    """`create URL` and `create --url URL` are synonyms; both must agree."""
    if positional is not None and option is not None and positional.strip() != option.strip():
        raise ValidationError(
            f"URL задан дважды и по-разному: «{positional}» и --url «{option}».",
            hint="Оставьте что-то одно: позиционный аргумент или --url.",
        )
    text = (positional if positional is not None else option) or ""
    if not text.strip():
        raise ValidationError(
            "Не указан URL вебхука.",
            hint="Например: yougile webhook create https://example.com/hook -e task-created",
        )
    return text


def _apply_output(
    app_ctx: AppContext,
    *,
    json_fields: str | None = None,
    jq: str | None = None,
    full_ids: bool = False,
) -> None:
    """Fold the per-command output flags into the context's output options.

    `-o/--output` stays a root flag: cli.hoist_root_flags lets it trail any
    subcommand, so redeclaring it here would only split the help text.
    """
    if json_fields is not None:
        app_ctx.out.json_fields = [name.strip() for name in json_fields.split(",") if name.strip()]
    if jq:
        app_ctx.out.jq = jq
    if full_ids:
        app_ctx.out.full_ids = True


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


def _as_rows(data: Any) -> list[dict[str, Any]]:
    """The listing may arrive as one object, a bare list or a paged envelope."""
    if data is None:
        return []
    if isinstance(data, dict):
        content = data.get("content")
        if isinstance(content, list):
            return [item for item in content if isinstance(item, dict)]
        return [data] if data else []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _fetch(client: YouGileClient, *, include_deleted: bool = False) -> list[dict[str, Any]]:
    params = {"includeDeleted": True} if include_deleted else None
    return _as_rows(client.get(WEBHOOKS_PATH, params))


def _resolve_location(client: YouGileClient, value: str) -> str:
    """A location filter holds a project/board/column id; look names up in that order."""
    text = value.strip()
    if is_uuid(text):
        return text
    for resolver in (resolve_project_id, resolve_board_id, resolve_column_id):
        try:
            return resolver(client, text)
        except AmbiguousNameError:
            raise
        except ResolveError:
            continue
    raise ResolveError(
        f"Для фильтра location не найдено ни проекта, ни доски, ни колонки «{text}»."
    )


def _build_filters(client: YouGileClient, values: list[str] | None) -> list[dict[str, Any]] | None:
    if not values:
        return None
    grouped: dict[str, list[str]] = {}
    for raw in values:
        name, sep, value = raw.partition("=")
        name = name.strip()
        if not sep or not name or not value.strip():
            raise ValidationError(f"Ожидался формат имя=значение, получено «{raw}».")
        if name not in FILTER_NAMES:
            raise ValidationError(
                f"Неизвестный фильтр «{name}».",
                hint=f"Доступны: {', '.join(FILTER_NAMES)}.",
            )
        if name == "location":
            value = _resolve_location(client, value)
        grouped.setdefault(name, []).append(value)

    filters: list[dict[str, Any]] = []
    for name, items in grouped.items():
        # Only location takes an array of ids; title and chat_message take one regexp.
        if name not in LIST_VALUE_FILTERS and len(items) > 1:
            raise ValidationError(
                f"Фильтр «{name}» можно указать только один раз.",
                hint=f"Объедините шаблоны в одно регулярное выражение: {'|'.join(items)}",
            )
        payload: Any = items if name in LIST_VALUE_FILTERS else items[0]
        filters.append({"name": name, "value": payload})
    return filters


def _find_webhook(client: YouGileClient, value: str) -> dict[str, Any]:
    """Accept an id or the subscription URL. A webhook URL may itself contain a UUID,
    so an id is only assumed when the whole argument is one."""
    text = (value or "").strip()
    if not text:
        raise ResolveError(not_specified_message(KIND))

    items = _fetch(client, include_deleted=True)
    if is_uuid(text):
        for item in items:
            if item.get("id") == text:
                return item
        raise not_found_error(KIND, text)

    needle = text.casefold()
    exact = [i for i in items if str(i.get("url") or "").casefold() == needle]
    matches = exact or [i for i in items if needle in str(i.get("url") or "").casefold()]
    if not matches:
        raise not_found_error(KIND, text)
    if len(matches) > 1:
        raise ambiguous_error(
            KIND,
            text,
            [{"id": i.get("id", ""), "title": i.get("url", "")} for i in matches[:20]],
            hint="Уточните URL или укажите ID.",
        )
    return matches[0]


def _webhook_id(client: YouGileClient, value: str) -> str:
    webhook_id = _find_webhook(client, value).get("id")
    if not isinstance(webhook_id, str) or not webhook_id:
        raise ResolveError(resource_words(KIND).without_id(value))
    return webhook_id


@app.command("list")
def list_webhooks(
    ctx: typer.Context,
    include_deleted: bool = typer.Option(
        False, "--include-deleted", help="Показывать в том числе удалённые вебхуки"
    ),
    limit: int = LIMIT_OPT,
    json_fields: str | None = JSON_OPT,
    jq: str | None = JQ_OPT,
    full_ids: bool = FULL_IDS_OPT,
) -> None:
    """Список вебхуков."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq, full_ids=full_ids)
    items = _fetch(ctx_client(ctx), include_deleted=include_deleted)
    if limit > 0:
        items = items[:limit]
    columns = [*LIST_COLUMNS, "deleted"] if include_deleted else LIST_COLUMNS
    emit(app_ctx, items, columns=columns)


@app.command("view")
def view_webhook(
    ctx: typer.Context,
    webhook: str = typer.Argument(..., metavar="ВЕБХУК", help=WEBHOOK_ARG_HELP),
    json_fields: str | None = JSON_OPT,
    jq: str | None = JQ_OPT,
    full_ids: bool = FULL_IDS_OPT,
) -> None:
    """Показать вебхук."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq, full_ids=full_ids)
    emit(app_ctx, _find_webhook(ctx_client(ctx), webhook))


@app.command("create")
def create_webhook(
    ctx: typer.Context,
    target: str | None = typer.Argument(None, metavar="URL", help="URL, на который слать события"),
    url: str | None = typer.Option(
        None, "--url", "-u", metavar="URL", help="Тот же URL, но флагом"
    ),
    event: str = typer.Option(
        ...,
        "--event",
        "-e",
        metavar="СОБЫТИЕ",
        help="Событие, например task-created или .* (см. `yougile webhook events`)",
    ),
    filters: Annotated[
        list[str] | None,
        typer.Option("--filter", "-f", metavar="ФИЛЬТР", help=FILTER_OPT_HELP),
    ] = None,
    json_fields: str | None = JSON_OPT,
    jq: str | None = JQ_OPT,
) -> None:
    """Создать вебхук."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    client = ctx_client(ctx)
    payload = {
        "url": single_url(target, url),
        "event": event,
        "filters": _build_filters(client, list(filters or [])) or [],
    }
    _emit_result(app_ctx, client.post(WEBHOOKS_PATH, payload))


@app.command("edit")
def edit_webhook(
    ctx: typer.Context,
    webhook: str = typer.Argument(..., metavar="ВЕБХУК", help=WEBHOOK_ARG_HELP),
    url: str | None = typer.Option(None, "--url", "-u", metavar="URL", help="Новый URL вебхука"),
    event: str | None = typer.Option(
        None, "--event", "-e", metavar="СОБЫТИЕ", help="Новое событие вебхука"
    ),
    enabled: bool | None = typer.Option(
        None, "--enable/--disable", help="Включить или выключить вебхук"
    ),
    filters: Annotated[
        list[str] | None,
        typer.Option("--filter", "-f", metavar="ФИЛЬТР", help=FILTER_OPT_HELP),
    ] = None,
    undelete: bool = typer.Option(False, "--undelete", help="Восстановить удалённый вебхук"),
    json_fields: str | None = JSON_OPT,
    jq: str | None = JQ_OPT,
) -> None:
    """Изменить вебхук."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    if url is None and event is None and enabled is None and not filters and not undelete:
        raise ValidationError(
            "Нечего менять.",
            hint="Укажите --url, --event, --enable/--disable, --filter или --undelete.",
        )
    client = ctx_client(ctx)
    webhook_id = _webhook_id(client, webhook)
    payload: dict[str, Any] = {
        "url": url,
        "event": event,
        "disabled": None if enabled is None else not enabled,
        "filters": _build_filters(client, list(filters or [])),
        "deleted": False if undelete else None,
    }
    _emit_result(app_ctx, client.put(f"{WEBHOOKS_PATH}/{webhook_id}", payload))


@app.command("delete")
def delete_webhook(
    ctx: typer.Context,
    webhook: str = typer.Argument(..., metavar="ВЕБХУК", help=WEBHOOK_ARG_HELP),
    yes: bool = YES_OPT,
    json_fields: str | None = JSON_OPT,
    jq: str | None = JQ_OPT,
) -> None:
    """Удалить вебхук."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    client = ctx_client(ctx)
    webhook_id = _webhook_id(client, webhook)
    _confirm(app_ctx, f"Удалить вебхук {shorten_id(webhook_id)}?", yes)
    # Webhooks have no DELETE method: deleting is a PUT with deleted=true.
    _emit_result(app_ctx, client.put(f"{WEBHOOKS_PATH}/{webhook_id}", {"deleted": True}))


@app.command("events")
def list_events(
    ctx: typer.Context,
    json_fields: str | None = JSON_OPT,
    jq: str | None = JQ_OPT,
) -> None:
    """Известные события, на которые можно подписаться."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    emit(app_ctx, list(EVENT_ROWS), columns=["event", "description"])
    if not app_ctx.out.machine_readable and not app_ctx.quiet:
        app_ctx.err_console.print(EVENTS_NOTE)
