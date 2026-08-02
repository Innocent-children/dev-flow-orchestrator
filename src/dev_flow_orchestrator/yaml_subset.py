"""Strict parser for the small YAML subset used by workflow definitions.

The plugin runtime is standard-library only, so PyYAML is not available.
This module parses the YAML 1.2 subset used by workflow files -- block
mappings, block sequences, flow collections, and plain scalars -- and
rejects everything else with a line-numbered error. Callers should try
``json.loads`` first: JSON is a YAML 1.2 subset and the standard library
parses it for free, so workflow authors may write either dialect.

Rejected constructs (hard errors, never silently accepted): tab
characters anywhere, anchors/aliases/tags, block scalars (``|`` and
``>``), multiline quoted strings, unterminated flow collections,
duplicate keys, mixed mapping/sequence blocks, nested sequence items,
and trailing content.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, List, Mapping, Sequence, Tuple


_INTEGER_RE = re.compile(r"^[+-]?[0-9]+$")


class YAMLSubsetError(ValueError):
    """A parse violation with a 1-based line number."""

    def __init__(self, message: str, line: int) -> None:
        super().__init__("line {}: {}".format(line, message))
        self.line = line


class _JSONSemanticError(ValueError):
    """A valid JSON token stream whose object semantics are disallowed."""


@dataclass(frozen=True)
class _MappingEntry:
    line: int
    key: str
    value: object


@dataclass(frozen=True)
class _SequenceEntry:
    line: int
    value: object


def _strip_comment(line: str) -> str:
    """Remove a trailing ``#`` comment that is not inside a quoted string."""
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(line):
        if in_double and char == "\\" and not escaped:
            escaped = True
            continue
        if escaped:
            escaped = False
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif (
            char == "#"
            and not in_single
            and not in_double
            and (index == 0 or line[index - 1].isspace())
        ):
            return line[:index]
    return line


