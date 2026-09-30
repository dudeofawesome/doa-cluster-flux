"""Run upstream migrations and web server without the root-only cron wrapper."""

import os
from pathlib import Path
import subprocess
from urllib.parse import quote

# CloudNativePG owns the credentials; encode reserved characters in passwords.
os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://"
    + quote(os.environ["DB_USER"], safe="")
    + ":"
    + quote(os.environ["DB_PASSWORD"], safe="")
    + "@postgres-rw:5432/filaman"
)
Path("/app/data/uploads").mkdir(parents=True, exist_ok=True)
Path("/app/data/python").mkdir(parents=True, exist_ok=True)
subprocess.run(["alembic", "upgrade", "head"], check=True)
os.execvp("gunicorn", [
    "gunicorn", "--workers", "1",
    "--worker-class", "uvicorn.workers.UvicornWorker",
    "--bind", "0.0.0.0:8000", "--timeout", "120",
    "--keep-alive", "5", "--worker-tmp-dir", "/tmp", "--no-control-socket",
    "--access-logfile", "-", "app.main:app",
])
