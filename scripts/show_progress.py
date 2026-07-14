"""Show completion progress for a book.

Usage: python scripts/show_progress.py <book_id>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

from app.progress import get_progress_summary

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("book_id", type=int)
    args = parser.parse_args()

    summary = get_progress_summary(args.book_id)

    print(f"{summary.completed_count} of {summary.total_lessons} lessons complete")
    if summary.last_completed_at:
        print(f"Last completed: {summary.last_completed_at}")
    print()

    for lesson in summary.lessons:
        box = "[x]" if lesson.is_complete else "[ ]"
        print(f"{box} [{lesson.order_index:>3}] {lesson.title}")
