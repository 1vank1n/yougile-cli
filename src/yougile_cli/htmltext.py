"""HTML -> readable plain text, standard library only.

Task descriptions and chat messages arrive as HTML, and printing them raw makes
`task view` unreadable. The conversion is deliberately forgiving: an unclosed
tag, a stray ``<`` or a truncated entity must never raise — the worst outcome
allowed is text with a tag left in it.
"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

__all__ = ["BULLET", "html_to_text", "looks_like_html"]

BULLET = "• "

# Tags that open and close a block: text on either side must not run together.
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "dl",
        "fieldset",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "ul",
    }
)
# Blocks separated by a single newline rather than a blank line.
_LINE_TAGS = frozenset({"dd", "dt", "li", "td", "th", "tr"})
_SKIP_TAGS = frozenset({"script", "style", "head", "title"})
_TAG_RE = re.compile(r"<[^>]*>")
_SPACES_RE = re.compile(r"[^\S\n]+")
_TRAILING_RE = re.compile(r"[^\S\n]*\n[^\S\n]*")
_BLANKS_RE = re.compile(r"\n{3,}")
_WHITESPACE_RE = re.compile(r"\s+")


def looks_like_html(text: str) -> bool:
    """True when the value carries markup worth unwrapping."""
    return bool(text) and bool(re.search(r"<[a-zA-Z/!]", text))


class _TextExtractor(HTMLParser):
    """Collects text, turning block structure into blank lines and bullets.

    Breaks are buffered instead of appended: two adjacent tags must not add up to
    an extra blank line, and a bullet has to survive the break in front of it.
    """

    def __init__(self, *, collapse_newlines: bool = True) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._collapse = collapse_newlines
        self._pending = 0
        self._bullet = False
        self._skip_depth = 0

    def _break(self, level: int) -> None:
        self._pending = max(self._pending, level)

    def _flush(self) -> None:
        if self._pending:
            if self.parts:
                self.parts.append("\n" * self._pending)
            self._pending = 0
        if self._bullet:
            self.parts.append(BULLET)
            self._bullet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if name == "br":
            self._break(1)
        elif name == "li":
            self._break(1)
            self._bullet = True
        elif name in _LINE_TAGS:
            self._break(1)
        elif name in _BLOCK_TAGS:
            self._break(2)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if name in _LINE_TAGS:
            self._break(1)
        elif name in _BLOCK_TAGS:
            self._break(2)

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not data:
            return
        if not data.strip():
            # Whitespace between block tags is layout, not content.
            if not self._pending and self.parts:
                self.parts.append(" ")
            return
        self._flush()
        # Inside markup a source newline is layout: only tags create real breaks.
        self.parts.append(_WHITESPACE_RE.sub(" ", data) if self._collapse else data)

    def handle_entityref(self, name: str) -> None:  # pragma: no cover - convert_charrefs
        self.handle_data(unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:  # pragma: no cover - convert_charrefs
        self.handle_data(unescape(f"&#{name};"))


def _normalize(text: str) -> str:
    """Collapse runs of spaces without destroying deliberate line breaks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = _SPACES_RE.sub(" ", text)
    text = _TRAILING_RE.sub("\n", text)
    text = _BLANKS_RE.sub("\n\n", text)
    return text.strip()


def html_to_text(html: str) -> str:
    """Readable text out of an HTML fragment; never raises."""
    if not html:
        return ""
    parser = _TextExtractor(collapse_newlines=looks_like_html(html))
    try:
        parser.feed(html)
        parser.close()
        text = "".join(parser.parts)
    except Exception:
        # Malformed markup must still yield something a human can read.
        text = unescape(_TAG_RE.sub(" ", html))
    return _normalize(text)
