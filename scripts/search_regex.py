#!/usr/bin/env python3
"""Wrapper: la lógica vive en pseudo_rag.textsearch.search_regex. Funciona sin instalar nada."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pseudo_rag.textsearch.search_regex import *  # noqa: F401,F403,E402
from pseudo_rag.textsearch.search_regex import main  # noqa: E402

if __name__ == "__main__":
    main()
