"""Tests for `yougile_cli.attachments`: вложения задач и их скачивание (дефекты №9, №10)."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

import pytest
import respx

from yougile_cli.attachments import (
    KIND_FILE,
    KIND_IMAGE,
    SOURCE_CHAT,
    SOURCE_DESCRIPTION,
    absolute_url,
    download,
    filename_from_url,
    from_description,
    from_message,
    strip_preview,
)
from yougile_cli.client import YouGileClient
from yougile_cli.errors import ApiError, NotFoundError, ValidationError, YouGileError

HOST = "yougile.com"
IMAGE = "/user-data/aaaaaaaa/IMG_20260828_173932.jpg"
DOC = "/user-data/bbbbbbbb/договор.pdf"


# ------------------------------------------------------------------------------- ссылки


def test_absolute_url_resolves_against_the_host() -> None:
    assert absolute_url(IMAGE, HOST) == f"https://yougile.com{IMAGE}"
    assert absolute_url(IMAGE, "https://ru.yougile.com/") == f"https://ru.yougile.com{IMAGE}"
    assert absolute_url("https://cdn.example/x.png", HOST) == "https://cdn.example/x.png"
    assert absolute_url("", HOST) == ""


def test_strip_preview_removes_the_thumbnail_parameter() -> None:
    """С previews[] сервер отдаёт 480×480 вместо оригинала."""
    url = f"https://yougile.com{IMAGE}?previews[]=480x480&sign=abc"
    assert strip_preview(url) == f"https://yougile.com{IMAGE}?sign=abc"
    assert strip_preview(url, keep=True) == url
    assert strip_preview(f"https://yougile.com{IMAGE}") == f"https://yougile.com{IMAGE}"


def test_strip_preview_handles_the_encoded_parameter() -> None:
    url = f"https://yougile.com{IMAGE}?previews%5B%5D=480x480"
    assert strip_preview(url) == f"https://yougile.com{IMAGE}"


def test_filename_from_url_decodes_and_stays_a_single_segment() -> None:
    assert filename_from_url("https://yougile.com/user-data/a/%D0%B8%D0%BC%D1%8F.png") == "имя.png"
    assert (
        filename_from_url(f"https://yougile.com{IMAGE}?previews[]=1") == "IMG_20260828_173932.jpg"
    )
    assert filename_from_url("https://yougile.com/user-data/a/") == "attachment"


# --------------------------------------------------------------------------- извлечение


def test_from_description_finds_images_and_links() -> None:
    html = f'<p>Текст</p><img src="{IMAGE}?previews%5B%5D=480x480"><a href="{DOC}">договор</a>'
    found = from_description(html, HOST)
    assert [a.name for a in found] == ["IMG_20260828_173932.jpg", "договор.pdf"]
    assert [a.kind for a in found] == [KIND_IMAGE, KIND_FILE]
    assert {a.source for a in found} == {SOURCE_DESCRIPTION}
    assert found[1].url == f"https://yougile.com{DOC}"


def test_from_description_ignores_foreign_links() -> None:
    assert from_description('<a href="https://example.com/x.pdf">внешняя</a>', HOST) == []
    assert from_description("", HOST) == []


def test_from_description_ignores_user_data_on_a_foreign_host() -> None:
    """Описание пишет коллега: ссылка на чужой хост не должна скачиваться."""
    html = '<img src="https://attacker.example/user-data/x/pixel.png">'
    assert from_description(html, HOST) == []
    assert from_message(f'<a href="{html}">x</a>', HOST) == []
    # Веб-зеркало облака — тот же origin, его сохраняем.
    mirror = f'<a href="https://ru.yougile.com{DOC}">договор</a>'
    assert [a.url for a in from_description(mirror, HOST)] == [f"https://ru.yougile.com{DOC}"]


def test_from_message_decodes_the_chat_service_form() -> None:
    """`/root/#file:…%3Fpreviews%5B%5D%3D…` нечитаем, пока его не раскодировать."""
    text = f'Смотри <a href="/root/#file:{IMAGE}%3Fpreviews%5B%5D%3D480x480">файл</a>'
    found = from_message(text, HOST)
    assert len(found) == 1
    assert found[0].source == SOURCE_CHAT
    assert found[0].name == "IMG_20260828_173932.jpg"
    assert found[0].kind == KIND_IMAGE
    assert found[0].url == f"https://yougile.com{IMAGE}?previews[]=480x480"


def test_from_message_reads_plain_links_too() -> None:
    found = from_message(f'<img src="{IMAGE}">', HOST)
    assert [a.source for a in found] == [SOURCE_CHAT]
    assert from_message("просто текст", HOST) == []


# -------------------------------------------------------------------------- скачивание


def test_download_streams_to_a_named_file(
    api: respx.MockRouter, client: YouGileClient, tmp_path: Path
) -> None:
    route = api.get(IMAGE).respond(200, content=b"x" * 1000)
    target = download(client, f"https://yougile.com{IMAGE}", tmp_path / "снимок.jpg")
    assert target.read_bytes() == b"x" * 1000
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-key"


def test_download_into_a_directory_uses_the_url_name(
    api: respx.MockRouter, client: YouGileClient, tmp_path: Path
) -> None:
    api.get(IMAGE).respond(200, content=b"data")
    target = download(client, f"https://yougile.com{IMAGE}", tmp_path)
    assert target == tmp_path / "IMG_20260828_173932.jpg"


def test_download_drops_the_preview_parameter_by_default(
    api: respx.MockRouter, client: YouGileClient, tmp_path: Path
) -> None:
    route = api.get(IMAGE).respond(200, content=b"original")
    download(client, f"https://yougile.com{IMAGE}?previews[]=480x480", tmp_path)
    assert b"previews" not in route.calls.last.request.url.query


def test_download_keeps_the_preview_when_asked(
    api: respx.MockRouter, client: YouGileClient, tmp_path: Path
) -> None:
    route = api.get(IMAGE).respond(200, content=b"thumb")
    download(client, f"https://yougile.com{IMAGE}?previews[]=480x480", tmp_path, preview=True)
    assert b"previews" in route.calls.last.request.url.query


def test_download_refuses_to_overwrite(
    api: respx.MockRouter, client: YouGileClient, tmp_path: Path
) -> None:
    api.get(IMAGE).respond(200, content=b"new")
    existing = tmp_path / "IMG_20260828_173932.jpg"
    existing.write_bytes(b"old")
    with pytest.raises(ValidationError) as excinfo:
        download(client, f"https://yougile.com{IMAGE}", tmp_path)
    assert excinfo.value.exit_code == 2
    assert existing.read_bytes() == b"old"

    assert download(client, f"https://yougile.com{IMAGE}", tmp_path, force=True) == existing
    assert existing.read_bytes() == b"new"


def test_failed_download_leaves_no_partial_file(
    api: respx.MockRouter, client: YouGileClient, tmp_path: Path
) -> None:
    api.get(IMAGE).respond(404, json={"message": "нет файла"})
    into = tmp_path / "downloads"
    into.mkdir()
    with pytest.raises(NotFoundError):
        download(client, f"https://yougile.com{IMAGE}", into)
    assert list(into.iterdir()) == []


def test_download_requires_a_url(client: YouGileClient) -> None:
    with pytest.raises(ValidationError):
        download(client, "  ", None)


def test_download_is_streamed_not_buffered(
    api: respx.MockRouter, client: YouGileClient, tmp_path: Path, monkeypatch: Any
) -> None:
    """Файл на 2 ГБ не должен оказаться в памяти целиком."""
    api.get(IMAGE).respond(200, content=b"y" * 4096)

    def forbidden(self: Any) -> bytes:  # pragma: no cover - вызывается только при ошибке
        raise AssertionError("тело ответа читалось целиком")

    monkeypatch.setattr("httpx.Response.content", property(forbidden))
    target = download(client, f"https://yougile.com{IMAGE}", tmp_path)
    assert target.stat().st_size == 4096
    assert stat.S_ISREG(target.stat().st_mode)


def test_download_follows_the_storage_redirect_without_the_token(
    api: respx.MockRouter, client: YouGileClient, tmp_path: Path
) -> None:
    """`/user-data/...` отвечает 302 на user-data.<хост>, а хранилище отвергает Bearer."""
    storage = "https://user-data.yougile.com/aaaaaaaa/IMG_20260828_173932.jpg"
    api.get(IMAGE).respond(302, headers={"Location": storage})
    hop = api.get(storage).respond(200, content=b"jpeg" * 100)

    target = download(client, f"https://yougile.com{IMAGE}", tmp_path)

    assert target.read_bytes() == b"jpeg" * 100
    assert "authorization" not in {k.lower() for k in hop.calls.last.request.headers}


def test_download_rejects_an_empty_body_instead_of_writing_a_zero_byte_file(
    api: respx.MockRouter, client: YouGileClient, tmp_path: Path
) -> None:
    api.get(IMAGE).respond(200, content=b"")
    with pytest.raises(ApiError) as excinfo:
        download(client, f"https://yougile.com{IMAGE}", tmp_path)
    assert excinfo.value.exit_code == 1
    assert not (tmp_path / "IMG_20260828_173932.jpg").exists()


def test_download_rejects_a_truncated_body(
    api: respx.MockRouter, client: YouGileClient, tmp_path: Path
) -> None:
    api.get(IMAGE).respond(200, content=b"half", headers={"Content-Length": "999"})
    with pytest.raises(ApiError):
        download(client, f"https://yougile.com{IMAGE}", tmp_path)
    assert not (tmp_path / "IMG_20260828_173932.jpg").exists()


def test_download_keeps_the_token_for_the_web_host(client: YouGileClient, tmp_path: Path) -> None:
    """`ru.yougile.com` — тот же облачный origin, что и `yougile.com` (дефект №5)."""
    url = f"https://ru.yougile.com{IMAGE}"
    with respx.mock(assert_all_called=False) as router:
        route = router.get(url).respond(200, content=b"jpeg" * 10)
        download(client, url, tmp_path)
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-key"


def test_local_write_failure_is_not_a_usage_error(
    api: respx.MockRouter, client: YouGileClient, tmp_path: Path, monkeypatch: Any
) -> None:
    """Сбой записи на диск — код 1, двойка зарезервирована за неверными аргументами."""
    api.get(IMAGE).respond(200, content=b"data" * 10)

    def full_disk(src: Any, dst: Any) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("os.replace", full_disk)
    with pytest.raises(YouGileError) as excinfo:
        download(client, f"https://yougile.com{IMAGE}", tmp_path)
    assert excinfo.value.exit_code == 1
    assert not isinstance(excinfo.value, ValidationError)
    assert not (tmp_path / "IMG_20260828_173932.jpg").exists()
