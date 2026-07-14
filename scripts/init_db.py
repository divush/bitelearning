"""Create all tables in the SQLite database (idempotent)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DB_PATH
from app.db import init_db

if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
