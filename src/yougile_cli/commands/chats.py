"""`yougile chat` — групповые чаты, история сообщений и сами сообщения."""

from __future__ import annotations

import html
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import typer

from ..attachments import Attachment, absolute_url, filename_from_url, from_message, strip_preview
from ..client import YouGileClient
from ..context import AppContext, get_ctx
from ..editor import open_editor
from ..errors import (
    AmbiguousNameError,
    CancelledError,
    ResolveError,
    ValidationError,
    not_specified_message,
    single_name,
)
from ..htmltext import html_to_text
from ..output import OutputFormat, is_tty, target_label
from ..resolve import extract_id_from_url, is_uuid, resolve_one, resolve_task_id, resolve_user_id

__all__ = ["app", "message_app"]

CHATS_PATH = "/api-v2/group-chats"

DEFAULT_LIMIT = 30
LIST_COLUMNS = ["id", "title"]
MESSAGE_COLUMNS = ["id", "fromUserId", "text", "label", "editTimestamp"]

# Chat messages carry files as the service form `/root/#file:<url-encoded path>`,
# which renders as gibberish; in table mode it becomes «📎 имя файла».
ATTACHMENT_MARK = "\U0001f4ce "
ATTACHMENTS_HEADER = "ВЛОЖЕНИЯ"
_FILE_TOKEN_RE = re.compile(r"""\S*#file:([^\s"'<>]+)""")

# The exact set PUT /chats/{chatId}/messages/{id} accepts — anything else is rejected.
REACTIONS = ("👍", "👎", "👏", "🙂", "😀", "😕", "🎉", "❤", "🚀", "✔")

DEFAULT_ROLE = "user"
# users/userRoleMap/roleConfigMap are all required on create, so the CLI ships defaults:
# every named employee gets `user` unless a role is spelled out, and any unknown role
# falls back to the `user` permissions below.
ROLE_CONFIGS: dict[str, dict[str, bool]] = {
    "owner": {
        "editProperties": True,
        "editAdmins": True,
        "editUsers": True,
        "sendMessages": True,
        "removeMessages": True,
    },
    "admin": {
        "editProperties": True,
        "editAdmins": True,
        "editUsers": True,
        "sendMessages": True,
        "removeMessages": True,
    },
    "user": {
        "editProperties": False,
        "editAdmins": False,
        "editUsers": True,
        "sendMessages": True,
        "removeMessages": False,
    },
}

app = typer.Typer(
    no_args_is_help=True,
    help="Чаты: список, просмотр, создание, изменение, удаление, история и отправка сообщений.",
)
message_app = typer.Typer(
    no_args_is_help=True,
    help="Сообщения чата: просмотр, быстрая ссылка, реакции, удаление.",
)
app.add_typer(message_app, name="message")

# --------------------------------------------------------------------------- shared flags

_CHAT_ARG = typer.Argument(..., metavar="ЧАТ", help="Чат: ID, имя или ссылка")
_TARGET_ARG = typer.Argument(
    ..., metavar="ЧАТ", help="Чат или задача: ID, код задачи, имя или ссылка"
)
_MESSAGE_ARG = typer.Argument(..., metavar="ID", help="ID сообщения (число)")
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
_INCLUDE_DELETED_OPT = typer.Option(False, "--include-deleted", help="Показывать удалённые")
_YES_OPT = typer.Option(False, "--yes", "-y", help="Не спрашивать подтверждение")
_LABEL_OPT = typer.Option(None, "--label", "-l", metavar="ТЕКСТ", help="Быстрая ссылка сообщения")
_USER_OPT = typer.Option(
    None,
    "--user",
    "-u",
    metavar="СОТРУДНИК",
    help=f"Участник в формате «сотрудник[=роль]» (ID, e-mail или имя; роль — {DEFAULT_ROLE})",
)
_NOTIFY_OPT = typer.Option(
    True, "--notify/--no-notify", help="Включить участникам уведомления чата"
)


