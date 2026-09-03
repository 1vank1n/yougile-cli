"""On-disk configuration in the GitHub CLI layout.

Two YAML files live in ``config_dir()``:

* ``hosts.yml``  — credentials, mode 0600, written atomically::

      yougile.com:
        active_user: ivan@example.com
        users:
          ivan@example.com:
            api_key: "…"
            user_id: "…"
            real_name: "Иван Лукьянец"
            company_id: "…"
            company_name: "Моя компания"

* ``config.yml`` — settings and aliases (``version``, ``output``, ``prompt``,
  ``aliases``).

Source precedence, strictly: command-line flag → environment variable →
``hosts.yml`` / ``config.yml`` → built-in default.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from platformdirs import user_config_dir
from pydantic import BaseModel, Field, RootModel
from pydantic import ValidationError as PydanticValidationError

from .errors import LOGIN_HINT, AuthError, ConfigError, ValidationError

__all__ = [
    "DEFAULT_HOST",
    "WEB_HOST",
    "DEFAULT_OUTPUT",
    "ENV_API_KEY",
    "ENV_CONFIG_DIR",
    "ENV_HOST",
    "ENV_TOKEN",
    "SETTING_KEYS",
    "Host",
    "HostUser",
    "Hosts",
    "ResolvedAuth",
    "Settings",
    "cache_dir",
    "config_dir",
    "delete_alias",
    "get_alias",
    "get_setting",
    "host_to_base_url",
    "host_to_web_url",
    "hosts_path",
    "list_accounts",
    "list_aliases",
    "list_settings",
    "load_hosts",
    "load_settings",
    "login_user",
    "logout_user",
    "migrate_legacy_config",
    "normalize_host",
    "resolve_auth",
    "save_hosts",
    "save_settings",
    "set_alias",
    "set_setting",
    "settings_path",
    "switch_user",
    "write_atomic",
]

DEFAULT_HOST = "yougile.com"
WEB_HOST = "ru.yougile.com"
DEFAULT_OUTPUT = "table"

ENV_TOKEN = "YOUGILE_TOKEN"
ENV_API_KEY = "YOUGILE_API_KEY"
ENV_HOST = "YOUGILE_HOST"
ENV_CONFIG_DIR = "YOUGILE_CONFIG_DIR"
ENV_PYTEST = "PYTEST_CURRENT_TEST"

SETTING_KEYS = ("version", "output", "prompt")


# --------------------------------------------------------------------------- models


class HostUser(BaseModel):
    """One authenticated account on one host."""

    api_key: str
    user_id: str | None = None
    real_name: str | None = None
    email: str | None = None
    company_id: str | None = None
    company_name: str | None = None


class Host(BaseModel):
    """All accounts known for a single host, plus the active one."""

    active_user: str | None = None
    users: dict[str, HostUser] = Field(default_factory=dict)


class Hosts(RootModel[dict[str, Host]]):
    """``hosts.yml`` as a whole: hostname -> Host."""

    root: dict[str, Host] = Field(default_factory=dict)

    def __contains__(self, host: str) -> bool:
        return host in self.root

    def __getitem__(self, host: str) -> Host:
        return self.root[host]

    def __iter__(self) -> Any:
        return iter(self.root)

    def get(self, host: str) -> Host | None:
        return self.root.get(host)

    def hostnames(self) -> list[str]:
        return list(self.root)


class Settings(BaseModel):
    """``config.yml``: defaults and aliases.

    Extra keys are ignored on purpose (no ``extra="forbid"``): files written by
    older versions carry settings that no longer exist, and loading must not fail
    on them.
    """

    version: str = "1"
    output: str = DEFAULT_OUTPUT
    prompt: str = "enabled"
    aliases: dict[str, str] = Field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedAuth:
    """The credentials one CLI invocation will actually use."""

    host: str
    base_url: str
    api_key: str | None = None
    user_email: str | None = None
    user_id: str | None = None
    real_name: str | None = None
    company_id: str | None = None
    company_name: str | None = None
    source: str = "none"

    @property
    def authenticated(self) -> bool:
        return bool(self.api_key)


# --------------------------------------------------------------------------- paths


def config_dir() -> Path:
    """Config directory, overridable with ``YOUGILE_CONFIG_DIR``."""
    override = (os.environ.get(ENV_CONFIG_DIR) or "").strip()
    if override:
        return Path(override).expanduser()
    if os.environ.get(ENV_PYTEST):
        # A test run once wrote `output: json` into the developer's real config.
        # Under pytest the real directory is off limits, no exceptions.
        raise ConfigError(
            f"Под pytest каталог настроек обязан задаваться через {ENV_CONFIG_DIR}.",
            hint=f"Например: {ENV_CONFIG_DIR}=$(mktemp -d).",
        )
    return Path(user_config_dir("yougile"))


def cache_dir() -> Path:
    """Local cache directory; `yougile config clear-cache` removes exactly this one."""
    return config_dir() / "cache"


def hosts_path() -> Path:
    return config_dir() / "hosts.yml"


def settings_path() -> Path:
    return config_dir() / "config.yml"


_HOST_RE = re.compile(
    r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*(:\d{1,5})?$"
)


def normalize_host(value: str | None) -> str:
    """``https://YouGile.com/`` -> ``yougile.com``; empty stays empty."""
    text = (value or "").strip()
    if not text:
        return ""
    for scheme in ("https://", "http://"):
        if text.lower().startswith(scheme):
            text = text[len(scheme) :]
            break
    text = text.split("/", 1)[0]
    text = text.strip().strip(".").lower()
    # A userinfo "@" or any stray character would silently redirect requests (and credentials)
    # to a foreign host once interpolated into the base URL.
    if text and not _HOST_RE.match(text):
        raise ValidationError(
            f"Недопустимое имя хоста «{value}».",
            hint="Укажите только имя хоста, например yougile.com.",
        )
    return text


