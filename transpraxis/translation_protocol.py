"""Canonical protocol for translation-model responses.

The translation runtime has one acceptance point for model output.  A response
is either converted into exactly ``expected`` non-empty texts or rejected with
an explicit reason; callers must never recover by treating the raw response as
translation text.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence


_TEXT_KEYS = ("translation", "target", "text", "译文", "翻译", "content")
_EXPLANATION_PREFIX = re.compile(
    r"^(?:以下是(?:译文|翻译)|下面是(?:译文|翻译)|译文如下|"
    r"here(?:'s| is) the translation|translation)\s*[:：]",
    re.IGNORECASE,
)
_NUMBERED_LINE = re.compile(r"^\s*(\d+)[.)、]\s*(.*?)\s*$")


@dataclass
class TranslationProtocolError(ValueError):
    """A model response failed the translation response contract."""

    code: str
    expected: int
    excerpt: str = ""

    def __str__(self) -> str:  # pragma: no cover - exercised through callers
        detail = f"；响应预览：{self.excerpt[:160]!r}" if self.excerpt else ""
        return f"翻译响应协议错误（{self.code}，期望 {self.expected} 项）{detail}"


def _excerpt(response: Any) -> str:
    return str(response or "").strip()[:500]


def _error(code: str, expected: int, response: Any) -> TranslationProtocolError:
    return TranslationProtocolError(code, expected, _excerpt(response))


def _strip_code_fence(value: str) -> tuple[str, bool]:
    match = re.match(r"^\s*```(?:json|text|plaintext)?\s*\n?", value,
                     flags=re.IGNORECASE)
    if not match:
        return value.strip(), False
    candidate = value[match.end():]
    closing = re.search(r"\n?\s*```\s*$", candidate)
    if not closing:
        raise TranslationProtocolError("unclosed_markdown_wrapper", 1, value[:500])
    return candidate[:closing.start()].strip(), True


def _item_text(item: Any, expected: int, response: Any) -> str:
    if isinstance(item, str):
        text = item.strip()
    elif isinstance(item, dict):
        # The legacy array-of-objects form remains accepted, but arbitrary
        # objects are not silently converted by taking their first value.
        values = [item.get(key) for key in _TEXT_KEYS]
        text = next((value.strip() for value in values
                     if isinstance(value, str) and value.strip()), "")
    else:
        text = ""
    if not text:
        raise _error("empty_item_or_unsupported_item", expected, response)
    return text


def _decode_json(candidate: str) -> Optional[Any]:
    try:
        return json.loads(candidate)
    except (TypeError, ValueError):
        pass
    # Keep the old provider tolerance for a short explanation before a JSON
    # payload, while still validating the decoded shape below.
    decoder = json.JSONDecoder()
    for marker in ("[", "{"):
        for match in re.finditer(re.escape(marker), candidate):
            try:
                value, _ = decoder.raw_decode(candidate[match.start():])
            except (TypeError, ValueError):
                continue
            return value
    return None


def _array_items(value: Sequence[Any], expected: int, response: Any) -> List[str]:
    if len(value) != expected:
        raise _error("wrong_item_count", expected, response)
    return [_item_text(item, expected, response) for item in value]


def _object_items(value: Dict[str, Any], expected: int, response: Any) -> List[str]:
    translations = value.get("translations")
    if isinstance(translations, list):
        if len(translations) != expected:
            raise _error("wrong_item_count", expected, response)
        output: List[str] = []
        indexes = []
        for item in translations:
            if not isinstance(item, dict):
                raise _error("unsupported_structured_item", expected, response)
            index = item.get("index")
            if isinstance(index, bool) or not isinstance(index, int):
                raise _error("missing_translation_index", expected, response)
            indexes.append(index)
            output.append(_item_text(item, expected, response))
        if indexes != list(range(expected)):
            raise _error("translation_indexes_not_sequential", expected, response)
        return output

    # Numeric-key objects were emitted by older compatible endpoints.  Keep
    # this narrow compatibility path; arbitrary objects are transport errors.
    if all(str(index) in value for index in range(1, expected + 1)) \
            and len(value) == expected:
        return [_item_text(value[str(index)], expected, response)
                for index in range(1, expected + 1)]
    raise _error("unsupported_structured_shape", expected, response)


def _numbered_items(candidate: str, expected: int, response: Any) -> Optional[List[str]]:
    matches = [_NUMBERED_LINE.match(line) for line in candidate.splitlines()]
    matches = [match for match in matches if match]
    if not matches:
        return None
    indexes = [int(match.group(1)) for match in matches]
    if indexes != list(range(1, expected + 1)):
        raise _error("wrong_numbered_items", expected, response)
    output = [match.group(2).strip() for match in matches]
    if any(not item for item in output):
        raise _error("empty_item", expected, response)
    return output


def parse_translation_response(response: Any, expected: int) -> List[str]:
    """Parse one response into exactly ``expected`` translation strings.

    Accepted forms are the canonical JSON array, the explicit
    ``{"translations": [{"index": 0, "text": "..."}]}`` envelope, the
    legacy numeric-key object, numbered lines, and plain text for a single
    segment.  JSON/Markdown/explanation wrappers never become a target string.
    """
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
        raise ValueError("expected must be a positive integer")
    if not isinstance(response, str) or not response.strip():
        raise _error("empty_response", expected, response)
    raw = response.strip()
    candidate, fenced = _strip_code_fence(raw)
    decoded = _decode_json(candidate)
    if decoded is not None:
        if isinstance(decoded, list):
            return _array_items(decoded, expected, response)
        if isinstance(decoded, dict):
            return _object_items(decoded, expected, response)
        raise _error("unsupported_json_shape", expected, response)

    numbered = _numbered_items(candidate, expected, response)
    if numbered is not None:
        return numbered
    if expected != 1:
        raise _error("missing_structured_response", expected, response)
    if fenced:
        raise _error("markdown_wrapper_without_json", expected, response)
    if candidate.startswith(("[", "{")):
        raise _error("unparseable_transport_wrapper", expected, response)
    if _EXPLANATION_PREFIX.match(candidate):
        raise _error("explanation_prefix", expected, response)
    return [candidate]


def parse_translation_array(response: Any, expected: int) -> Optional[List[str]]:
    """Compatibility wrapper returning ``None`` instead of raising."""
    try:
        return parse_translation_response(response, expected)
    except (TranslationProtocolError, ValueError):
        return None


def json_schema_for_translations(expected: int) -> Dict[str, Any]:
    """Return a provider-neutral strict envelope schema for native JSON output."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "transpraxis_translations",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "translations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "index": {"type": "integer", "minimum": 0},
                                "text": {"type": "string", "minLength": 1},
                            },
                            "required": ["index", "text"],
                        },
                        "minItems": expected,
                        "maxItems": expected,
                    },
                },
                "required": ["translations"],
            },
        },
    }
