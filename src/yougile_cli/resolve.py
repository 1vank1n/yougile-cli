"""Turning what a human typed into an object id.

Accepted everywhere: a bare UUID, a YouGile link, a task code or a name. Links
come in several shapes — ``/board/<boardId>#TASK-CODE``,
``/team/<anything>/#TASK-CODE``, ``#sticker-<uuid>``, ``#chat-<uuid>``,
``/api-v2/tasks/<uuid>`` — so :func:`extract_id_from_url` reports *what* it
found: an id or a task code (``LinkTarget.kind``).

A task code lives in ``idTaskProject`` / ``idTaskCommon`` and no endpoint
filters by it, so :func:`resolve_task_code` walks ``/api-v2/task-list`` once and
caches the whole ``CODE -> id`` map in
``<config_dir>/cache/tasks-<host>-<account>.json``
for 24 hours. With a board id in hand the cheaper column-by-column walk runs
first.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import cache_dir, write_atomic
from .errors import (
    ResolveError,
    ValidationError,
    YouGileError,
    ambiguous_error,
    not_found_error,
    not_specified_message,
    resource_words,
)

if TYPE_CHECKING:  # pragma: no cover
    from .client import YouGileClient

__all__ = [
    "ME",
    "account_tag",
    "LinkTarget",
    "TASK_CACHE_TTL",
    "TaskRef",
    "extract_id_from_url",
    "resolve_task_code",
    "task_cache_path",
    "is_uuid",
    "parse_field_pairs",
    "parse_kv_options",
    "parse_task_url",
    "resolve_board_id",
    "resolve_column_id",
    "resolve_one",
    "resolve_project_id",
    "resolve_task_id",
    "resolve_user_id",
]

ME = "@me"

# Upper bound for the unfiltered substring scan when the exact name filter finds nothing.
FALLBACK_SCAN_LIMIT = 2000

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_UUID_FULL_RE = re.compile(rf"^{_UUID_RE.pattern}$", re.IGNORECASE)
_BOARD_URL_RE = re.compile(rf"/board/({_UUID_RE.pattern})", re.IGNORECASE)
_STICKER_RE = re.compile(rf"#sticker-({_UUID_RE.pattern})", re.IGNORECASE)
_CHAT_RE = re.compile(rf"#chat-({_UUID_RE.pattern})", re.IGNORECASE)
_TASK_CODE_RE = re.compile(r"^[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9]{0,15}-\d+$")
_API_ID_RE = re.compile(rf"/api-v2/[a-z0-9-]+/({_UUID_RE.pattern})", re.IGNORECASE)

# A cached code map goes stale as tasks are created; a day is short enough that a
# wrong hit is unlikely and long enough to spare the 50-requests-per-minute budget.
TASK_CACHE_TTL = 24 * 60 * 60


def is_uuid(value: str) -> bool:
    return bool(value) and bool(_UUID_FULL_RE.match(value.strip()))


ID_TARGET = "id"
CODE_TARGET = "code"


class LinkTarget(str):
    """What a link points at: an object id or a task code.

    It *is* the string, so existing callers keep working; ``kind`` tells the two
    apart, because a code needs a lookup while an id does not.
    """

    __slots__ = ("kind",)
    kind: str

    def __new__(cls, value: str, kind: str = ID_TARGET) -> LinkTarget:
        target = super().__new__(cls, value)
        object.__setattr__(target, "kind", kind)
        return target

    @property
    def is_id(self) -> bool:
        return self.kind == ID_TARGET

    @property
    def is_code(self) -> bool:
        return self.kind == CODE_TARGET

    @property
    def value(self) -> str:
        return str(self)


@dataclass(frozen=True)
class TaskRef:
    """What a YouGile board link points at."""

    board_id: str | None = None
    task_code: str | None = None
    sticker_id: str | None = None
    task_id: str | None = None


def parse_task_url(value: str) -> TaskRef | None:
    """Split ``…/board/<boardId>#<TASK-CODE|sticker-uuid|uuid>`` into its parts."""
    text = (value or "").strip()
    if not text:
        return None
    board = _BOARD_URL_RE.search(text)
    board_id = board.group(1) if board else None
    fragment = text.split("#", 1)[1].strip() if "#" in text else ""
    if board_id is None and not (fragment and _looks_like_url(text)):
        return None
    sticker = _STICKER_RE.search(text)
    if sticker:
        return TaskRef(board_id=board_id, sticker_id=sticker.group(1))
    if fragment and is_uuid(fragment):
        return TaskRef(board_id=board_id, task_id=fragment)
    if fragment and not _TASK_CODE_RE.match(fragment):
        # ``#chat-…`` and other anchors are not task codes.
        return TaskRef(board_id=board_id) if board_id else None
    return TaskRef(board_id=board_id, task_code=fragment or None)


