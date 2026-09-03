"""Tests for `yougile_cli.htmltext`: HTML описания -> читаемый текст (дефект №10)."""

from __future__ import annotations

import pytest

from yougile_cli.htmltext import html_to_text, looks_like_html


def test_paragraphs_become_blank_line_separated_blocks() -> None:
    assert html_to_text("<p>Первый абзац</p><p>Второй абзац</p>") == "Первый абзац\n\nВторой абзац"


def test_br_is_a_single_newline() -> None:
    assert html_to_text("строка<br>вторая<br/>третья") == "строка\nвторая\nтретья"


def test_list_items_become_bullets() -> None:
    assert html_to_text("<ul><li>раз</li><li>два</li></ul>") == "• раз\n• два"


def test_list_after_a_paragraph_keeps_the_blank_line() -> None:
    text = html_to_text("<p>До</p><ul><li>раз</li><li>два</li></ul><p>После</p>")
    assert text == "До\n\n• раз\n• два\n\nПосле"


def test_entities_are_decoded_and_tags_stripped() -> None:
    assert html_to_text("<p>&lt;тег&gt; &amp; &quot;кавычки&quot;</p>") == '<тег> & "кавычки"'
    assert html_to_text("<p>нераз&nbsp;рывный</p>") == "нераз рывный"


def test_inline_tags_do_not_glue_words_together() -> None:
    assert html_to_text("<div>текст <b>жир</b> и <i>курсив</i></div>") == "текст жир и курсив"


def test_scripts_and_styles_are_dropped() -> None:
    assert (
        html_to_text("<style>p{color:red}</style><script>var x=1</script><p>видно</p>") == "видно"
    )


def test_whitespace_is_collapsed_but_line_breaks_survive() -> None:
    assert html_to_text("<p>много    пробелов</p>\n\n   <p>и\nпереносов</p>") == (
        "много пробелов\n\nи переносов"
    )


@pytest.mark.parametrize(
    "broken",
    [
        "<p>не закрыт <span>текст",
        "<<>>",
        "<p>a</p" * 3,
        "text < 5 and > 3",
        "<img src=",
        "&#xZZ; &notanentity",
    ],
)
def test_malformed_html_never_raises(broken: str) -> None:
    assert isinstance(html_to_text(broken), str)


def test_plain_text_passes_through() -> None:
    assert html_to_text("обычный текст") == "обычный текст"
    assert html_to_text("") == ""


def test_looks_like_html() -> None:
    assert looks_like_html("<p>да</p>") is True
    assert looks_like_html("нет 1 < 2") is False
    assert looks_like_html("") is False
