"""Chapter boundary detection, in order of preference:
  1. Embedded PDF outline/bookmarks (cheap, reliable when present)
  2. Font-size/regex heading heuristic (for PDFs with no usable outline)
  3. Single-chapter fallback (never error out, just produce a coarser plan)
"""

import re
import statistics
from collections import Counter
from dataclasses import dataclass

from app.ingestion.pdf_parser import HeadingCandidate, OutlineEntry, ParsedPDF

CHAPTER_HEADING_RE = re.compile(
    r"^(chapter|part|section)\s+([0-9]+|[ivxlcdm]+\b|[a-z]+\b)", re.IGNORECASE
)


@dataclass
class DetectedChapter:
    order_index: int
    title: str
    start_page: int  # 0-based, inclusive
    end_page: int  # 0-based, inclusive


def detect_chapters(parsed: ParsedPDF) -> list[DetectedChapter]:
    chapters = _from_outline(parsed.outline, parsed.num_pages)
    if chapters:
        return chapters

    chapters = _from_heading_heuristic(parsed.heading_candidates, parsed.num_pages)
    if chapters:
        return chapters

    return _single_chapter_fallback(parsed.num_pages)


def _build_chapters(starts: list[tuple[int, str]], num_pages: int) -> list[DetectedChapter]:
    """starts: sorted, deduped list of (start_page, title) tuples."""
    chapters = []
    for i, (start_page, title) in enumerate(starts):
        end_page = starts[i + 1][0] - 1 if i + 1 < len(starts) else num_pages - 1
        if end_page < start_page:
            end_page = start_page
        chapters.append(DetectedChapter(order_index=i, title=title, start_page=start_page, end_page=end_page))
    return chapters


def _from_outline(outline: list[OutlineEntry], num_pages: int) -> list[DetectedChapter]:
    for level in (1, 2, 3):
        entries = sorted(
            (e for e in outline if e.level == level),
            key=lambda e: e.page,
        )
        if len(entries) < 2:
            continue

        starts: list[tuple[int, str]] = []
        seen_pages = set()
        for e in entries:
            if e.page in seen_pages:
                continue
            seen_pages.add(e.page)
            starts.append((e.page, e.title))

        if len(starts) >= 2:
            return _build_chapters(starts, num_pages)

    return []


def _from_heading_heuristic(candidates: list[HeadingCandidate], num_pages: int) -> list[DetectedChapter]:
    if not candidates:
        return []

    body_size = _dominant_font_size(candidates)
    heading_threshold = body_size * 1.25

    raw_headings = [
        c
        for c in candidates
        if CHAPTER_HEADING_RE.match(c.text.strip())
        or (c.font_size >= heading_threshold and len(c.text) <= 80 and not c.text.rstrip().endswith("."))
    ]
    if not raw_headings:
        return []

    # Drop text that repeats across many pages (running headers/footers, not real headings)
    text_counts = Counter(c.text.strip() for c in raw_headings)
    repeat_threshold = max(3, num_pages // 3)
    headings = [c for c in raw_headings if text_counts[c.text.strip()] < repeat_threshold]
    if len(headings) < 2:
        return []

    # Collapse consecutive candidates on the same page into a single heading
    starts: list[tuple[int, str]] = []
    seen_pages = set()
    for c in headings:
        if c.page in seen_pages:
            continue
        seen_pages.add(c.page)
        starts.append((c.page, c.text.strip()))

    if len(starts) < 2:
        return []

    starts.sort(key=lambda s: s[0])
    return _build_chapters(starts, num_pages)


def _dominant_font_size(candidates: list[HeadingCandidate]) -> float:
    sizes = [round(c.font_size, 1) for c in candidates]
    return statistics.mode(sizes)


def _single_chapter_fallback(num_pages: int) -> list[DetectedChapter]:
    return [DetectedChapter(order_index=0, title="Full Book", start_page=0, end_page=max(num_pages - 1, 0))]
