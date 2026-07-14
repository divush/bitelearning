"""CLI: generate rolling per-chapter summaries for an already-ingested book.

Usage: python scripts/summarize_book.py <book_id> [--force]
"""

import argparse
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.generation.summarizer import summarize_book

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("book_id", type=int)
    parser.add_argument("--force", action="store_true", help="Regenerate summaries even if already present")
    args = parser.parse_args()

    for result in summarize_book(args.book_id, force=args.force):
        chapter = result.chapter
        if result.status == "skipped_empty":
            print(f"[{chapter.order_index:>3}] {chapter.title!r} -- skipped (0 chunks)")
        elif result.status == "skipped_existing":
            print(f"[{chapter.order_index:>3}] {chapter.title!r} -- already summarized, skipped")
        else:
            print(f"[{chapter.order_index:>3}] {chapter.title!r} -- generated:")
            print(textwrap.indent(textwrap.fill(chapter.summary, width=100), "      "))
        print()
