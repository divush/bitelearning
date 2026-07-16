import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / os.environ.get("BITELEARNING_DB_PATH", "data/bitelearning.db")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

CHUNK_TARGET_TOKENS = 5000
CHUNK_OVERLAP_TOKENS = 1000

SUMMARY_MODEL = "gpt-4.1-mini"
SUMMARY_MAP_BATCH_TOKENS = 950_000

PLAN_MODEL = "gpt-4.1"
MIN_CHUNKS_FOR_LESSON_CANDIDACY = 8

LESSON_RESEARCH_MODEL = "gpt-4.1-mini"
LESSON_COMPOSE_MODEL = "gpt-4.1"
LESSON_GRAPH_RECURSION_LIMIT = 15
