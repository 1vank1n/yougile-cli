from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from yougile_cli.config import (
    DEFAULT_HOST,
    ENV_CONFIG_DIR,
    Host,
    Hosts,
    HostUser,
    cache_dir,
    config_dir,
    delete_alias,
    get_alias,
    get_setting,
    host_to_base_url,
    host_to_web_url,
    hosts_path,
    list_accounts,
    list_aliases,
    list_settings,
    load_hosts,
    load_settings,
    login_user,
    logout_user,
    migrate_legacy_config,
    normalize_host,
    resolve_auth,
    save_hosts,
    set_alias,
    set_setting,
    settings_path,
    switch_user,
)
from yougile_cli.errors import EXIT_AUTH, EXIT_USAGE, AuthError, ConfigError, ValidationError

OTHER = "other@example.com"


def _user(email: str, key: str) -> HostUser:
    return HostUser(api_key=key, email=email, real_name=email.split("@")[0])


def test_config_dir_follows_env(isolated_config: Path) -> None:
    assert config_dir() == isolated_config
    assert hosts_path().name == "hosts.yml"
    assert settings_path().name == "config.yml"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://YouGile.com/", "yougile.com"),
        ("http://my.server/api", "my.server"),
        ("yougile.com", "yougile.com"),
        ("  ", ""),
        (None, ""),
    ],
)
def test_normalize_host(raw: str | None, expected: str) -> None:
    assert normalize_host(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["yougile.com@evil.tld", "yougile com", "yougile.com:port", "yougile_com"],
)
def test_normalize_host_rejects_foreign_hosts(raw: str) -> None:
    """A userinfo "@" would silently redirect requests and credentials elsewhere."""
    with pytest.raises(ValidationError):
        normalize_host(raw)


def test_host_to_base_url_defaults() -> None:
    assert host_to_base_url(None) == "https://yougile.com"
    assert host_to_base_url("https://my.server/") == "https://my.server"


def test_host_to_web_url_defaults() -> None:
    # Ссылка сохраняет хост, на котором выполнен вход: UI отдают и yougile.com, и зеркало.
    assert host_to_web_url(None) == "https://yougile.com"
    assert host_to_web_url("yougile.com") == "https://yougile.com"
    assert host_to_web_url("ru.yougile.com") == "https://ru.yougile.com"
    assert host_to_web_url("my.server") == "https://my.server"


def test_write_to_unwritable_dir_is_config_error(isolated_config: Path) -> None:
    isolated_config.chmod(0o500)
    try:
        with pytest.raises(ConfigError):
            set_setting("output", "json")
    finally:
        isolated_config.chmod(0o700)


def test_save_hosts_is_atomic_and_private(logged_in: HostUser) -> None:
    path = hosts_path()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(path.parent.glob(".hosts.yml-*"))
    hosts = load_hosts()
    assert hosts[DEFAULT_HOST].active_user == logged_in.email
    assert hosts[DEFAULT_HOST].users[str(logged_in.email)].api_key == "test-key"


def test_load_hosts_missing_file_is_empty() -> None:
    assert load_hosts().root == {}


