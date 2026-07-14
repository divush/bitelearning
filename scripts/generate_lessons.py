"""CLI: generate lesson content for a book with an existing plan.

Usage: python scripts/generate_lessons.py <book_id> [--force] [--lesson-index N]
"""

import argparse
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.generation.lesson_generator import generate_book_lessons

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("book_id", type=int)
    parser.add_argument("--force", action="store_true", help="Regenerate even if already generated")
    parser.add_argument("--lesson-index", type=int, default=None, help="Only generate this one lesson (by order_index)")
    args = parser.parse_args()

    try:
        results = generate_book_lessons(
            args.book_id, force=args.force, lesson_index=args.lesson_index
        )
        for result in results:
            lesson = result.lesson
            if result.status == "skipped_existing":
                print(f"[{lesson.order_index:>3}] {lesson.title!r} -- already generated, skipped\n")
                continue
            if result.status == "failed":
                print(f"[{lesson.order_index:>3}] {lesson.title!r} -- FAILED: {result.error}\n")
                continue

            print(f"[{lesson.order_index:>3}] {lesson.title!r} -- generated")
            print(textwrap.indent(textwrap.fill(lesson.content, width=100), "      "))

            references = json.loads(lesson.external_references or "[]")
            if references:
                print("      references:")
                for ref in references:
                    print(f"        - {ref['title']} ({ref['url']}) -- {ref['why_relevant']}")

            exercises = json.loads(lesson.exercises or "[]")
            if exercises:
                print("      exercises:")
                for ex in exercises:
                    print(f"        - {ex['prompt']}")
                    if ex.get("guidance"):
                        print(f"          guidance: {ex['guidance']}")
            print()
    except ValueError as e:
        print(f"Not generated: {e}")
        sys.exit(1)
