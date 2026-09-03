"""`yougile api` — the escape hatch, modelled on `gh api`.

Anything the typed commands do not cover can be reached from here: the
endpoint is normalised (``task-list``, ``/task-list`` and ``/api-v2/task-list``
are the same request), fields are collected gh-style with ``-f``/``-F``, and
``--paginate`` walks ``paging.offset`` gluing the ``content`` arrays together.

The body is always sent as pre-serialised JSON so that an explicit
``-F key=null`` survives: the client strips ``None`` out of ``json=`` bodies.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Any

import typer

from ..client import MAX_PAGE_LIMIT, YouGileClient, merged_envelope
from ..context import AppContext, get_ctx
from ..errors import ValidationError
from ..output import OutputFormat, render
from ..resolve import parse_field_pairs, parse_kv_options

__all__ = ["api_cmd", "normalize_endpoint"]

API_PREFIX = "/api-v2"
AUTH_PREFIX = "/api-v2/auth/"
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")

HELP = """Произвольный запрос к API YouGile.

Путь можно писать как `task-list`, `/task-list` или `/api-v2/task-list`.
Метод по умолчанию GET; если задано тело — POST.
"""


def normalize_endpoint(endpoint: str, *, company_id: str | None = None) -> str:
    """`task-list`, `/task-list` and `/api-v2/task-list` all mean the same path."""
    text = (endpoint or "").strip()
    if not text:
        raise ValidationError("Не указан эндпоинт.", hint="Например: yougile api task-list")
    if "{company}" in text:
        if not company_id:
            raise ValidationError(
                "В пути есть {company}, но компания неизвестна.",
                hint="Выполните: yougile auth login",
            )
        text = text.replace("{company}", company_id)
    if text.startswith(("http://", "https://")):
        return text
    if not text.startswith("/"):
        text = f"/{text}"
    if text != API_PREFIX and not text.startswith(f"{API_PREFIX}/"):
        text = f"{API_PREFIX}{text}"
    return text


def _split_query(path: str) -> tuple[str, dict[str, Any]]:
    """Keep a query string written into the endpoint itself."""
    head, sep, query = path.partition("?")
    if not sep or not query:
        return path, {}
    from urllib.parse import parse_qsl

    params: dict[str, Any] = {}
    for key, value in parse_qsl(query, keep_blank_values=True):
        if key in params:
            current = params[key]
            params[key] = [*current, value] if isinstance(current, list) else [current, value]
        else:
            params[key] = value
    return head, params


def _parse_headers(values: list[str] | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw in values or []:
        name, sep, value = raw.partition(":")
        if not sep or not name.strip():
            raise ValidationError(
                f"Неверный заголовок «{raw}».",
                hint='Формат: -H "Имя: значение"',
            )
        headers[name.strip()] = value.strip()
    return headers


def _read_input(source: str) -> bytes:
    if source == "-":
        stream = getattr(sys.stdin, "buffer", None)
        if stream is not None:
            return bytes(stream.read())
        return sys.stdin.read().encode("utf-8")
    try:
        return Path(source).read_bytes()
    except OSError as exc:
        raise ValidationError(f"Не удалось прочитать файл «{source}»: {exc}") from exc


def _query_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return [_query_value(item) for item in value]
    if value is None:
        return "null"
    if isinstance(value, (dict,)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _decode(response: Any) -> tuple[Any, bool, bool]:
    """(payload, is_json, has_body) — a non-JSON answer is handed back as text."""
    if not response.content:
        return None, True, False
    try:
        return response.json(), True, True
    except ValueError:
        return response.text, False, True


def _dump_request(
    app_ctx: AppContext,
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
) -> None:
    lines = [f"> {method} {url}"]
    for name, value in headers.items():
        lines.append(f"> {name}: {value}")
    if body:
        lines.append(f"> {body.decode('utf-8', 'replace')}")
    for line in lines:
        app_ctx.err_console.print(line, markup=False, highlight=False)


def _print_head(app_ctx: AppContext, response: Any) -> None:
    version = getattr(response, "http_version", "HTTP/1.1") or "HTTP/1.1"
    app_ctx.console.print(
        f"{version} {response.status_code} {response.reason_phrase}".rstrip(),
        markup=False,
        highlight=False,
    )
    for name, value in response.headers.items():
        app_ctx.console.print(f"{name}: {value}", markup=False, highlight=False)
    app_ctx.console.print("", markup=False, highlight=False)


def _emit_body(app_ctx: AppContext, payload: Any, *, is_json: bool, jq: str | None) -> None:
    if not is_json:
        if jq:
            raise ValidationError(
                "Ответ не в формате JSON — фильтр --jq применить нельзя.",
                hint="Уберите --jq или воспользуйтесь --include для диагностики.",
            )
        text = payload if isinstance(payload, str) else str(payload)
        sys.stdout.write(text if text.endswith("\n") else f"{text}\n")
        return
    opts = replace(app_ctx.out, jq=jq or app_ctx.out.jq)
    # The escape hatch answers with JSON by default, like `gh api`; -o still wins.
    if opts.fmt is OutputFormat.TABLE and not opts.json_fields:
        opts = replace(opts, fmt=OutputFormat.JSON)
    render(payload, opts, console=app_ctx.console)


def _page_limit(params: dict[str, Any]) -> int:
    raw = params.get("limit")
    try:
        value = int(raw) if raw is not None else MAX_PAGE_LIMIT
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Некорректное значение limit: «{raw}».") from exc
    return max(1, min(value, MAX_PAGE_LIMIT))


def _page_offset(params: dict[str, Any]) -> int:
    raw = params.get("offset")
    try:
        value = int(raw) if raw is not None else 0
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Некорректное значение offset: «{raw}».") from exc
    return max(0, value)


def api_cmd(
    ctx: typer.Context,
    endpoint: Annotated[
        str,
        typer.Argument(
            metavar="ЭНДПОИНТ",
            help="Путь API: task-list, /task-list или /api-v2/task-list",
        ),
    ],
    method: Annotated[
        str | None,
        typer.Option(
            "-X", "--method", metavar="МЕТОД", help="HTTP-метод; по умолчанию GET, с телом — POST"
        ),
    ] = None,
    raw_field: Annotated[
        list[str] | None,
        typer.Option(
            "-f",
            "--raw-field",
            metavar="ПОЛЕ=ЗНАЧЕНИЕ",
            help="Строковое поле (можно повторять)",
        ),
    ] = None,
    field: Annotated[
        list[str] | None,
        typer.Option(
            "-F",
            "--field",
            metavar="ПОЛЕ=ЗНАЧЕНИЕ",
            help="Типизированное поле: true/false/null/число/JSON/@файл",
        ),
    ] = None,
    input_: Annotated[
        str | None,
        typer.Option("--input", metavar="ФАЙЛ", help="Тело запроса из файла; «-» — из stdin"),
    ] = None,
    header: Annotated[
        list[str] | None,
        typer.Option(
            "-H",
            "--header",
            metavar="ЗАГОЛОВОК",
            help='Заголовок в виде "Имя: значение" (можно повторять)',
        ),
    ] = None,
    paginate: Annotated[
        bool,
        typer.Option("--paginate", help="Пройти все страницы по paging.offset и склеить content"),
    ] = False,
    jq: Annotated[
        str | None,
        typer.Option("-q", "--jq", metavar="ВЫРАЖЕНИЕ", help="Отфильтровать JSON выражением jq"),
    ] = None,
    include: Annotated[
        bool,
        typer.Option("-i", "--include", help="Напечатать строку статуса и заголовки ответа"),
    ] = False,
    silent: Annotated[
        bool,
        typer.Option("--silent", help="Не печатать тело ответа"),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Вывести отправляемый запрос в stderr"),
    ] = False,
) -> None:
    """Произвольный запрос к API YouGile."""
    app_ctx = get_ctx(ctx)

    if input_ is not None and (raw_field or field):
        raise ValidationError("Укажите либо --input, либо поля -f/-F, но не всё сразу.")
    if paginate and input_ is not None:
        raise ValidationError("Флаг --paginate несовместим с --input.")
    if paginate and include:
        raise ValidationError("Флаг --paginate несовместим с --include.")

    path, params = _split_query(normalize_endpoint(endpoint, company_id=app_ctx.auth.company_id))
    headers = _parse_headers(header)

    fields: dict[str, Any] = {}
    fields.update(parse_kv_options(list(raw_field or [])))
    fields.update(parse_field_pairs(list(field or [])))

    body: bytes | None = None
    if input_ is not None:
        body = _read_input(input_)

    verb = (method or "").strip().upper()
    if verb and verb not in METHODS:
        raise ValidationError(
            f"Неизвестный HTTP-метод «{method}».",
            hint=f"Допустимы: {', '.join(METHODS)}.",
        )
    if not verb:
        verb = "POST" if (fields or body) else "GET"

    if fields:
        if verb in ("GET", "HEAD"):
            params.update({key: _query_value(value) for key, value in fields.items()})
        else:
            body = json.dumps(fields, ensure_ascii=False).encode("utf-8")

    if paginate and verb != "GET":
        raise ValidationError("Флаг --paginate работает только с методом GET.")

    # POST /api-v2/auth/* is the only family that must go out without a bearer.
    anonymous = verb == "POST" and path.startswith(AUTH_PREFIX)
    borrowed: YouGileClient | None = None
    if anonymous and not app_ctx.auth.api_key:
        borrowed = YouGileClient(base_url=app_ctx.auth.base_url, host=app_ctx.auth.host)
        client = borrowed
    else:
        client = app_ctx.client()

    try:
        if paginate:
            payload, is_json, has_body = _paginate(
                app_ctx,
                client,
                path,
                params,
                headers=headers,
                auth=not anonymous,
                verbose=verbose,
            )
        else:
            if verbose:
                _dump_request(app_ctx, verb, _display_url(client, path, params), headers, body)
            response = client.request_raw(
                verb,
                path,
                params=params or None,
                content=body,
                headers=headers or None,
                auth=not anonymous,
            )
            if include:
                _print_head(app_ctx, response)
            payload, is_json, has_body = _decode(response)
    finally:
        if borrowed is not None:
            borrowed.close()

    if silent or not has_body:
        return
    _emit_body(app_ctx, payload, is_json=is_json, jq=jq)


def _display_url(client: YouGileClient, path: str, params: dict[str, Any]) -> str:
    base = path if path.startswith(("http://", "https://")) else f"{client.base_url}{path}"
    if not params:
        return base
    from urllib.parse import urlencode

    pairs: list[tuple[str, str]] = []
    for key, value in params.items():
        if isinstance(value, list):
            pairs.extend((key, str(item)) for item in value)
        else:
            pairs.append((key, str(value)))
    return f"{base}?{urlencode(pairs)}"


def _paginate(
    app_ctx: AppContext,
    client: YouGileClient,
    path: str,
    params: dict[str, Any],
    *,
    headers: dict[str, str],
    auth: bool,
    verbose: bool,
) -> tuple[Any, bool, bool]:
    """Walk `paging.offset` until `paging.next` is false, gluing `content`."""
    limit = _page_limit(params)
    start = _page_offset(params)
    offset = start
    envelope: dict[str, Any] | None = None
    merged: list[Any] = []
    previous_page: list[Any] | None = None

    while True:
        page_params = dict(params)
        page_params["limit"] = limit
        page_params["offset"] = offset
        if verbose:
            _dump_request(app_ctx, "GET", _display_url(client, path, page_params), headers, None)
        response = client.request_raw(
            "GET",
            path,
            params=page_params,
            headers=headers or None,
            auth=auth,
        )
        payload, is_json, has_body = _decode(response)
        if not is_json or not has_body:
            return payload, is_json, has_body
        if isinstance(payload, list):
            if envelope is None:
                envelope = {}
            # Endpoints without limit/offset parameters answer with the same full
            # array every time, so a short page is not the only stop condition.
            if not payload or payload == previous_page:
                break
            merged.extend(payload)
            if len(payload) < limit:
                break
            previous_page = payload
            offset += len(payload)
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
            return payload, True, True
        content: list[Any] = payload["content"]
        if envelope is None:
            envelope = payload
        merged.extend(content)
        paging = payload.get("paging") or {}
        if not content or not paging.get("next"):
            break
        offset += len(content)

    if envelope is None or not envelope:
        return merged, True, True
    # The paging block of the last page describes that page, not the merged result.
    return merged_envelope(merged, envelope), True, True
