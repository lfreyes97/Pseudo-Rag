"""API programática para el pipeline de IA.

Expone una clase `SearchEngine` y funciones de alto nivel que devuelven
estructuras Python (listas de dict) en lugar de imprimir por consola.
Pensado para ser importado por agentes/IA o llamado vía `pipeline.py`.

Ejemplo:
    from search_engine import SearchEngine
    eng = SearchEngine(root="/data", all_text=True)
    res = eng.search("pacto", mode="regex", ignore_case=True, context=2)
    # res es lista de dict con keys: path, line_no, line, column, matched_text,
    # context_before, context_after
"""

from __future__ import annotations

import os
import sys
from typing import List, Dict, Any, Optional

from .utils import discover_files, Match
from .search_basic import search_file as basic_search
from .search_regex import search_file as regex_search
from .search_context import search_file as context_search
from .search_fuzzy import search_file as fuzzy_search


class SearchEngine:
    def __init__(self, root: str = ".", extensions=None, all_text: bool = False,
                 recursive: bool = True, max_size: Optional[int] = None):
        self.root = root
        self.extensions = extensions
        self.all_text = all_text
        self.recursive = recursive
        self.max_size = max_size
        self._files: Optional[List[str]] = None

    @property
    def files(self) -> List[str]:
        if self._files is None:
            if os.path.isfile(self.root):
                self._files = [self.root]
            else:
                self._files = discover_files(self.root, extensions=self.extensions,
                                             recursive=self.recursive, max_size=self.max_size,
                                             all_text=self.all_text)
        return self._files

    def refresh(self):
        self._files = None

    def search(self, pattern: str, mode: str = "basic", ignore_case: bool = True,
               regex: bool = False, word: bool = False, whole_line: bool = False,
               context: int = 0, before: Optional[int] = None, after: Optional[int] = None,
               fuzzy_threshold: float = 0.6, fuzzy_level: str = "word",
               max_edits: Optional[int] = None, max_results: Optional[int] = None,
               strip_accents: bool = False) -> List[Dict[str, Any]]:
        """Ejecuta la búsqueda y devuelve lista de dicts."""
        before = before if before is not None else context
        after = after if after is not None else context

        all_matches: List[Match] = []
        for f in self.files:
            if mode == "regex":
                import re as _re
                flags = _re.IGNORECASE if ignore_case else 0
                ms = regex_search(f, pattern, flags=flags, multiline=False)
            elif mode == "context":
                ms = context_search(f, pattern, before=before, after=after,
                                    regex=regex, ignore_case=ignore_case)
            elif mode == "fuzzy":
                ms = fuzzy_search(f, pattern, threshold=fuzzy_threshold, level=fuzzy_level,
                                  max_edits=max_edits, ignore_case=ignore_case)
            else:
                ms = basic_search(f, pattern, ignore_case=ignore_case, word=word,
                                  whole_line=whole_line, strip_accents=strip_accents)
            all_matches.extend(ms)

        # ordenar
        all_matches.sort(key=lambda m: (m.path, m.line_no))

        if max_results is not None:
            all_matches = all_matches[:max_results]

        return [m.to_dict() for m in all_matches]

    def count(self, pattern: str, **kwargs) -> int:
        return len(self.search(pattern, **kwargs))

    def files_with_matches(self, pattern: str, **kwargs) -> List[str]:
        res = self.search(pattern, **kwargs)
        return sorted({m["path"] for m in res})


def search_once(root: str = ".", pattern: str = "", **kwargs) -> List[Dict[str, Any]]:
    """Función de conveniencia."""
    eng = SearchEngine(root=root, all_text=kwargs.pop("all_text", False),
                       extensions=kwargs.pop("extensions", None))
    return eng.search(pattern, **kwargs)
