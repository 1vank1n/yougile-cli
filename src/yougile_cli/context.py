"""Per-invocation application context stored in ``typer.Context.obj``.

The HTTP client is built lazily so that ``auth``, ``config``, ``version`` and
``--help`` keep working with no API key configured; asking for the client
without a key is what raises :class:`AuthError` (exit code 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import typer
from rich.console import Console

from .client import YouGileClient
from .config import DEFAULT_HOST as _DEFAULT_HOST
from .config import ResolvedAuth, Settings, host_to_base_url
from .errors import LOGIN_HINT, AuthError, ConfigError
from .output import OutputFormat, OutputOptions, render
from .output import get_console as _get_console

__all__ = ["AppContext", "ctx_client", "emit", "get_client", "get_ctx"]


def _default_auth() -> ResolvedAuth:
    return ResolvedAuth(host=_DEFAULT_HOST, base_url=host_to_base_url(_DEFAULT_HOST))


@dataclass
class AppContext:
    """Everything a command needs for one run."""

    auth: ResolvedAuth = field(default_factory=_default_auth)
    out: OutputOptions = field(default_factory=OutputOptions)
    settings: Settings = field(default_factory=Settings)
    console: Console = field(default_factory=_get_console)
    err_console: Console = field(default_factory=lambda: _get_console(stderr=True))
    prompt_enabled: bool = True
    quiet: bool = False
    _client: YouGileClient | None = field(default=None, repr=False)

    @property
    def fmt(self) -> OutputFormat:
        return self.out.fmt

    @property
    def host(self) -> str:
        return self.auth.host

    def client(self) -> YouGileClient:
        """Build the HTTP client on first use; require a key at that moment."""
        if self._client is None:
            if not self.auth.api_key:
                raise AuthError(f"Вход на {self.auth.host} не выполнен.", hint=LOGIN_HINT)
            self._client = YouGileClient(
                api_key=self.auth.api_key,
                base_url=self.auth.base_url,
                host=self.auth.host,
            )
        return self._client

    def set_client(self, client: YouGileClient) -> None:
        """Inject a ready client (tests, `auth login` reusing an open session)."""
        self._client = client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def emit(self, data: Any, columns: list[str] | None = None) -> None:
        emit(self, data, columns)


def get_ctx(ctx: typer.Context | AppContext) -> AppContext:
    """Fetch the AppContext out of a typer context (or pass one through)."""
    if isinstance(ctx, AppContext):
        return ctx
    obj = getattr(ctx, "obj", None)
    if not isinstance(obj, AppContext):
        raise ConfigError(
            "Контекст приложения не инициализирован.",
            hint="Запускайте команды через `yougile ...`, а не импортируя модуль напрямую.",
        )
    return obj


def ctx_client(ctx: typer.Context | AppContext) -> YouGileClient:
    """The lazily built client; raises AuthError (exit 4) when no key is set."""
    return get_ctx(ctx).client()


# Backwards-compatible alias used by the command modules.
get_client = ctx_client


def emit(
    ctx: typer.Context | AppContext,
    data: Any,
    columns: list[str] | None = None,
) -> None:
    """Render `data` with the output flags this invocation was given."""
    app = get_ctx(ctx)
    if app.quiet and app.out.fmt is OutputFormat.TABLE and not app.out.json_fields:
        return
    render(data, app.out, columns=columns, console=app.console)
