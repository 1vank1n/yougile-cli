"""Метаданные упаковки: зависимости, обещания pyproject дистрибутиву и релизный workflow."""

from __future__ import annotations

import importlib
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

# 0.26 — первый typer с вендоренным click (`typer._click`), который патчит i18n;
# на 0.12–0.13 приложение вообще не собирается, на 0.13–0.25 интерфейс английский.
MIN_TYPER = (0, 26)


ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict[str, Any]:
    pyproject = ROOT / "pyproject.toml"
    if not pyproject.exists():  # pragma: no cover - установленный пакет без исходников
        pytest.skip("нет pyproject.toml")
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))


def _requirements() -> list[str]:
    return list(_pyproject()["project"]["dependencies"])


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


def test_version_is_dynamic_and_read_from_the_package_module() -> None:
    data = _pyproject()
    project = data["project"]
    assert "version" in project.get("dynamic", []), "version должна быть в dynamic"
    assert "version" not in project, "статический version вернули в [project]"
    path = data["tool"]["hatch"]["version"]["path"]
    assert path == "src/yougile_cli/__init__.py"
    module = ROOT / path
    assert module.exists(), f"{path} не существует — hatchling не найдёт версию"
    source = module.read_text(encoding="utf-8")
    assert re.search(r"^__version__\s*=", source, re.MULTILINE), f"в {path} нет __version__"


# Сборкой артефакта эти два утверждения не проверяются, и это осознанный пробел:
# `uv build` здесь падает на глобальном `~/.python-version` (2.7.18) до запуска
# бэкенда, а самого hatchling в dev-зависимостях нет — собрать колесо внутри теста
# нечем, новых зависимостей таск не заводит. Поэтому НЕ покрыты тестом ровно два
# отказа: py.typed не попал в колесо и CHANGELOG/CONTRIBUTING/docs не попали в
# sdist. Их ловит задача `build` в CI, которая смотрит внутрь dist/.
def test_py_typed_marker_sits_next_to_the_package_init() -> None:
    package = ROOT / "src" / "yougile_cli"
    assert (package / "__init__.py").exists()
    marker = package / "py.typed"
    assert marker.exists(), "PEP 561: без py.typed потребитель видит Any вместо типов"
    assert marker.read_bytes() == b""


# Из спецификации 0.2.0, §«Состав sdist»: обязательный минимум архива — мейнтейнеру
# дистрибутива нужны история изменений и справочник по командам. Список открыт:
# добавить в include что-то ещё можно, потерять эти семь — нет.
SDIST_MUST_INCLUDE = (
    "/src",
    "/tests",
    "/README.md",
    "/LICENSE",
    "/CHANGELOG.md",
    "/CONTRIBUTING.md",
    "/docs",
)


def test_sdist_include_keeps_the_required_minimum_and_matches_the_repository() -> None:
    include = _pyproject()["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    missing = [entry for entry in SDIST_MUST_INCLUDE if entry not in include]
    assert not missing, f"выпали из include: {missing}"
    for entry in include:
        assert (ROOT / entry.lstrip("/")).exists(), f"{entry} в include, но нет в репозитории"


# Публикующий action PyPA — единственный поддерживаемый способ Trusted Publishing;
# по нему и опознаётся публикующий job, чтобы тест не зависел от его имени.
PYPI_PUBLISH_ACTION = "pypa/gh-action-pypi-publish"


def _release_workflow() -> dict[str, Any]:
    workflow = ROOT / ".github" / "workflows" / "release.yml"
    if not workflow.exists():  # pragma: no cover - установленный пакет без исходников
        pytest.skip("нет .github/workflows/release.yml")
    data: dict[str, Any] = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    return data


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return list(job.get("steps") or [])


def _uses(job: dict[str, Any], needle: str) -> list[dict[str, Any]]:
    return [step for step in _steps(job) if needle in str(step.get("uses", ""))]


def _runs(job: dict[str, Any], needle: str) -> list[dict[str, Any]]:
    return [step for step in _steps(job) if needle in str(step.get("run", ""))]


def test_release_publishes_to_pypi_after_the_release_job_and_without_a_password() -> None:
    jobs = _release_workflow()["jobs"]
    publishing = {name: job for name, job in jobs.items() if _uses(job, PYPI_PUBLISH_ACTION)}
    assert list(publishing) and len(publishing) == 1, (
        f"ожидался ровно один публикующий job: {list(publishing)}"
    )
    job = next(iter(publishing.values()))

    needs = job.get("needs") or []
    if isinstance(needs, str):
        needs = [needs]
    assert needs, "публикация без needs стартует параллельно проверкам и заливает непроверенное"
    for dependency in needs:
        assert dependency in jobs, f"needs ссылается на несуществующий job {dependency}"

    permissions = job.get("permissions") or {}
    assert permissions.get("id-token") == "write", "без id-token: write OIDC не выдаст токен PyPI"
    assert "contents" not in permissions, "публикующему job'у нечего писать в репозиторий"

    text = yaml.safe_dump(job, allow_unicode=True)
    for forbidden in ("password", "secrets.", "PYPI_API_TOKEN"):
        assert forbidden not in text, (
            f"в публикующем job'е появился {forbidden}: аутентификация только по OIDC"
        )

    publish_step = _uses(job, PYPI_PUBLISH_ACTION)[0]
    assert (publish_step.get("with") or {}).get("skip-existing") is True, (
        "без skip-existing перезапуск релиза на залитой версии красит workflow"
    )

    assert _uses(job, "download-artifact"), (
        "публикуются артефакты сборки, а не пересобранные заново"
    )
    assert not _uses(job, "build-and-verify")
    assert not _runs(job, "uv build")

    gate = jobs[needs[0]]
    build = _uses(gate, "build-and-verify")[0]
    assert (build.get("with") or {}).get("artifact-name"), (
        "релизный job обязан выгрузить dist, иначе публикующему нечего скачивать"
    )