def _looks_like_url(text: str) -> bool:
    return "/" in text or text.lower().startswith("http")


def extract_id_from_url(value: str) -> LinkTarget | None:
    """Pull the most specific target out of a YouGile link, id or task code.

    Returns a :class:`LinkTarget` — a plain string that also says whether it is
    an object id (``kind == "id"``) or a task code (``kind == "code"``), because
    ``…/team/a1b2c3d4e5f6/#ILS-343`` carries no id at all.
    """
    text = (value or "").strip()
    if not text:
        return None
    if is_uuid(text):
        return LinkTarget(text, ID_TARGET)
    for pattern in (_CHAT_RE, _STICKER_RE):
        found = pattern.search(text)
        if found:
            return LinkTarget(found.group(1), ID_TARGET)
    fragment = text.split("#", 1)[1].strip() if "#" in text else ""
    if fragment:
        if is_uuid(fragment):
            return LinkTarget(fragment, ID_TARGET)
        if _TASK_CODE_RE.match(fragment):
            return LinkTarget(fragment, CODE_TARGET)
    if "/" in text or text.lower().startswith("http"):
        api = _API_ID_RE.search(text)
        if api:
            return LinkTarget(api.group(1), ID_TARGET)
        found = _UUID_RE.search(text)
        if found:
            return LinkTarget(found.group(0), ID_TARGET)
    return None


def _label(item: dict[str, Any], name_field: str) -> str:
    for key in (name_field, "title", "name", "realName", "email"):
        value = item.get(key)
        if isinstance(value, str):
            return value
    return ""


def _pick(
    items: list[dict[str, Any]],
    text: str,
    name_field: str,
    kind: str,
    hint: str | None = None,
) -> str:
    needle = text.casefold()
    exact = [i for i in items if _label(i, name_field).casefold() == needle]
    matches = exact or [i for i in items if needle in _label(i, name_field).casefold()]
    if not matches:
        raise not_found_error(kind, text, hint=hint)
    if len(matches) > 1:
        raise ambiguous_error(
            kind,
            text,
            [{"id": i.get("id", ""), "title": _label(i, name_field)} for i in matches[:20]],
        )
    resolved = matches[0].get("id")
    if not isinstance(resolved, str) or not resolved:
        raise ResolveError(resource_words(kind).without_id(text))
    return resolved


def resolve_one(
    client: YouGileClient,
    *,
    path: str,
    value: str,
    name_field: str = "title",
    extra_params: dict[str, Any] | None = None,
    kind: str = "объект",
) -> str:
    """Return an id for `value`: pass ids and links through, look names up otherwise."""
    text = (value or "").strip()
    if not text:
        raise ResolveError(not_specified_message(kind))
    if is_uuid(text):
        return text
    from_url = extract_id_from_url(text)
    if from_url is not None and from_url.is_id:
        return from_url.value
    if from_url is not None and from_url.is_code:
        # `…/board/<id>#SAI-515` still names a board: the anchor is only the task.
        in_path = _UUID_RE.search(text.split("#", 1)[0])
        if in_path:
            return in_path.group(0)

    params: dict[str, Any] = dict(extra_params or {})
    items = client.collect(path, {**params, name_field: text})
    if not items:
        # The exact server-side filter missed, so fall back to a substring scan — bounded,
        # because an unfiltered walk of a large company burns the whole rate-limit budget.
        items = client.collect(path, params, max_items=FALLBACK_SCAN_LIMIT)
        if len(items) >= FALLBACK_SCAN_LIMIT:
            hint = f"Просмотрены первые {FALLBACK_SCAN_LIMIT} записей: укажите ID или ссылку."
            return _pick(items, text, name_field, kind, hint)
    return _pick(items, text, name_field, kind)


