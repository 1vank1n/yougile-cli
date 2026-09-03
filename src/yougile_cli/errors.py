"""Exception hierarchy and gh-compatible process exit codes.

gh uses a very small set of exit codes; we mirror it exactly:

* ``0`` — success
* ``1`` — generic error
* ``2`` — usage error: **our own** validation, before anything is sent
* ``4`` — authentication required
* ``130`` — interrupted with Ctrl+C

Every error carries an optional ``hint`` that the CLI prints on a second line,
gh-style::

    ошибка: не найден проект «Ремонт»
    подсказка: посмотрите список: yougile project list
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "EXIT_OK",
    "EXIT_ERROR",
    "EXIT_USAGE",
    "EXIT_AUTH",
    "EXIT_INTERRUPT",
    "LOGIN_HINT",
    "YouGileError",
    "ApiError",
    "AuthError",
    "NotFoundError",
    "RateLimitError",
    "BadRequestError",
    "UsageError",
    "ValidationError",
    "ConfigError",
    "ResolveError",
    "AmbiguousNameError",
    "CancelledError",
    "RESOURCES",
    "ResourceWords",
    "ambiguous_error",
    "ambiguous_message",
    "exit_code_for",
    "format_error",
    "not_found_error",
    "not_found_message",
    "not_specified_message",
    "resource_words",
    "single_name",
]

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_AUTH = 4
EXIT_INTERRUPT = 130

LOGIN_HINT = "Выполните: yougile auth login"


class YouGileError(Exception):
    """Base class for every error raised by yougile-cli."""

    exit_code: int = EXIT_ERROR

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return self.message


def _server_message(payload: Any) -> str | None:
    """Pull a human message out of an API error body of any known shape."""
    if isinstance(payload, dict):
        for key in ("message", "error", "detail", "title"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list) and value:
                return "; ".join(str(item) for item in value)
        return None
    if isinstance(payload, str) and payload.strip():
        return payload.strip()
    return None


class ApiError(YouGileError):
    """Non-2xx answer from the YouGile API."""

    exit_code = EXIT_ERROR

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        status_code: int | None = None,
        method: str | None = None,
        url: str | None = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.status_code = status_code
        self.method = method
        self.url = url
        self.payload = payload

    def __str__(self) -> str:
        server = _server_message(self.payload)
        body = self.message
        if server and server != self.message:
            body = f"{self.message}: {server}"
        if self.status_code is not None:
            return f"{body} (HTTP {self.status_code})"
        return body


class AuthError(ApiError):
    """No key at all, or the key was rejected (401/403)."""

    exit_code = EXIT_AUTH

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("hint", LOGIN_HINT)
        super().__init__(message, **kwargs)


class NotFoundError(ApiError):
    """404 — object does not exist or is not visible to this key."""


class RateLimitError(ApiError):
    """429 — 50 requests per minute per company exhausted."""

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after

    def __str__(self) -> str:
        base = super().__str__()
        if self.retry_after is not None:
            return f"{base}, повторите через {self.retry_after:g} с"
        return base


class BadRequestError(ApiError):
    """400/422 — the server rejected the request.

    This is a runtime failure, not a usage error: exit code 1. Exit code 2 is
    reserved for validation we perform ourselves before any request goes out.
    """


class UsageError(YouGileError):
    """Our own pre-flight validation of arguments and local input (exit code 2)."""

    exit_code = EXIT_USAGE


class ValidationError(UsageError):
    """Historical name for :class:`UsageError`; local validation only."""


class ConfigError(YouGileError):
    """Local configuration is missing or broken."""


class ResolveError(YouGileError):
    """A name could not be resolved to an id."""


class AmbiguousNameError(ResolveError):
    """A name matched more than one object."""

    exit_code = EXIT_USAGE

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        candidates: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.candidates = candidates or []

    def __str__(self) -> str:
        if not self.candidates:
            return self.message
        lines = [self.message, "подходящие варианты:"]
        for item in self.candidates:
            label = item.get("title") or item.get("name") or item.get("realName") or ""
            lines.append(f"  {item.get('id', '?')}  {label}")
        return "\n".join(lines)


class CancelledError(YouGileError):
    """The user aborted an interactive prompt."""

    def __init__(self, message: str = "Отменено.", *, hint: str | None = None) -> None:
        super().__init__(message, hint=hint)


# --------------------------------------------------------------------------- wording

# Russian nouns have gender, so «Не найден {kind}» cannot be templated: the verb
# has to agree with the noun. Every resource therefore carries its finished
# phrases instead of a fragment that gets substituted into a template.


@dataclass(frozen=True)
class ResourceWords:
    """Finished Russian wording for one resource kind."""

    nominative: str
    found: str
    specified: str
    genitive_plural: str
    match_phrase: str = "с именем"

    @property
    def capitalized(self) -> str:
        return self.nominative[:1].upper() + self.nominative[1:]

    def not_found(self, name: str | None = None) -> str:
        if name:
            return f"{self.capitalized} «{name}» не {self.found}."
        return f"{self.capitalized} не {self.found}."

    def not_specified(self) -> str:
        return f"Не {self.specified} {self.nominative}."

    def ambiguous(self, name: str, count: int | None = None) -> str:
        number = f" ({count})" if count else ""
        return f"Найдено несколько{number} {self.genitive_plural} {self.match_phrase} «{name}»."

    def without_id(self, name: str) -> str:
        return f"{self.capitalized} «{name}» {self.found}, но без ID."


def _words(
    nominative: str,
    found: str,
    specified: str,
    genitive_plural: str,
    match_phrase: str = "с именем",
) -> ResourceWords:
    return ResourceWords(nominative, found, specified, genitive_plural, match_phrase)


RESOURCES: dict[str, ResourceWords] = {
    "задача": _words("задача", "найдена", "указана", "задач"),
    "доска": _words("доска", "найдена", "указана", "досок"),
    "колонка": _words("колонка", "найдена", "указана", "колонок"),
    "проект": _words("проект", "найден", "указан", "проектов"),
    "отдел": _words("отдел", "найден", "указан", "отделов"),
    "стикер": _words("стикер", "найден", "указан", "стикеров"),
    "строковый стикер": _words("строковый стикер", "найден", "указан", "строковых стикеров"),
    "стикер-спринт": _words("стикер-спринт", "найден", "указан", "стикеров-спринтов"),
    "чат": _words("чат", "найден", "указан", "чатов"),
    "вебхук": _words("вебхук", "найден", "указан", "вебхуков"),
    "сотрудник": _words("сотрудник", "найден", "указан", "сотрудников", "по запросу"),
    "роль": _words("роль", "найдена", "указана", "ролей"),
    "компания": _words("компания", "найдена", "указана", "компаний"),
    "файл": _words("файл", "найден", "указан", "файлов"),
    "вложение": _words("вложение", "найдено", "указано", "вложений"),
    "объект": _words("объект", "найден", "указан", "объектов"),
}

_FALLBACK = RESOURCES["объект"]


def resource_words(kind: str | ResourceWords | None) -> ResourceWords:
    """Look a resource up by its Russian name; unknown kinds get neutral wording."""
    if isinstance(kind, ResourceWords):
        return kind
    if not kind:
        return _FALLBACK
    return RESOURCES.get(kind.strip().casefold(), _FALLBACK)


def not_found_message(kind: str | ResourceWords, name: str | None = None) -> str:
    return resource_words(kind).not_found(name)


def not_specified_message(kind: str | ResourceWords) -> str:
    return resource_words(kind).not_specified()


def ambiguous_message(kind: str | ResourceWords, name: str, count: int | None = None) -> str:
    return resource_words(kind).ambiguous(name, count)


def single_name(
    positional: str | None,
    option: str | None,
    *,
    genitive: str,
    flag: str = "--title",
    hint: str | None = None,
) -> str:
    """The name of a new object: positional argument or flag, but not two different ones."""
    if positional is not None and option is not None and positional.strip() != option.strip():
        raise ValidationError(
            f"Название задано дважды и по-разному: «{positional}» и {flag} «{option}».",
            hint=f"Оставьте что-то одно: позиционный аргумент или {flag}.",
        )
    value = positional if positional is not None else option
    if value is None or not value.strip():
        raise ValidationError(
            f"Не указано название {genitive}.",
            hint=hint or f"Передайте название позиционным аргументом или флагом {flag}.",
        )
    return value


def not_found_error(
    kind: str | ResourceWords,
    name: str | None = None,
    *,
    hint: str | None = None,
) -> ResolveError:
    """Ready-to-raise «Доска «X» не найдена.» for a resource kind."""
    return ResolveError(not_found_message(kind, name), hint=hint)


def ambiguous_error(
    kind: str | ResourceWords,
    name: str,
    candidates: list[dict[str, Any]] | None = None,
    *,
    hint: str | None = None,
    count: int | None = None,
) -> AmbiguousNameError:
    """Ready-to-raise «Найдено несколько досок с именем «X».» for a resource kind."""
    items = candidates or []
    return AmbiguousNameError(
        ambiguous_message(kind, name, count if count is not None else len(items) or None),
        hint=hint if hint is not None else "Уточните имя или укажите ID.",
        candidates=items,
    )


def exit_code_for(exc: BaseException | None) -> int:
    """Map an exception to the process exit code (0 when there is no error)."""
    if exc is None:
        return EXIT_OK
    if isinstance(exc, KeyboardInterrupt):
        return EXIT_INTERRUPT
    if isinstance(exc, YouGileError):
        return exc.exit_code
    return EXIT_ERROR


def format_error(exc: BaseException) -> str:
    """gh-style stderr text: `ошибка: …` plus an optional hint line."""
    lines = [f"ошибка: {exc}"]
    hint = getattr(exc, "hint", None)
    if hint:
        lines.append(f"подсказка: {hint}")
    return "\n".join(lines)
