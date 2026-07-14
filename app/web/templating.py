"""Shared Jinja2Templates instance, kept separate from app.py to avoid a
circular import between app.py and routes.py.
"""

from pathlib import Path

import markdown as markdown_lib
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["markdown"] = lambda text: markdown_lib.markdown(
    text or "", extensions=["extra"]
)
