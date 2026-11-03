#!/usr/bin/env python3
"""Búsqueda paralela en múltiples ficheros usando multiprocessing.

Ideal para directorios con muchos ficheros grandes. Reparte el trabajo entre
varios procesos y agrega los resultados.

Uso:
    python search_parallel.py PATRON [FICHERO_O_DIR] [--workers 4] [--regex]
                              [--ignore-case] [--max N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Tuple

from .utils import discover_files, Match


def _worker(args: Tuple) -> List[dict]:
    path, pattern, regex, ignore_case = args
    out: List[dict] = []
    try:
        if regex:
            import re
            flags = re.IGNORECASE if ignore_case else 0
            rx = re.compile(pattern, flags)
            def hit(s):
                return rx.search(s) is not None
        else:
            nd = pattern.casefold() if ignore_case else pattern
            def hit(s):
                hay = s.casefold() if ignore_case else s
                return nd in hay
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for i, raw in enumerate(fh, 1):
                line = raw.rstrip("\n").rstrip("\r")
                if hit(line):
                    out.append({"path": path, "line_no": i, "line": line,
                                "column": 0, "matched_text": pattern})
    except Exception as e:
        out.append({"__error__": str(e), "path": path})
    return out


def main():
    ap = argparse.ArgumentParser(description="Búsqueda paralela en múltiples ficheros.")
    ap.add_argument("pattern")
    ap.add_argument("target", nargs="?", default=".")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--regex", action="store_true")
    ap.add_argument("-i", "--ignore-case", action="store_true")
    ap.add_argument("--max", type=int, default=None)
    ap.add_argument("--ext", default=None)
    ap.add_argument("--all-text", action="store_true", help="Incluir cualquier fichero de texto (typ, md, html, ...)")
    ap.add_argument("--json", action="store_true", help="Salida JSON (para pipelines de IA)")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()

    exts = [e.strip() for e in args.ext.split(",")] if args.ext else None
    if os.path.isfile(args.target):
        files = [args.target]
    else:
        files = discover_files(args.target, extensions=exts, all_text=args.all_text)

    tasks = [(f, args.pattern, args.regex, args.ignore_case) for f in files]
    all_matches = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(_worker, t) for t in tasks]
        for fut in as_completed(futures):
            res = fut.result()
            for r in res:
                if "__error__" in r:
                    print(f"Error en {r['path']}: {r['__error__']}", file=sys.stderr)
                    continue
                m = Match(path=r["path"], line_no=r["line_no"], line=r["line"],
                          column=r["column"], matched_text=r["matched_text"])
                all_matches.append(m)

    # ordenar por fichero y línea
    all_matches.sort(key=lambda m: (m.path, m.line_no))

    if args.json:
        out = [m.to_dict() for m in all_matches]
        if args.max is not None:
            out = out[:args.max]
        print(json.dumps({"ok": True, "count": len(out), "results": out,
                         "files": len(files)}, ensure_ascii=False))
        return

    n = 0
    for m in all_matches:
        if args.max is not None and n >= args.max:
            print(f"... ({len(all_matches) - n} resultados más)", file=sys.stderr)
            break
        prefix = f"{m.path}:{m.line_no}: "
        print(prefix + m.line)
        n += 1
    print(f"\nTotal: {len(all_matches)} coincidencia(s) en {len(files)} fichero(s).", file=sys.stderr)


if __name__ == "__main__":
    main()
