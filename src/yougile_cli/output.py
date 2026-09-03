"""Rendering layer: gh-style tables plus json/yaml/csv/tsv/ids.

Table output copies `gh issue list`: UPPERCASE headers, no borders, a two-space
gap between columns, identifiers shortened to 8 characters unless
``--full-ids`` is given, booleans as ``да``/``нет`` and millisecond timestamps
humanised. Colour is dropped whenever stdout is not a terminal, when
``NO_COLOR`` is set, and kept when ``CLICOLOR_FORCE`` is set.

``OutputOptions`` carries the flags a command was invoked with; ``render``
applies them in gh's order: ``--json`` field selection first, then ``--jq``,
then the chosen format.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import IO, Any

import yaml
from rich.console import Console

from .errors import ValidationError, YouGileError
from .fields import static_fields

__all__ = [
    "EMPTY_NOTICE",
    "ID_WIDTH",
    "OutputFormat",
    "OutputOptions",
    "apply_json_fields",
    "available_fields",
    "color_enabled",
    "compact",
    "fields_error",
    "flatten",
    "format_value",
    "get_console",
    "humanize_timestamp",
    "is_tty",
    "is_uuid_like",
    "as_rows",
    "notify_empty",
    "pick_columns",
    "print_kv",
    "render",
    "render_table",
    "run_jq",
    "sanitize_terminal_text",
    "select_fields",
    "shorten_id",
    "shorten_ids",
    "target_label",
]

ID_WIDTH = 8
EMPTY_NOTICE = "Ничего не найдено."

PREFERRED_FIRST = ("id", "title", "name", "realName", "email", "key")
PREFERRED_LAST = ("deleted", "timestamp", "description")

_ID_KEYS = ("id", "key")
# Every identifier the API returns is a UUID; shortening keys off the value, not the
# field name, so `createdBy` and the members of `assigned` are cut like `id` is.
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_TS_KEYS = ("deadline", "lastactivity", "since", "atmoment")

# ESC plus the rest of C0 (tab and newline stay: they are handled by the callers) and C1.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x80-\x9f]")
_PLACEHOLDER = "\ufffd"


def sanitize_terminal_text(text: str) -> str:
    """Server text is data, not commands: no escape sequence may reach the terminal.

    Each stripped character becomes U+FFFD so the user can tell a plain title from
    one that carried something invisible.
    """
    return _CONTROL_RE.sub(_PLACEHOLDER, text)


class OutputFormat(StrEnum):
    TABLE = "table"
    JSON = "json"
    YAML = "yaml"
    CSV = "csv"
    TSV = "tsv"
    IDS = "ids"


@dataclass
class OutputOptions:
    """Output flags of one command invocation."""

    fmt: OutputFormat = OutputFormat.TABLE
    json_fields: list[str] | None = None
    jq: str | None = None
    limit: int = 30
    full_ids: bool = False
    columns: list[str] | None = field(default=None)
    resource: str | None = None

    @property
    def machine_readable(self) -> bool:
        """True when the output must stay parseable (no decoration, no prompts)."""
        return bool(self.json_fields or self.jq) or self.fmt is not OutputFormat.TABLE


# --------------------------------------------------------------------------- tty


def is_tty(stream: IO[str] | None = None) -> bool:
    target = stream or sys.stdout
    try:
        return bool(target.isatty())
    except (AttributeError, ValueError):
        return False


_color_override: bool | None = None


def set_color_override(value: bool | None) -> None:
    """`--no-color` is a flag, so it must outrank NO_COLOR and CLICOLOR_FORCE alike."""
    global _color_override
    _color_override = value


def color_enabled(stream: IO[str] | None = None) -> bool:
    """An explicit flag wins; then CLICOLOR_FORCE, then NO_COLOR, then the terminal."""
    if _color_override is not None:
        return _color_override
    if os.environ.get("CLICOLOR_FORCE", "").strip() not in ("", "0"):
        return True
    if os.environ.get("NO_COLOR") is not None:
        return False
    return is_tty(stream)


def get_console(*, stderr: bool = False, color: bool | None = None) -> Console:
    stream = sys.stderr if stderr else sys.stdout
    use_color = color_enabled(stream) if color is None else color
    return Console(
        file=stream,
        no_color=not use_color,
        force_terminal=True if use_color else None,
        highlight=False,
        soft_wrap=True,
        emoji=False,
    )


# --------------------------------------------------------------------------- values


def shorten_id(value: str, *, full: bool = False) -> str:
    if full or len(value) <= ID_WIDTH:
        return value
    return value[:ID_WIDTH]


def is_uuid_like(value: Any) -> bool:
    """True for a bare UUID string, in any case, with no surrounding text."""
    return isinstance(value, str) and bool(_UUID_RE.match(value.strip()))


def shorten_ids(value: Any, *, full: bool = False) -> Any:
    """Shorten every UUID inside a value, however deeply it is nested."""
    if full:
        return value
    if isinstance(value, str):
        return shorten_id(value) if is_uuid_like(value) else value
    if isinstance(value, (list, tuple)):
        return [shorten_ids(item) for item in value]
    if isinstance(value, dict):
        return {key: shorten_ids(item) for key, item in value.items()}
    return value


def target_label(typed: str | None, obj_id: str) -> str:
    """Prompt label for a resolved object: the text the user typed plus a short id."""
    text = (typed or "").strip()
    short = shorten_id(obj_id)
    if not text or text == obj_id or "/" in text:
        return short
    return f"«{text}» ({short})"


def humanize_timestamp(value: Any) -> str:
    """YouGile timestamps are epoch milliseconds."""
    try:
        moment = datetime.fromtimestamp(float(value) / 1000.0)
    except (TypeError, ValueError, OSError, OverflowError):
        return str(value)
    return moment.strftime("%Y-%m-%d %H:%M")


def _looks_like_id(key: str | None, value: str) -> bool:
    if not key:
        return False
    lowered = key.lower()
    return (lowered in _ID_KEYS or lowered.endswith("id") or lowered.endswith("ids")) and len(
        value
    ) > ID_WIDTH


def _looks_like_timestamp(key: str | None, value: Any) -> bool:
    if not key or not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    lowered = key.lower()
    if lowered.endswith("timestamp") or lowered.endswith("date") or lowered in _TS_KEYS:
        return float(value) > 1e11
    return False


def compact(value: Any, limit: int = 60) -> str:
    """One-line printable form of a cell value."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    else:
        text = str(value)
    text = sanitize_terminal_text(text).replace("\n", " ").replace("\t", " ").strip()
    if limit and len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def format_value(
    value: Any,
    *,
    key: str | None = None,
    full_ids: bool = False,
    limit: int = 60,
) -> str:
    """Cell text for the human-facing formats (table, key/value view)."""
    if _looks_like_timestamp(key, value):
        return humanize_timestamp(value)
    if not full_ids:
        value = shorten_ids(value)
    text = compact(value, limit=limit)
    if isinstance(value, str) and _looks_like_id(key, value):
        return shorten_id(text, full=full_ids)
    return text