def _apply_output(app_ctx: AppContext, json_fields: str | None, jq: str | None) -> None:
    """`--json ПОЛЯ` и `--jq` живут на команде, а не на корневом приложении."""
    if json_fields is not None:
        app_ctx.out.json_fields = [name.strip() for name in json_fields.split(",") if name.strip()]
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


def _messages_path(chat_id: str) -> str:
    return f"/api-v2/chats/{chat_id}/messages"


def _group_chat_id(client: YouGileClient, value: str) -> str:
    return resolve_one(client, path=CHATS_PATH, value=value, kind="чат")


def _chat_target_id(client: YouGileClient, value: str) -> str:
    """A task id is a valid chatId too, so fall back to the task lookup by name or code."""
    text = (value or "").strip()
    if not text:
        raise ResolveError(not_specified_message("чат"))
    if is_uuid(text):
        return text
    target = extract_id_from_url(text)
    if target is not None:
        if target.is_id:
            return target.value
        # The link carried a task code (`…/team/…/#ILS-343`), not an id: the whole
        # link goes to the task resolver, which knows the board-scoped shortcut.
        return resolve_task_id(client, text)
    try:
        return _group_chat_id(client, text)
    except AmbiguousNameError:
        raise
    except ResolveError:
        return resolve_task_id(client, text)


def _parse_since(value: str) -> int:
    """`--since` принимает timestamp или ISO-дату; API ждёт миллисекунды."""
    text = value.strip()
    if text.isdigit():
        return int(text)
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError(
            f"Не удалось разобрать дату «{value}».",
            hint="Используйте ISO-формат (2024-05-01 или 2024-05-01T10:30) либо timestamp.",
        ) from exc
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return int(moment.timestamp() * 1000)


def _default_html(text: str) -> str:
    return "<p>" + html.escape(text).replace("\n", "<br>") + "</p>"


def _read_body(
    body: str | None,
    body_file: str | None,
    editor: bool,
    *,
    app_ctx: AppContext | None = None,
) -> str:
    """Текст сообщения: аргумент, файл (`-` — stdin) или $EDITOR."""
    if body is not None and body_file is not None:
        raise ValidationError("Укажите либо текст сообщения, либо --body-file, но не оба.")

    text = body
    if body_file is not None:
        if body_file == "-":
            text = sys.stdin.read()
        else:
            path = Path(body_file)
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise ValidationError(f"не удалось прочитать файл «{body_file}»: {exc}") from exc

    if editor:
        # $EDITOR is interactive by nature: refuse it when prompts are off.
        if app_ctx is None or not app_ctx.prompt_enabled or not is_tty(sys.stdin):
            raise ValidationError(
                "Отключены интерактивные вопросы, редактор открыть нельзя.",
                hint="Передайте текст аргументом или через --body-file.",
            )
        edited = open_editor(text or "")
        if edited is None:
            raise CancelledError("Сообщение не сохранено.")
        text = edited

    if text is None:
        raise ValidationError(
            "Нужен текст сообщения.",
            hint="Передайте его аргументом, через --body-file или --editor.",
        )
    text = text.strip("\n")
    if not text.strip():
        raise ValidationError("Пустое сообщение отправить нельзя.")
    return text


def _membership(
    client: YouGileClient,
    users: list[str] | None,
    notified: bool,
) -> tuple[dict[str, Any], dict[str, str], dict[str, dict[str, bool]]]:
    """Собрать users / userRoleMap / roleConfigMap из повторяемого `--user сотрудник=роль`."""
    members: dict[str, Any] = {}
    roles: dict[str, str] = {}
    for raw in users or []:
        value, sep, role = raw.partition("=")
        value = value.strip()
        role = role.strip() if sep else ""
        if not value:
            raise ValidationError(f"Ожидался формат сотрудник[=роль], получено «{raw}».")
        user_id = resolve_user_id(client, value)
        members[user_id] = {"notified": notified}
        roles[user_id] = role or DEFAULT_ROLE

    role_config = {
        "admin": ROLE_CONFIGS["admin"],
        DEFAULT_ROLE: ROLE_CONFIGS[DEFAULT_ROLE],
    }
    for role in roles.values():
        role_config[role] = ROLE_CONFIGS.get(role, ROLE_CONFIGS[DEFAULT_ROLE])
    return members, roles, role_config


