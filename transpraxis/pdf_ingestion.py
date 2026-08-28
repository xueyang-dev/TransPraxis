"""Deterministic PDF layout extraction and paragraph reconstruction.

The extractor deliberately keeps layout evidence until after block roles are
classified. Captions, footnotes and running furniture are therefore never
fed into the paragraph joiner merely because a preceding sentence is open.
"""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict
from typing import Any, Dict, List, Sequence, Tuple

import fitz


SENTENCE_TERMINAL = set('.!?"”’…:;)')
ORNAMENT_RE = re.compile(r"^[\s*•·▪◦‣❦❧—–\-]{1,12}$")
PAGE_NUMBER_RE = re.compile(
    r"^\s*(?:page\s+)?\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?\s*$",
    re.IGNORECASE,
)
CAPTION_CUE_RE = re.compile(
    r"^(?:fig(?:ure)?\.?\s*\d+|plate\s*\d+|photo(?:graph)?\.?|"
    r"image\s*\d+|table\s*\d+|source\s*:|courtesy\s*:)",
    re.IGNORECASE,
)
BIBLIOGRAPHY_CUE_RE = re.compile(r"^\s*(?:\[\d+\]|\d+[.)])\s+\S")
ABBREV_RE = re.compile(
    r"\b(?:Lt|Col|Gen|Maj|Capt|Sgt|Brig|Mr|Mrs|Ms|Dr|St|No|Vol|pp|"
    r"e\.g|i\.e|vs|etc|a\.m|p\.m|U\.S|A\.F|B\.C|A\.D)\.",
    re.IGNORECASE,
)

SKIPPED_ROLES = {
    "caption", "footnote", "header", "footer", "page_number", "ornament", "image",
}
JOINABLE_ROLES = {"body", "quote", "bibliography"}


def _bbox(value: Sequence[Any]) -> Dict[str, float]:
    values = list(value or [])[:4]
    values += [0.0] * (4 - len(values))
    x0, y0, x1, y1 = (float(item or 0) for item in values)
    return {
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
        "width": max(0.0, x1 - x0),
        "height": max(0.0, y1 - y0),
    }


def _normalise_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _normalise_repeat(text: str) -> str:
    return re.sub(r"\d+", "#", _normalise_line(text)).casefold()


def _font_metrics(spans: Sequence[Dict[str, Any]]) -> Tuple[float, int, List[str]]:
    sizes = [
        float(span.get("size") or 0)
        for span in spans
        if float(span.get("size") or 0) > 0
    ]
    flags = [int(span.get("flags") or 0) for span in spans]
    fonts = [str(span.get("font") or "") for span in spans if span.get("font")]
    return (
        statistics.median(sizes) if sizes else 0.0,
        max(flags) if flags else 0,
        sorted(set(fonts)),
    )


def extract_layout_blocks(file_bytes: bytes) -> List[Dict[str, Any]]:
    """Extract text and image blocks while retaining page/layout metadata.

    Returned objects are plain dictionaries so they can be inspected in tests
    and persisted as JSON without introducing a second state model.
    """
    blocks: List[Dict[str, Any]] = []
    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
        order = 0
        for page_number, page in enumerate(doc):
            width, height = float(page.rect.width), float(page.rect.height)
            page_dict = page.get_text("dict")
            for raw_number, raw in enumerate(page_dict.get("blocks") or []):
                block_box = _bbox(raw.get("bbox"))
                block_id = f"p{page_number + 1}-b{raw_number}"
                block_type = int(raw.get("type") or 0)
                if block_type == 1:
                    blocks.append(
                        {
                            "block_id": block_id,
                            "block_type": "image",
                            "role": "image",
                            "page_number": page_number + 1,
                            "reading_order": order,
                            "bbox": block_box,
                            "x0": block_box["x0"],
                            "y0": block_box["y0"],
                            "x1": block_box["x1"],
                            "y1": block_box["y1"],
                            "font_size": 0.0,
                            "font_flags": 0,
                            "font_style": [],
                            "relative_width": block_box["width"] / width if width else 0.0,
                            "page_width": width,
                            "page_height": height,
                            "text": "",
                            "lines": [],
                        }
                    )
                    order += 1
                    continue
                if block_type != 0:
                    continue
                line_records = []
                all_spans = []
                for line_number, line in enumerate(raw.get("lines") or []):
                    spans = [
                        span
                        for span in line.get("spans") or []
                        if str(span.get("text") or "")
                    ]
                    text = "".join(str(span.get("text") or "") for span in spans)
                    if not _normalise_line(text):
                        continue
                    line_box = _bbox(line.get("bbox"))
                    size, flags, fonts = _font_metrics(spans)
                    line_records.append(
                        {
                            "line_id": f"{block_id}-l{line_number}",
                            "text": text,
                            "bbox": line_box,
                            "x0": line_box["x0"],
                            "y0": line_box["y0"],
                            "x1": line_box["x1"],
                            "y1": line_box["y1"],
                            "font_size": size,
                            "font_flags": flags,
                            "font_style": fonts,
                        }
                    )
                    all_spans.extend(spans)
                if not line_records:
                    continue
                size, flags, fonts = _font_metrics(all_spans)
                text = _normalise_line(
                    " ".join(line["text"] for line in line_records)
                )
                blocks.append(
                    {
                        "block_id": block_id,
                        "block_type": "text",
                        "role": "unknown",
                        "page_number": page_number + 1,
                        "reading_order": order,
                        "bbox": block_box,
                        "x0": block_box["x0"],
                        "y0": block_box["y0"],
                        "x1": block_box["x1"],
                        "y1": block_box["y1"],
                        "font_size": size,
                        "font_flags": flags,
                        "font_style": fonts,
                        "relative_width": block_box["width"] / width if width else 0.0,
                        "page_width": width,
                        "page_height": height,
                        "text": text,
                        "lines": line_records,
                    }
                )
                order += 1
    return blocks


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _near_image(
    block: Dict[str, Any], image: Dict[str, Any], body_size: float
) -> bool:
    horizontal = _overlap(
        block["x0"], block["x1"], image["x0"], image["x1"]
    )
    if horizontal <= 0:
        return False
    gap = max(image["y0"] - block["y1"], block["y0"] - image["y1"], 0.0)
    return gap <= max(12.0, body_size * 2.8)


