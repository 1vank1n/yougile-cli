"""`yougile company|file|crm|config|alias|browse|status|version` — остальные команды.

Здесь живут мелкие ветки CLI, которым не нужен отдельный модуль: текущая
компания, загрузка и скачивание файлов, CRM-контакты, локальные настройки и алиасы,
открытие ссылок в браузере, сводка «мои задачи» и вывод версии.
"""

from __future__ import annotations

import platform
import re
import shlex
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

import typer

from .. import __version__
from ..attachments import absolute_url, download, strip_preview
from ..client import YouGileClient
from ..config import (
    cache_dir,
    delete_alias,
    get_setting,
    host_to_web_url,
    list_aliases,
    list_settings,
    set_alias,
    set_setting,
    settings_path,
)
from ..context import AppContext, get_ctx
from ..errors import (
    CancelledError,
    ConfigError,
    ValidationError,
    not_found_message,
    not_specified_message,
    single_name,
)
from ..output import OutputFormat, apply_json_fields, is_tty, sanitize_terminal_text
from ..resolve import (
    parse_kv_options,
    parse_task_url,
    resolve_board_id,
    resolve_project_id,
    resolve_task_id,
    resolve_user_id,
)

__all__ = [
    "alias_app",
    "browse_cmd",
    "company_app",
    "config_app",
    "crm_app",
    "expand_alias",
    "file_app",
    "status_cmd",
    "version_cmd",
]

COMPANIES_PATH = "/api-v2/companies"
CRM_CONTACT_PERSONS_PATH = "/api-v2/crm/contact-persons"
CRM_BY_EXTERNAL_ID_PATH = "/api-v2/crm/contacts/by-external-id"
BOARDS_PATH = "/api-v2/boards"
COLUMNS_PATH = "/api-v2/columns"
TASKS_PATH = "/api-v2/tasks"
TASK_LIST_PATH = "/api-v2/task-list"

DEFAULT_LIMIT = 30
PROMPT_VALUES = ("enabled", "disabled")
TASK_CODE_RE = re.compile(r"^[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9]{0,15}-\d+$")
PLACEHOLDER_RE = re.compile(r"\$(\d+)")

company_app = typer.Typer(no_args_is_help=True, help="Текущая компания: просмотр и изменение.")
file_app = typer.Typer(
    no_args_is_help=True, help="Файлы: загрузка на сервер YouGile и скачивание вложений."
)
crm_app = typer.Typer(no_args_is_help=True, help="CRM: контактные лица и поиск контактов.")
contact_app = typer.Typer(no_args_is_help=True, help="Контактные лица CRM.")
config_app = typer.Typer(no_args_is_help=True, help="Локальные настройки: get / set / list.")
alias_app = typer.Typer(no_args_is_help=True, help="Алиасы команд: list / set / delete.")

crm_app.add_typer(contact_app, name="contact")

# --------------------------------------------------------------------------- shared flags

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
    metavar="ЧИСЛО",
    min=0,
    help="Сколько элементов показать; 0 — все",
)
_YES_OPT = typer.Option(False, "--yes", "-y", help="Не спрашивать подтверждение")
_COMPANY_OPT = typer.Option(
    None,
    "--company-id",
    "-c",
    metavar="ID",
    help="ID компании; по умолчанию — компания текущего ключа",
)


