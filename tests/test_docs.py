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
