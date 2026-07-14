"""Raw PDF extraction via PyMuPDF: page text, embedded outline, and heading-candidate
spans (font size/weight metadata). Structural decisions (what counts as a chapter)
live in chaptering.py, not here.
"""

from dataclasses import dataclass

import fitz  # PyMuPDF

BOLD_FLAG = 1 << 4


@dataclass
class OutlineEntry:
    level: int
    title: str
    page: int  # 0-based page index


@dataclass
class HeadingCandidate:
    page: int  # 0-based page index
    text: str
    font_size: float
    is_bold: bool


@dataclass
class ParsedPDF:
    num_pages: int
    pages: list[str]  # page text, index = 0-based page number
    outline: list[OutlineEntry]
    heading_candidates: list[HeadingCandidate]


def parse_pdf(path: str) -> ParsedPDF:
    doc = fitz.open(path)
    try:
        pages = [page.get_text() for page in doc]
        outline = _extract_outline(doc)
        heading_candidates = _extract_heading_candidates(doc)
        return ParsedPDF(
            num_pages=doc.page_count,
            pages=pages,
            outline=outline,
            heading_candidates=heading_candidates,
        )
    finally:
        doc.close()


def _extract_outline(doc: "fitz.Document") -> list[OutlineEntry]:
    toc = doc.get_toc(simple=True)  # [[level, title, page(1-based)], ...]
    return [
        OutlineEntry(level=level, title=title.strip(), page=max(page - 1, 0))
        for level, title, page in toc
    ]


def _extract_heading_candidates(doc: "fitz.Document") -> list[HeadingCandidate]:
    """Collect one candidate per text line, tagged with its dominant font size/weight.
    Body-text-size filtering happens in chaptering.py once it has seen the whole
    distribution of sizes.
    """
    candidates: list[HeadingCandidate] = []
    for page_index, page in enumerate(doc):
        raw = page.get_text("dict")
        for block in raw.get("blocks", []):
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                text = "".join(span["text"] for span in spans).strip()
                if not text:
                    continue
                # use the largest span in the line as representative
                dominant = max(spans, key=lambda s: s["size"])
                candidates.append(
                    HeadingCandidate(
                        page=page_index,
                        text=text,
                        font_size=dominant["size"],
                        is_bold=bool(dominant["flags"] & BOLD_FLAG),
                    )
                )
    return candidates