def _preprocess(text: str) -> List[Tuple[int, str]]:
    """Split into (line_number, content) pairs, comments removed."""
    lines: List[Tuple[int, str]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw:
            raise YAMLSubsetError("tab characters are not allowed", number)
        content = _strip_comment(raw).rstrip()
        if not content.strip():
            continue
        lines.append((number, content))
    if not lines:
        raise YAMLSubsetError("empty document", 1)
    return lines


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _put_unique(mapping: dict, key: object, value: object, line: int) -> None:
    if key in mapping:
        raise YAMLSubsetError("duplicate key {!r}".format(key), line)
    mapping[key] = value


def _unquote_key(key: str, line: int) -> str:
    key = key.strip()
    if not key:
        raise YAMLSubsetError("empty mapping key", line)
    if key[0] == '"' or key[0] == "'":
        return _parse_scalar(key, line)  # type: ignore[return-value]
    return key


def _split_key(part: str, line: int) -> Tuple[str, int]:
    """Split ``key: value`` at the first colon outside quotes."""
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(part):
        if in_double and char == "\\" and not escaped:
            escaped = True
            continue
        if escaped:
            escaped = False
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == ":" and not in_single and not in_double:
            return _unquote_key(part[:index], line), index
    raise YAMLSubsetError("expected a mapping entry 'key: value'", line)


def _parse_double_quoted(text: str, line: int) -> str:
    if len(text) < 2 or text[-1] != '"':
        raise YAMLSubsetError("unterminated double-quoted string", line)
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise YAMLSubsetError("invalid double-quoted string: {}".format(exc), line)
    if not isinstance(value, str):
        raise YAMLSubsetError("expected a quoted string", line)
    return value


def _parse_single_quoted(text: str, line: int) -> str:
    if len(text) < 2 or text[-1] != "'":
        raise YAMLSubsetError("unterminated single-quoted string", line)
    return text[1:-1].replace("''", "'")


def _split_flow_parts(content: str, line: int) -> List[str]:
    """Split a flow collection body on top-level commas outside quotes."""
    parts: List[str] = []
    start = 0
    depth = 0
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(content):
        if in_double and char == "\\" and not escaped:
            escaped = True
            continue
        if escaped:
            escaped = False
            continue
        if in_single:
            if char == "'":
                in_single = False
            continue
        if in_double:
            if char == '"':
                in_double = False
            continue
        if char == "'":
            in_single = True
        elif char == '"':
            in_double = True
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth < 0:
                raise YAMLSubsetError("unbalanced flow collection", line)
        elif char == "," and depth == 0:
            parts.append(content[start:index].strip())
            start = index + 1
    if in_single or in_double or depth != 0:
        raise YAMLSubsetError("unbalanced flow collection", line)
    parts.append(content[start:].strip())
    return parts


def _parse_flow(text: str, line: int) -> object:
    opener = text[0]
    closer = "}" if opener == "{" else "]"
    if text[-1] != closer:
        raise YAMLSubsetError("unterminated flow collection", line)
    content = text[1:-1].strip()
    if not content:
        return {} if opener == "{" else []
    parts = _split_flow_parts(content, line)
    if opener == "{":
        mapping: dict = {}
        for part in parts:
            if not part:
                raise YAMLSubsetError("empty flow mapping entry", line)
            key, separator = _split_key(part, line)
            value_text = part[separator + 1 :].strip()
            if not value_text:
                raise YAMLSubsetError(
                    "flow mapping entry {!r} has no value".format(part), line
                )
            _put_unique(mapping, key, _parse_scalar(value_text, line), line)
        return mapping
    return [_parse_scalar(part, line) for part in parts]


def _parse_scalar(text: str, line: int) -> object:
    text = text.strip()
    if not text:
        return None
    if text[0] == '"':
        return _parse_double_quoted(text, line)
    if text[0] == "'":
        return _parse_single_quoted(text, line)
    if text[0] in "[{":
        return _parse_flow(text, line)
    if text[0] in "&*!|>":
        raise YAMLSubsetError(
            "unsupported YAML construct (anchors, aliases, tags and block "
            "scalars are not supported)",
            line,
        )
    if text == "true":
        return True
    if text == "false":
        return False
    if text == "null":
        return None
    if _INTEGER_RE.fullmatch(text):
        return int(text)
    return text


def _block_to_value(entries: List[object], line: int) -> object:
    """Turn parsed block entries into a dict or a list."""
    if not entries:
        return {}
    if isinstance(entries[0], _MappingEntry):
        mapping: dict = {}
        for entry in entries:
            if not isinstance(entry, _MappingEntry):
                raise YAMLSubsetError(
                    "mixed mapping and sequence entries are not supported",
                    entry.line,
                )
            _put_unique(mapping, entry.key, entry.value, entry.line)
        return mapping
    items: List[object] = []
    for entry in entries:
        if not isinstance(entry, _SequenceEntry):
            raise YAMLSubsetError(
                "mixed mapping and sequence entries are not supported",
                entry.line,
            )
        items.append(entry.value)
    return items


def _parse_block(
    lines: Sequence[Tuple[int, str]], index: int, column: int
) -> Tuple[List[object], int]:
    """Parse entries at exactly ``column``; return (entries, next_index)."""
    entries: List[object] = []
    while index < len(lines):
        number, line = lines[index]
        indent = _indent(line)
        if indent < column:
            break
        if indent > column:
            raise YAMLSubsetError("unexpected indentation", number)
        stripped = line.strip()
        if stripped.startswith("-") and (len(stripped) == 1 or stripped[1] == " "):
            item, index = _parse_sequence_item(lines, index, column)
            entries.append(_SequenceEntry(number, item))
        else:
            number2, key, value, index = _parse_mapping_entry(lines, index)
            entries.append(_MappingEntry(number2, key, value))
    return entries, index


def _parse_mapping_entry(
    lines: Sequence[Tuple[int, str]], index: int
) -> Tuple[int, str, object, int]:
    """Parse one mapping entry at lines[index]; return (line, key, value, next)."""
    number, line = lines[index]
    key, separator = _split_key(line, number)
    rest = line[separator + 1 :].strip()
    if rest:
        return number, key, _parse_scalar(rest, number), index + 1
    if index + 1 >= len(lines):
        raise YAMLSubsetError(
            "mapping key {!r} has no value".format(key), number
        )
    child_column = _indent(lines[index + 1][1])
    if child_column <= _indent(line):
        raise YAMLSubsetError(
            "mapping key {!r} has no value".format(key), number
        )
    child, next_index = _parse_block(lines, index + 1, child_column)
    return number, key, _block_to_value(child, number), next_index


def _sequence_mapping_entry(part: str, line: int) -> Tuple[str, int] | None:
    """Split an inline sequence-item mapping entry.

    ``- key: value`` is a mapping item; ``- /path`` is a plain scalar.
    A colon qualifies as a mapping separator only when followed by a
    space or end of line (matching the YAML plain-scalar rule).
    """
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(part):
        if in_double and char == "\\" and not escaped:
            escaped = True
            continue
        if escaped:
            escaped = False
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == ":" and not in_single and not in_double:
            if index + 1 == len(part) or part[index + 1] in " \t":
                return _unquote_key(part[:index], line), index
            return None
    return None


def _parse_sequence_item(
    lines: Sequence[Tuple[int, str]], index: int, column: int
) -> Tuple[object, int]:
    """Parse one sequence item starting at lines[index]; return (item, next)."""
    number, line = lines[index]
    rest = line.strip()[1:].strip()
    index += 1
    if not rest:
        if index >= len(lines):
            raise YAMLSubsetError("empty sequence item", number)
        child_column = _indent(lines[index][1])
        if child_column <= column:
            raise YAMLSubsetError("sequence item has no value", number)
        child, next_index = _parse_block(lines, index, child_column)
        return _block_to_value(child, number), next_index
    if rest[0] in "[{":
        return _parse_flow(rest, number), index
    if rest.startswith("-") and (len(rest) == 1 or rest[1] == " "):
        raise YAMLSubsetError("nested sequence items are not supported", number)
    inline = _sequence_mapping_entry(rest, number)
    if inline is None:
        return _parse_scalar(rest, number), index
    key, separator = inline
    mapping: dict = {}
    value_text = rest[separator + 1 :].strip()
    if value_text:
        mapping[key] = _parse_scalar(value_text, number)
    elif index < len(lines) and _indent(lines[index][1]) > column + 2:
        child_column = _indent(lines[index][1])
        child, next_index = _parse_block(lines, index, child_column)
        mapping[key] = _block_to_value(child, number)
        index = next_index
    else:
        raise YAMLSubsetError(
            "sequence item {!r} has no value".format(rest), number
        )
    while index < len(lines):
        number2, line2 = lines[index]
        indent2 = _indent(line2)
        if indent2 < column + 2:
            break
        if indent2 > column + 2:
            raise YAMLSubsetError("unexpected indentation", number2)
        stripped2 = line2.strip()
        if stripped2.startswith("-") and (len(stripped2) == 1 or stripped2[1] == " "):
            raise YAMLSubsetError(
                "unexpected sequence inside a mapping item", number2
            )
        number3, key2, value2, next_index = _parse_mapping_entry(lines, index)
        _put_unique(mapping, key2, value2, number3)
        index = next_index
    return mapping, index


def load(text: str) -> object:
    """Parse a document in the YAML subset.

    Raises :class:`YAMLSubsetError` (a ``ValueError``) on any violation.
    Returns plain ``dict``/``list``/scalar values.
    """
    lines = _preprocess(text)
    number, first = lines[0]
    if first[0] in "[{":
        if len(lines) != 1:
            raise YAMLSubsetError("content after a flow document", lines[1][0])
        return _parse_flow(first, number)
    entries, index = _parse_block(lines, 0, 0)
    if index != len(lines):
        raise YAMLSubsetError("trailing content", lines[index][0])
    return _block_to_value(entries, number)


def load_or_json(text: str) -> object:
    """Parse JSON first (free, exact), then the YAML subset."""
    def unique_object(pairs: List[Tuple[str, object]]) -> dict:
        mapping = {}
        for key, value in pairs:
            if key in mapping:
                raise _JSONSemanticError(
                    "duplicate JSON key {!r}".format(key)
                )
            mapping[key] = value
        return mapping

    def reject_constant(value: str) -> object:
        raise _JSONSemanticError(
            "non-finite JSON number {!r} is not supported".format(value)
        )

    try:
        return json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError:
        return load(text)