# --------------------------------------------------------------------------- shapes


def as_rows(data: Any) -> list[dict[str, Any]]:
    """Normalise anything an endpoint returns into a list of dict rows."""
    if data is None:
        return []
    if isinstance(data, dict):
        if isinstance(data.get("content"), list):
            return [item for item in data["content"] if isinstance(item, dict)]
        return [data]
    if isinstance(data, list):
        return [item if isinstance(item, dict) else {"value": item} for item in data]
    return [{"value": data}]


def pick_columns(rows: list[dict[str, Any]]) -> list[str]:
    """Column order derived from the rows: ids and names first, noise last."""
    seen = available_fields(rows)
    first = [k for k in PREFERRED_FIRST if k in seen]
    last = [k for k in PREFERRED_LAST if k in seen]
    middle = [k for k in seen if k not in first and k not in last]
    return first + middle + last


def available_fields(rows: list[dict[str, Any]]) -> list[str]:
    """Every field name present in the rows, in first-seen order."""
    seen: list[str] = []
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    return seen


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested dicts into dotted keys; lists become compact JSON."""
    flat: dict[str, Any] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                nested = flatten(value, name)
                flat.update(nested if nested else {name: ""})
            elif isinstance(value, (list, tuple)):
                flat[name] = json.dumps(list(value), ensure_ascii=False, default=str)
            else:
                flat[name] = value
        return flat
    return {prefix or "value": obj}


def _get_path(row: dict[str, Any], path: str) -> Any:
    current: Any = row
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def select_fields(
    rows: list[dict[str, Any]], fields: list[str], resource: str | None = None
) -> list[dict[str, Any]]:
    """`--json a,b,c`: keep only the named fields (dotted paths allowed)."""
    wanted = [f.strip() for f in fields if f.strip()]
    if not wanted:
        raise fields_error(rows, resource)
    # A field the schema promises stays valid even when this answer happens to omit it.
    known = set(available_fields(rows)) | set(static_fields(resource))
    unknown = [f for f in wanted if f.split(".")[0] not in known] if known else []
    if unknown:
        raise YouGileError(
            f"неизвестные поля: {', '.join(unknown)}",
            hint=f"доступные поля: {', '.join(sorted(known))}",
        )
    return [{name: _get_path(row, name) for name in wanted} for row in rows]


def fields_error(rows: list[dict[str, Any]], resource: str | None = None) -> YouGileError:
    """`--json` with no value: list the fields and exit 1, exactly like gh.

    The static schema is what makes the answer available before the first request;
    the rows add whatever the server returned beyond it.
    """
    names = set(static_fields(resource)) | set(available_fields(rows))
    listing = ", ".join(sorted(names)) if names else "нет данных для определения полей"
    return YouGileError(
        "укажите поля через запятую: --json ПОЛЕ1,ПОЛЕ2",
        hint=f"доступные поля: {listing}",
    )


def apply_json_fields(
    opts: OutputOptions,
    value: str | None,
    resource: str | None = None,
    *,
    rows: list[dict[str, Any]] | None = None,
) -> None:
    """Fold one `--json` value into `opts` — the single place the flag is parsed.

    A bare `--json` asks for names, not for data, and is answered as completely as it
    can be without paying for a request: from the static schema, from `rows` when the
    command composed them locally, or from both. With neither at hand — and no rows
    is the same as no rows yet — the empty selection travels on and `render` answers
    from the rows the command does fetch, exactly as it did before the schema existed.
    """
    if value is None:
        return
    opts.resource = resource
    selected = [name.strip() for name in value.split(",") if name.strip()]
    if not selected and (rows or static_fields(resource)):
        raise fields_error(rows or [], resource)
    opts.json_fields = selected


def run_jq(data: Any, expr: str) -> str:
    """Filter JSON through the external `jq` binary, as gh does."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    try:
        proc = subprocess.run(
            ["jq", "-r", expr],
            input=payload,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValidationError(
            "не найден бинарник jq",
            hint="Установите jq (brew install jq / apt install jq) или используйте --json.",
        ) from exc
    if proc.returncode != 0:
        raise ValidationError(
            f"jq не смог обработать выражение: {proc.stderr.strip()}",
            hint=f"Проверьте выражение: {expr}",
        )
    return proc.stdout


# --------------------------------------------------------------------------- writers


def _write(console: Console, line: str, *, style: str | None = None) -> None:
    console.print(
        sanitize_terminal_text(line),
        style=style,
        markup=False,
        highlight=False,
        overflow="ignore",
        crop=False,
    )


def notify_empty(console: Console | None = None, message: str = EMPTY_NOTICE) -> None:
    """Table mode only: say so on stderr, so a pipe still sees an empty stdout."""
    _write(console or get_console(stderr=True), message, style="dim")


def render_table(
    rows: list[dict[str, Any]],
    columns: list[str] | None = None,
    *,
    console: Console | None = None,
    full_ids: bool = False,
) -> None:
    """gh-style borderless table: UPPERCASE headers, two-space gaps."""
    out = console or get_console()
    if not rows:
        notify_empty()
        return
    headers = columns or pick_columns(rows)
    cells = [
        [format_value(row.get(name), key=name, full_ids=full_ids) for name in headers]
        for row in rows
    ]
    widths = [len(h) for h in headers]
    for line in cells:
        for index, text in enumerate(line):
            widths[index] = max(widths[index], len(text))

    def join(values: list[str]) -> str:
        parts = [
            value if index == len(values) - 1 else value.ljust(widths[index])
            for index, value in enumerate(values)
        ]
        return "  ".join(parts).rstrip()

    _write(out, join([h.upper() for h in headers]), style="bold")
    for line in cells:
        _write(out, join(line))


def print_kv(
    obj: dict[str, Any],
    *,
    console: Console | None = None,
    full_ids: bool = False,
    columns: list[str] | None = None,
) -> None:
    """Aligned key/value view of a single object, gh-style."""
    out = console or get_console()
    items = [(k, obj[k]) for k in (columns or list(obj)) if k in obj]
    if not items:
        return
    width = max(len(k) for k, _ in items)
    for key, value in items:
        text = format_value(value, key=key, full_ids=full_ids, limit=0)
        _write(out, f"{key.ljust(width)}  {text}")


# `\r` is absent on purpose: _sanitize_cell turns it into U+FFFD before this check,
# so a CR branch here would be dead. `\t` survives sanitising and still needs it.
FORMULA_STARTERS = ("=", "+", "-", "@", "\t")


def _sanitize_cell(value: Any) -> Any:
    """`csv`/`tsv` land in files a shell later `cat`s: ESC must not survive the trip."""
    return sanitize_terminal_text(value) if isinstance(value, str) else value


def _defuse_formula(value: Any) -> Any:
    """Spreadsheets evaluate a cell that starts with =, +, -, @ or a tab."""
    if isinstance(value, str) and value.startswith(FORMULA_STARTERS):
        return "'" + value
    return value


def _write_delimited(rows: list[dict[str, Any]], delimiter: str, columns: list[str] | None) -> str:
    flat_rows = [flatten(row) for row in rows]
    headers = columns or available_fields(flat_rows)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
    writer.writerow([_sanitize_cell(h) for h in headers])
    for row in flat_rows:
        writer.writerow(
            [
                "" if row.get(h) is None else _defuse_formula(_sanitize_cell(row.get(h)))
                for h in headers
            ]
        )
    return buffer.getvalue()


def render(
    data: Any,
    opts: OutputOptions | OutputFormat | str | None = None,
    *,
    columns: list[str] | None = None,
    console: Console | None = None,
) -> None:
    """Print `data`, applying --json field selection, then --jq, then the format."""
    if opts is None:
        options = OutputOptions()
    elif isinstance(opts, OutputOptions):
        options = opts
    else:
        options = OutputOptions(fmt=OutputFormat(opts))

    out = console or get_console()
    payload = data
    fmt = options.fmt

    if options.json_fields is not None:
        payload = select_fields(as_rows(data), options.json_fields, options.resource)
        fmt = OutputFormat.JSON

    if options.jq:
        sys.stdout.write(run_jq(payload, options.jq))
        return

    if fmt is OutputFormat.JSON:
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        sys.stdout.write(text + "\n")
        return

    if fmt is OutputFormat.YAML:
        sys.stdout.write(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, default_flow_style=False)
        )
        return

    rows = as_rows(payload)
    picked = columns or options.columns

    if fmt is OutputFormat.IDS:
        printed = 0
        for row in rows:
            value = row.get("id") or row.get("key")
            if value is not None:
                sys.stdout.write(f"{value}\n")
                printed += 1
        if rows and not printed:
            # Silence would look like "ничего не найдено" instead of a wrong format.
            get_console(stderr=True).print(
                "[yellow]предупреждение:[/yellow] формат ids не подходит: "
                "в этих данных нет поля id — вывод пуст.",
                highlight=False,
            )
            get_console(stderr=True).print(
                "[dim]подсказка:[/dim] повторите с -o table или -o json.",
                highlight=False,
            )
        return

    if fmt in (OutputFormat.CSV, OutputFormat.TSV):
        delimiter = "," if fmt is OutputFormat.CSV else "\t"
        sys.stdout.write(_write_delimited(rows, delimiter, picked))
        return

    single = isinstance(payload, dict) and not isinstance(payload.get("content"), list)
    if single and rows:
        print_kv(rows[0], console=out, full_ids=options.full_ids, columns=picked)
        return
    render_table(rows, picked, console=out, full_ids=options.full_ids)
