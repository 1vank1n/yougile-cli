"""`yougile auth` — a calque of `gh auth`: login, logout, status, token, switch, refresh.

Plus the YouGile-specific `auth keys` registry, because the API exposes the key
list directly (`POST /api-v2/auth/keys/get`) and an account may hold at most 30
keys.  Every `POST /api-v2/auth/*` call carries login+password in the body and
must go out *without* a bearer token, hence the explicit ``auth=False``.
"""

from __future__ import annotations

import sys
from typing import Any
from urllib.parse import quote

import typer

from ..client import YouGileClient
from ..config import (
    DEFAULT_HOST,
    Host,
    HostUser,
    host_to_base_url,
    hosts_path,
    list_accounts,
    load_hosts,
    login_user,
    logout_user,
    normalize_host,
    switch_user,
)
from ..context import AppContext, get_ctx
from ..errors import (
    LOGIN_HINT,
    AmbiguousNameError,
    ApiError,
    AuthError,
    CancelledError,
    ConfigError,
    ResolveError,
    ValidationError,
)
from ..output import OutputFormat, apply_json_fields, is_tty, sanitize_terminal_text

__all__ = ["app", "keys_app"]

app = typer.Typer(no_args_is_help=True, help="Аутентификация: вход, выход, статус и API-ключи")
keys_app = typer.Typer(no_args_is_help=True, help="Реестр API-ключей аккаунта")
app.add_typer(keys_app, name="keys")

KEY_COLUMNS = ["key", "companyId", "timestamp", "deleted"]
ACCOUNT_COLUMNS = ["host", "email", "real_name", "active", "company_name", "company_id"]

_NO_PROMPT_HINT = "Отключены интерактивные вопросы (config prompt: disabled или не терминал)."


# ------------------------------------------------------------------ shared flags


def _hostname_opt() -> Any:
    return typer.Option(None, "--hostname", metavar="ХОСТ", help="Хост YouGile")


def _user_opt(help_text: str = "Учётная запись (email)") -> Any:
    return typer.Option(None, "--user", "-u", metavar="ПОЧТА", help=help_text)


def _company_opt() -> Any:
    return typer.Option(
        None, "--company", "-c", metavar="КОМПАНИЯ", help="ID или название компании"
    )


def _yes_opt() -> Any:
    return typer.Option(False, "--yes", "-y", help="Не спрашивать подтверждение")


def _json_opt() -> Any:
    return typer.Option(
        None, "--json", metavar="ПОЛЯ", help="Вывести JSON только с указанными полями"
    )


def _jq_opt() -> Any:
    return typer.Option(None, "-q", "--jq", metavar="ВЫРАЖЕНИЕ", help="Прогнать JSON через jq")


def _limit_opt() -> Any:
    return typer.Option(
        30, "-L", "--limit", metavar="ЧИСЛО", min=0, help="Сколько записей вывести; 0 — все"
    )


def _full_ids_opt() -> Any:
    return typer.Option(False, "--full-ids", help="Не сокращать идентификаторы")


def _apply_output(
    app_ctx: AppContext,
    *,
    json_fields: str | None = None,
    jq: str | None = None,
    limit: int | None = None,
    full_ids: bool = False,
    resource: str | None = "api-key",
) -> None:
    """Fold per-command output flags into the invocation-wide OutputOptions."""
    apply_json_fields(app_ctx.out, json_fields, resource)
    if jq:
        app_ctx.out.jq = jq
    if limit is not None:
        app_ctx.out.limit = limit
    if full_ids:
        app_ctx.out.full_ids = True