def resolve_project_id(client: YouGileClient, value: str) -> str:
    return resolve_one(client, path="/api-v2/projects", value=value, kind="проект")


def resolve_board_id(client: YouGileClient, value: str, project_id: str | None = None) -> str:
    extra = {"projectId": project_id} if project_id else None
    return resolve_one(client, path="/api-v2/boards", value=value, extra_params=extra, kind="доска")


def resolve_column_id(client: YouGileClient, value: str, board_id: str | None = None) -> str:
    extra = {"boardId": board_id} if board_id else None
    return resolve_one(
        client, path="/api-v2/columns", value=value, extra_params=extra, kind="колонка"
    )


def _task_code_matches(task: dict[str, Any], code: str) -> bool:
    """Full-code match only: a partial one would silently hit an unrelated task."""
    wanted = code.casefold()
    for key in ("idTaskProject", "idTaskCommon"):
        value = task.get(key)
        if value is None or value == "":
            continue
        if str(value).casefold() == wanted:
            return True
    return False


def _find_task_by_code(client: YouGileClient, board_id: str, code: str) -> str:
    """Task listing has no code filter, so walk the board column by column."""
    columns = client.collect("/api-v2/columns", {"boardId": board_id})
    for column in columns:
        column_id = column.get("id")
        if not isinstance(column_id, str):
            continue
        for task in client.paginate("/api-v2/task-list", {"columnId": column_id}):
            if _task_code_matches(task, code):
                task_id = task.get("id")
                if isinstance(task_id, str) and task_id:
                    return task_id
    raise not_found_error(
        "задача",
        code,
        hint="Проверьте код задачи или укажите её ID.",
    )


# --------------------------------------------------------------------------- code cache


def account_tag(api_key: str | None) -> str:
    """Short digest of the API key: task codes are per company, not per host."""
    key = (api_key or "").strip()
    if not key:
        return ""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def task_cache_path(host: str | None, account: str | None = None) -> Path:
    """``<config_dir>/cache/tasks-<host>[-<account>].json`` — one code map per account.

    Two accounts on one host live in different companies, where the same code
    names different tasks, so the account digest is part of the file name.
    """
    name = re.sub(r"[^a-z0-9._-]+", "-", (host or "").strip().lower()).strip("-")
    tag = re.sub(r"[^a-z0-9]+", "", (account or "").lower())
    suffix = f"-{tag}" if tag else ""
    return cache_dir() / f"tasks-{name or 'yougile.com'}{suffix}.json"


def _read_task_cache(host: str | None, account: str | None = None) -> dict[str, str]:
    """The stored code map, or an empty one when it is missing, stale or broken."""
    try:
        raw = json.loads(task_cache_path(host, account).read_text(encoding="utf-8"))
    except (OSError, ValueError, YouGileError):
        return {}
    if not isinstance(raw, dict):
        return {}
    updated = raw.get("updated")
    codes = raw.get("codes")
    if not isinstance(codes, dict) or not isinstance(updated, (int, float)):
        return {}
    if time.time() - float(updated) > TASK_CACHE_TTL:
        return {}
    return {str(k).upper(): v for k, v in codes.items() if isinstance(v, str) and v}


