"""
Pytest database isolation.

The application database may contain an older local schema. Tests should always
run against a fresh SQLite database built from the current repository schema.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from memoria.core.config import configs
from memoria.db import repository


def pytest_sessionstart(session):
    db_dir = Path(tempfile.mkdtemp(prefix="memoria_pytest_"))
    configs.database_url = ""
    configs.database_path = str(db_dir / "memoria.db")
    repository.init_db()