def _apply_output(
    app_ctx: AppContext,
    json_fields: str | None,
    jq: str | None,
    resource: str | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> None:
    """`--json ПОЛЯ` и `--jq` живут на команде, а не на корневом приложении."""
    apply_json_fields(app_ctx.out, json_fields, resource, rows=rows)
    if jq:
        app_ctx.out.jq = jq


def _max_items(limit: int) -> int | None:
    return None if limit <= 0 else limit


def _confirm(app_ctx: AppContext, message: str, yes: bool) -> None:
    if yes:
        return
    if not app_ctx.prompt_enabled or app_ctx.out.machine_readable or not is_tty(sys.stdin):
        raise ValidationError(
            "Требуется подтверждение, но задать вопрос некому.",
            hint="Повторите команду с флагом --yes.",
        )
    if not typer.confirm(message):
        raise CancelledError()


def _say(app_ctx: AppContext, message: str) -> None:
    """Служебные сообщения идут в stderr, чтобы не мешать пайпам."""
    if not app_ctx.quiet and not app_ctx.out.machine_readable:
        app_ctx.err_console.print(message)


def _echo(app_ctx: AppContext, value: str) -> None:
    if not app_ctx.quiet:
        app_ctx.console.print(value, markup=False, highlight=False)


def _company_path(company_id: str | None) -> str:
    """Путь в схеме — /api-v2/companies{*companyId}: сегмент необязателен."""
    ident = (company_id or "").strip()
    if not ident:
        return COMPANIES_PATH
    # Значение приходит из --company: без экранирования «..» или «#» уводят запрос
    # на совсем другой эндпоинт.
    if set("/?#%") & set(ident) or any(ch.isspace() for ch in ident):
        raise ValidationError(
            f"Недопустимый идентификатор компании «{company_id}».",
            hint="Укажите ID компании без пробелов и символов «/», «?», «#», «%».",
        )
    return f"{COMPANIES_PATH}/{quote(ident, safe='')}"


# --------------------------------------------------------------------------- company


@company_app.command("view", help="Показать детали текущей компании.")
def view_company(
    ctx: typer.Context,
    company_id: str | None = _COMPANY_OPT,
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq, "company")
    app_ctx.emit(app_ctx.client().get(_company_path(company_id)))


@company_app.command("edit", help="Изменить название или произвольные данные компании.")
def edit_company(
    ctx: typer.Context,
    title: str | None = typer.Option(
        None, "--title", "-t", metavar="НАЗВАНИЕ", help="Новое название компании"
    ),
    api_data: list[str] | None = typer.Option(
        None,
        "--api-data",
        "-a",
        metavar="КЛЮЧ=ЗНАЧЕНИЕ",
        help="Произвольные данные (можно повторять)",
    ),
    deleted: bool | None = typer.Option(
        None, "--deleted/--restore", help="Пометить компанию удалённой или снять пометку"
    ),
    company_id: str | None = _COMPANY_OPT,
    yes: bool = _YES_OPT,
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq, "company")
    extra = parse_kv_options(list(api_data or []))
    body: dict[str, Any] = {"title": title, "apiData": extra or None, "deleted": deleted}
    if all(value is None for value in body.values()):
        raise ValidationError(
            "Нечего менять.",
            hint="Укажите --title, --api-data или --deleted/--restore.",
        )
    if deleted:
        _confirm(app_ctx, "Пометить компанию удалённой?", yes)
    # У компаний нет DELETE: удаление — это PUT с deleted=true.
    app_ctx.emit(app_ctx.client().put(_company_path(company_id), body))


# --------------------------------------------------------------------------- file


@file_app.command("upload", help="Загрузить файл и получить его ссылку.")
def upload_file(
    ctx: typer.Context,
    path: Path = typer.Argument(..., metavar="ФАЙЛ", help="Путь к файлу, который нужно загрузить"),
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    if not path.is_file():
        raise ValidationError(not_found_message("файл", str(path)))
    result = app_ctx.client().upload_file(path)
    app_ctx.emit(result, columns=["url", "fullUrl"])


@file_app.command("download", help="Скачать файл по ссылке YouGile.")
def download_file(
    ctx: typer.Context,
    url: str = typer.Argument(
        ...,
        metavar="URL",
        help="Ссылка на файл или путь вида /user-data/<id>/<имя>",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        metavar="ФАЙЛ|КАТАЛОГ",
        help="Куда сохранить: имя файла или существующий каталог",
    ),
    preview: bool = typer.Option(False, "--preview", help="Скачать превью 480×480, а не оригинал"),
    force: bool = typer.Option(False, "--force", "-f", help="Перезаписать существующий файл"),
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    if not (url or "").strip():
        raise ValidationError(not_specified_message("файл"))
    client = app_ctx.client()
    # Относительный путь из описания или чата разворачивается на хост, к которому
    # мы авторизованы, иначе заголовок Bearer будет срезан как чужой.
    address = absolute_url(url.strip(), client.host)
    path = download(client, address, output, force=force, preview=preview)
    app_ctx.emit(
        {
            "path": str(path),
            "size": path.stat().st_size,
            "url": strip_preview(address, keep=preview),
        },
        columns=["path", "size"],
    )


# --------------------------------------------------------------------------- crm


@contact_app.command("create", help="Создать контактное лицо CRM.")
def create_contact(
    ctx: typer.Context,
    title_arg: str | None = typer.Argument(
        None, metavar="НАЗВАНИЕ", help="Имя контактного лица (можно передать и флагом --title)"
    ),
    title: str | None = typer.Option(
        None, "--title", "-t", metavar="НАЗВАНИЕ", help="То же имя, но флагом"
    ),
    project: str = typer.Option(
        ..., "--project", "-p", metavar="ПРОЕКТ", help="Проект: ID, имя или ссылка"
    ),
    position: str | None = typer.Option(None, "--position", metavar="ДОЛЖНОСТЬ", help="Должность"),
    phone: str | None = typer.Option(None, "--phone", metavar="ТЕЛЕФОН", help="Телефон"),
    additional_phone: str | None = typer.Option(
        None, "--additional-phone", metavar="ТЕЛЕФОН", help="Дополнительный телефон"
    ),
    email: str | None = typer.Option(
        None, "--email", "-e", metavar="ПОЧТА", help="Электронная почта"
    ),
    address: str | None = typer.Option(None, "--address", metavar="АДРЕС", help="Адрес"),
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    client = app_ctx.client()
    fields = {
        "position": position,
        "phone": phone,
        "additionalPhone": additional_phone,
        "email": email,
        "address": address,
    }
    name = single_name(
        title_arg,
        title,
        genitive="контактного лица",
        hint="Например: yougile crm contact create «Иван».",
    )
    body: dict[str, Any] = {
        "projectId": resolve_project_id(client, project),
        "title": name,
        "fields": {key: value for key, value in fields.items() if value is not None} or None,
    }
    app_ctx.emit(client.post(CRM_CONTACT_PERSONS_PATH, body))


@contact_app.command("view", help="Найти контакт CRM по ID чата во внешнем мессенджере.")
def view_contact(
    ctx: typer.Context,
    external_id: str | None = typer.Option(
        None,
        "--external-id",
        "-i",
        metavar="ПРОВАЙДЕР:ЧАТ",
        help="Внешний идентификатор целиком, например telegram:12345",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        metavar="ПРОВАЙДЕР",
        help="Провайдер внешней интеграции, например telegram",
    ),
    chat_id: str | None = typer.Option(
        None, "--chat-id", metavar="ЧАТ", help="ID чата во внешнем мессенджере"
    ),
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    if external_id:
        head, sep, tail = external_id.partition(":")
        if not sep or not head.strip() or not tail.strip():
            raise ValidationError(
                f"Не разобрать внешний идентификатор «{external_id}».",
                hint="Формат: --external-id провайдер:идентификатор_чата.",
            )
        provider, chat_id = head.strip(), tail.strip()
    if not provider or not chat_id:
        raise ValidationError(
            "Не указан внешний идентификатор контакта.",
            hint="Передайте --external-id провайдер:чат либо --provider и --chat-id.",
        )
    params = {"provider": provider, "chatId": chat_id}
    app_ctx.emit(app_ctx.client().get(CRM_BY_EXTERNAL_ID_PATH, params))


# --------------------------------------------------------------------------- config


def _validate_setting(key: str, value: str) -> None:
    name = key.strip()
    if name == "output":
        allowed = [item.value for item in OutputFormat]
        if value not in allowed:
            raise ValidationError(
                f"Недопустимый формат вывода «{value}».",
                hint=f"Допустимы: {', '.join(allowed)}.",
            )
    elif name == "prompt" and value not in PROMPT_VALUES:
        raise ValidationError(
            f"Недопустимое значение «{value}» для prompt.",
            hint=f"Допустимы: {', '.join(PROMPT_VALUES)}.",
        )


@config_app.command("get", help="Показать значение настройки.")
def config_get(
    ctx: typer.Context,
    key: str = typer.Argument(
        ..., metavar="КЛЮЧ", help="Имя настройки, например output или aliases.mine"
    ),
) -> None:
    app_ctx = get_ctx(ctx)
    value = get_setting(key)
    # `ids` would print the key name instead of the value, so it echoes like table.
    if app_ctx.out.machine_readable and app_ctx.out.fmt is not OutputFormat.IDS:
        app_ctx.emit({"key": key, "value": value})
        return
    _echo(app_ctx, value or "")


@config_app.command("set", help="Задать значение настройки.")
def config_set(
    ctx: typer.Context,
    key: str = typer.Argument(
        ..., metavar="КЛЮЧ", help="Имя настройки, например output или aliases.mine"
    ),
    value: str = typer.Argument(..., metavar="ЗНАЧЕНИЕ", help="Новое значение"),
) -> None:
    app_ctx = get_ctx(ctx)
    _validate_setting(key, value)
    path = set_setting(key, value)
    _say(app_ctx, f"✓ {key} = {value} ({path})")
    if app_ctx.out.machine_readable:
        app_ctx.emit({"key": key, "value": value})


@config_app.command("list", help="Показать все настройки.")
def config_list(
    ctx: typer.Context,
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    # The aliases live in the same file, so this answer knows more than the schema does.
    settings = list_settings()
    _apply_output(app_ctx, json_fields, jq, "setting", rows=[dict(settings)])
    app_ctx.emit(settings)


def _cache_entries(cache: Path) -> int:
    """Файлов в кэше: карты кодов задач лежат по одной на хост."""
    if not cache.is_dir():
        return 0
    return sum(1 for item in cache.rglob("*") if item.is_file())


@config_app.command("clear-cache", help="Очистить локальный кэш каталога конфигурации.")
def config_clear_cache(
    ctx: typer.Context,
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq, "cache")
    cache = cache_dir()
    entries = _cache_entries(cache)
    removed = cache.is_dir()
    if removed:
        shutil.rmtree(cache, ignore_errors=True)
    _say(
        app_ctx,
        f"✓ Кэш очищен: удалено записей — {entries}." if removed else "Кэш пуст.",
    )
    if app_ctx.out.machine_readable:
        app_ctx.emit({"path": str(cache), "removed": removed, "entries": entries})


# --------------------------------------------------------------------------- alias


def expand_alias(argv: list[str], aliases: Mapping[str, str]) -> list[str]:
    """Подставить алиас в начало argv, как это делает `gh`.

    ``$1``…``$N`` заменяются позиционными аргументами, ``$@`` — всеми
    оставшимися. Аргументы, не попавшие ни в одну подстановку, дописываются
    в конец.
    """
    args = list(argv)
    if not args or args[0].startswith("-"):
        return args
    expansion = aliases.get(args[0])
    if not expansion:
        return args

    rest = args[1:]
    try:
        tokens = shlex.split(expansion)
    except ValueError as exc:
        raise ValidationError(f"Некорректный алиас «{args[0]}»: {exc}") from exc
    if not tokens:
        return args

    used: set[int] = set()
    consumed_all = False
    result: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if index < 1 or index > len(rest):
            raise ValidationError(
                f"Недостаточно аргументов для алиаса «{args[0]}».",
                hint=f"Ожидается как минимум {index}, передано {len(rest)}.",
            )
        used.add(index)
        return rest[index - 1]

    for token in tokens:
        if token == "$@":
            result.extend(rest)
            consumed_all = True
            continue
        result.append(PLACEHOLDER_RE.sub(substitute, token) if "$" in token else token)

    if not consumed_all:
        result.extend(value for index, value in enumerate(rest, 1) if index not in used)
    return result


def _core_commands(ctx: typer.Context) -> set[str]:
    root = ctx.find_root().command
    commands = getattr(root, "commands", None)
    return set(commands) if isinstance(commands, dict) else set()


@alias_app.command("list", help="Показать сохранённые алиасы.")
def alias_list(
    ctx: typer.Context,
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq, "alias")
    rows = [{"name": name, "expansion": value} for name, value in sorted(list_aliases().items())]
    app_ctx.emit(rows, columns=["name", "expansion"])


@alias_app.command("set", help="Задать алиас: yougile alias set mine 'task list --assignee @me'.")
def alias_set(
    ctx: typer.Context,
    name: str = typer.Argument(..., metavar="НАЗВАНИЕ", help="Имя алиаса"),
    expansion: str = typer.Argument(
        ..., metavar="КОМАНДА", help="Команда, в которую он разворачивается"
    ),
) -> None:
    app_ctx = get_ctx(ctx)
    alias = name.strip()
    if not alias:
        raise ValidationError("Не указано имя алиаса.")
    if alias in _core_commands(ctx):
        raise ValidationError(
            f"«{alias}» — встроенная команда, алиас с таким именем невозможен.",
            hint="Выберите другое имя.",
        )
    body = expansion.strip()
    if not body:
        raise ValidationError("Пустой алиас: укажите команду, в которую он разворачивается.")
    set_alias(alias, body)
    _say(app_ctx, f"✓ Алиас «{alias}» → «{body}»")
    if app_ctx.out.machine_readable:
        app_ctx.emit({"name": alias, "expansion": body})


@alias_app.command("delete", help="Удалить алиас.")
def alias_delete(
    ctx: typer.Context,
    name: str = typer.Argument(..., metavar="НАЗВАНИЕ", help="Имя алиаса"),
    yes: bool = _YES_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    alias = name.strip()
    aliases = list_aliases()
    if alias not in aliases:
        raise ConfigError(
            f"Алиас «{alias}» не найден.",
            hint=f"Список алиасов: yougile alias list ({settings_path()})",
        )
    _confirm(app_ctx, f"Удалить алиас «{alias}»?", yes)
    delete_alias(alias)
    _say(app_ctx, f"✓ Алиас «{alias}» удалён.")
    if app_ctx.out.machine_readable:
        app_ctx.emit({"name": alias, "expansion": aliases[alias]})


# --------------------------------------------------------------------------- browse


def _board_url(base_url: str, board_id: str, fragment: str | None = None) -> str:
    url = f"{base_url.rstrip('/')}/board/{board_id}"
    return f"{url}#{fragment}" if fragment else url


def _column_board_id(client: YouGileClient, column_id: str) -> str:
    column = client.get(f"{COLUMNS_PATH}/{column_id}")
    board_id = column.get("boardId") if isinstance(column, dict) else None
    if not isinstance(board_id, str) or not board_id:
        raise ValidationError(f"У колонки {column_id} не указана доска.")
    return board_id


def _task_browse_url(app_ctx: AppContext, target: str) -> str:
    """Ссылка на задачу: доска берётся через колонку задачи, якорь — её код."""
    base = host_to_web_url(app_ctx.host)
    ref = parse_task_url(target)
    if ref is not None and ref.board_id:
        if ref.sticker_id:
            return _board_url(base, ref.board_id, f"sticker-{ref.sticker_id}")
        return _board_url(base, ref.board_id, ref.task_code or ref.task_id)

    client = app_ctx.client()
    task_id = resolve_task_id(client, target)
    task = client.get(f"{TASKS_PATH}/{task_id}")
    column_id = task.get("columnId") if isinstance(task, dict) else None
    if not isinstance(column_id, str) or not column_id:
        raise ValidationError("Задача не лежит ни в одной колонке, ссылку построить нельзя.")
    board_id = _column_board_id(client, column_id)
    code = task.get("idTaskProject") or task.get("idTaskCommon") or task_id
    return _board_url(base, board_id, str(code))


def _project_browse_url(app_ctx: AppContext, target: str) -> str:
    """У проекта нет своей страницы — открываем его первую доску."""
    client = app_ctx.client()
    project_id = resolve_project_id(client, target)
    boards = client.collect(BOARDS_PATH, {"projectId": project_id}, max_items=1)
    if not boards:
        raise ValidationError(
            f"В проекте «{target}» нет ни одной доски.",
            hint="Откройте конкретную доску: yougile browse <доска> --board.",
        )
    return _board_url(host_to_web_url(app_ctx.host), str(boards[0].get("id")))


def browse_cmd(
    ctx: typer.Context,
    target: str | None = typer.Argument(
        None, metavar="ЦЕЛЬ", help="Задача, доска, проект или ссылка; без цели — корень хоста"
    ),
    as_task: bool = typer.Option(False, "--task", "-t", help="Считать цель задачей"),
    as_board: bool = typer.Option(False, "--board", "-b", help="Считать цель доской"),
    as_project: bool = typer.Option(False, "--project", "-p", help="Считать цель проектом"),
    no_browser: bool = typer.Option(
        False, "--no-browser", "-n", help="Напечатать ссылку, не открывая браузер"
    ),
) -> None:
    """Открыть задачу, доску или проект в браузере."""
    app_ctx = get_ctx(ctx)
    if sum((as_task, as_board, as_project)) > 1:
        raise ValidationError("Укажите только один из флагов --task, --board или --project.")

    text = (target or "").strip()
    if not text:
        url = host_to_web_url(app_ctx.host).rstrip("/")
    elif text.startswith(("http://", "https://")) and parse_task_url(text) is None:
        url = text
    elif as_project:
        url = _project_browse_url(app_ctx, text)
    elif as_board:
        url = _board_url(host_to_web_url(app_ctx.host), resolve_board_id(app_ctx.client(), text))
    elif as_task or TASK_CODE_RE.match(text) or parse_task_url(text) is not None:
        url = _task_browse_url(app_ctx, text)
    else:
        url = _board_url(host_to_web_url(app_ctx.host), resolve_board_id(app_ctx.client(), text))

    if no_browser or app_ctx.out.machine_readable:
        if app_ctx.out.machine_readable:
            app_ctx.emit({"url": url})
        else:
            _echo(app_ctx, url)
        return
    _say(app_ctx, f"Открываю {url}")
    typer.launch(url)


# --------------------------------------------------------------------------- status


def _board_title(client: YouGileClient, board_id: str, cache: dict[str, str]) -> str:
    if board_id not in cache:
        board = client.get(f"{BOARDS_PATH}/{board_id}")
        title = board.get("title") if isinstance(board, dict) else None
        cache[board_id] = str(title) if title else board_id
    return cache[board_id]


def _column_info(
    client: YouGileClient, column_id: str, cache: dict[str, dict[str, str]]
) -> dict[str, str]:
    if column_id not in cache:
        column = client.get(f"{COLUMNS_PATH}/{column_id}")
        data = column if isinstance(column, dict) else {}
        cache[column_id] = {
            "title": str(data.get("title") or ""),
            "boardId": str(data.get("boardId") or ""),
        }
    return cache[column_id]


def status_cmd(
    ctx: typer.Context,
    limit: int = _LIMIT_OPT,
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    """Мои незакрытые задачи, сгруппированные по доскам."""
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq, "assigned-task")
    client = app_ctx.client()
    user_id = resolve_user_id(client, "@me")

    cap = _max_items(limit)
    boards: dict[str, str] = {}
    columns: dict[str, dict[str, str]] = {}
    rows: list[dict[str, Any]] = []

    for task in client.paginate(TASK_LIST_PATH, {"assignedTo": user_id}):
        if task.get("completed") or task.get("archived") or task.get("deleted"):
            continue
        column_id = task.get("columnId")
        board_id = ""
        column_title = ""
        if isinstance(column_id, str) and column_id:
            info = _column_info(client, column_id, columns)
            column_title = info["title"]
            board_id = info["boardId"]
        rows.append(
            {
                "id": task.get("id"),
                "code": task.get("idTaskProject") or task.get("idTaskCommon") or "",
                "title": task.get("title"),
                "board": _board_title(client, board_id, boards) if board_id else "",
                "boardId": board_id,
                "column": column_title,
                "deadline": (task.get("deadline") or {}).get("deadline"),
            }
        )
        if cap is not None and len(rows) >= cap:
            break

    if app_ctx.out.machine_readable:
        app_ctx.emit(rows, columns=["code", "title", "board", "column"])
        return
    if not rows:
        _say(app_ctx, "Нет незакрытых задач на вас.")
        return
    if app_ctx.quiet:
        return

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["board"] or "Без доски"), []).append(row)

    width = max(len(str(row["code"])) for row in rows)
    for board, items in grouped.items():
        app_ctx.console.print(
            sanitize_terminal_text(f"\n{board}"), style="bold", markup=False, highlight=False
        )
        for row in items:
            code = str(row["code"]).ljust(width)
            column = f"  ({row['column']})" if row["column"] else ""
            app_ctx.console.print(
                sanitize_terminal_text(f"  {code}  {row['title']}{column}"),
                markup=False,
                highlight=False,
            )


# --------------------------------------------------------------------------- version


def version_cmd(ctx: typer.Context) -> None:
    """Показать версию CLI и окружения."""
    app_ctx = get_ctx(ctx)
    python = platform.python_version()
    system = f"{platform.system().lower()} {platform.machine()}"
    if app_ctx.out.machine_readable:
        app_ctx.emit({"version": __version__, "python": python, "platform": system})
        return
    _echo(app_ctx, f"yougile version {__version__}")
    _echo(app_ctx, f"python {python} ({system})")