def host_to_base_url(host: str | None) -> str:
    """Hostname -> API base URL. Everything else in the app appends /api-v2/…."""
    name = normalize_host(host) or DEFAULT_HOST
    return f"https://{name}"


def host_to_web_url(host: str | None) -> str:
    """Hostname -> board UI base URL.

    Both yougile.com and the ru. mirror serve the board UI, so the link keeps the
    host the user is actually signed in to instead of being rewritten to WEB_HOST.
    """
    name = normalize_host(host) or DEFAULT_HOST
    return f"https://{name}"


# --------------------------------------------------------------------------- io


def _brief_error(exc: Exception) -> str:
    """pydantic and PyYAML dump multi-line traces with library URLs; users need one line."""
    if isinstance(exc, PydanticValidationError):
        parts = []
        for item in exc.errors()[:3]:
            location = ".".join(str(part) for part in item.get("loc", ())) or "корень файла"
            parts.append(f"«{location}»: {item.get('msg', 'некорректное значение')}")
        if parts:
            return "; ".join(parts)
    text = str(exc).strip()
    first = text.splitlines()[0].strip() if text else ""
    return first or exc.__class__.__name__


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(
            f"Не удалось прочитать {path}: {_brief_error(exc)}",
            hint="Исправьте файл вручную или удалите его.",
        ) from exc


def _write_error(path: Path, exc: OSError) -> ConfigError:
    return ConfigError(
        f"Не удалось записать {path}: {exc}",
        hint="Проверьте права на каталог настроек.",
    )


