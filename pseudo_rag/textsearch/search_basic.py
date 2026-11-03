#!/usr/bin/env python3
"""Búsqueda literal (y por palabras) de texto en ficheros extensos.

Uso:
    python search_basic.py PATRON [FICHERO_O_DIR] [--ignore-case] [--word] [--whole-line]
                            [--count] [--files-with-matches] [--max N]
                            [--ext .txt,.log] [--encoding utf-8]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import List, Optional

from .utils import (discover_files, iter_lines, Match, print_matches, normalize_text)


def search_file(path: str, needle: str, ignore_case: bool = False,
                word: bool = False, whole_line: bool = False,
                normalize: bool = False, strip_accents: bool = False) -> List[Match]:
    matches: List[Match] = []
    needle_n = normalize_text(needle, casefold=ignore_case, strip_accents=strip_accents) if (ignore_case or normalize or strip_accents) else needle
    # precompilar regex de palabra si hace falta
    word_re = None
    if word:
        flags = re.IGNORECASE if ignore_case else 0
        import re
        word_re = re.compile(r"\b" + re.escape(needle) + r"\b", flags)

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, raw in enumerate(fh, 1):
            line = raw.rstrip("\n").rstrip("\r")
            hay = normalize_text(line, casefold=ignore_case, strip_accents=strip_accents) if (ignore_case or normalize or strip_accents) else line
            found = False
            col = 0
            matched_text = needle
            if whole_line:
                if hay == needle_n:
                    found = True
                    col = 1
            elif word and word_re is not None:
                m = word_re.search(line)
                if m:
                    found = True
                    col = m.start() + 1
                    matched_text = m.group(0)
            else:
                idx = hay.find(needle_n)
                if idx >= 0:
                    found = True
                    col = idx + 1
                    # recuperar texto original coincidente
                    matched_text = line[idx:idx + len(needle)]
            if found:
                matches.append(Match(path=path, line_no=i, line=line, column=col,
                                    matched_text=matched_text))
    return matches


def main():
    ap = argparse.ArgumentParser(description="Búsqueda literal de texto en ficheros.")
    ap.add_argument("pattern", help="Texto a buscar")
    ap.add_argument("target", nargs="?", default=".", help="Fichero o directorio")
    ap.add_argument("-i", "--ignore-case", action="store_true", help="Ignorar mayúsculas/minúsculas")
    ap.add_argument("-w", "--word", action="store_true", help="Coincidencia de palabra completa")
    ap.add_argument("-x", "--whole-line", action="store_true", help="La línea entera debe coincidir")
    ap.add_argument("-c", "--count", action="store_true", help="Solo contar coincidencias")
    ap.add_argument("-l", "--files-with-matches", action="store_true", help="Solo listar ficheros con coincidencias")
    ap.add_argument("-m", "--max", type=int, default=None, help="Máximo de resultados")
    ap.add_argument("--ext", default=None, help="Extensiones separadas por coma (ej. .txt,.log)")
    ap.add_argument("--encoding", default="utf-8")
    ap.add_argument("--strip-accents", action="store_true", help="Ignorar acentos")
    ap.add_argument("--all-text", action="store_true", help="Incluir cualquier fichero de texto (typ, md, html, ...)")
    ap.add_argument("--json", action="store_true", help="Salida JSON (para pipelines de IA)")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()

    exts = [e.strip() for e in args.ext.split(",")] if args.ext else None
    if os.path.isfile(args.target):
        files = [args.target]
    else:
        files = discover_files(args.target, extensions=exts, all_text=args.all_text)

    total = 0
    files_with = []
    all_matches = []
    for f in files:
        ms = search_file(f, args.pattern, ignore_case=args.ignore_case, word=args.word,
                         whole_line=args.whole_line, strip_accents=args.strip_accents)
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
        print(json.dumps({"ok": True, "count": len(out), "results": out},
                         ensure_ascii=False))
        return
    print_matches(all_matches, color=not args.no_color, max_results=args.max)


if __name__ == "__main__":
    main()