def _write_task_cache(host: str | None, codes: dict[str, str], account: str | None = None) -> None:
    """Best effort: a cache that cannot be written must never fail the command."""
    if not codes:
        return
    payload = {"host": host or "", "updated": time.time(), "codes": codes}
    try:
        write_atomic(
            task_cache_path(host, account),
            json.dumps(payload, ensure_ascii=False),
            mode=0o600,
        )
    except (OSError, YouGileError):
        return


def _cache_lookup(codes: dict[str, str], code: str) -> str | None:
    return codes.get(code.upper())


def _remember_code(store: dict[str, str], ambiguous: set[str], code: str, task_id: str) -> None:
    """One code must name one task; a clash is dropped rather than guessed."""
    previous = store.get(code)
    if previous is None:
        store[code] = task_id
    elif previous != task_id:
        ambiguous.add(code)


def resolve_task_code(client: YouGileClient, code: str) -> str:
    """Task id by its human code (``ILS-343``), matched case-insensitively.

    No endpoint filters by code, so the first miss walks the whole task list and
    caches every ``CODE -> id`` pair it saw for the next 24 hours.
    """
    wanted = (code or "").strip()
    if not wanted:
        raise ResolveError(not_specified_message("задача"))
    host = getattr(client, "host", "") or ""
    account = account_tag(getattr(client, "api_key", "") or "")
    cached = _cache_lookup(_read_task_cache(host, account), wanted)
    if cached:
        return cached

    project_codes: dict[str, str] = {}
    common_codes: dict[str, str] = {}
    project_clashes: set[str] = set()
    common_clashes: set[str] = set()
    for task in client.paginate("/api-v2/task-list"):
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id:
            continue
        for key, store, clashes in (
            ("idTaskProject", project_codes, project_clashes),
            ("idTaskCommon", common_codes, common_clashes),
        ):
            value = task.get(key)
            if value is None or value == "":
                continue
            _remember_code(store, clashes, str(value).upper(), task_id)
    # A project code is what people quote, so it wins over the company-wide counter.
    codes = {key: value for key, value in common_codes.items() if key not in common_clashes}
    codes.update({key: value for key, value in project_codes.items() if key not in project_clashes})
    _write_task_cache(host, codes, account)

    found = _cache_lookup(codes, wanted)
    if found:
        return found
    raise not_found_error(
        "задача",
        wanted,
        hint="Проверьте код задачи или укажите её ID.",
    )


def resolve_task_id(
    client: YouGileClient,
    value: str,
    column_id: str | None = None,
    board_id: str | None = None,
) -> str:
    """Accepts an id, a link of any shape, a bare task code or a title."""
    text = (value or "").strip()
    if not text:
        raise ResolveError(not_specified_message("задача"))
    if is_uuid(text):
        return text

    code: str | None = None
    from_link = False
    ref = parse_task_url(text)
    if ref is not None:
        if ref.task_id:
            return ref.task_id
        if ref.sticker_id:
            raise ResolveError(
                "Ссылка указывает на стикер, а не на задачу.",
                hint="Откройте задачу и скопируйте ссылку с её кодом.",
            )
        if ref.task_code:
            code, from_link = ref.task_code, True
            if ref.board_id:
                try:
                    return _find_task_by_code(client, ref.board_id, code)
                except ResolveError:
                    pass
        else:
            target = extract_id_from_url(text)
            if target is not None and target.is_id:
                return target.value
    elif _TASK_CODE_RE.match(text):
        code = text
        if board_id:
            try:
                return _find_task_by_code(client, board_id, code)
            except ResolveError:
                pass

    if code:
        try:
            return resolve_task_code(client, code)
        except ResolveError:
            # A link can only have carried a code; a bare «Спринт-2» may be a title.
            if from_link:
                raise

    extra = {"columnId": column_id} if column_id else None
    return resolve_one(
        client, path="/api-v2/task-list", value=text, extra_params=extra, kind="задача"
    )