# --------------------------------------------------------------------------- messages view


def _readable_text(value: Any, host: str) -> Any:
    """Текст сообщения для таблицы: без HTML и без служебной формы `#file:`."""
    if not isinstance(value, str) or not value:
        return value
    text = html_to_text(value)

    def replace(match: re.Match[str]) -> str:
        url = absolute_url(unquote(match.group(1)), host)
        return ATTACHMENT_MARK + filename_from_url(url)

    return _FILE_TOKEN_RE.sub(replace, text)


def _message_attachments(message: dict[str, Any], host: str) -> list[Attachment]:
    """Файлы одного сообщения: и служебная форма, и ссылки из HTML-версии."""
    found: list[Attachment] = []
    seen: set[str] = set()
    for key in ("text", "textHtml"):
        value = message.get(key)
        if not isinstance(value, str):
            continue
        for item in from_message(value, host):
            if item.url in seen:
                continue
            seen.add(item.url)
            found.append(item)
    return found


def _humanize_messages(
    items: list[dict[str, Any]], host: str
) -> tuple[list[dict[str, Any]], list[tuple[Any, Attachment]]]:
    """Табличный вид истории: читаемый текст плюс список вложений со ссылками."""
    rows: list[dict[str, Any]] = []
    attachments: list[tuple[Any, Attachment]] = []
    for message in items:
        if not isinstance(message, dict):
            rows.append(message)
            continue
        row = dict(message)
        row["text"] = _readable_text(row.get("text"), host)
        rows.append(row)
        attachments.extend(
            (message.get("id"), item) for item in _message_attachments(message, host)
        )
    return rows, attachments


def _print_attachments(app_ctx: AppContext, attachments: list[tuple[Any, Attachment]]) -> None:
    """Ссылки печатаются отдельным блоком: в ячейку таблицы они не помещаются."""
    if not attachments:
        return
    console = app_ctx.console
    console.print("")
    console.print(ATTACHMENTS_HEADER, style="bold", markup=False, highlight=False, crop=False)
    width = max(len(str(message_id)) for message_id, _ in attachments)
    for message_id, item in attachments:
        console.print(
            f"{str(message_id).ljust(width)}  {ATTACHMENT_MARK}{item.name}  "
            # Without `previews[]` the link answers with the original, not a 480×480 preview.
            f"{strip_preview(item.url)}",
            markup=False,
            highlight=False,
            crop=False,
            overflow="ignore",
        )


# --------------------------------------------------------------------------- chats


