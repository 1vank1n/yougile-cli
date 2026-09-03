"""Attachments hidden in task descriptions and chat messages.

YouGile stores uploads under ``/user-data/<uuid>/<имя>`` and references them in
two very different ways:

* a description is HTML, so files show up as ``<img src>`` and ``<a href>``;
* a chat message carries the service form
  ``/root/#file:/user-data/<uuid>/<имя>%3Fpreviews%5B%5D%3D…`` — a URL-encoded
  path that renders as gibberish unless it is decoded.

The ``previews[]`` query parameter is what makes the server answer with a
480×480 thumbnail instead of the original, so it is stripped by default.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from .errors import ApiError, ValidationError, YouGileError

if TYPE_CHECKING:  # pragma: no cover
    from .client import YouGileClient

__all__ = [
    "KIND_FILE",
    "KIND_IMAGE",
    "PREVIEW_PARAM",
    "SOURCE_CHAT",
    "SOURCE_DESCRIPTION",
    "USER_DATA_PREFIX",
    "Attachment",
    "absolute_url",
    "download",
    "filename_from_url",
    "from_description",
    "from_message",
    "is_own_host",
    "strip_preview",
]

SOURCE_DESCRIPTION = "описание"
SOURCE_CHAT = "чат"
KIND_IMAGE = "изображение"
KIND_FILE = "файл"

USER_DATA_PREFIX = "/user-data/"
# The public cloud serves boards from ru.yougile.com while the API answers on
# yougile.com — one origin as far as attachments go.
_CLOUD_HOSTS = frozenset({"yougile.com", "ru.yougile.com"})
PREVIEW_PARAM = "previews[]"

_IMAGE_SUFFIXES = frozenset(
    {
        ".apng",
        ".avif",
        ".bmp",
        ".gif",
        ".heic",
        ".jpeg",
        ".jpg",
        ".png",
        ".svg",
        ".tif",
        ".tiff",
        ".webp",
    }
)
# The chat service form: everything up to the first quote, angle bracket or space.
_FILE_LINK_RE = re.compile(r"#file:([^\s\"'<>]+)")
_UNSAFE_NAME_RE = re.compile(r"[\\/\x00]+")
_CHUNK = 64 * 1024


@dataclass(frozen=True)
class Attachment:
    """One file referenced from a task."""

    source: str
    name: str
    url: str
    kind: str


# --------------------------------------------------------------------------- urls


def _clean_host(host: str) -> str:
    text = (host or "").strip()
    for scheme in ("https://", "http://"):
        if text.lower().startswith(scheme):
            text = text[len(scheme) :]
            break
    return text.split("/", 1)[0].strip("/") or "yougile.com"


def absolute_url(value: str, host: str) -> str:
    """Resolve ``/user-data/…`` against the host the CLI is authenticated to."""
    text = (value or "").strip()
    if not text:
        return ""
    if text.lower().startswith(("http://", "https://")):
        return text
    if text.startswith("//"):
        return f"https:{text}"
    name = _clean_host(host)
    return f"https://{name}/{text.lstrip('/')}"


def strip_preview(url: str, *, keep: bool = False) -> str:
    """Drop ``previews[]`` so the original is fetched, not a 480×480 thumbnail."""
    if keep or not url or PREVIEW_PARAM not in unquote(url):
        return url
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in (PREVIEW_PARAM, "previews")
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment)
    )


def filename_from_url(url: str) -> str:
    """Last path segment, decoded; never a path of its own."""
    path = urlsplit(url or "").path
    name = unquote(path.rsplit("/", 1)[-1]).strip()
    name = _UNSAFE_NAME_RE.sub("_", name).strip(". ")
    return name or "attachment"


def _kind_for(url: str, *, image: bool = False) -> str:
    if image:
        return KIND_IMAGE
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return KIND_IMAGE
    return KIND_IMAGE if PREVIEW_PARAM in unquote(url) else KIND_FILE


def _is_user_data(url: str) -> bool:
    return USER_DATA_PREFIX in unquote(url or "")


def is_own_host(url: str, host: str) -> bool:
    """Descriptions are user input: a link off the authenticated host is not ours.

    Without this a colleague could point the CLI at any server simply by editing
    a task description, and ``--download`` would fetch it.
    """
    netloc = urlsplit(url or "").netloc.lower()
    if not netloc:
        return True
    own = _clean_host(host).lower()
    if netloc == own:
        return True
    return {netloc, own} <= _CLOUD_HOSTS


def _make(source: str, url: str, host: str, *, image: bool = False) -> Attachment:
    absolute = absolute_url(url, host)
    return Attachment(
        source=source,
        name=filename_from_url(absolute),
        url=absolute,
        kind=_kind_for(absolute, image=image),
    )


def _dedupe(items: Iterable[Attachment]) -> list[Attachment]:
    seen: set[str] = set()
    result: list[Attachment] = []
    for item in items:
        if item.url in seen:
            continue
        seen.add(item.url)
        result.append(item)
    return result


# --------------------------------------------------------------------------- sources


class _LinkCollector(HTMLParser):
    """``<img src>`` and ``<a href>`` pointing into ``/user-data/``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, bool]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name not in ("img", "a", "source", "video", "audio"):
            return
        wanted = "href" if name == "a" else "src"
        for key, value in attrs:
            if key.lower() != wanted or not value or not _is_user_data(value):
                continue
            if "#file:" in value:
                # The chat service form is decoded by the regex below, not as a link.
                continue
            self.links.append((value, name in ("img", "source")))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def _scan_html(text: str) -> list[tuple[str, bool]]:
    parser = _LinkCollector()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        return parser.links
    return parser.links


