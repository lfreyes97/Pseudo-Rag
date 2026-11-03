"""Wrapper: la web vive en pseudo_rag.web.app. Usa app/ como carpeta de datos (search.db, chroma_db).

    cd app && python main.py        (o:  prag serve)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("PRAG_HOME", os.path.dirname(os.path.abspath(__file__)))

import uvicorn  # noqa: E402
from pseudo_rag.web.app import create_app_from_env  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(create_app_from_env(), host="127.0.0.1", port=5001)
