"""Commands for string stickers and sprint stickers."""

from __future__ import annotations

import sys
from typing import Annotated, Any

import typer

from ..client import YouGileClient
from ..context import emit, get_client, get_ctx
from ..errors import AmbiguousNameError, ResolveError, ValidationError, single_name
from ..output import apply_json_fields, humanize_timestamp, is_tty
from ..resolve import is_uuid, resolve_board_id, resolve_one
from .tasks import parse_datetime_to_ms

__all__ = [
    "STRING_STICKER_ICONS",
    "app",
    "sprint_app",
    "sprint_state_app",
    "string_app",
    "string_state_app",
]

STRING_PATH = "/api-v2/string-stickers"
SPRINT_PATH = "/api-v2/sprint-stickers"

STRING_STICKER_ICONS: tuple[str, ...] = (
    "",
    "star",
    "heart",
    "check",
    "cloud",
    "filter",
    "alarm",
    "bolt",
    "bookmark",
    "box",
    "bulb",
    "prio",
    "code",
    "ruble",
    "dollar",
    "euro",
    "eye",
    "flag",
    "flame",
    "history",
    "info",
    "key",
    "anchor",
    "message",
    "movie",
    "mnote",
    "pencil",
    "picture",
    "pin",
    "clockwise",
    "clockwiseDot",
    "rectangle",
    "shield",
    "stack",
    "string",
    "timeStop",
    "design",
    "user",
    "plus",
    "gear",
    "sort",
    "calendar",
)

STRING_LIST_COLUMNS = ["id", "name", "icon"]
SPRINT_LIST_COLUMNS = ["id", "name"]
STRING_STATE_COLUMNS = ["id", "name", "color"]
SPRINT_STATE_COLUMNS = ["id", "name", "begin", "end"]

ICON_HELP = (
    "Иконка стикера; пустая строка — без иконки. Полный список: yougile sticker string icons"
)
JSON_HELP = "Вывести JSON только с перечисленными через запятую полями"
JQ_HELP = "Отфильтровать JSON выражением jq"


# --------------------------------------------------------------------------- helpers


