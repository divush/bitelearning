"""Mark a lesson complete (or, with --undo, back to incomplete).

Usage: python scripts/mark_lesson.py <book_id> <lesson_index> [--undo]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

from app.progress import mark_lesson_complete, mark_lesson_incomplete

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("book_id", type=int)
    parser.add_argument("lesson_index", type=int)
    parser.add_argument("--undo", action="store_true", help="Mark incomplete instead of complete")
    args = parser.parse_args()

    try:
        if args.undo:
            lesson = mark_lesson_incomplete(args.book_id, args.lesson_index)
            print(f"[{lesson.order_index:>3}] {lesson.title!r} -- marked incomplete")
        else:
            lesson = mark_lesson_complete(args.book_id, args.lesson_index)
            print(f"[{lesson.order_index:>3}] {lesson.title!r} -- marked complete at {lesson.completed_at}")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
