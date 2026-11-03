#!/usr/bin/env python3
"""Índice invertido para búsquedas rápidas en colecciones de ficheros extensos.

Construye un índice (JSON) que mapea cada token a la lista de (fichero, línea)
donde aparece. Permite búsquedas posteriores casi instantáneas.

Uso:
    # Construir índice
    python search_index.py build RUTA --out indice.json [--ext .txt,.log]

    # Buscar en índice
    python search_index.py search TERMINO --index indice.json [--max N]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from typing import Dict, List

from .utils import discover_files, normalize_text


TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str, casefold: bool = True, min_len: int = 2) -> List[str]:
    if casefold:
        text = text.casefold()
    return [t for t in TOKEN_RE.findall(text) if len(t) >= min_len]


def build_index(root: str, extensions=None, min_len: int = 2, all_text: bool = False) -> dict:
    files = discover_files(root, extensions=extensions, all_text=all_text)
    # índice: token -> {path: [line_numbers]}
    index: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))
    file_meta: Dict[str, dict] = {}
    for path in files:
        file_meta[path] = {"size": os.path.getsize(path), "lines": 0}
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for i, raw in enumerate(fh, 1):
                file_meta[path]["lines"] += 1
                line = raw.rstrip("\n").rstrip("\r")
                seen = set()
                for tok in tokenize(line, min_len=min_len):
                    if tok not in seen:
                        index[tok][path].append(i)
                        seen.add(tok)
    # convertir defaultdict a dict serializable
    out_index = {t: {p: lns for p, lns in paths.items()} for t, paths in index.items()}
    return {"files": file_meta, "index": out_index, "min_len": min_len}


def save_index(idx: dict, out: str):
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(idx, fh, ensure_ascii=False, indent=2)


def load_index(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def search_index(idx: dict, term: str) -> List[tuple]:
    """Devuelve lista de (path, line_no) para un término (o prefijo)."""
    term = term.casefold()
    results = []
    index = idx["index"]
    # coincidencia exacta
    if term in index:
        for path, lns in index[term].items():
            for ln in lns:
                results.append((path, ln))
    else:
        # prefijo
        for tok, paths in index.items():
            if tok.startswith(term):
                for path, lns in paths.items():
                    for ln in lns:
                        results.append((path, ln))
    return results


def main():
    ap = argparse.ArgumentParser(description="Índice invertido para búsqueda rápida.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="Construir índice")
    b.add_argument("root")
    b.add_argument("--out", default="search_index.json")
    b.add_argument("--ext", default=None)
    b.add_argument("--all-text", action="store_true", help="Incluir cualquier fichero de texto (typ, md, html, ...)")
    b.add_argument("--min-len", type=int, default=2)

    s = sub.add_parser("search", help="Buscar en índice")
    s.add_argument("term")
    s.add_argument("--index", default="search_index.json")
    s.add_argument("--max", type=int, default=50)
    s.add_argument("--show-line", action="store_true", help="Mostrar la línea")
    s.add_argument("--json", action="store_true", help="Salida JSON (para pipelines de IA)")

    args = ap.parse_args()

    if args.cmd == "build":
        exts = [e.strip() for e in args.ext.split(",")] if args.ext else None
        idx = build_index(args.root, extensions=exts, min_len=args.min_len, all_text=args.all_text)
        save_index(idx, args.out)
        print(f"Índice creado: {args.out}")
        print(f"  Ficheros: {len(idx['files'])}")
        print(f"  Tokens únicos: {len(idx['index'])}")
    else:
        idx = load_index(args.index)
        res = search_index(idx, args.term)
        if args.json:
            out_res = []
            shown = 0
            for path, ln in res:
                if args.max is not None and shown >= args.max:
                    break
                entry = {"path": path, "line_no": ln}
                if args.show_line:
                    try:
                        with open(path, "r", encoding="utf-8", errors="replace") as fh:
                            for i, raw in enumerate(fh, 1):
                                if i == ln:
                                    entry["line"] = raw.rstrip()
                                    break
                    except OSError:
                        entry["line"] = None
                out_res.append(entry)
                shown += 1
            print(json.dumps({"ok": True, "count": len(res), "results": out_res},
                             ensure_ascii=False))
            return

        print(f"Resultados para '{args.term}': {len(res)}")
        shown = 0
        for path, ln in res:
            if args.max is not None and shown >= args.max:
                print(f"... ({len(res) - shown} más)")
                break
            if args.show_line:
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as fh:
                        for i, raw in enumerate(fh, 1):
                            if i == ln:
                                print(f"{path}:{ln}: {raw.rstrip()}")
                                break
                except OSError:
                    print(f"{path}:{ln}")
            else:
                print(f"{path}:{ln}")
            shown += 1


if __name__ == "__main__":
    main()
