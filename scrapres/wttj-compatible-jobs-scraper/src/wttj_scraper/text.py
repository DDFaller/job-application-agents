from __future__ import annotations

import html
import re
import unicodedata
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def clean_text(value: object) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value)).replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def strip_html(value: object) -> str:
    parser = _TextExtractor()
    parser.feed(str(value or ""))
    return clean_text(" ".join(parser.parts))


def fold(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", clean_text(value))
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", without_marks.lower()).strip()

