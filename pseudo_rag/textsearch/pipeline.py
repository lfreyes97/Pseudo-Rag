#!/usr/bin/env python3
"""Punto de entrada para pipelines de IA.

Lee una configuración JSON (por stdin o --config ARCHIVO) y ejecuta la búsqueda,
devolviendo resultados JSON por stdout. Diseñado para ser invocado por agentes/IA.

Esquema de entrada:
{
  "root": "/ruta/o/fichero",
  "pattern": "texto a buscar",
  "mode": "basic|regex|context|fuzzy",
  "all_text": true,
  "ignore_case": true,
  "regex": false,
  "word": false,
  "whole_line": false,
  "context": 3,
  "before": 2,
  "after": 2,
  "fuzzy_threshold": 0.6,
  "fuzzy_level": "word",
  "max_edits": 2,
  "max_results": 100,
  "extensions": [".md", ".typ"],
  "strip_accents": false,
  "count_only": false,
  "files_with_matches": false
}

Salida:
{
  "ok": true,
  "count": N,
  "results": [ {path, line_no, line, column, matched_text, context_before, context_after}, ... ],
  "files_with_matches": [...]
}
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .search_engine import SearchEngine


def main():
    ap = argparse.ArgumentParser(description="Pipeline de búsqueda para IA (JSON in/out).")
    ap.add_argument("--config", "-c", help="Archivo JSON de configuración (si no, lee stdin)")
    ap.add_argument("--pretty", action="store_true", help="JSON con indentación")
    args = ap.parse_args()

    if args.config:
        with open(args.config, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    else:
        raw = sys.stdin.read()
        if not raw.strip():
            print(json.dumps({"ok": False, "error": "Sin configuración (stdin vacío y sin --config)"}))
            sys.exit(2)
        cfg = json.loads(raw)

    root = cfg.get("root", ".")
    pattern = cfg.get("pattern", "")
    if not pattern:
        print(json.dumps({"ok": False, "error": "pattern vacío"}))
        sys.exit(2)

    engine = SearchEngine(
        root=root,
        extensions=cfg.get("extensions"),
        all_text=cfg.get("all_text", False),
    )

    kwargs = {
        "mode": cfg.get("mode", "basic"),
        "ignore_case": cfg.get("ignore_case", True),
        "regex": cfg.get("regex", False),
        "word": cfg.get("word", False),
        "whole_line": cfg.get("whole_line", False),
        "context": cfg.get("context", 0),
        "before": cfg.get("before"),
        "after": cfg.get("after"),
        "fuzzy_threshold": cfg.get("fuzzy_threshold", 0.6),
        "fuzzy_level": cfg.get("fuzzy_level", "word"),
        "max_edits": cfg.get("max_edits"),
        "max_results": cfg.get("max_results"),
        "strip_accents": cfg.get("strip_accents", False),
    }

    results = engine.search(pattern, **kwargs)

    out = {"ok": True, "count": len(results), "results": results}
    if cfg.get("files_with_matches"):
        out["files_with_matches"] = engine.files_with_matches(pattern, **kwargs)
    if cfg.get("count_only"):
        out["count"] = len(results)
        out["results"] = []

    print(json.dumps(out, ensure_ascii=False, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
