#!/usr/bin/env python3
"""Wrapper: la lógica vive en pseudo_rag.textsearch.search_engine. Funciona sin instalar nada."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pseudo_rag.textsearch.search_engine import *  # noqa: F401,F403,E402
