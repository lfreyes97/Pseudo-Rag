#!/usr/bin/env python3
"""Búsqueda con contexto de líneas circundantes (grep -C / -A / -B).

Soporta búsqueda literal o regex, con N líneas antes/después, agrupación de
bloques solapados y salida coloreada.

Uso:
    python search_context.py PATRON [FICHERO_O_DIR] [-C 3] [-A 2] [-B 2]
                             [--regex] [-i] [--max N]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import List, Optional, Tuple

from .utils import discover_files, Match, print_matches


def search_file(path: str, needle, before: int = 0, after: int = 0,
                regex: bool = False, ignore_case: bool = False) -> List[Match]:
    # leer todas las líneas (ficheros extensos: streaming en dos pasadas es costoso;
    # se mantiene buffer deslizante)
    lines: List[str] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            lines.append(raw.rstrip("\n").rstrip("\r"))

    if regex:
        flags = re.IGNORECASE if ignore_case else 0
        rx = re.compile(needle, flags)
        def is_match(s: str) -> bool:
            return rx.search(s) is not None
    else:
        nd = needle.casefold() if ignore_case else needle
        def is_match(s: str) -> bool:
            hay = s.casefold() if ignore_case else s
            return nd in hay

    matches: List[Match] = []
    n = len(lines)
    hit_indices = [i for i in range(n) if is_match(lines[i])]

    # agrupar índices solapados en bloques
    blocks: List[Tuple[int, int, List[int]]] = []
    for idx in hit_indices:
        if blocks and idx - blocks[-1][1] <= (before + after):
            # solapa o está cerca -> extender
            s, e, hs = blocks[-1]
            ns = min(s, max(0, idx - before))
            ne = max(e, min(n - 1, idx + after))
            blocks[-1] = (ns, ne, hs + [idx])
        else:
            blocks.append((max(0, idx - before), min(n - 1, idx + after), [idx]))

    for s, e, hs in blocks:
        first = hs[0]
        ctx_before = [(ln + 1, lines[ln]) for ln in range(s, first)]
        ctx_after = [(ln + 1, lines[ln]) for ln in range(first + 1, e + 1)]
        matches.append(Match(path=path, line_no=first + 1, line=lines[first],
                            column=0, matched_text=needle if not regex else "",
                            context_before=ctx_before, context_after=ctx_after))
    return matches


def main():
    ap = argparse.ArgumentParser(description="Búsqueda con contexto.")
    ap.add_argument("pattern")
    ap.add_argument("target", nargs="?", default=".")
    ap.add_argument("-C", "--context", type=int, default=0, help="Líneas de contexto antes y después")
    ap.add_argument("-A", "--after", type=int, default=None, help="Líneas después")
    ap.add_argument("-B", "--before", type=int, default=None, help="Líneas antes")
    ap.add_argument("--regex", action="store_true")
    ap.add_argument("-i", "--ignore-case", action="store_true")
    ap.add_argument("--max", type=int, default=None)
    ap.add_argument("--ext", default=None)
    ap.add_argument("--all-text", action="store_true", help="Incluir cualquier fichero de texto (typ, md, html, ...)")
    ap.add_argument("--json", action="store_true", help="Salida JSON (para pipelines de IA)")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()

    before = args.before if args.before is not None else args.context
    after = args.after if args.after is not None else args.context

    exts = [e.strip() for e in args.ext.split(",")] if args.ext else None
    if os.path.isfile(args.target):
        files = [args.target]
    else:
        files = discover_files(args.target, extensions=exts, all_text=args.all_text)

    all_matches = []
    for f in files:
        ms = search_file(f, args.pattern, before=before, after=after,
                         regex=args.regex, ignore_case=args.ignore_case)
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