def test_load_hosts_rejects_garbage() -> None:
    hosts_path().write_text("- not a mapping\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_hosts()


def test_resolve_auth_precedence_flag_beats_env(
    logged_in: HostUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YOUGILE_TOKEN", "from-env")
    auth = resolve_auth(token="from-flag")
    assert auth.api_key == "from-flag"
    assert auth.source == "flag"


def test_resolve_auth_token_beats_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUGILE_TOKEN", "t")
    monkeypatch.setenv("YOUGILE_API_KEY", "k")
    assert resolve_auth().api_key == "t"


def test_resolve_auth_api_key_env_used_when_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUGILE_API_KEY", "k")
    auth = resolve_auth()
    assert (auth.api_key, auth.source) == ("k", "YOUGILE_API_KEY")


def test_resolve_auth_falls_back_to_hosts_file(logged_in: HostUser) -> None:
    auth = resolve_auth()
    assert auth.api_key == "test-key"
    assert auth.source == "hosts.yml"
    assert auth.user_email == "ivan@example.com"
    assert auth.company_name == "Моя компания"
    assert auth.base_url == "https://yougile.com"
    assert auth.authenticated is True


def test_resolve_auth_without_key_is_anonymous() -> None:
    auth = resolve_auth()
    assert auth.api_key is None
    assert auth.host == DEFAULT_HOST
    assert auth.authenticated is False


def test_resolve_auth_require_key_raises_auth_error() -> None:
    with pytest.raises(AuthError) as excinfo:
        resolve_auth(require_key=True)
    assert excinfo.value.exit_code == EXIT_AUTH
    assert excinfo.value.hint == "Выполните: yougile auth login"


def test_resolve_auth_host_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    save_hosts(
        Hosts({"only.host": Host(active_user="a@b.c", users={"a@b.c": _user("a@b.c", "k")})})
    )
    assert resolve_auth().host == "only.host"  # single configured host
    monkeypatch.setenv("YOUGILE_HOST", "env.host")
    assert resolve_auth().host == "env.host"
    assert resolve_auth(hostname="https://flag.host/").host == "flag.host"


def test_login_logout_switch_and_list_accounts() -> None:
    login_user(DEFAULT_HOST, _user("ivan@example.com", "k1"))
    login_user(DEFAULT_HOST, _user(OTHER, "k2"), make_active=False)

    accounts = list_accounts()
    assert {a["email"] for a in accounts} == {"ivan@example.com", OTHER}
    assert [a["email"] for a in accounts if a["active"]] == ["ivan@example.com"]

    switch_user(DEFAULT_HOST, OTHER)
    assert resolve_auth().api_key == "k2"

    assert logout_user(DEFAULT_HOST, OTHER) is True
    assert resolve_auth().api_key == "k1"
    assert logout_user(DEFAULT_HOST, "nobody@example.com") is False

    assert logout_user(DEFAULT_HOST) is True
    assert load_hosts().root == {}


def test_switch_user_unknown_account_raises() -> None:
    login_user(DEFAULT_HOST, _user("ivan@example.com", "k1"))
    with pytest.raises(ConfigError):
        switch_user(DEFAULT_HOST, "ghost@example.com")


def test_resolve_auth_named_user(logged_in: HostUser) -> None:
    login_user(DEFAULT_HOST, _user(OTHER, "k2"), make_active=False)
    assert resolve_auth(user=OTHER).api_key == "k2"


def test_settings_roundtrip_and_defaults() -> None:
    defaults = load_settings()
    assert (defaults.version, defaults.output, defaults.prompt) == ("1", "table", "enabled")

    set_setting("output", "json")
    assert get_setting("output") == "json"
    assert stat.S_IMODE(settings_path().stat().st_mode) == 0o644
    assert list_settings()["output"] == "json"


def test_settings_reject_unknown_key() -> None:
    with pytest.raises(ValidationError) as excinfo:
        set_setting("nonsense", "1")
    assert excinfo.value.exit_code == EXIT_USAGE
    with pytest.raises(ValidationError):
        get_setting("nonsense")


def test_dotted_alias_keys() -> None:
    set_setting("aliases.mine", "task list --assignee @me")
    assert get_setting("aliases.mine") == "task list --assignee @me"
    assert list_settings()["aliases.mine"] == "task list --assignee @me"
    assert get_alias("mine") == "task list --assignee @me"

    set_alias("bugs", "task list --search bug")
    assert set(list_aliases()) == {"mine", "bugs"}
    assert delete_alias("bugs") is True
    assert delete_alias("bugs") is False
    assert get_alias("bugs") is None


def test_migrates_legacy_config_json(isolated_config: Path) -> None:
    legacy = isolated_config / "config.json"
    legacy.write_text(
        json.dumps(
            {
                "current_profile": "default",
                "profiles": {
                    "default": {
                        "api_key": "legacy-key",
                        "base_url": "https://yougile.com",
                        "login": "old@example.com",
                        "company_id": "c1",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert migrate_legacy_config() is True
    auth = resolve_auth()
    assert auth.api_key == "legacy-key"
    assert auth.user_email == "old@example.com"
    assert auth.company_id == "c1"
    # A second run must be a no-op, never a crash.
    assert migrate_legacy_config() is False


def test_migration_keeps_every_profile_key(isolated_config: Path) -> None:
    """Two legacy profiles must not collapse onto one hosts.yml entry."""
    (isolated_config / "config.json").write_text(
        json.dumps(
            {
                "current_profile": "personal",
                "profiles": {
                    "work": {"api_key": "AAA"},
                    "personal": {"api_key": "BBB"},
                },
            }
        ),
        encoding="utf-8",
    )
    assert migrate_legacy_config() is True
    users = load_hosts().root["yougile.com"].users
    assert {user.api_key for user in users.values()} == {"AAA", "BBB"}


def test_corrupt_hosts_file_hints_at_repair(isolated_config: Path) -> None:
    hosts_path().write_text('yougile.com:\n  users:\n    a@b.c: "notadict"\n', encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_hosts()
    assert "auth login" not in (excinfo.value.hint or "")


def test_corrupt_file_message_stays_one_line(isolated_config: Path) -> None:
    """Пользователя нельзя отправлять читать errors.pydantic.dev (дефект №12)."""
    hosts_path().write_text('yougile.com: "not a mapping"\n', encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_hosts()
    message = str(excinfo.value)
    assert "errors.pydantic.dev" not in message
    assert "\n" not in message
    assert "yougile.com" in message

    settings_path().write_text("pager: 42\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_settings()
    assert "errors.pydantic.dev" not in str(excinfo.value)
    assert "\n" not in str(excinfo.value)
    assert excinfo.value.hint

    settings_path().write_text("aliases:\n  - [unbalanced\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_settings()
    assert "\n" not in str(excinfo.value)


def test_migration_never_crashes_on_broken_legacy_file(isolated_config: Path) -> None:
    (isolated_config / "config.json").write_text("{not json", encoding="utf-8")
    assert migrate_legacy_config() is False
    assert load_hosts().root == {}


# ------------------------------------------------- изоляция конфига под pytest (№7)


def test_config_dir_refuses_the_real_directory_under_pytest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Прогон агента однажды записал output: json в реальный ~/.config пользователя."""
    monkeypatch.delenv(ENV_CONFIG_DIR, raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_config.py::test (call)")
    with pytest.raises(ConfigError) as excinfo:
        config_dir()
    assert ENV_CONFIG_DIR in str(excinfo.value)


def test_config_dir_uses_platform_dir_outside_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_CONFIG_DIR, raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert config_dir().name == "yougile"


def test_cache_dir_lives_inside_the_config_dir(isolated_config: Path) -> None:
    assert cache_dir() == isolated_config / "cache"
