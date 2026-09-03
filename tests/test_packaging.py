"""Заявленные зависимости: объявленный минимум должен на деле запускать CLI."""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest

# 0.26 — первый typer с вендоренным click (`typer._click`), который патчит i18n;
# на 0.12–0.13 приложение вообще не собирается, на 0.13–0.25 интерфейс английский.
MIN_TYPER = (0, 26)


def _requirements() -> list[str]:
    root = Path(__file__).resolve().parents[1]
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():  # pragma: no cover - установленный пакет без исходников
        pytest.skip("нет pyproject.toml")
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return list(data["project"]["dependencies"])


def _spec(name: str) -> str:
    for item in _requirements():
        if item.split(">=")[0].split("<")[0].split("[")[0].strip() == name:
            return item
    raise AssertionError(f"{name} нет в зависимостях")


def test_typer_floor_is_a_version_that_runs_the_cli() -> None:
    spec = _spec("typer")
    floor = spec.split(">=", 1)[1].split(",", 1)[0].strip()
    parts = tuple(int(piece) for piece in floor.split(".")[:2])
    assert parts >= MIN_TYPER, spec
    assert "<" in spec, f"нужен верхний предел: {spec}"


def test_installed_typer_matches_the_declared_floor() -> None:
    import typer

    installed = tuple(int(piece) for piece in typer.__version__.split(".")[:2])
    assert installed >= MIN_TYPER
    assert importlib.import_module("typer._click") is not None
