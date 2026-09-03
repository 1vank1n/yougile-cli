"""Shared pytest fixtures for yougile-cli.

Every test module in this suite can rely on the fixtures below. Nothing here
ever touches the network and nothing ever reads the developer's real config:
``YOUGILE_CONFIG_DIR`` always points at a per-test ``tmp_path``.

Fixtures
--------
``isolated_config`` (autouse)
    Points ``YOUGILE_CONFIG_DIR`` at ``tmp_path/"config"`` and clears
    ``YOUGILE_TOKEN`` / ``YOUGILE_API_KEY`` / ``YOUGILE_HOST`` / ``NO_COLOR`` /
    ``CLICOLOR_FORCE``. Yields the config directory ``Path``.

``guard_config_dir`` (autouse)
    Fails the test outright when ``YOUGILE_CONFIG_DIR`` is unset or points
    outside a temporary directory: a run once wrote into the developer's real
    ``config.yml``.

``no_sleep`` (autouse)
    Makes ``time.sleep`` inside the client a no-op, so retry backoff and the
    rate limiter never slow the suite down.

``api``
    ``respx`` router bound to ``https://yougile.com`` with
    ``assert_all_called=False``. Register routes like::

        api.get("/api-v2/projects").respond(json=paged([{"id": "p1"}]))

``client``
    ``YouGileClient(api_key="test-key", base_url="https://yougile.com")`` with
    zero backoff. Closed automatically.

``logged_in``
    Writes a valid ``hosts.yml`` into the temp config dir and returns the
    ``HostUser`` it stored (``api_key="test-key"``, ``ivan@example.com``,
    host ``yougile.com``).

``run``
    ``run(args, input=None, token="test-key", env=None) -> click Result``.
    Runs the real Typer app through ``CliRunner``; the CLI module is imported
    lazily inside the call. ``token=None`` runs unauthenticated. ``Result.output``
    mixes stdout and stderr; ``Result.stdout`` / ``Result.stderr`` are separate.

``runner``
    A bare ``typer.testing.CliRunner``.

``paged``
    ``paged(items, limit=1000, offset=0, count=None, next_page=False)`` builds a
    ``{"paging": {...}, "content": [...]}`` list body.
"""

from __future__ import annotations

import importlib
import os
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import respx
from typer.testing import CliRunner

from yougile_cli.client import YouGileClient

BASE_URL = "https://yougile.com"
HOST = "yougile.com"
TEST_KEY = "test-key"
TEST_EMAIL = "ivan@example.com"

ENV_VARS = (
    "YOUGILE_TOKEN",
    "YOUGILE_API_KEY",
    "YOUGILE_HOST",
    "NO_COLOR",
    "CLICOLOR_FORCE",
)


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Never read or write the developer's real configuration."""
    config_home = tmp_path / "config"
    config_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("YOUGILE_CONFIG_DIR", str(config_home))
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return config_home


@pytest.fixture(autouse=True)
def guard_config_dir(isolated_config: Path, tmp_path: Path) -> None:
    """No test may reach the developer's real configuration — not even to read it."""
    value = (os.environ.get("YOUGILE_CONFIG_DIR") or "").strip()
    if not value:
        pytest.fail("YOUGILE_CONFIG_DIR не задан: тест писал бы в реальный конфиг пользователя.")
    resolved = Path(value).expanduser().resolve()
    allowed = (tmp_path.resolve(), Path(tempfile.gettempdir()).resolve())
    if not any(resolved == root or resolved.is_relative_to(root) for root in allowed):
        pytest.fail(
            f"YOUGILE_CONFIG_DIR={resolved} вне временного каталога: "
            "тест может испортить реальный конфиг."
        )


@pytest.fixture(autouse=True)
def reset_color_override() -> Iterator[None]:
    """`--no-color` sets a process-global override; it must not leak between tests."""
    from yougile_cli.output import set_color_override

    set_color_override(None)
    yield
    set_color_override(None)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry/rate-limit backoff must not slow the suite down."""
    monkeypatch.setattr("yougile_cli.client.time.sleep", lambda *_a, **_k: None)


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
def client() -> Iterator[YouGileClient]:
    with YouGileClient(
        api_key=TEST_KEY, base_url=BASE_URL, max_retries=3, backoff_factor=0.0
    ) as instance:
        yield instance


@pytest.fixture
def logged_in(isolated_config: Path) -> Any:
    """A ready hosts.yml with one active account."""
    from yougile_cli.config import Host, Hosts, HostUser, save_hosts

    user = HostUser(
        api_key=TEST_KEY,
        user_id="11111111-1111-4111-8111-111111111111",
        real_name="Иван Лукьянец",
        email=TEST_EMAIL,
        company_id="22222222-2222-4222-8222-222222222222",
        company_name="Моя компания",
    )
    save_hosts(Hosts({HOST: Host(active_user=TEST_EMAIL, users={TEST_EMAIL: user})}))
    return user


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> Callable[..., Any]:
    """Invoke the real Typer app; returns the click ``Result``."""

    def _run(
        args: list[str] | str,
        *,
        input: str | None = None,
        token: str | None = TEST_KEY,
        env: dict[str, str] | None = None,
    ) -> Any:
        if token is None:
            monkeypatch.delenv("YOUGILE_TOKEN", raising=False)
        else:
            monkeypatch.setenv("YOUGILE_TOKEN", token)
        for key, value in (env or {}).items():
            monkeypatch.setenv(key, value)
        argv = args.split() if isinstance(args, str) else list(args)
        cli = importlib.import_module("yougile_cli.cli")
        return runner.invoke(cli.app, cli.expand_argv(argv), input=input)

    return _run


@pytest.fixture
def paged() -> Callable[..., dict[str, Any]]:
    def _paged(
        items: list[dict[str, Any]],
        *,
        limit: int = 1000,
        offset: int = 0,
        count: int | None = None,
        next_page: bool = False,
    ) -> dict[str, Any]:
        return {
            "paging": {
                "count": len(items) if count is None else count,
                "limit": limit,
                "offset": offset,
                "next": next_page,
            },
            "content": items,
        }

    return _paged
