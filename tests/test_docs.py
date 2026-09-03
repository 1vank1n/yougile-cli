"""Guards for the repository files a first-time user reads or a publish would leak."""

from __future__ import annotations

import re
from pathlib import Path

from yougile_cli import config

ROOT = Path(__file__).resolve().parents[1]

SUPPORTED_ENV = {
    config.ENV_TOKEN,
    config.ENV_API_KEY,
    config.ENV_HOST,
    config.ENV_CONFIG_DIR,
    "YOUGILE_EDITOR",
}


def test_env_example_lists_only_variables_the_cli_reads() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    names = set(re.findall(r"^(YOUGILE_[A-Z_]+)=", text, re.M))
    assert names
    assert names <= SUPPORTED_ENV


def test_gitignore_covers_the_files_the_cli_writes() -> None:
    lines = {
        line.strip().lstrip("/")
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    }
    assert {"config.yml", "hosts.yml", "cache/"} <= lines


def test_no_stray_config_in_the_repository_root() -> None:
    assert not (ROOT / "config.yml").exists()
    assert not (ROOT / "hosts.yml").exists()


def test_readme_documents_every_setting_and_env_var() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for key in config.SETTING_KEYS:
        assert key in readme
    for name in SUPPORTED_ENV:
        assert name in readme


def test_readme_offers_the_pypi_install_before_the_git_one() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    pypi = readme.index("uv tool install yougile-cli")
    assert "pipx install yougile-cli" in readme
    assert "pip install yougile-cli" in readme
    git_lines = [line for line in readme.splitlines() if "git+https://" in line]
    assert len(git_lines) == 1
    assert "неопубликованная версия" in git_lines[0].lower()
    assert "`main`" in git_lines[0]
    assert pypi < readme.index(git_lines[0])


def test_readme_links_are_absolute_so_pypi_does_not_resolve_them_against_itself() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    targets = re.findall(r"\]\(([^)\s]+)", readme)
    assert targets
    relative = [t for t in targets if not t.startswith(("http://", "https://", "mailto:", "#"))]
    assert relative == []