def _validate_icon(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in STRING_STICKER_ICONS:
        raise ValidationError(
            f"Неизвестная иконка «{value}».",
            hint="Список иконок: yougile sticker string icons.",
        )
    return value


def _emit(
    ctx: typer.Context,
    data: Any,
    *,
    columns: list[str] | None = None,
    jq: str | None = None,
) -> None:
    """Hand the data to the renderer; `--json` was settled before the request."""
    app_ctx = get_ctx(ctx)
    if jq:
        app_ctx.out.jq = jq
    emit(app_ctx, data, columns)


def _confirm(ctx: typer.Context, message: str, yes: bool) -> None:
    if yes:
        return
    app_ctx = get_ctx(ctx)
    if not app_ctx.prompt_enabled or app_ctx.out.machine_readable or not is_tty(sys.stdin):
        raise ValidationError(
            "Требуется подтверждение, но ввод неинтерактивный.",
            hint="Повторите с флагом --yes.",
        )
    typer.confirm(message, abort=True)


def _string_id(client: YouGileClient, value: str) -> str:
    return resolve_one(
        client, path=STRING_PATH, value=value, name_field="name", kind="строковый стикер"
    )


def _sprint_id(client: YouGileClient, value: str) -> str:
    return resolve_one(
        client, path=SPRINT_PATH, value=value, name_field="name", kind="стикер-спринт"
    )


def _states(sticker: Any, *, include_deleted: bool = False) -> list[dict[str, Any]]:
    raw = sticker.get("states") if isinstance(sticker, dict) else None
    rows = [item for item in raw or [] if isinstance(item, dict)]
    if include_deleted:
        return rows
    return [item for item in rows if not item.get("deleted")]


def _state_id(client: YouGileClient, path: str, sticker_id: str, value: str) -> str:
    """States live inside their sticker, so a name is matched against that sticker only."""
    text = (value or "").strip()
    if not text:
        raise ResolveError("Не указано состояние стикера.")
    if is_uuid(text):
        return text
    sticker = client.get(f"{path}/{sticker_id}")
    matches = [
        state
        for state in _states(sticker, include_deleted=True)
        if str(state.get("name") or "").strip().lower() == text.lower()
    ]
    if not matches:
        raise ResolveError(
            f"Состояние «{value}» не найдено.",
            hint="Список состояний: … state list",
        )
    if len(matches) > 1:
        raise AmbiguousNameError(
            f"Найдено несколько состояний с именем «{value}».",
            hint="Уточните имя или укажите ID.",
            candidates=matches,
        )
    return str(matches[0].get("id") or "")


def _list_stickers(
    client: YouGileClient,
    path: str,
    *,
    search: str | None,
    board: str | None,
    include_deleted: bool,
    limit: int,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "name": search,
        "boardId": resolve_board_id(client, board) if board else None,
        "includeDeleted": True if include_deleted else None,
    }
    return client.collect(path, params, max_items=limit or None)


def _split_state(raw: str, parts: int) -> list[str]:
    """`--state` fields are separated by ';' when given, else by ':' (times contain ':')."""
    text = raw.strip()
    separator = ";" if ";" in text else ":"
    return [chunk.strip() for chunk in text.split(separator, parts - 1)]


def _parse_string_state(raw: str) -> dict[str, Any]:
    chunks = _split_state(raw, 2)
    if not chunks[0]:
        raise ValidationError(f"У состояния «{raw}» нет названия.")
    state: dict[str, Any] = {"name": chunks[0]}
    if len(chunks) > 1 and chunks[1]:
        state["color"] = chunks[1]
    return state


def _parse_sprint_state(raw: str) -> dict[str, Any]:
    chunks = _split_state(raw, 3)
    if not chunks[0]:
        raise ValidationError(f"У состояния «{raw}» нет названия.")
    state: dict[str, Any] = {"name": chunks[0]}
    if len(chunks) > 1 and chunks[1]:
        state["begin"] = parse_datetime_to_ms(chunks[1])
    if len(chunks) > 2 and chunks[2]:
        state["end"] = parse_datetime_to_ms(chunks[2])
    return state


def _sprint_state_rows(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sprint boundaries come back as epoch milliseconds; show them as dates."""
    rows: list[dict[str, Any]] = []
    for state in states:
        row = dict(state)
        for key in ("begin", "end"):
            value = row.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                row[key] = humanize_timestamp(value)
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- options

StickerArg = Annotated[str, typer.Argument(metavar="СТИКЕР", help="Стикер: ID или название")]
StateArg = Annotated[str, typer.Argument(metavar="СОСТОЯНИЕ", help="Состояние: ID или название")]
NameArg = Annotated[str, typer.Argument(metavar="НАЗВАНИЕ", help="Название")]
CreateNameArg = Annotated[
    str | None, typer.Argument(metavar="НАЗВАНИЕ", help="Название нового стикера")
]
CreateNameOpt = Annotated[
    str | None,
    typer.Option("--name", "-n", metavar="НАЗВАНИЕ", help="То же название, но флагом"),
]
SearchOpt = Annotated[
    str | None, typer.Option("--search", "-S", metavar="ТЕКСТ", help="Фильтр по имени стикера")
]
BoardOpt = Annotated[
    str | None,
    typer.Option("--board", "-b", metavar="ДОСКА", help="Доска (ID, ссылка или название)"),
]
IncludeDeletedOpt = Annotated[
    bool, typer.Option("--include-deleted", help="Показывать удалённые объекты")
]
LimitOpt = Annotated[
    int,
    typer.Option(
        "--limit", "-L", metavar="ЧИСЛО", min=0, help="Сколько записей показать (0 — все)"
    ),
]
JsonOpt = Annotated[str | None, typer.Option("--json", metavar="ПОЛЯ", help=JSON_HELP)]
JqOpt = Annotated[str | None, typer.Option("--jq", "-q", metavar="ВЫРАЖЕНИЕ", help=JQ_HELP)]
YesOpt = Annotated[bool, typer.Option("--yes", "-y", help="Не спрашивать подтверждение")]
IconOpt = Annotated[
    str | None,
    typer.Option("--icon", "-i", metavar="ИКОНКА", help=ICON_HELP, callback=_validate_icon),
]
NewNameOpt = Annotated[
    str | None, typer.Option("--name", "-n", metavar="НАЗВАНИЕ", help="Новое название")
]
ColorOpt = Annotated[
    str | None, typer.Option("--color", "-c", metavar="ЦВЕТ", help="Цвет состояния, например red")
]
BeginOpt = Annotated[
    str | None,
    typer.Option("--begin", metavar="ДАТА", help="Начало спринта: дата или миллисекунды"),
]
EndOpt = Annotated[
    str | None, typer.Option("--end", metavar="ДАТА", help="Конец спринта: дата или миллисекунды")
]

app = typer.Typer(no_args_is_help=True, help="Стикеры: строковые и спринты.")
string_app = typer.Typer(no_args_is_help=True, help="Строковые стикеры.")
sprint_app = typer.Typer(no_args_is_help=True, help="Стикеры-спринты.")
string_state_app = typer.Typer(no_args_is_help=True, help="Состояния строкового стикера.")
sprint_state_app = typer.Typer(no_args_is_help=True, help="Состояния стикера-спринта.")

app.add_typer(string_app, name="string")
app.add_typer(sprint_app, name="sprint")
string_app.add_typer(string_state_app, name="state")
sprint_app.add_typer(sprint_state_app, name="state")


# --------------------------------------------------------------------------- string


@string_app.command("icons")
def string_icons(ctx: typer.Context, json_fields: JsonOpt = None, jq: JqOpt = None) -> None:
    """Показать допустимые иконки строкового стикера."""
    rows = [{"icon": icon} for icon in STRING_STICKER_ICONS if icon]
    apply_json_fields(get_ctx(ctx).out, json_fields, None, rows=rows)
    _emit(ctx, rows, columns=["icon"], jq=jq)


@string_app.command("list")
def string_list(
    ctx: typer.Context,
    search: SearchOpt = None,
    board: BoardOpt = None,
    include_deleted: IncludeDeletedOpt = False,
    limit: LimitOpt = 30,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Список строковых стикеров."""
    apply_json_fields(get_ctx(ctx).out, json_fields, "sticker-string")
    client = get_client(ctx)
    rows = _list_stickers(
        client,
        STRING_PATH,
        search=search,
        board=board,
        include_deleted=include_deleted,
        limit=limit,
    )
    _emit(ctx, rows, columns=STRING_LIST_COLUMNS, jq=jq)


@string_app.command("view")
def string_view(
    ctx: typer.Context,
    sticker: StickerArg,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Показать строковый стикер."""
    apply_json_fields(get_ctx(ctx).out, json_fields, "sticker-string")
    client = get_client(ctx)
    data = client.get(f"{STRING_PATH}/{_string_id(client, sticker)}")
    _emit(ctx, data, jq=jq)


@string_app.command("create")
def string_create(
    ctx: typer.Context,
    name: CreateNameArg = None,
    sticker_name: CreateNameOpt = None,
    icon: IconOpt = None,
    state: Annotated[
        list[str] | None,
        typer.Option(
            "--state",
            "-s",
            metavar="СОСТОЯНИЕ",
            help="Состояние «Название[:цвет]»; можно повторять",
        ),
    ] = None,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Создать строковый стикер."""
    apply_json_fields(get_ctx(ctx).out, json_fields, "sticker-string")
    client = get_client(ctx)
    payload: dict[str, Any] = {
        "name": single_name(
            name,
            sticker_name,
            genitive="стикера",
            flag="--name",
            hint="Например: yougile sticker string create «Приоритет».",
        )
    }
    if icon is not None:
        payload["icon"] = icon
    if state:
        payload["states"] = [_parse_string_state(item) for item in state]
    _emit(ctx, client.post(STRING_PATH, payload), jq=jq)


@string_app.command("edit")
def string_edit(
    ctx: typer.Context,
    sticker: StickerArg,
    name: NewNameOpt = None,
    icon: IconOpt = None,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Изменить строковый стикер."""
    apply_json_fields(get_ctx(ctx).out, json_fields, "sticker-string")
    if name is None and icon is None:
        raise ValidationError("Нечего менять.", hint="Укажите --name и/или --icon.")
    client = get_client(ctx)
    sticker_id = _string_id(client, sticker)
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if icon is not None:
        payload["icon"] = icon
    _emit(ctx, client.put(f"{STRING_PATH}/{sticker_id}", payload), jq=jq)


@string_app.command("delete")
def string_delete(
    ctx: typer.Context,
    sticker: StickerArg,
    yes: YesOpt = False,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Удалить строковый стикер."""
    apply_json_fields(get_ctx(ctx).out, json_fields, "sticker-string")
    client = get_client(ctx)
    sticker_id = _string_id(client, sticker)
    _confirm(ctx, f"Удалить строковый стикер {sticker_id}?", yes)
    # The API has no DELETE for stickers: deletion is a PUT with deleted=true.
    data = client.put(f"{STRING_PATH}/{sticker_id}", {"deleted": True})
    _emit(ctx, data, jq=jq)


@string_state_app.command("list")
def string_state_list(
    ctx: typer.Context,
    sticker: StickerArg,
    include_deleted: IncludeDeletedOpt = False,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Список состояний строкового стикера."""
    apply_json_fields(get_ctx(ctx).out, json_fields, "sticker-string-state")
    client = get_client(ctx)
    sticker_id = _string_id(client, sticker)
    data = client.get(f"{STRING_PATH}/{sticker_id}")
    rows = _states(data, include_deleted=include_deleted)
    _emit(ctx, rows, columns=STRING_STATE_COLUMNS, jq=jq)


@string_state_app.command("add")
def string_state_add(
    ctx: typer.Context,
    sticker: StickerArg,
    name: NameArg,
    color: ColorOpt = None,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Добавить состояние строковому стикеру."""
    apply_json_fields(get_ctx(ctx).out, json_fields, "sticker-string-state")
    client = get_client(ctx)
    sticker_id = _string_id(client, sticker)
    payload: dict[str, Any] = {"name": name}
    if color is not None:
        payload["color"] = color
    data = client.post(f"{STRING_PATH}/{sticker_id}/states", payload)
    _emit(ctx, data, jq=jq)


@string_state_app.command("edit")
def string_state_edit(
    ctx: typer.Context,
    sticker: StickerArg,
    state: StateArg,
    name: NewNameOpt = None,
    color: ColorOpt = None,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Изменить состояние строкового стикера."""
    apply_json_fields(get_ctx(ctx).out, json_fields, "sticker-string-state")
    if name is None and color is None:
        raise ValidationError("Нечего менять.", hint="Укажите --name и/или --color.")
    client = get_client(ctx)
    sticker_id = _string_id(client, sticker)
    state_id = _state_id(client, STRING_PATH, sticker_id, state)
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if color is not None:
        payload["color"] = color
    data = client.put(f"{STRING_PATH}/{sticker_id}/states/{state_id}", payload)
    _emit(ctx, data, jq=jq)


@string_state_app.command("delete")
def string_state_delete(
    ctx: typer.Context,
    sticker: StickerArg,
    state: StateArg,
    yes: YesOpt = False,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Удалить состояние строкового стикера."""
    apply_json_fields(get_ctx(ctx).out, json_fields, "sticker-string-state")
    client = get_client(ctx)
    sticker_id = _string_id(client, sticker)
    state_id = _state_id(client, STRING_PATH, sticker_id, state)
    _confirm(ctx, f"Удалить состояние {state_id}?", yes)
    data = client.put(f"{STRING_PATH}/{sticker_id}/states/{state_id}", {"deleted": True})
    _emit(ctx, data, jq=jq)


# --------------------------------------------------------------------------- sprint


@sprint_app.command("list")
def sprint_list(
    ctx: typer.Context,
    search: SearchOpt = None,
    board: BoardOpt = None,
    include_deleted: IncludeDeletedOpt = False,
    limit: LimitOpt = 30,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Список стикеров-спринтов."""
    apply_json_fields(get_ctx(ctx).out, json_fields, "sticker-sprint")
    client = get_client(ctx)
    rows = _list_stickers(
        client,
        SPRINT_PATH,
        search=search,
        board=board,
        include_deleted=include_deleted,
        limit=limit,
    )
    _emit(ctx, rows, columns=SPRINT_LIST_COLUMNS, jq=jq)


@sprint_app.command("view")
def sprint_view(
    ctx: typer.Context,
    sticker: StickerArg,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Показать стикер-спринт."""
    apply_json_fields(get_ctx(ctx).out, json_fields, "sticker-sprint")
    client = get_client(ctx)
    data = client.get(f"{SPRINT_PATH}/{_sprint_id(client, sticker)}")
    _emit(ctx, data, jq=jq)


@sprint_app.command("create")
def sprint_create(
    ctx: typer.Context,
    name: CreateNameArg = None,
    sticker_name: CreateNameOpt = None,
    state: Annotated[
        list[str] | None,
        typer.Option(
            "--state",
            "-s",
            metavar="СОСТОЯНИЕ",
            help=(
                "Состояние «Название[:начало[:конец]]» (или через «;», "
                "если во времени есть двоеточие); можно повторять"
            ),
        ),
    ] = None,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Создать стикер-спринт."""
    apply_json_fields(get_ctx(ctx).out, json_fields, "sticker-sprint")
    client = get_client(ctx)
    payload: dict[str, Any] = {
        "name": single_name(
            name,
            sticker_name,
            genitive="стикера",
            flag="--name",
            hint="Например: yougile sticker string create «Приоритет».",
        )
    }
    if state:
        payload["states"] = [_parse_sprint_state(item) for item in state]
    _emit(ctx, client.post(SPRINT_PATH, payload), jq=jq)


@sprint_app.command("edit")
def sprint_edit(
    ctx: typer.Context,
    sticker: StickerArg,
    name: Annotated[str, typer.Option("--name", "-n", metavar="НАЗВАНИЕ", help="Новое название")],
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Изменить стикер-спринт."""
    apply_json_fields(get_ctx(ctx).out, json_fields, "sticker-sprint")
    client = get_client(ctx)
    sticker_id = _sprint_id(client, sticker)
    data = client.put(f"{SPRINT_PATH}/{sticker_id}", {"name": name})
    _emit(ctx, data, jq=jq)


@sprint_app.command("delete")
def sprint_delete(
    ctx: typer.Context,
    sticker: StickerArg,
    yes: YesOpt = False,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Удалить стикер-спринт."""
    apply_json_fields(get_ctx(ctx).out, json_fields, "sticker-sprint")
    client = get_client(ctx)
    sticker_id = _sprint_id(client, sticker)
    _confirm(ctx, f"Удалить стикер-спринт {sticker_id}?", yes)
    # The API has no DELETE for stickers: deletion is a PUT with deleted=true.
    data = client.put(f"{SPRINT_PATH}/{sticker_id}", {"deleted": True})
    _emit(ctx, data, jq=jq)


@sprint_state_app.command("list")
def sprint_state_list(
    ctx: typer.Context,
    sticker: StickerArg,
    include_deleted: IncludeDeletedOpt = False,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Список состояний стикера-спринта."""
    apply_json_fields(get_ctx(ctx).out, json_fields, "sticker-sprint-state")
    app_ctx = get_ctx(ctx)
    client = get_client(ctx)
    sticker_id = _sprint_id(client, sticker)
    data = client.get(f"{SPRINT_PATH}/{sticker_id}")
    rows = _states(data, include_deleted=include_deleted)
    if json_fields is None and not jq and not app_ctx.out.machine_readable:
        rows = _sprint_state_rows(rows)
    _emit(ctx, rows, columns=SPRINT_STATE_COLUMNS, jq=jq)


@sprint_state_app.command("add")
def sprint_state_add(
    ctx: typer.Context,
    sticker: StickerArg,
    name: NameArg,
    begin: BeginOpt = None,
    end: EndOpt = None,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Добавить состояние стикеру-спринту."""
    apply_json_fields(get_ctx(ctx).out, json_fields, "sticker-sprint-state")
    client = get_client(ctx)
    sticker_id = _sprint_id(client, sticker)
    payload: dict[str, Any] = {"name": name}
    if begin is not None:
        payload["begin"] = parse_datetime_to_ms(begin)
    if end is not None:
        payload["end"] = parse_datetime_to_ms(end)
    data = client.post(f"{SPRINT_PATH}/{sticker_id}/states", payload)
    _emit(ctx, data, jq=jq)


@sprint_state_app.command("edit")
def sprint_state_edit(
    ctx: typer.Context,
    sticker: StickerArg,
    state: StateArg,
    name: NewNameOpt = None,
    begin: BeginOpt = None,
    end: EndOpt = None,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Изменить состояние стикера-спринта."""
    apply_json_fields(get_ctx(ctx).out, json_fields, "sticker-sprint-state")
    if name is None and begin is None and end is None:
        raise ValidationError("Нечего менять.", hint="Укажите --name, --begin и/или --end.")
    client = get_client(ctx)
    sticker_id = _sprint_id(client, sticker)
    state_id = _state_id(client, SPRINT_PATH, sticker_id, state)
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if begin is not None:
        payload["begin"] = parse_datetime_to_ms(begin)
    if end is not None:
        payload["end"] = parse_datetime_to_ms(end)
    data = client.put(f"{SPRINT_PATH}/{sticker_id}/states/{state_id}", payload)
    _emit(ctx, data, jq=jq)


@sprint_state_app.command("delete")
def sprint_state_delete(
    ctx: typer.Context,
    sticker: StickerArg,
    state: StateArg,
    yes: YesOpt = False,
    json_fields: JsonOpt = None,
    jq: JqOpt = None,
) -> None:
    """Удалить состояние стикера-спринта."""
    apply_json_fields(get_ctx(ctx).out, json_fields, "sticker-sprint-state")
    client = get_client(ctx)
    sticker_id = _sprint_id(client, sticker)
    state_id = _state_id(client, SPRINT_PATH, sticker_id, state)
    _confirm(ctx, f"Удалить состояние {state_id}?", yes)
    data = client.put(f"{SPRINT_PATH}/{sticker_id}/states/{state_id}", {"deleted": True})
    _emit(ctx, data, jq=jq)
