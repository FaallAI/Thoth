"""Decode the seroval-serialized data X's pages stream to the browser; no code is run.

Logged-out X pages stream their data through TanStack Router scripts of the form
`($R=>$R[n].next(<value>))($R["<key>"])`. `<value>` is a JavaScript literal: objects with
bare or quoted keys, arrays, strings, numbers, `!0`/`!1`, `void 0`, and `$R[n]=` assignments
and `$R[n]` references into a per-stream table. `decode_scripts` reads that subset only.
A wrapper holding anything else (the router runtime, functions, constructors) decodes to
nothing, and the decoder never raises.
"""

from __future__ import annotations

import re
from typing import Any

SCRIPT = re.compile(r"<script[^>]*>(.*?)</script>", re.S)
WRAPPER = re.compile(r"\(\$R=>")
CALL = re.compile(r"\$R\[\d+\]\.(next|return|throw)\(")
INDEX = re.compile(r"\d+")
KEY = re.compile(r"[A-Za-z_$][\w$]*|\d+")
NUMBER = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
HEX = re.compile(r"[0-9a-fA-F]+")
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
WORDS: tuple[tuple[str, Any], ...] = (
    ("void 0", None),
    ("undefined", None),
    ("null", None),
    ("true", True),
    ("false", False),
    ("!0", True),
    ("!1", False),
)
MAX_DEPTH = 200


class _Unsupported(Exception):
    """The wrapper holds something outside the decoded subset."""


class _Ref:
    __slots__ = ("index",)

    def __init__(self, index: int) -> None:
        self.index = index


class _Parser:
    def __init__(self, text: str, pos: int) -> None:
        self.text, self.pos = text, pos
        self.table: dict[int, Any] = {}

    def take(self, token: str) -> bool:
        if self.text.startswith(token, self.pos):
            self.pos += len(token)
            return True
        return False

    def expect(self, token: str) -> None:
        if not self.take(token):
            raise _Unsupported

    def match(self, pattern: re.Pattern[str]) -> str:
        found = pattern.match(self.text, self.pos)
        if found is None:
            raise _Unsupported
        self.pos = found.end()
        return found.group()

    def value(self, depth: int = 0) -> Any:
        if depth > MAX_DEPTH or self.pos >= len(self.text):
            raise _Unsupported
        char = self.text[self.pos]
        if char == "{":
            return self.object(depth)
        if char == "[":
            return self.array(depth)
        if char == '"':
            return self.string()
        for word, decoded in WORDS:
            if self.take(word):
                return decoded
        if self.take("$R["):
            index = int(self.match(INDEX))
            self.expect("]")
            if self.take("="):
                self.table[index] = self.value(depth + 1)
                return self.table[index]
            return _Ref(index)
        number = self.match(NUMBER)
        return float(number) if any(c in number for c in ".eE") else int(number)

    def object(self, depth: int) -> dict[str, Any]:
        self.expect("{")
        out: dict[str, Any] = {}
        if self.take("}"):
            return out
        while True:
            key = self.string() if self.text.startswith('"', self.pos) else self.match(KEY)
            self.expect(":")
            out[key] = self.value(depth + 1)
            if self.take("}"):
                return out
            self.expect(",")

    def array(self, depth: int) -> list[Any]:
        self.expect("[")
        out: list[Any] = []
        if self.take("]"):
            return out
        while True:
            out.append(self.value(depth + 1))
            if self.take("]"):
                return out
            self.expect(",")

    def string(self) -> str:
        self.expect('"')
        chars: list[str] = []
        while self.pos < len(self.text):
            char = self.text[self.pos]
            self.pos += 1
            if char == '"':
                # `😀` arrives as two halves; re-encoding joins the pair.
                return "".join(chars).encode("utf-16", "surrogatepass").decode("utf-16", "replace")
            if char != "\\":
                chars.append(char)
                continue
            code = self.text[self.pos : self.pos + 1]
            self.pos += 1
            if code in ("x", "u"):
                width = 2 if code == "x" else 4
                digits = self.text[self.pos : self.pos + width]
                if len(digits) != width or HEX.fullmatch(digits) is None:
                    raise _Unsupported
                chars.append(chr(int(digits, 16)))
                self.pos += width
            else:
                chars.append(ESCAPES.get(code, code))
        raise _Unsupported


def _resolve(value: Any, table: dict[int, Any], seen: set[int]) -> Any:
    if isinstance(value, _Ref):
        target = table.get(value.index)
        return None if isinstance(target, _Ref) else _resolve(target, table, seen)
    if id(value) in seen:
        return value
    if isinstance(value, dict):
        seen.add(id(value))
        for key, item in value.items():
            value[key] = _resolve(item, table, seen)
    elif isinstance(value, list):
        seen.add(id(value))
        for index, item in enumerate(value):
            value[index] = _resolve(item, table, seen)
    return value


def _wrapper(body: str, start: int) -> tuple[Any, str, dict[int, Any]] | None:
    """Decode one `($R=>...)($R["key"])` wrapper; None for a non-data or unknown one."""
    parser = _Parser(body, start)
    call = CALL.match(body, start)
    if call is not None:
        if call.group(1) != "next":
            return None
        parser.pos = call.end()
    value = parser.value()
    parser.expect(")")
    if call is not None:
        parser.expect(")")
    parser.expect("($R[")
    key = parser.string()
    parser.expect("])")
    return value, key, parser.table


def decode_scripts(html: str) -> list[Any]:
    """Every data value the page streams, references resolved per stream; never raises."""
    tables: dict[str, dict[int, Any]] = {}
    decoded: list[tuple[Any, str]] = []
    for body in SCRIPT.findall(html):
        if "$R" not in body:
            continue
        for wrapper in WRAPPER.finditer(body):
            try:
                found = _wrapper(body, wrapper.end())
            except (_Unsupported, ValueError, RecursionError):
                continue
            if found is None:
                continue
            value, key, table = found
            tables.setdefault(key, {}).update(table)
            decoded.append((value, key))
    resolved: list[Any] = []
    for value, key in decoded:
        try:
            resolved.append(_resolve(value, tables[key], set()))
        except RecursionError:
            # A reference chain nests deeper than the parser's own depth limit allows.
            continue
    return resolved
