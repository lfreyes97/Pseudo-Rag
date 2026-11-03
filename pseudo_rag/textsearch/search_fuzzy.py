#!/usr/bin/env python3
"""Búsqueda difusa (fuzzy) tolerante a errores tipográficos en ficheros extensos.

Usa distancia de Levenshtein a nivel de línea o de palabra. No requiere dependencias
externas (implementación pura en Python). Para grandes volúmenes se recomienda
pre-filtrar con search_basic.

Uso:
    python search_fuzzy.py PATRON [FICHERO_O_DIR] [--threshold 0.6] [--level line|word]
                           [--max-edits 2] [--max N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from .utils import discover_files, Match, print_matches, normalize_text


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    # optimización: solo una fila
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    d = levenshtein(a, b)
    return 1.0 - d / max(len(a), len(b))


def search_file(path: str, needle: str, threshold: float = 0.6,
                level: str = "line", max_edits: Optional[int] = None,
                ignore_case: bool = True) -> List[Match]:
    matches: List[Match] = []
    needle_n = normalize_text(needle, casefold=ignore_case)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, raw in enumerate(fh, 1):
            line = raw.rstrip("\n").rstrip("\r")
            hay = normalize_text(line, casefold=ignore_case)
            ok = False
            col = 1
            mt = line
            if level == "line":
                if needle_n and len(hay) > 0:
                    sim = similarity(needle_n, hay)
                    dist = levenshtein(needle_n, hay)
                    if (max_edits is not None and dist <= max_edits) or (max_edits is None and sim >= threshold):
                        ok = True
            else:  # word
                words = hay.split()
                for w in words:
                    dist = levenshtein(needle_n, w)
                    if (max_edits is not None and dist <= max_edits) or (max_edits is None and similarity(needle_n, w) >= threshold):
                        ok = True
                        break
            if ok:
                matches.append(Match(path=path, line_no=i, line=line, column=col,
                                    matched_text=mt))
    return matches


def main():
    ap = argparse.ArgumentParser(description="Búsqueda difusa tolerante a errores.")
    ap.add_argument("pattern")
    ap.add_argument("target", nargs="?", default=".")
    ap.add_argument("--threshold", type=float, default=0.6, help="Similitud mínima 0-1")
    ap.add_argument("--level", choices=["line", "word"], default="line")
    ap.add_argument("--max-edits", type=int, default=None, help="Distancia máxima de Levenshtein")
    ap.add_argument("-i", "--ignore-case", action="store_true", default=True)
    ap.add_argument("--no-ignore-case", action="store_true")
    ap.add_argument("--max", type=int, default=None)
    ap.add_argument("--ext", default=None)
    ap.add_argument("--all-text", action="store_true", help="Incluir cualquier fichero de texto (typ, md, html, ...)")
    ap.add_argument("--json", action="store_true", help="Salida JSON (para pipelines de IA)")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()

    ignore_case = not args.no_ignore_case

    exts = [e.strip() for e in args.ext.split(",")] if args.ext else None
    if os.path.isfile(args.target):
        files = [args.target]
    else:
        files = discover_files(args.target, extensions=exts, all_text=args.all_text)

    all_matches = []
    for f in files:
        ms = search_file(f, args.pattern, threshold=args.threshold, level=args.level,
                         max_edits=args.max_edits, ignore_case=ignore_case)
        all_matches.extend(ms)

    if args.json:
        out = [m.to_dict() for m in all_matches]
        if args.max is not None:
            out = out[:args.max]
        print(json.dumps({"ok": True, "count": len(out), "results": out}, ensure_ascii=False))
        return
    print_matches(all_matches, color=not args.no_color, max_results=args.max)


if __name__ == "__main__":
    main()