def _is_sentence_terminal(text: str) -> bool:
    value = _normalise_line(text)
    if not value:
        return False
    value = re.sub(r"[\]\)}」』”’]+$", "", value).rstrip()
    if ABBREV_RE.search(value[-12:]):
        return False
    return value[-1] in SENTENCE_TERMINAL


def _body_left_edge(text_blocks: Sequence[Dict[str, Any]]) -> float:
    counts = Counter(
        round(float(block.get("x0") or 0), 1) for block in text_blocks
    )
    if not counts:
        return 0.0
    max_count = max(counts.values())
    candidates = [
        x for x, count in counts.items() if count >= max(1, max_count * 0.45)
    ]
    return min(candidates) if candidates else counts.most_common(1)[0][0]


def classify_blocks(blocks: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Assign deterministic roles using typography, position and image relation."""
    out = [dict(block) for block in blocks or []]
    text_blocks = [block for block in out if block.get("block_type") == "text"]
    if not text_blocks:
        return out
    page_counts = {
        int(block.get("page_number") or 0)
        for block in out
        if block.get("page_number")
    }
    body_x0 = _body_left_edge(text_blocks)
    sizes = [
        float(block.get("font_size") or 0)
        for block in text_blocks
        if float(block.get("font_size") or 0) > 0
    ]
    size_counts = Counter(round(size, 1) for size in sizes)
    max_size_count = max(size_counts.values()) if size_counts else 0
    body_candidates = [
        size for size, count in size_counts.items() if count == max_size_count
    ]
    body_size = max(body_candidates) if body_candidates else 10.0
    repeated = Counter(_normalise_repeat(block.get("text")) for block in text_blocks)
    image_by_page = defaultdict(list)
    for block in out:
        if block.get("block_type") == "image":
            image_by_page[int(block.get("page_number") or 0)].append(block)
    page_number = len(page_counts)
    repeat_threshold = max(2, math.ceil(page_number * 0.2)) if page_number > 1 else 99
    for block in out:
        if block.get("block_type") != "text":
            continue
        text = _normalise_line(block.get("text"))
        page_height = float(block.get("page_height") or 0)
        font_size = float(block.get("font_size") or body_size)
        near_image = any(
            _near_image(block, image, body_size)
            for image in image_by_page.get(block.get("page_number"), [])
        )
        role = "body"
        if ORNAMENT_RE.fullmatch(text):
            role = "ornament"
        elif PAGE_NUMBER_RE.fullmatch(text) and (
            block["y0"] < page_height * 0.12
            or block["y1"] > page_height * 0.88
        ):
            role = "page_number"
        elif bool(CAPTION_CUE_RE.match(text)) and (
            font_size <= body_size * 1.05 and len(text) <= 420
        ):
            role = "caption"
        elif near_image and (
            bool(CAPTION_CUE_RE.match(text))
            or (
                font_size <= body_size * 0.96
                and len(text) <= 420
                and len(block.get("lines") or []) <= 6
            )
        ):
            role = "caption"
        elif font_size <= body_size * 0.78 and block["y0"] > page_height * 0.68:
            role = "footnote"
        elif BIBLIOGRAPHY_CUE_RE.match(text) and len(text) <= 700:
            role = "bibliography"
        elif (
            len(text) < 100
            and (repeated[_normalise_repeat(text)] >= repeat_threshold
                 or font_size <= body_size * 0.9)
            and (block["y0"] < page_height * 0.12
                 or block["y1"] > page_height * 0.88)
        ):
            role = "header" if block["y0"] < page_height * 0.2 else "footer"
        elif (
            (font_size >= body_size * 1.18 or block.get("font_flags", 0) & 16)
            and len(text) <= 220
            and len(block.get("lines") or []) <= 4
            and not _is_sentence_terminal(text)
        ):
            role = "heading"
        elif block["x0"] > body_x0 + body_size * 2.2 and len(text) <= 700:
            role = "quote"
        block["role"] = role
        block["body_x0"] = body_x0
        block["body_font_size"] = body_size
        block["near_image"] = near_image
        for line in block.get("lines") or []:
            line["role"] = role
    return out


def _join_text(left: str, right: str) -> str:
    left, right = _normalise_line(left), _normalise_line(right)
    if left.endswith("-") and right[:1].islower():
        return left[:-1] + right
    return f"{left} {right}".strip()


def _line_groups(block: Dict[str, Any]) -> List[Dict[str, Any]]:
    lines = [
        line
        for line in block.get("lines") or []
        if _normalise_line(line.get("text"))
    ]
    if not lines:
        return []
    body_x0 = float(block.get("body_x0") or block.get("x0") or 0)
    body_size = float(
        block.get("body_font_size") or block.get("font_size") or 10
    )
    groups: List[List[Dict[str, Any]]] = [[]]
    for line in lines:
        if groups[-1] and line["x0"] >= body_x0 + max(2.0, body_size * 0.14):
            groups.append([])
        groups[-1].append(line)
    result = []
    for group in groups:
        text = _normalise_line(group[0]["text"])
        for line in group[1:]:
            text = _join_text(text, line["text"])
        result.append(
            {
                "text": text,
                "role": block.get("role") or "body",
                "page_number": block.get("page_number"),
                "block_id": block.get("block_id"),
                "first_line_x0": group[0].get("x0", block.get("x0", 0)),
                "last_y1": group[-1].get("y1", block.get("y1", 0)),
                "page_height": block.get("page_height", 0),
            }
        )
    return result


def reconstruct_paragraph_records(
    blocks: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Join only compatible text roles and return text plus layout provenance."""
    records: List[Dict[str, Any]] = []
    ordered_blocks = sorted(
        blocks or [], key=lambda item: item.get("reading_order", 0)
    )
    last_kept_order = None
    for block in ordered_blocks:
        role = block.get("role") or "body"
        if role in SKIPPED_ROLES:
            continue
        current_order = block.get("reading_order", 0)
        intervening_image = any(
            item.get("role") == "image"
            and (last_kept_order is None or
                 last_kept_order < item.get("reading_order", 0) < current_order)
            for item in ordered_blocks
        )
        for group in _line_groups(block):
            if not group["text"] or group["role"] in SKIPPED_ROLES:
                continue
            current = {
                "text": group["text"],
                "role": group["role"],
                "page_numbers": [group["page_number"]],
                "block_ids": [group["block_id"]],
                "first_line_x0": group["first_line_x0"],
                "last_y1": group["last_y1"],
                "page_height": group["page_height"],
                "reading_order": current_order,
            }
            if records:
                previous = records[-1]
                same_role = (
                    previous["role"] in JOINABLE_ROLES
                    and role in JOINABLE_ROLES
                )
                body_x0 = float(
                    block.get("body_x0") or block.get("x0") or 0
                )
                is_indented = current["first_line_x0"] >= body_x0 + max(
                    2.0, float(block.get("body_font_size") or 10) * 0.14
                )
                page_break = (
                    current["page_numbers"][0]
                    != previous["page_numbers"][-1]
                )
                gap = current["last_y1"] - previous["last_y1"]
                close_enough = page_break or gap <= max(
                    220.0, float(block.get("body_font_size") or 10) * 12
                ) or intervening_image
                if (
                    same_role
                    and not is_indented
                    and not _is_sentence_terminal(previous["text"])
                    and (len(previous["text"]) > 40 or intervening_image)
                    and close_enough
                ):
                    previous["text"] = _join_text(
                        previous["text"], current["text"]
                    )
                    previous["page_numbers"].extend(current["page_numbers"])
                    previous["block_ids"].extend(current["block_ids"])
                    previous["last_y1"] = current["last_y1"]
                    previous["reading_order"] = current_order
                    last_kept_order = current_order
                    continue
            records.append(current)
            last_kept_order = current_order
    return records


def reconstruct_paragraphs(blocks: Sequence[Dict[str, Any]]) -> List[str]:
    """Reconstruct main-text paragraphs after role classification."""
    return [
        record["text"]
        for record in reconstruct_paragraph_records(blocks)
        if record.get("text") and not ORNAMENT_RE.fullmatch(record["text"])
    ]


def extract_pdf_paragraphs(file_bytes: bytes) -> List[str]:
    """Extract body/heading paragraphs while excluding captions and page furniture."""
    return reconstruct_paragraphs(classify_blocks(extract_layout_blocks(file_bytes)))