def write_atomic(path: Path, text: str, *, mode: int = 0o600) -> Path:
    """Write via a temp file in the same directory, then rename; mode 0600 by default."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}-")
    except OSError as exc:
        raise _write_error(path, exc) from exc
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        raise _write_error(path, exc) from exc
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    try:
        os.chmod(path, mode)
    except OSError as exc:
        raise _write_error(path, exc) from exc
    return path


def _dump_yaml(payload: Any) -> str:
    return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, default_flow_style=False)


def load_hosts() -> Hosts:
    """Read ``hosts.yml`` (migrating the legacy ``config.json`` if needed)."""
    migrate_legacy_config()
    raw = _read_yaml(hosts_path())
    if raw is None:
        return Hosts({})
    if not isinstance(raw, dict):
        raise ConfigError(
            f"Файл {hosts_path()} повреждён: ожидался словарь хостов.",
            hint="Исправьте файл вручную или удалите его.",
        )
    try:
        return Hosts.model_validate(raw)
    except Exception as exc:
        raise ConfigError(
            f"Файл {hosts_path()} повреждён: {_brief_error(exc)}",
            hint="Исправьте файл вручную или удалите его.",
        ) from exc


def save_hosts(hosts: Hosts) -> Path:
    """Write ``hosts.yml`` atomically with mode 0600."""
    payload = {
        host: {
            "active_user": entry.active_user,
            "users": {
                email: {k: v for k, v in user.model_dump().items() if v is not None}
                for email, user in entry.users.items()
            },
        }
        for host, entry in hosts.root.items()
    }
    return write_atomic(hosts_path(), _dump_yaml(payload))


def load_settings() -> Settings:
    raw = _read_yaml(settings_path())
    if raw is None:
        return Settings()
    if not isinstance(raw, dict):
        raise ConfigError(f"Файл {settings_path()} повреждён: ожидался словарь настроек.")
    try:
        return Settings.model_validate(raw)
    except Exception as exc:
        raise ConfigError(
            f"Файл {settings_path()} повреждён: {_brief_error(exc)}",
            hint="Исправьте файл вручную или удалите его.",
        ) from exc


def save_settings(settings: Settings) -> Path:
    return write_atomic(settings_path(), _dump_yaml(settings.model_dump()), mode=0o644)


# --------------------------------------------------------------------------- migration


def _unique_user_key(entry: Host, email: str, company_id: Any, profile_name: str) -> str:
    """First free key for a migrated profile, so two profiles never collapse into one."""
    candidates = [email]
    if company_id:
        candidates.append(f"{email} ({company_id})")
    candidates.append(f"{email} ({profile_name})")
    for candidate in candidates:
        if candidate not in entry.users:
            return candidate
    index = 2
    while f"{candidates[-1]}-{index}" in entry.users:
        index += 1
    return f"{candidates[-1]}-{index}"


def migrate_legacy_config() -> bool:
    """Best-effort import of the pre-gh ``config.json`` profile layout."""
    legacy = config_dir() / "config.json"
    target = hosts_path()
    if target.exists() or not legacy.exists():
        return False
    try:
        raw = json.loads(legacy.read_text(encoding="utf-8"))
        profiles = raw.get("profiles") if isinstance(raw, dict) else None
        if not isinstance(profiles, dict):
            return False
        hosts = Hosts({})
        for name, profile in profiles.items():
            if not isinstance(profile, dict):
                continue
            api_key = profile.get("api_key")
            if not api_key:
                continue
            host = normalize_host(profile.get("base_url")) or DEFAULT_HOST
            email = str(profile.get("login") or name or "unknown")
            entry = hosts.root.setdefault(host, Host())
            # Legacy profiles may share a login (one key per company): never overwrite a key.
            key = _unique_user_key(entry, email, profile.get("company_id"), str(name))
            entry.users[key] = HostUser(
                api_key=str(api_key),
                email=email,
                company_id=profile.get("company_id"),
            )
            if entry.active_user is None:
                entry.active_user = key
        if not hosts.root:
            return False
        save_hosts(hosts)
    except Exception:
        # Migration must never break a normal run.
        return False
    return True


# --------------------------------------------------------------------------- auth


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _pick_host(hostname: str | None, hosts: Hosts) -> str:
    explicit = normalize_host(hostname)
    if explicit:
        return explicit
    from_env = normalize_host(os.environ.get(ENV_HOST))
    if from_env:
        return from_env
    names = hosts.hostnames()
    if len(names) == 1:
        return names[0]
    return DEFAULT_HOST


def _pick_user(entry: Host | None, user: str | None) -> tuple[str | None, HostUser | None]:
    if entry is None:
        return None, None
    wanted = _clean(user)
    if wanted:
        found = entry.users.get(wanted)
        if found is None:
            lowered = wanted.casefold()
            for email, candidate in entry.users.items():
                if email.casefold() == lowered:
                    return email, candidate
            return wanted, None
        return wanted, found
    active = entry.active_user
    if active and active in entry.users:
        return active, entry.users[active]
    if entry.users:
        email = next(iter(entry.users))
        return email, entry.users[email]
    return None, None


def resolve_auth(
    hostname: str | None = None,
    user: str | None = None,
    token: str | None = None,
    *,
    require_key: bool = False,
    hosts: Hosts | None = None,
) -> ResolvedAuth:
    """Merge flag > env > ``hosts.yml`` into the credentials for this run.

    Key precedence: ``token`` argument, ``YOUGILE_TOKEN``, ``YOUGILE_API_KEY``,
    the stored user. Host precedence: ``hostname`` argument, ``YOUGILE_HOST``,
    the single configured host, ``yougile.com``.
    """
    store = hosts if hosts is not None else load_hosts()
    host = _pick_host(hostname, store)
    entry = store.get(host)
    email, stored = _pick_user(entry, user)

    explicit = _clean(token)
    env_token = _clean(os.environ.get(ENV_TOKEN))
    env_key = _clean(os.environ.get(ENV_API_KEY))

    if explicit:
        api_key, source = explicit, "flag"
    elif env_token:
        api_key, source = env_token, ENV_TOKEN
    elif env_key:
        api_key, source = env_key, ENV_API_KEY
    elif stored is not None:
        api_key, source = stored.api_key, "hosts.yml"
    else:
        api_key, source = None, "none"

    if api_key is None and require_key:
        raise AuthError(f"Вход на {host} не выполнен.", hint=LOGIN_HINT)

    from_store = stored if (stored is not None and api_key == stored.api_key) else None
    return ResolvedAuth(
        host=host,
        base_url=host_to_base_url(host),
        api_key=api_key,
        user_email=from_store.email if from_store else (email if stored is not None else None),
        user_id=from_store.user_id if from_store else None,
        real_name=from_store.real_name if from_store else None,
        company_id=from_store.company_id if from_store else None,
        company_name=from_store.company_name if from_store else None,
        source=source,
    )


def login_user(host: str, user: HostUser, *, make_active: bool = True) -> Path:
    """Store one account in ``hosts.yml`` and (by default) make it active."""
    email = _clean(user.email)
    if not email:
        raise ConfigError("У учётной записи нет почты — нечего сохранять в hosts.yml.")
    name = normalize_host(host) or DEFAULT_HOST
    hosts = load_hosts()
    entry = hosts.root.setdefault(name, Host())
    entry.users[email] = user
    if make_active or entry.active_user is None:
        entry.active_user = email
    return save_hosts(hosts)


def logout_user(host: str, email: str | None = None) -> bool:
    """Drop one account (or the whole host when ``email`` is None)."""
    name = normalize_host(host) or DEFAULT_HOST
    hosts = load_hosts()
    entry = hosts.root.get(name)
    if entry is None:
        return False
    if email is None:
        del hosts.root[name]
        save_hosts(hosts)
        return True
    target, _ = _pick_user(entry, email)
    if target is None or target not in entry.users:
        return False
    del entry.users[target]
    if entry.active_user == target:
        entry.active_user = next(iter(entry.users), None)
    if not entry.users:
        del hosts.root[name]
    save_hosts(hosts)
    return True


def switch_user(host: str, email: str) -> HostUser:
    """Make another stored account active on ``host``."""
    name = normalize_host(host) or DEFAULT_HOST
    hosts = load_hosts()
    entry = hosts.root.get(name)
    target, found = _pick_user(entry, email)
    if entry is None or found is None or target is None:
        raise ConfigError(
            f"Учётная запись «{email}» не найдена на {name}.",
            hint=LOGIN_HINT,
        )
    entry.active_user = target
    save_hosts(hosts)
    return found


def list_accounts() -> list[dict[str, Any]]:
    """Every stored account, flat, for ``yougile auth status``."""
    hosts = load_hosts()
    rows: list[dict[str, Any]] = []
    for name, entry in hosts.root.items():
        for email, user in entry.users.items():
            rows.append(
                {
                    "host": name,
                    "email": email,
                    "active": email == entry.active_user,
                    "user_id": user.user_id,
                    "real_name": user.real_name,
                    "company_id": user.company_id,
                    "company_name": user.company_name,
                    "api_key": user.api_key,
                }
            )
    return rows


# --------------------------------------------------------------------------- settings


def _split_key(key: str) -> tuple[str, str | None]:
    head, sep, tail = key.strip().partition(".")
    return head, (tail if sep else None)


def get_setting(key: str) -> str | None:
    """Read a setting; ``aliases.NAME`` reads one alias."""
    head, tail = _split_key(key)
    settings = load_settings()
    if head == "aliases":
        if tail:
            return settings.aliases.get(tail)
        return None
    if head in SETTING_KEYS:
        value = getattr(settings, head)
        return None if value is None else str(value)
    raise ValidationError(
        f"Неизвестная настройка «{key}».",
        hint=f"Доступные: {', '.join(SETTING_KEYS)}, aliases.<имя>",
    )


def set_setting(key: str, value: str) -> Path:
    """Write a setting; ``aliases.NAME`` writes one alias."""
    head, tail = _split_key(key)
    settings = load_settings()
    if head == "aliases":
        if not tail:
            raise ValidationError("Укажите имя алиаса: aliases.<имя>.")
        settings.aliases[tail] = value
    elif head in SETTING_KEYS:
        setattr(settings, head, value)
    else:
        raise ValidationError(
            f"Неизвестная настройка «{key}».",
            hint=f"Доступные: {', '.join(SETTING_KEYS)}, aliases.<имя>",
        )
    return save_settings(settings)


def list_settings() -> dict[str, str]:
    """Flat view of ``config.yml`` with dotted alias keys."""
    settings = load_settings()
    flat = {key: str(getattr(settings, key)) for key in SETTING_KEYS}
    for name, expansion in settings.aliases.items():
        flat[f"aliases.{name}"] = expansion
    return flat


def get_alias(name: str) -> str | None:
    return load_settings().aliases.get(name.strip())


def set_alias(name: str, expansion: str) -> Path:
    settings = load_settings()
    settings.aliases[name.strip()] = expansion
    return save_settings(settings)


def delete_alias(name: str) -> bool:
    settings = load_settings()
    if name.strip() not in settings.aliases:
        return False
    del settings.aliases[name.strip()]
    save_settings(settings)
    return True


def list_aliases() -> dict[str, str]:
    return dict(load_settings().aliases)
