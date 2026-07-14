"""Set (or update) the single standing Learner Profile.

Usage: python scripts/set_learner_profile.py [--example-first-vs-theory-first ...]
           [--session-length ...] [--depth-vs-breadth ...] [--tone ...] [--notes ...]

Only flags that are passed get updated; omitted flags leave the existing value untouched.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_session, init_db
from app.models import LearnerProfile

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--example-first-vs-theory-first")
    parser.add_argument("--session-length")
    parser.add_argument("--depth-vs-breadth")
    parser.add_argument("--tone")
    parser.add_argument("--notes")
    args = parser.parse_args()

    init_db()
    session = get_session()
    try:
        profile = session.query(LearnerProfile).filter_by(id=1).one_or_none()
        if profile is None:
            profile = LearnerProfile(id=1)
            session.add(profile)

        if args.example_first_vs_theory_first is not None:
            profile.example_first_vs_theory_first = args.example_first_vs_theory_first
        if args.session_length is not None:
            profile.session_length_pref = args.session_length
        if args.depth_vs_breadth is not None:
            profile.depth_vs_breadth = args.depth_vs_breadth
        if args.tone is not None:
            profile.tone_pref = args.tone
        if args.notes is not None:
            profile.raw_notes = args.notes

        session.commit()

        print("Learner profile:")
        print(f"  example_first_vs_theory_first: {profile.example_first_vs_theory_first}")
        print(f"  session_length_pref:           {profile.session_length_pref}")
        print(f"  depth_vs_breadth:              {profile.depth_vs_breadth}")
        print(f"  tone_pref:                     {profile.tone_pref}")
        print(f"  raw_notes:                     {profile.raw_notes}")
    finally:
        session.close()
