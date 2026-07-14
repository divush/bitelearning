"""CLI: ingest a PDF and print a chapter/chunk report for manual inspection.

Usage: python scripts/ingest_book.py path/to/book.pdf ["Optional Title"]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import init_db
from app.ingestion.pipeline import ingest_book

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/ingest_book.py path/to/book.pdf [\"Optional Title\"]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else None

    init_db()
    report = ingest_book(pdf_path, title=title)

    print(f"\nBook #{report.book_id}: {report.title} ({report.num_pages} pages)")
    print(f"{len(report.chapters)} chapter(s) detected:\n")
    for ch in report.chapters:
        pages = f"pages {ch.start_page + 1}-{ch.end_page + 1}"
        print(f"  [{ch.order_index:>3}] {ch.title!r:60} {pages:>18}  ({ch.num_chunks} chunks)")
