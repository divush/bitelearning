"""FastAPI dependency for a DB session - the one seam where request handling
crosses into persistence. Lives in app/services/ (not app/web/) so the web
package itself never imports app.db directly.
"""

from app.db import get_session


def get_db():
    session = get_session()
    try:
        yield session
    finally:
        session.close()
