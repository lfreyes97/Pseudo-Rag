"""Resolución de la carpeta de datos (como .git/): la comparten el CLI y la web."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

HOME_DIRNAME = ".prag"


def find_home(start: Optional[str] = None) -> Optional[Path]:
    """PRAG_HOME si existe; si no, busca `.prag/` hacia arriba desde `start` (cwd)."""
    env = os.environ.get("PRAG_HOME")
    if env:
        return Path(env).expanduser().resolve()
    cur = Path(start or os.getcwd()).resolve()
    for d in (cur, *cur.parents):
        cand = d / HOME_DIRNAME
        if cand.is_dir():
            return cand
    return None


def resolve_home(create: bool = False, start: Optional[str] = None) -> Path:
    home = find_home(start)
    if home is None:
        if not create:
            raise FileNotFoundError(
                "No hay índice. Ejecuta `prag index RUTA` aquí o define PRAG_HOME.")
        home = Path(start or os.getcwd()).resolve() / HOME_DIRNAME
    if create:
        home.mkdir(parents=True, exist_ok=True)
    return home


def db_url(home: Path) -> str:
    return f"sqlite:///{home / 'search.db'}"


def chroma_dir(home: Path) -> str:
    return str(home / "chroma_db")