@app.command("list", help="Список групповых чатов.")
def list_chats(
    ctx: typer.Context,
    search: str | None = typer.Option(
        None, "--search", "-S", metavar="ТЕКСТ", help="Искать по имени чата"
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
    if include_deleted:
        params["includeDeleted"] = True

    items = client.collect(CHATS_PATH, params, max_items=_max_items(limit))
    columns = [*LIST_COLUMNS, "deleted"] if include_deleted else LIST_COLUMNS
    app_ctx.emit(items, columns=columns)


@app.command("view", help="Показать чат.")
def view_chat(
    ctx: typer.Context,
    chat: str = _CHAT_ARG,
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    client = app_ctx.client()
    chat_id = _group_chat_id(client, chat)
    app_ctx.emit(client.get(f"{CHATS_PATH}/{chat_id}"))


@app.command("create", help="Создать групповой чат.")
def create_chat(
    ctx: typer.Context,
    name: str | None = typer.Argument(None, metavar="НАЗВАНИЕ", help="Имя нового чата"),
    title: str | None = typer.Option(
        None, "--title", "-t", metavar="НАЗВАНИЕ", help="Имя нового чата (то же, что аргумент)"
    ),
    users: list[str] | None = _USER_OPT,
    notified: bool = _NOTIFY_OPT,
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    chat_title = single_name(
        name, title, genitive="чата", hint="Передайте его аргументом НАЗВАНИЕ или через --title."
    )
    if not users:
        raise ValidationError(
            "Укажите хотя бы одного участника.",
            hint="Добавьте --user СОТРУДНИК[=роль].",
        )

    client = app_ctx.client()
    members, roles, role_config = _membership(client, users, notified)
    payload = {
        "title": chat_title,
        "users": members,
        "userRoleMap": roles,
        "roleConfigMap": role_config,
    }
    app_ctx.emit(client.post(CHATS_PATH, payload))


@app.command("edit", help="Изменить чат.")
def edit_chat(
    ctx: typer.Context,
    chat: str = _CHAT_ARG,
    title: str | None = typer.Option(
        None, "--title", "-t", metavar="НАЗВАНИЕ", help="Новое имя чата"
    ),
    users: list[str] | None = _USER_OPT,
    notified: bool = _NOTIFY_OPT,
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    if title is None and not users:
        raise ValidationError("Нечего менять.", hint="Укажите --title или --user.")

    client = app_ctx.client()
    chat_id = _group_chat_id(client, chat)
    payload: dict[str, Any] = {"title": title}
    if users:
        # PUT replaces users/userRoleMap/roleConfigMap wholesale, so merge onto the current state
        # instead of dropping everyone who is not named on the command line.
        current = client.get(f"{CHATS_PATH}/{chat_id}")
        current_data: dict[str, Any] = current if isinstance(current, dict) else {}
        members, roles, role_config = _membership(client, users, notified)
        payload["users"] = {**(current_data.get("users") or {}), **members}
        payload["userRoleMap"] = {**(current_data.get("userRoleMap") or {}), **roles}
        # Roles already configured on the chat (notably "owner") win over the local defaults.
        payload["roleConfigMap"] = {**role_config, **(current_data.get("roleConfigMap") or {})}
    app_ctx.emit(client.put(f"{CHATS_PATH}/{chat_id}", payload))


@app.command("delete", help="Удалить чат.")
def delete_chat(
    ctx: typer.Context,
    chat: str = _CHAT_ARG,
    yes: bool = _YES_OPT,
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    client = app_ctx.client()
    chat_id = _group_chat_id(client, chat)
    _confirm(app_ctx, f"Удалить чат {target_label(chat, chat_id)}?", yes)
    # API has no DELETE for group chats: deleting is a PUT with deleted=true.
    app_ctx.emit(client.put(f"{CHATS_PATH}/{chat_id}", {"deleted": True}))


# --------------------------------------------------------------------------- messages


@app.command("send", help="Отправить сообщение в чат или в задачу.")
def send_message(
    ctx: typer.Context,
    chat: str = _TARGET_ARG,
    body: str | None = typer.Argument(None, metavar="ТЕКСТ", help="Текст сообщения"),
    body_file: str | None = typer.Option(
        None, "--body-file", "-F", metavar="ФАЙЛ", help="Прочитать текст из файла («-» — stdin)"
    ),
    editor: bool = typer.Option(False, "--editor", "-e", help="Написать текст в $EDITOR"),
    text_html: str | None = typer.Option(
        None,
        "--html",
        metavar="ТЕКСТ",
        help="HTML-версия сообщения (по умолчанию — текст в <p>…</p>)",
    ),
    label: str = typer.Option(
        "", "--label", "-l", metavar="ТЕКСТ", help="Быстрая ссылка сообщения"
    ),
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    text = _read_body(body, body_file, editor, app_ctx=app_ctx)

    client = app_ctx.client()
    chat_id = _chat_target_id(client, chat)
    # text, textHtml and label are all required by the API, so fill the missing ones in.
    payload = {
        "text": text,
        "textHtml": text_html if text_html is not None else _default_html(text),
        "label": label,
    }
    app_ctx.emit(client.post(_messages_path(chat_id), payload))


@app.command("messages", help="История сообщений чата или задачи.")
def list_messages(
    ctx: typer.Context,
    chat: str = _TARGET_ARG,
    from_user: str | None = typer.Option(
        None,
        "--from-user",
        metavar="СОТРУДНИК",
        help="Только сообщения этого сотрудника (ID, e-mail, имя или @me)",
    ),
    search: str | None = typer.Option(
        None, "--search", "-S", metavar="ТЕКСТ", help="Искать сообщения с этой подстрокой"
    ),
    label: str | None = _LABEL_OPT,
    since: str | None = typer.Option(
        None, "--since", metavar="ДАТА", help="Сообщения новее даты (ISO или timestamp)"
    ),
    include_system: bool = typer.Option(
        False, "--include-system", help="Включать системные сообщения"
    ),
    include_deleted: bool = _INCLUDE_DELETED_OPT,
    limit: int = _LIMIT_OPT,
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    client = app_ctx.client()
    chat_id = _chat_target_id(client, chat)

    params: dict[str, Any] = {"text": search, "label": label}
    if from_user:
        params["fromUserId"] = resolve_user_id(client, from_user)
    if since:
        params["since"] = _parse_since(since)
    if include_system:
        params["includeSystem"] = True
    if include_deleted:
        params["includeDeleted"] = True

    items = client.collect(_messages_path(chat_id), params, max_items=_max_items(limit))
    columns = [*MESSAGE_COLUMNS, "deleted"] if include_deleted else MESSAGE_COLUMNS
    if app_ctx.out.fmt is not OutputFormat.TABLE or app_ctx.out.machine_readable:
        # Machine-readable output stays exactly what the API answered.
        app_ctx.emit(items, columns=columns)
        return

    # In table mode the history reads like a chat log: the newest message stays at the bottom.
    rows, attachments = _humanize_messages(list(reversed(items)), client.host)
    app_ctx.emit(rows, columns=columns)
    if not app_ctx.quiet:
        _print_attachments(app_ctx, attachments)


@app.command("typing", help="Показать в чате, что вы печатаете.")
def send_typing(
    ctx: typer.Context,
    chat: str = _TARGET_ARG,
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    client = app_ctx.client()
    chat_id = _chat_target_id(client, chat)
    app_ctx.emit(client.post(f"/api-v2/chats/{chat_id}/typing"))


@message_app.command("view", help="Показать сообщение.")
def view_message(
    ctx: typer.Context,
    chat: str = _TARGET_ARG,
    message_id: int = _MESSAGE_ARG,
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    client = app_ctx.client()
    chat_id = _chat_target_id(client, chat)
    app_ctx.emit(client.get(f"{_messages_path(chat_id)}/{message_id}"))


@message_app.command("edit", help="Изменить быструю ссылку или поставить реакцию.")
def edit_message(
    ctx: typer.Context,
    chat: str = _TARGET_ARG,
    message_id: int = _MESSAGE_ARG,
    label: str | None = typer.Option(
        None, "--label", "-l", metavar="ТЕКСТ", help="Новая быстрая ссылка"
    ),
    react: str | None = typer.Option(
        None, "--react", "-r", metavar="РЕАКЦИЯ", help="Реакция, одна из: " + " ".join(REACTIONS)
    ),
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    if label is None and react is None:
        raise ValidationError("Нечего менять.", hint="Укажите --label или --react.")
    if react is not None and react not in REACTIONS:
        raise ValidationError(
            f"Недопустимая реакция «{react}».",
            hint="Допустимые: " + " ".join(REACTIONS) + ".",
        )

    client = app_ctx.client()
    chat_id = _chat_target_id(client, chat)
    payload: dict[str, Any] = {"label": label, "react": react}
    app_ctx.emit(client.put(f"{_messages_path(chat_id)}/{message_id}", payload))


@message_app.command("delete", help="Удалить сообщение.")
def delete_message(
    ctx: typer.Context,
    chat: str = _TARGET_ARG,
    message_id: int = _MESSAGE_ARG,
    yes: bool = _YES_OPT,
    json_fields: str | None = _JSON_OPT,
    jq: str | None = _JQ_OPT,
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    client = app_ctx.client()
    chat_id = _chat_target_id(client, chat)
    _confirm(app_ctx, f"Удалить сообщение {message_id}?", yes)
    # API has no DELETE for chat messages: deleting is a PUT with deleted=true.
    app_ctx.emit(client.put(f"{_messages_path(chat_id)}/{message_id}", {"deleted": True}))