def resolve_user_id(client: YouGileClient, value: str) -> str:
    """Match a user by id, email, real name or the literal ``@me``."""
    text = (value or "").strip()
    if not text:
        raise ResolveError(not_specified_message("сотрудник"))
    if text.casefold() == ME:
        me = client.get("/api-v2/users/me")
        user_id = me.get("id") if isinstance(me, dict) else None
        if not isinstance(user_id, str) or not user_id:
            raise ResolveError("Не удалось определить текущего пользователя.")
        return user_id
    if is_uuid(text):
        return text
    from_url = extract_id_from_url(text)
    if from_url is not None and from_url.is_id:
        return from_url.value

    items = client.collect("/api-v2/users", {"email": text} if "@" in text else None)
    if not items and "@" in text:
        items = client.collect("/api-v2/users")

    needle = text.casefold()

    def fields(item: dict[str, Any]) -> list[str]:
        return [str(item.get("email") or ""), str(item.get("realName") or "")]

    exact = [i for i in items if any(f.casefold() == needle for f in fields(i))]
    matches = exact or [i for i in items if any(needle in f.casefold() for f in fields(i))]

    if not matches:
        raise not_found_error("сотрудник", text, hint="Посмотрите список: yougile user list")
    if len(matches) > 1:
        raise ambiguous_error(
            "сотрудник",
            text,
            [
                {
                    "id": i.get("id", ""),
                    "title": f"{i.get('realName') or ''} <{i.get('email') or ''}>".strip(),
                }
                for i in matches[:20]
            ],
            hint="Уточните почту или укажите ID.",
        )
    resolved = matches[0].get("id")
    if not isinstance(resolved, str) or not resolved:
        raise ResolveError(resource_words("сотрудник").without_id(text))
    return resolved


# --------------------------------------------------------------------------- `yougile api`

_JSON_LITERALS = {"true", "false", "null"}
_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")


def _split_pair(raw: str) -> tuple[str, str]:
    key, sep, value = raw.partition("=")
    key = key.strip()
    if not sep or not key:
        raise ValidationError(
            f"Ожидался формат key=value, получено «{raw}».",
            hint="Например: -f title=Задача",
        )
    return key, value


def _store(result: dict[str, Any], key: str, value: Any) -> None:
    """Repeating a key builds a list, the way `gh api -f a=1 -f a=2` does."""
    if key.endswith("[]"):
        name = key[:-2]
        result.setdefault(name, [])
        if isinstance(result[name], list):
            result[name].append(value)
        return
    if key in result:
        existing = result[key]
        if isinstance(existing, list):
            existing.append(value)
        else:
            result[key] = [existing, value]
        return
    result[key] = value


def parse_kv_options(values: list[str] | None, *, typed: bool = False) -> dict[str, Any]:
    """`-f key=value`: every value stays a string unless ``typed`` is set."""
    result: dict[str, Any] = {}
    for raw in values or []:
        key, value = _split_pair(raw)
        _store(result, key, _decode_value(value) if typed else value)
    return result


def parse_field_pairs(
    values: list[str] | None,
    *,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """`-F key=value`: typed values — ``true``/``false``/``null``/number/JSON/``@файл``."""
    root = Path(base_dir) if base_dir is not None else Path.cwd()
    result: dict[str, Any] = {}
    for raw in values or []:
        key, value = _split_pair(raw)
        _store(result, key, _decode_typed(value, root))
    return result


def _decode_typed(value: str, root: Path) -> Any:
    if value.startswith("@"):
        name = value[1:]
        if name == "-":
            return sys.stdin.read()
        path = Path(name)
        if not path.is_absolute():
            path = root / path
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValidationError(f"Не удалось прочитать файл «{name}»: {exc}") from exc
    return _decode_value(value)


def _decode_value(value: str) -> Any:
    text = value.strip()
    if text == "":
        return ""
    if text.casefold() in _JSON_LITERALS:
        return json.loads(text.casefold())
    if _NUMBER_RE.match(text):
        return json.loads(text)
    if text[0] in '{["':
        try:
            return json.loads(text)
        except ValueError:
            return value
    return value