def _cut(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return rows if limit <= 0 else rows[:limit]


# ------------------------------------------------------------------ prompting


def _can_prompt(app_ctx: AppContext) -> bool:
    """Interactive questions need both an enabled prompt setting and a real tty."""
    if not app_ctx.prompt_enabled or app_ctx.settings.prompt == "disabled":
        return False
    return is_tty(sys.stdin)


def _require_prompt(app_ctx: AppContext, hint: str) -> None:
    if not _can_prompt(app_ctx):
        raise ValidationError(_NO_PROMPT_HINT, hint=hint)


def _ask(app_ctx: AppContext, text: str, *, default: str | None = None, hide: bool = False) -> str:
    _require_prompt(app_ctx, "Передайте значение флагом.")
    value = typer.prompt(text, default=default, hide_input=hide)
    return str(value).strip()


def _confirm(app_ctx: AppContext, message: str, yes: bool) -> None:
    if yes:
        return
    if not _can_prompt(app_ctx):
        raise ValidationError(_NO_PROMPT_HINT, hint="Добавьте флаг --yes.")
    if not typer.confirm(message):
        raise CancelledError()


def _note(app_ctx: AppContext, message: str) -> None:
    """Human-facing line: printed only for the table format so JSON stays parseable."""
    if app_ctx.out.fmt is OutputFormat.TABLE and not app_ctx.quiet:
        app_ctx.console.print(message)


def _report(app_ctx: AppContext, data: Any, message: str, columns: list[str] | None = None) -> None:
    if app_ctx.out.fmt is OutputFormat.TABLE and app_ctx.out.json_fields is None:
        _note(app_ctx, message)
    else:
        app_ctx.emit(data, columns)


# ------------------------------------------------------------------ tokens & hosts


def mask_token(value: str | None, *, show: bool = False) -> str:
    if not value:
        return ""
    if show:
        return value
    if len(value) <= 8:
        return "…"
    # Eight characters wide so the table renderer does not shorten it further.
    return f"{value[:3]}…{value[-4:]}"


def _host_of(app_ctx: AppContext, hostname: str | None) -> str:
    return normalize_host(hostname) or app_ctx.auth.host or DEFAULT_HOST


def _stored_user(host: str, email: str | None) -> tuple[str, HostUser] | None:
    entry: Host | None = load_hosts().get(host)
    if entry is None or not entry.users:
        return None
    if email:
        needle = email.strip().casefold()
        for stored_email, user in entry.users.items():
            if stored_email.casefold() == needle:
                return stored_email, user
        return None
    active = entry.active_user
    if active and active in entry.users:
        return active, entry.users[active]
    first = next(iter(entry.users))
    return first, entry.users[first]


# ------------------------------------------------------------------ api helpers


def _anon(host: str) -> YouGileClient:
    return YouGileClient(api_key=None, base_url=host_to_base_url(host), host=host)


def _fetch_companies(
    client: YouGileClient, login: str, password: str, name: str | None = None
) -> list[dict[str, Any]]:
    body = client.post(
        "/api-v2/auth/companies",
        {"login": login, "password": password, "name": name},
        params={"limit": 1000},
        auth=False,
    )
    content = body.get("content") if isinstance(body, dict) else body
    if not isinstance(content, list):
        return []
    return [item for item in content if isinstance(item, dict)]


def _fetch_keys(
    client: YouGileClient, login: str, password: str, company_id: str | None
) -> list[dict[str, Any]]:
    body = client.post(
        "/api-v2/auth/keys/get",
        {"login": login, "password": password, "companyId": company_id},
        auth=False,
    )
    if isinstance(body, dict):
        body = body.get("content")
    if not isinstance(body, list):
        return []
    return [item for item in body if isinstance(item, dict)]


def _create_key(client: YouGileClient, login: str, password: str, company_id: str) -> str:
    created = client.post(
        "/api-v2/auth/keys",
        {"login": login, "password": password, "companyId": company_id},
        auth=False,
    )
    key = str(created.get("key") or "") if isinstance(created, dict) else ""
    if not key:
        raise ApiError("Сервер не вернул API-ключ.")
    return key


def _match_companies(companies: list[dict[str, Any]], wanted: str) -> list[dict[str, Any]]:
    needle = wanted.strip().casefold()
    by_id = [c for c in companies if str(c.get("id", "")).casefold() == needle]
    if by_id:
        return by_id
    exact = [c for c in companies if str(c.get("name", "")).casefold() == needle]
    if exact:
        return exact
    return [c for c in companies if needle in str(c.get("name", "")).casefold()]


def _choose_company(
    app_ctx: AppContext, companies: list[dict[str, Any]], wanted: str | None
) -> dict[str, Any]:
    if not companies:
        raise ResolveError("У этого аккаунта нет доступных компаний.")
    if wanted:
        matches = _match_companies(companies, wanted)
        if not matches:
            raise ResolveError(f"Компания «{wanted}» не найдена.")
        if len(matches) > 1:
            raise AmbiguousNameError(
                f"Найдено несколько компаний по запросу «{wanted}».",
                hint="Уточните название или укажите ID компании.",
                candidates=[{"id": c.get("id", ""), "title": c.get("name", "")} for c in matches],
            )
        return matches[0]
    if len(companies) == 1:
        return companies[0]
    _require_prompt(app_ctx, "Укажите компанию флагом --company.")
    app_ctx.console.print("Доступные компании:")
    for index, company in enumerate(companies, start=1):
        app_ctx.console.print(
            sanitize_terminal_text(
                f"  {index}. {company.get('name', '')} ({company.get('id', '')})"
            ),
            markup=False,
            highlight=False,
        )
    number = typer.prompt("Номер компании", type=int)
    if not 1 <= number <= len(companies):
        raise ValidationError(f"Нет компании с номером {number}.")
    return companies[number - 1]


def _fetch_me(client: YouGileClient) -> dict[str, Any]:
    me = client.get("/api-v2/users/me")
    if not isinstance(me, dict):
        raise ApiError("Сервер вернул неожиданный ответ на /api-v2/users/me.")
    return me


def _fetch_company(client: YouGileClient) -> dict[str, Any]:
    """Details of the company the key belongs to; the path's companyId part is optional."""
    try:
        company = client.get("/api-v2/companies")
    except ApiError:
        return {}
    return company if isinstance(company, dict) else {}


def _store(
    host: str,
    api_key: str,
    me: dict[str, Any],
    company: dict[str, Any],
    *,
    make_active: bool = True,
) -> HostUser:
    email = str(me.get("email") or "").strip()
    if not email:
        raise ApiError("Сервер не вернул email пользователя — нечего сохранять.")
    user = HostUser(
        api_key=api_key,
        user_id=str(me.get("id") or "") or None,
        real_name=str(me.get("realName") or "") or None,
        email=email,
        company_id=str(company.get("id") or "") or None,
        company_name=str(company.get("title") or company.get("name") or "") or None,
    )
    login_user(host, user, make_active=make_active)
    return user


def _verify_and_store(host: str, api_key: str, *, make_active: bool = True) -> HostUser:
    """Check the key with GET /api-v2/users/me, then write it to hosts.yml."""
    with YouGileClient(api_key=api_key, base_url=host_to_base_url(host), host=host) as client:
        me = _fetch_me(client)
        company = _fetch_company(client)
    return _store(host, api_key, me, company, make_active=make_active)


def _read_stdin_token() -> str:
    token = sys.stdin.read().strip()
    if not token:
        raise ValidationError(
            "Пустой ввод: API-ключ не передан.",
            hint="Пример: echo КЛЮЧ | yougile auth login --with-token",
        )
    return token.splitlines()[0].strip()


def _success_line(user: HostUser) -> str:
    name = user.real_name or user.email or ""
    return f"[green]✓[/green] Вход выполнен как {name} ({user.email})"


# ------------------------------------------------------------------ login


@app.command("login", help="Войти в аккаунт YouGile и сохранить API-ключ")
def login_command(
    ctx: typer.Context,
    hostname: str | None = _hostname_opt(),
    with_token: bool = typer.Option(
        False, "--with-token", help="Прочитать готовый API-ключ из stdin"
    ),
    company: str | None = _company_opt(),
    user: str | None = _user_opt("Email для входа"),
    new_key: bool = typer.Option(
        False, "--new-key", help="Всегда создавать новый ключ, не переиспользуя существующий"
    ),
) -> None:
    app_ctx = get_ctx(ctx)
    host = normalize_host(hostname) or ""

    if with_token:
        host = host or app_ctx.auth.host or DEFAULT_HOST
        stored = _verify_and_store(host, _read_stdin_token())
        _report(
            app_ctx,
            {"host": host, "email": stored.email, "real_name": stored.real_name},
            _success_line(stored),
        )
        return

    if not _can_prompt(app_ctx):
        raise ValidationError(
            _NO_PROMPT_HINT,
            hint="Передайте ключ: echo КЛЮЧ | yougile auth login --with-token",
        )

    # Flags switch the command into a non-interactive login: only the password is asked.
    interactive = user is None and company is None
    if not host:
        host = (
            normalize_host(_ask(app_ctx, "Хост", default=DEFAULT_HOST))
            if interactive
            else app_ctx.auth.host or DEFAULT_HOST
        )

    use_password = True
    if interactive:
        choice = typer.prompt(
            "Как авторизоваться? 1 — логин и пароль, 2 — готовый API-ключ", default="1"
        )
        use_password = str(choice).strip() != "2"

    if not use_password:
        api_key = typer.prompt("API-ключ", hide_input=True).strip()
        if not api_key:
            raise ValidationError("Пустой API-ключ.")
        stored = _verify_and_store(host, api_key)
        _report(
            app_ctx,
            {"host": host, "email": stored.email, "real_name": stored.real_name},
            _success_line(stored),
        )
        return

    email = (user or "").strip() or _ask(app_ctx, "Email")
    password = _ask(app_ctx, "Пароль", hide=True)

    with _anon(host) as anon:
        chosen = _choose_company(app_ctx, _fetch_companies(anon, email, password), company)
        company_id = str(chosen.get("id") or "")
        api_key = ""
        if not new_key:
            # Reusing a live key keeps the account under the 30-keys-per-account limit.
            live = [
                item
                for item in _fetch_keys(anon, email, password, company_id)
                if not item.get("deleted") and str(item.get("companyId") or "") == company_id
            ]
            if live:
                api_key = str(live[0].get("key") or "")
        reused = bool(api_key)
        if not api_key:
            api_key = _create_key(anon, email, password, company_id)

    with YouGileClient(api_key=api_key, base_url=host_to_base_url(host), host=host) as client:
        me = _fetch_me(client)
    company_payload = {"id": company_id, "title": chosen.get("name")}
    stored = _store(host, api_key, me, company_payload)

    _report(
        app_ctx,
        {
            "host": host,
            "email": stored.email,
            "real_name": stored.real_name,
            "company_id": company_id,
            "company_name": stored.company_name,
            "reused_key": reused,
        },
        _success_line(stored),
    )


# ------------------------------------------------------------------ logout


@app.command("logout", help="Удалить сохранённую учётную запись")
def logout_command(
    ctx: typer.Context,
    hostname: str | None = _hostname_opt(),
    user: str | None = _user_opt(),
    yes: bool = _yes_opt(),
) -> None:
    app_ctx = get_ctx(ctx)
    host = _host_of(app_ctx, hostname)
    found = _stored_user(host, user)
    if found is None:
        target = f" «{user}»." if user else "."
        raise ConfigError(f"На {host} нет сохранённой учётной записи{target}", hint=LOGIN_HINT)
    email, _stored = found
    _confirm(app_ctx, f"Удалить учётную запись {email} на {host}?", yes)
    logout_user(host, email)
    _report(
        app_ctx,
        {"host": host, "email": email, "logged_out": True},
        f"[green]✓[/green] Выход выполнен: {email} на {host}",
    )


# ------------------------------------------------------------------ status


def _status_rows(host: str | None, active_only: bool) -> list[dict[str, Any]]:
    rows = list_accounts()
    if host:
        rows = [row for row in rows if row["host"] == host]
    if active_only:
        rows = [row for row in rows if row["active"]]
    return rows


def _unstored_key_row(app_ctx: AppContext) -> dict[str, Any]:
    """A key from --token / YOUGILE_TOKEN carries no identity, so the server names it.

    Without the check `auth status` would print a green tick for any garbage
    string and the user would meet the real failure only on the next command.
    """
    client = app_ctx.client()
    me = _fetch_me(client)
    company = _fetch_company(client)
    return {
        "host": app_ctx.auth.host,
        "email": str(me.get("email") or "") or app_ctx.auth.user_email,
        "active": True,
        "user_id": str(me.get("id") or "") or app_ctx.auth.user_id,
        "real_name": str(me.get("realName") or "") or app_ctx.auth.real_name,
        "company_id": str(company.get("id") or "") or app_ctx.auth.company_id,
        "company_name": str(company.get("title") or "") or app_ctx.auth.company_name,
        "api_key": app_ctx.auth.api_key,
        "source": app_ctx.auth.source,
    }


@app.command("status", help="Показать состояние аутентификации")
def status_command(
    ctx: typer.Context,
    hostname: str | None = _hostname_opt(),
    show_token: bool = typer.Option(False, "--show-token", "-t", help="Показать ключ целиком"),
    active: bool = typer.Option(False, "--active", help="Только активная учётная запись"),
) -> None:
    app_ctx = get_ctx(ctx)
    host = normalize_host(hostname) or None
    rows = _status_rows(host, active)

    if not rows and app_ctx.auth.authenticated and (host is None or host == app_ctx.auth.host):
        # Key came from a flag or the environment: report it the way gh does.
        rows = [_unstored_key_row(app_ctx)]

    if not rows:
        raise AuthError("Вход не выполнен.", hint=LOGIN_HINT)

    if app_ctx.out.fmt is not OutputFormat.TABLE or app_ctx.out.json_fields is not None:
        payload = [
            {**row, "api_key": mask_token(row.get("api_key"), show=show_token)} for row in rows
        ]
        app_ctx.emit(payload, ACCOUNT_COLUMNS)
        return

    console = app_ctx.console
    path = hosts_path()
    for name in dict.fromkeys(row["host"] for row in rows):
        console.print(name)
        for row in [r for r in rows if r["host"] == name]:
            label = row.get("real_name") or row.get("email") or "—"
            email = row.get("email") or "—"
            console.print(f"  [green]✓[/green] Вход выполнен как {label} ({email})")
            console.print(f"  - Активная учётная запись: {'да' if row.get('active') else 'нет'}")
            company = row.get("company_name") or "—"
            if row.get("company_id"):
                company = f"{company} ({row['company_id']})"
            console.print(f"  - Компания: {company}")
            console.print(f"  - Токен: {mask_token(row.get('api_key'), show=show_token)}")
            source = row.get("source")
            if source and source not in ("hosts.yml", "none"):
                console.print(f"  - Источник ключа: {source}")
            console.print(f"  - Хранилище: {path}")


# ------------------------------------------------------------------ token


@app.command("token", help="Напечатать API-ключ учётной записи")
def token_command(
    ctx: typer.Context,
    hostname: str | None = _hostname_opt(),
    user: str | None = _user_opt(),
) -> None:
    app_ctx = get_ctx(ctx)
    host = _host_of(app_ctx, hostname)
    found = _stored_user(host, user)
    if found is not None:
        typer.echo(found[1].api_key)
        return
    if user is None and app_ctx.auth.authenticated and app_ctx.auth.host == host:
        typer.echo(app_ctx.auth.api_key)
        return
    raise AuthError(f"Вход на {host} не выполнен.", hint=LOGIN_HINT)


# ------------------------------------------------------------------ switch


@app.command("switch", help="Переключиться на другую сохранённую учётную запись")
def switch_command(
    ctx: typer.Context,
    hostname: str | None = _hostname_opt(),
    user: str | None = _user_opt(),
) -> None:
    app_ctx = get_ctx(ctx)
    host = _host_of(app_ctx, hostname)
    entry = load_hosts().get(host)
    if entry is None or not entry.users:
        raise ConfigError(f"На {host} нет сохранённых учётных записей.", hint=LOGIN_HINT)

    email = (user or "").strip()
    if not email:
        candidates = [name for name in entry.users if name != entry.active_user]
        if len(candidates) == 1:
            email = candidates[0]
        elif not candidates:
            raise ConfigError(
                f"На {host} только одна учётная запись — переключаться не на что.",
                hint=LOGIN_HINT,
            )
        else:
            _require_prompt(app_ctx, "Укажите учётную запись флагом --user.")
            app_ctx.console.print(f"Учётные записи на {host}:")
            for index, name in enumerate(candidates, start=1):
                app_ctx.console.print(f"  {index}. {name}")
            number = typer.prompt("Номер учётной записи", type=int)
            if not 1 <= number <= len(candidates):
                raise ValidationError(f"Нет учётной записи с номером {number}.")
            email = candidates[number - 1]

    stored = switch_user(host, email)
    _report(
        app_ctx,
        {"host": host, "email": stored.email or email, "active": True},
        f"[green]✓[/green] Активная учётная запись на {host}: {stored.email or email}",
    )


# ------------------------------------------------------------------ refresh


@app.command("refresh", help="Перевыпустить API-ключ активной учётной записи")
def refresh_command(
    ctx: typer.Context,
    hostname: str | None = _hostname_opt(),
) -> None:
    app_ctx = get_ctx(ctx)
    host = _host_of(app_ctx, hostname)
    found = _stored_user(host, None)
    if found is None:
        raise AuthError(f"Вход на {host} не выполнен.", hint=LOGIN_HINT)
    email, stored = found
    if not stored.company_id:
        raise ConfigError(
            f"У учётной записи {email} не сохранена компания.",
            hint=LOGIN_HINT,
        )
    password = _ask(app_ctx, f"Пароль для {email}", hide=True)

    with _anon(host) as anon:
        api_key = _create_key(anon, email, password, stored.company_id)

    fresh = _verify_and_store(host, api_key)
    old_key = stored.api_key
    revoked = False
    if old_key and old_key != api_key:
        # The only real DELETE in the auth namespace; it needs a bearer token.
        with YouGileClient(api_key=api_key, base_url=host_to_base_url(host), host=host) as client:
            try:
                client.delete(f"/api-v2/auth/keys/{quote(old_key, safe='')}")
                revoked = True
            except ApiError:
                revoked = False

    _report(
        app_ctx,
        {
            "host": host,
            "email": fresh.email,
            "key": mask_token(api_key),
            "old_key_revoked": revoked,
        },
        f"[green]✓[/green] Ключ перевыпущен для {fresh.email}: {mask_token(api_key)}"
        + ("" if revoked else "\nСтарый ключ отозвать не удалось — удалите его вручную."),
    )


# ------------------------------------------------------------------ keys


@keys_app.command("list", help="Показать API-ключи аккаунта")
def keys_list_command(
    ctx: typer.Context,
    hostname: str | None = _hostname_opt(),
    user: str | None = _user_opt("Email для входа"),
    company: str | None = _company_opt(),
    include_deleted: bool = typer.Option(
        False, "--include-deleted", help="Показывать также удалённые ключи"
    ),
    show_token: bool = typer.Option(False, "--show-token", "-t", help="Показать ключи целиком"),
    json_fields: str | None = _json_opt(),
    jq: str | None = _jq_opt(),
    limit: int = _limit_opt(),
    full_ids: bool = _full_ids_opt(),
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(
        app_ctx, json_fields=json_fields, jq=jq, limit=limit, full_ids=full_ids or show_token
    )
    host = _host_of(app_ctx, hostname)
    email = (user or "").strip() or _default_email(app_ctx, host)
    password = _ask(app_ctx, "Пароль", hide=True)

    with _anon(host) as anon:
        company_id = _company_id(app_ctx, anon, host, email, password, company)
        keys = _fetch_keys(anon, email, password, company_id)

    if not include_deleted:
        keys = [item for item in keys if not item.get("deleted")]
    if not show_token:
        keys = [{**item, "key": mask_token(str(item.get("key") or ""))} for item in keys]
    app_ctx.emit(_cut(keys, limit), KEY_COLUMNS)


@keys_app.command("create", help="Создать новый API-ключ")
def keys_create_command(
    ctx: typer.Context,
    hostname: str | None = _hostname_opt(),
    user: str | None = _user_opt("Email для входа"),
    company: str | None = _company_opt(),
    json_fields: str | None = _json_opt(),
    jq: str | None = _jq_opt(),
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    host = _host_of(app_ctx, hostname)
    email = (user or "").strip() or _default_email(app_ctx, host)
    password = _ask(app_ctx, "Пароль", hide=True)

    with _anon(host) as anon:
        company_id = _company_id(app_ctx, anon, host, email, password, company, required=True)
        api_key = _create_key(anon, email, password, str(company_id))

    _report(
        app_ctx,
        {"key": api_key, "companyId": company_id},
        f"[green]✓[/green] Ключ создан: {api_key}",
        columns=["key", "companyId"],
    )


UNSAFE_KEY_CHARS = frozenset("/?#%")


def _key_segment(key: str) -> str:
    """A raw CLI string must never widen the path it is interpolated into."""
    value = key.strip()
    if not value or UNSAFE_KEY_CHARS & set(value) or any(ch.isspace() for ch in value):
        raise ValidationError(
            f"Недопустимый API-ключ «{key}».",
            hint="Ключ — одна строка без пробелов и символов «/», «?», «#», «%».",
        )
    return quote(value, safe="")


@keys_app.command("delete", help="Удалить API-ключ")
def keys_delete_command(
    ctx: typer.Context,
    key: str = typer.Argument(..., metavar="КЛЮЧ", help="Значение ключа"),
    hostname: str | None = _hostname_opt(),
    yes: bool = _yes_opt(),
    json_fields: str | None = _json_opt(),
    jq: str | None = _jq_opt(),
) -> None:
    app_ctx = get_ctx(ctx)
    _apply_output(app_ctx, json_fields=json_fields, jq=jq)
    host = _host_of(app_ctx, hostname)
    _confirm(app_ctx, f"Удалить API-ключ {mask_token(key)}?", yes)
    # One of the three endpoints with a real DELETE (elsewhere delete is PUT deleted=true).
    app_ctx.client().delete(f"/api-v2/auth/keys/{_key_segment(key)}")
    found = _stored_user(host, None)
    if found is not None and found[1].api_key == key:
        logout_user(host, found[0])
    _report(
        app_ctx,
        {"key": mask_token(key), "deleted": True},
        f"[green]✓[/green] Ключ {mask_token(key)} удалён.",
        columns=["key", "deleted"],
    )


def _default_email(app_ctx: AppContext, host: str) -> str:
    found = _stored_user(host, None)
    if found is not None:
        return found[0]
    return _ask(app_ctx, "Email")


def _company_id(
    app_ctx: AppContext,
    client: YouGileClient,
    host: str,
    login: str,
    password: str,
    wanted: str | None,
    *,
    required: bool = False,
) -> str | None:
    if wanted is None and not required:
        stored = _stored_user(host, None)
        return stored[1].company_id if stored is not None else None
    companies = _fetch_companies(client, login, password)
    return str(_choose_company(app_ctx, companies, wanted).get("id") or "")
