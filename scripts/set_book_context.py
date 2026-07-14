"""Set (or update) the per-book Book Context.

Usage: python scripts/set_book_context.py <book_id> [--goal ...] [--familiarity ...]
           [--focus ...] [--skip ...]

Only flags that are passed get updated; omitted flags leave the existing value untouched.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_session, init_db
from app.models import Book, BookContext

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("book_id", type=int)
    parser.add_argument("--goal")
    parser.add_argument("--familiarity")
    parser.add_argument("--focus")
    parser.add_argument("--skip")
    args = parser.parse_args()

    init_db()
    session = get_session()
    try:
        session.query(Book).filter_by(id=args.book_id).one()  # raises if book doesn't exist

        context = session.query(BookContext).filter_by(book_id=args.book_id).one_or_none()
        if context is None:
            context = BookContext(book_id=args.book_id)
            session.add(context)

        if args.goal is not None:
            context.goal = args.goal
        if args.familiarity is not None:
            context.prior_familiarity = args.familiarity
        if args.focus is not None:
            context.focus_areas = args.focus
        if args.skip is not None:
            context.skip_areas = args.skip

        session.commit()

        print(f"Book context for book {args.book_id}:")
        print(f"  goal:              {context.goal}")
        print(f"  prior_familiarity: {context.prior_familiarity}")
        print(f"  focus_areas:       {context.focus_areas}")
        print(f"  skip_areas:        {context.skip_areas}")
    finally:
        session.close()
