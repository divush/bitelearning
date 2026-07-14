import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ingestion.chaptering import detect_chapters
from app.ingestion.pdf_parser import HeadingCandidate, OutlineEntry, ParsedPDF


def _parsed(num_pages, outline=None, heading_candidates=None):
    return ParsedPDF(
        num_pages=num_pages,
        pages=["" for _ in range(num_pages)],
        outline=outline or [],
        heading_candidates=heading_candidates or [],
    )


def test_outline_based_detection():
    outline = [
        OutlineEntry(level=1, title="Chapter 1: Intro", page=0),
        OutlineEntry(level=1, title="Chapter 2: Basics", page=10),
        OutlineEntry(level=1, title="Chapter 3: Advanced", page=25),
        OutlineEntry(level=2, title="1.1 subsection", page=2),  # should not interfere
    ]
    parsed = _parsed(num_pages=40, outline=outline)

    chapters = detect_chapters(parsed)

    assert len(chapters) == 3
    assert [c.title for c in chapters] == ["Chapter 1: Intro", "Chapter 2: Basics", "Chapter 3: Advanced"]
    assert chapters[0].start_page == 0
    assert chapters[0].end_page == 9
    assert chapters[1].start_page == 10
    assert chapters[1].end_page == 24
    assert chapters[2].start_page == 25
    assert chapters[2].end_page == 39


def test_outline_falls_back_to_depth_two_when_depth_one_sparse():
    outline = [
        OutlineEntry(level=1, title="Book Title", page=0),  # only one depth-1 entry
        OutlineEntry(level=2, title="Chapter 1", page=1),
        OutlineEntry(level=2, title="Chapter 2", page=15),
    ]
    parsed = _parsed(num_pages=30, outline=outline)

    chapters = detect_chapters(parsed)

    assert len(chapters) == 2
    assert [c.title for c in chapters] == ["Chapter 1", "Chapter 2"]


def test_heading_heuristic_used_when_no_outline():
    body_size = 10.0
    heading_size = 18.0

    candidates = []
    # running header repeated on every page: must NOT be picked up as a chapter
    for page in range(20):
        candidates.append(HeadingCandidate(page=page, text="My Book Title", font_size=9.5, is_bold=False))

    candidates.append(HeadingCandidate(page=0, text="Chapter 1: Getting Started", font_size=heading_size, is_bold=True))
    for page in range(1, 9):
        candidates.append(HeadingCandidate(page=page, text="Body paragraph text here.", font_size=body_size, is_bold=False))

    candidates.append(HeadingCandidate(page=9, text="Chapter 2: Going Deeper", font_size=heading_size, is_bold=True))
    for page in range(10, 20):
        candidates.append(HeadingCandidate(page=page, text="More body paragraph text.", font_size=body_size, is_bold=False))

    parsed = _parsed(num_pages=20, outline=[], heading_candidates=candidates)

    chapters = detect_chapters(parsed)

    assert len(chapters) == 2
    assert chapters[0].title == "Chapter 1: Getting Started"
    assert chapters[0].start_page == 0
    assert chapters[1].title == "Chapter 2: Going Deeper"
    assert chapters[1].start_page == 9
    assert chapters[1].end_page == 19


def test_single_chapter_fallback_when_nothing_detected():
    parsed = _parsed(num_pages=12, outline=[], heading_candidates=[])

    chapters = detect_chapters(parsed)

    assert len(chapters) == 1
    assert chapters[0].start_page == 0
    assert chapters[0].end_page == 11
