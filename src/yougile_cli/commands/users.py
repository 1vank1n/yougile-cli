"""`yougile user` — company members: list, view, invite, edit, delete."""

from __future__ import annotations

import sys
from typing import Any

import typer

from ..context import AppContext, emit, get_client, get_ctx
from ..errors import CancelledError, ValidationError
from ..output import OutputOptions, apply_json_fields, is_tty
from ..resolve import ME, resolve_project_id, resolve_user_id

__all__ = ["app"]

USERS_PATH = "/api-v2/users"

LIST_COLUMNS = ["id", "realName", "email", "isAdmin", "messengerOnly", "status", "lastActivity"]

app = typer.Typer(no_args_is_help=True, help="Сотрудники компании")


def _json_option() -> Any:
    return typer.Option(
        None,
        "--json",
        metavar="ПОЛЯ",
        help="Вывести JSON только с указанными полями (через запятую)",
    )


def _jq_option() -> Any:
    return typer.Option(
        None, "-q", "--jq", metavar="ВЫРАЖЕНИЕ", help="Прогнать JSON через фильтр jq"
    )


def _limit_option() -> Any:
    return typer.Option(
        30, "-L", "--limit", metavar="ЧИСЛО", min=0, help="Сколько сотрудников показать (0 — все)"
    )


def _yes_option() -> Any:
    return typer.Option(False, "--yes", "-y", help="Не спрашивать подтверждение")


def _apply_output(
    app_ctx: AppContext,
    json_fields: str | None,
    jq: str | None,
    resource: str | None = "user",
) -> OutputOptions:
    """Merge the per-command output flags into the invocation-wide options."""
    opts = app_ctx.out
    apply_json_fields(opts, json_fields, resource)
    if jq:
        opts.jq = jq
    return opts


def _confirm(app_ctx: AppContext, message: str, *, yes: bool) -> None:
    if yes:
        return
    if not app_ctx.prompt_enabled or not is_tty(sys.stdin):
        raise ValidationError(
            "Требуется подтверждение, но интерактивный ввод недоступен.",
            hint="Повторите команду с флагом --yes.",
        )
    if not typer.confirm(message):
        raise CancelledError()


def single_email(positional: str | None, option: str | None) -> str:
    """`invite ПОЧТА` and `invite --email ПОЧТА` are synonyms; both must agree."""
    if positional is not None and option is not None and positional.strip() != option.strip():
        raise ValidationError(
            f"Почта задана дважды и по-разному: «{positional}» и --email «{option}».",
            hint="Оставьте что-то одно: позиционный аргумент или --email.",
        )
    text = (positional if positional is not None else option) or ""
    if not text.strip():
        raise ValidationError(
            "Не указана почта сотрудника.",
            hint="Например: yougile user invite ivan@example.com",
        )
    return text


def _matches(item: dict[str, Any], needle: str) -> bool:
    haystack = (str(item.get("realName") or ""), str(item.get("email") or ""))
    return any(needle in value.casefold() for value in haystack)


@app.command("list", help="Список сотрудников компании")
def list_users(
    ctx: typer.Context,
    email: str | None = typer.Option(
        None, "--email", metavar="ПОЧТА", help="Фильтр по почте сотрудника"
    ),
    project: str | None = typer.Option(
        None, "--project", metavar="ПРОЕКТ", help="Только участники проекта (ID или название)"
    ),
    search: str | None = typer.Option(
        None, "--search", "-S", metavar="ТЕКСТ", help="Поиск по имени или почте"
    ),
    limit: int = _limit_option(),
    json_fields: str | None = _json_option(),
    jq: str | None = _jq_option(),
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    client = get_client(ctx)

    params: dict[str, Any] = {"email": email}
    if project:
        params["projectId"] = resolve_project_id(client, project)

    # The endpoint has no text search, so `--search` filters the full listing locally.
    max_items = None if (search or not limit) else limit
    items = client.collect(USERS_PATH, params, max_items=max_items)
    if search:
        needle = search.strip().casefold()
        items = [item for item in items if _matches(item, needle)]
        if limit:
            items = items[:limit]

    emit(app_ctx, items, columns=LIST_COLUMNS)


@app.command("view", help="Карточка сотрудника: @me, ID, почта или имя")
def view_user(
    ctx: typer.Context,
    user: str = typer.Argument(ME, metavar="СОТРУДНИК", help="@me, ID, почта или имя сотрудника"),
    json_fields: str | None = _json_option(),
    jq: str | None = _jq_option(),
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    client = get_client(ctx)

    if user.strip().casefold() == ME:
        data = client.get(f"{USERS_PATH}/me")
    else:
        data = client.get(f"{USERS_PATH}/{resolve_user_id(client, user)}")
    emit(app_ctx, data)


@app.command("invite", help="Пригласить сотрудника в компанию")
def invite_user(
    ctx: typer.Context,
    address: str | None = typer.Argument(
        None, metavar="ПОЧТА", help="Почта приглашаемого сотрудника"
    ),
    email: str | None = typer.Option(
        None, "--email", metavar="ПОЧТА", help="Та же почта, но флагом"
    ),
    admin: bool = typer.Option(False, "--admin", help="Выдать права администратора"),
    messenger_only: bool = typer.Option(
        False, "--messenger-only", help="Доступ только к мессенджеру"
    ),
    json_fields: str | None = _json_option(),
    jq: str | None = _jq_option(),
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    client = get_client(ctx)
    body = {
        "email": single_email(address, email),
        "isAdmin": admin,
        "messengerOnly": messenger_only,
    }
    emit(app_ctx, client.post(USERS_PATH, body))


@app.command("edit", help="Изменить права сотрудника")
def edit_user(
    ctx: typer.Context,
    user: str = typer.Argument(..., metavar="СОТРУДНИК", help="@me, ID, почта или имя сотрудника"),
    admin: bool | None = typer.Option(
        None, "--admin/--no-admin", help="Выдать или снять права администратора"
    ),
    messenger_only: bool | None = typer.Option(
        None, "--messenger-only/--no-messenger-only", help="Доступ только к мессенджеру"
    ),
    json_fields: str | None = _json_option(),
    jq: str | None = _jq_option(),
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    client = get_client(ctx)
    if admin is None and messenger_only is None:
        raise ValidationError(
            "Нечего менять.",
            hint="Укажите --admin/--no-admin или --messenger-only/--no-messenger-only.",
        )
    user_id = resolve_user_id(client, user)
    emit(
        app_ctx,
        client.put(f"{USERS_PATH}/{user_id}", {"isAdmin": admin, "messengerOnly": messenger_only}),
    )


@app.command("delete", help="Удалить сотрудника из компании")
def delete_user(
    ctx: typer.Context,
    user: str = typer.Argument(..., metavar="СОТРУДНИК", help="ID, почта или имя сотрудника"),
    yes: bool = _yes_option(),
    json_fields: str | None = _json_option(),
    jq: str | None = _jq_option(),
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields, jq)
    client = get_client(ctx)
    user_id = resolve_user_id(client, user)
    _confirm(app_ctx, f"Удалить сотрудника {user_id} из компании?", yes=yes)
    # Users are one of the three resources with a real DELETE method.
    emit(app_ctx, client.delete(f"{USERS_PATH}/{user_id}"))
