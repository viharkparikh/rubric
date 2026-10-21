"""A parser for the slice of TOML the framework schema uses.

Only exists because macOS still ships Python 3.9 and `tomllib` arrived in 3.11.
When tomllib is available, rubric.py uses it instead and this file is dead code.

Supported, which is exactly what frameworks/*.toml needs:

    key = "string"              basic strings with \\n \\t \\" \\\\ escapes
    key = '''block'''           multi-line literal strings
    key = \"\"\"block\"\"\"             multi-line basic strings
    key = 12       key = 1.5    integers and floats
    key = true     key = false  booleans
    [table]                     tables, dotted names
    [[array.of.tables]]         arrays of tables
    key = { a = 1, b = 2 }      inline tables, one level, no nesting
    # comment                   whole-line and trailing

Not supported, and raises rather than guessing: dates, arrays of values,
nested inline tables, multi-line arrays, dotted keys on the left of `=`.
A framework file that needs any of those should run on 3.11.
"""

from __future__ import annotations

import re

_BOOL = {"true": True, "false": False}
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


class TomlSubsetError(ValueError):
    pass


def loads(text: str) -> dict:
    root: dict = {}
    current: dict = root
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line, i = _logical_line(lines, i)
        if line is None:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[["):
            name = stripped[2:stripped.index("]]")].strip()
            current = _append_table(root, name.split("."))
        elif stripped.startswith("["):
            name = stripped[1:stripped.index("]")].strip()
            current = _descend(root, name.split("."))
        else:
            key, _, raw = stripped.partition("=")
            if not _:
                raise TomlSubsetError(f"cannot parse line: {stripped!r}")
            current[key.strip()] = _value(raw.strip())
    return root


def _logical_line(lines: list[str], i: int):
    """Return one logical line, joining multi-line strings, and the next index."""
    line = lines[i]
    for delim in ('"""', "'''"):
        if delim in line:
            # Opening delimiter. Consume until the closing one.
            before, _, rest = line.partition(delim)
            if delim in rest:  # opens and closes on the same line
                return line, i + 1
            buf = [rest]
            j = i + 1
            while j < len(lines) and delim not in lines[j]:
                buf.append(lines[j])
                j += 1
            if j >= len(lines):
                raise TomlSubsetError(f"unterminated {delim} string")
            tail, _, after = lines[j].partition(delim)
            buf.append(tail)
            body = "\n".join(buf)
            marker = "\x00BLOCK\x00"
            _BLOCKS.append(body)
            return f"{before}{marker}{len(_BLOCKS) - 1}\x00{after}", j + 1
    return line, i + 1


_BLOCKS: list[str] = []


def _value(raw: str):
    raw = _strip_comment(raw).strip()
    if raw.startswith("\x00BLOCK\x00"):
        index = int(raw.split("\x00")[2])
        body = _BLOCKS[index]
        return body[1:] if body.startswith("\n") else body
    if raw.startswith("{"):
        return _inline_table(raw)
    if raw.startswith('"'):
        return _basic_string(raw)
    if raw.startswith("'"):
        return raw[1:raw.rindex("'")]
    if raw in _BOOL:
        return _BOOL[raw]
    if raw.startswith("["):
        raise TomlSubsetError("arrays of values are not supported; use 3.11+")
    if re.fullmatch(r"[+-]?\d+", raw):
        return int(raw)
    if re.fullmatch(r"[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?", raw):
        return float(raw)
    raise TomlSubsetError(f"cannot parse value: {raw!r}")


def _basic_string(raw: str) -> str:
    out = []
    i = 1
    while i < len(raw):
        char = raw[i]
        if char == "\\":
            nxt = raw[i + 1]
            if nxt not in _ESCAPES:
                raise TomlSubsetError(f"unsupported escape \\{nxt}")
            out.append(_ESCAPES[nxt])
            i += 2
            continue
        if char == '"':
            break
        out.append(char)
        i += 1
    return "".join(out)


def _inline_table(raw: str) -> dict:
    body = raw[1:raw.rindex("}")].strip()
    if not body:
        return {}
    if "{" in body:
        raise TomlSubsetError("nested inline tables are not supported")
    table = {}
    for part in _split_commas(body):
        key, _, value = part.partition("=")
        if not _:
            raise TomlSubsetError(f"cannot parse inline entry: {part!r}")
        table[key.strip()] = _value(value.strip())
    return table


def _split_commas(body: str) -> list[str]:
    """Split on commas that are not inside a quoted string."""
    parts, buf, quote = [], [], None
    for char in body:
        if quote:
            if char == quote:
                quote = None
            buf.append(char)
        elif char in "\"'":
            quote = char
            buf.append(char)
        elif char == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(char)
    if buf:
        parts.append("".join(buf))
    return [p for p in (part.strip() for part in parts) if p]


def _strip_comment(raw: str) -> str:
    out, quote = [], None
    for char in raw:
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#":
            break
        out.append(char)
    return "".join(out)


def _descend(root: dict, path: list[str]) -> dict:
    node = root
    for part in path:
        nxt = node.setdefault(part, {})
        node = nxt[-1] if isinstance(nxt, list) else nxt
    return node


def _append_table(root: dict, path: list[str]) -> dict:
    parent = _descend(root, path[:-1]) if len(path) > 1 else root
    bucket = parent.setdefault(path[-1], [])
    if not isinstance(bucket, list):
        raise TomlSubsetError(f"{'.'.join(path)} is both a table and an array")
    table: dict = {}
    bucket.append(table)
    return table