def from_description(html: str, host: str) -> list[Attachment]:
    """Files referenced from a task description (HTML)."""
    if not html:
        return []
    found = [_make(SOURCE_DESCRIPTION, url, host, image=image) for url, image in _scan_html(html)]
    return _dedupe(item for item in found if is_own_host(item.url, host))


def from_message(text: str, host: str) -> list[Attachment]:
    """Files referenced from a chat message, service form included."""
    if not text:
        return []
    found: list[Attachment] = []
    for raw in _FILE_LINK_RE.findall(text):
        decoded = unquote(raw)
        if _is_user_data(decoded):
            found.append(_make(SOURCE_CHAT, decoded, host))
    found.extend(_make(SOURCE_CHAT, url, host, image=image) for url, image in _scan_html(text))
    return _dedupe(item for item in found if is_own_host(item.url, host))


# --------------------------------------------------------------------------- download


def _target_path(url: str, dest: Path | str | None) -> Path:
    name = filename_from_url(url)
    if dest is None:
        return Path.cwd() / name
    text = str(dest)
    path = Path(text).expanduser()
    if path.is_dir() or text.endswith(("/", os.sep)):
        return path / name
    return path


def download(
    client: YouGileClient,
    url: str,
    dest: Path | str | None = None,
    *,
    force: bool = False,
    preview: bool = False,
) -> Path:
    """Stream a file to disk with the bearer header; returns the written path.

    ``previews[]`` is dropped unless ``preview`` is set, so the original is
    fetched instead of a 480×480 thumbnail. The body is never held in memory: it
    is piped chunk by chunk into a temp file next to the target, which is renamed
    into place only once the transfer ends.
    """
    address = strip_preview((url or "").strip(), keep=preview)
    if not address:
        raise ValidationError("Не указана ссылка на файл.")
    target = _target_path(address, dest)
    if target.exists() and not force:
        raise ValidationError(
            f"Файл «{target}» уже существует.",
            hint="Добавьте --force, чтобы перезаписать.",
        )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}-")
    except OSError as exc:
        raise YouGileError(f"Не удалось записать «{target}»: {exc}") from exc
    tmp_path = Path(tmp_name)
    try:
        written = 0
        with client.stream("GET", address) as response, os.fdopen(handle, "wb") as sink:
            for chunk in response.iter_bytes(_CHUNK):
                written += sink.write(chunk)
            declared = response.headers.get("content-length")
        # Пустой ответ на ссылку из вложения — всегда ошибка переноса, а не пустой файл:
        # молча положить 0 байт и отрапортовать успехом хуже, чем упасть.
        if written == 0 or (
            declared is not None and declared.isdigit() and written < int(declared)
        ):
            raise ApiError(
                f"Файл скачан не полностью: получено {written} Б.",
                method="GET",
                url=address,
                hint="Повторите попытку; если не помогает, откройте ссылку в браузере.",
            )
        os.replace(tmp_path, target)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        raise YouGileError(f"Не удалось записать «{target}»: {exc}") from exc
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return target
