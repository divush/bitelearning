"""CLI: generate the ordered lesson plan for an already-ingested, summarized book.

Usage: python scripts/generate_plan.py <book_id> [--force]
"""

import argparse
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_session
from app.generation.plan_generator import generate_plan
from app.models import Chapter, Lesson

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("book_id", type=int)
    parser.add_argument("--force", action="store_true", help="Delete and regenerate an existing plan")
    args = parser.parse_args()

    try:
        plan = generate_plan(args.book_id, force=args.force)
    except ValueError as e:
        print(f"Not generated: {e}")
        sys.exit(1)

    session = get_session()
    try:
        chapters_by_id = {c.id: c.title for c in session.query(Chapter).filter_by(book_id=args.book_id).all()}
        lessons = session.query(Lesson).filter_by(plan_id=plan.id).order_by(Lesson.order_index).all()

        print(f"Plan #{plan.id} for book {args.book_id}: {len(lessons)} lesson(s)\n")
        for lesson in lessons:
            source_titles = [chapters_by_id.get(cid, f"?({cid})") for cid in json.loads(lesson.source_chapter_ids)]
            print(f"[{lesson.order_index:>3}] {lesson.title}")
            print(textwrap.indent(textwrap.fill(lesson.topic_summary, width=100), "      "))
            print(f"      sources: {', '.join(source_titles)}")
            print()
    finally:
        session.close()
