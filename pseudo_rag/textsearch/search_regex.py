#!/usr/bin/env python3
"""Búsqueda con expresiones regulares en ficheros de texto extensos.

Uso:
    python search_regex.py PATRON [FICHERO_O_DIR] [--ignore-case] [--multiline]
                           [--only-matching] [--count] [--max N] [--ext ...]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import List, Optional

from .utils import discover_files, Match, print_matches


def search_file(path: str, pattern: str, flags: int = 0, multiline: bool = False,
                only_matching: bool = False) -> List[Match]:
    matches: List[Match] = []
    try:
        rx = re.compile(pattern, flags)
    except re.error as e:
        raise ValueError(f"Expresión regular inválida: {e}")

    if multiline:
        # leer todo el fichero (cuidado con tamaño)
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        for m in rx.finditer(text):
            # calcular número de línea del inicio
            line_no = text.count("\n", 0, m.start()) + 1
            # línea donde está el match
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.start())
            if line_end == -1:
                line_end = len(text)
            line = text[line_start:line_end]
            col = m.start() - line_start + 1
            matches.append(Match(path=path, line_no=line_no, line=line, column=col,
                                matched_text=m.group(0)))
        return matches

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, raw in enumerate(fh, 1):
            line = raw.rstrip("\n").rstrip("\r")
            for m in rx.finditer(line):
                mt = m.group(0) if not only_matching else m.group(0)
                matches.append(Match(path=path, line_no=i, line=line if not only_matching else mt,
                                    column=m.start() + 1, matched_text=m.group(0)))
                if only_matching:
                    # emitir una entrada por cada match en la línea
                    pass
    return matches


def main():
    ap = argparse.ArgumentParser(description="Búsqueda con expresiones regulares.")
    ap.add_argument("pattern", help="Expresión regular")
    ap.add_argument("target", nargs="?", default=".")
    ap.add_argument("-i", "--ignore-case", action="store_true")
    ap.add_argument("-m", "--multiline", action="store_true", help="Modo multilínea (DOTALL)")
    ap.add_argument("-o", "--only-matching", action="store_true", help="Mostrar solo la parte coincidente")
    ap.add_argument("-c", "--count", action="store_true")
    ap.add_argument("-l", "--files-with-matches", action="store_true")
    ap.add_argument("--max", type=int, default=None)
    ap.add_argument("--ext", default=None)
    ap.add_argument("--all-text", action="store_true", help="Incluir cualquier fichero de texto (typ, md, html, ...)")
    ap.add_argument("--json", action="store_true", help="Salida JSON (para pipelines de IA)")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()

    flags = re.IGNORECASE if args.ignore_case else 0
    if args.multiline:
        flags |= re.DOTALL | re.MULTILINE

    exts = [e.strip() for e in args.ext.split(",")] if args.ext else None
    if os.path.isfile(args.target):
        files = [args.target]
    else:
        files = discover_files(args.target, extensions=exts, all_text=args.all_text)

    all_matches = []
    files_with = []
    total = 0
    for f in files:
        try:
            ms = search_file(f, args.pattern, flags=flags, multiline=args.multiline,
                             only_matching=args.only_matching)
        except ValueError as e:
            print(e, file=sys.stderr)
            sys.exit(2)
        if ms:
            files_with.append(f)
            all_matches.extend(ms)
            total += len(ms)
            if args.files_with_matches:
                print(f)

    if args.count:
        if args.json:
            print(json.dumps({"ok": True, "count": total}, ensure_ascii=False))
        else:
            print(total)
        return
    if args.files_with_matches:
        if args.json:
            print(json.dumps({"ok": True, "count": len(files_with), "files": files_with},
                             ensure_ascii=False))
        return
    if args.json:
        out = [m.to_dict() for m in all_matches]
        if args.max is not None:
            out = out[:args.max]
        print(json.dumps({"ok": True, "count": len(out), "results": out}, ensure_ascii=False))
        return
    print_matches(all_matches, color=not args.no_color, max_results=args.max)


if __name__ == "__main__":
    main()
