"""CLI unificado `prag`.

  prag grep   PATRÓN [RUTA]   búsqueda en streaming, sin índice (solo stdlib)
  prag index  RUTA...         construye/actualiza el índice (incremental)
  prag search CONSULTA        búsqueda sobre el índice: text | semantic | hybrid
  prag status | history | serve | repl

Códigos de salida (como grep): 0 hay resultados, 1 sin resultados, 2 error.
Los imports pesados (SQLAlchemy, Chroma) son perezosos: `grep` solo usa la stdlib.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from .pages import cite_label

EXIT_OK, EXIT_NONE, EXIT_ERR = 0, 1, 2


# ---------- utilidades de salida ----------

def _color_ok(args) -> bool:
    return sys.stdout.isatty() and not getattr(args, "no_color", False) and "NO_COLOR" not in os.environ


def _c(text: str, code: str, on: bool) -> str:
    return f"\033[{code}m{text}\033[0m" if on else text


def _rel(path: str) -> str:
    """Ruta relativa al cwd si queda dentro (salida humana; el JSON conserva la absoluta)."""
    try:
        rel = os.path.relpath(path)
    except ValueError:
        return path
    return path if rel.startswith("..") else rel


def _pages_note(info) -> str:
    """Resumen de páginas para `index`/`status` (info: dict con pages/page_offset/offset_source)."""
    n, off, src = info.get("pages"), info.get("page_offset"), info.get("offset_source")
    if off is None:
        return f"{n} páginas, numeración impresa desconocida (usa --page-offset N; se citará «pdf N»)"
    how = "fijado a mano" if src == "manual" else "detectado"
    sup = info.get("offset_support")
    extra = f", en {sup}/{n} páginas" if sup else ""
    return f"{n} páginas, desfase {off} ({how}{extra})"


def _emit_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, default=str))


def _emit_jsonl(rows: List[Dict[str, Any]]) -> None:
    for r in rows:
        print(json.dumps(r, ensure_ascii=False, default=str))


def _err(msg: str, as_json: bool = False) -> int:
    if as_json:
        _emit_json({"ok": False, "error": msg})
    else:
        print(f"prag: {msg}", file=sys.stderr)
    return EXIT_ERR


def _exts(s: Optional[str]) -> Optional[List[str]]:
    return [e.strip() if e.strip().startswith(".") else "." + e.strip()
            for e in s.split(",") if e.strip()] if s else None


# ---------- grep ----------

def cmd_grep(args) -> int:
    from .textsearch.search_engine import SearchEngine

    ctx = args.context or 0
    before = args.before if args.before is not None else (ctx or None)
    after = args.after if args.after is not None else (ctx or None)
    if args.fuzzy:
        mode = "fuzzy"
    elif before or after:
        mode = "context"
    elif args.regex:
        mode = "regex"
    else:
        mode = "basic"

    if not os.path.exists(args.target):
        return _err(f"no existe: {args.target}", args.json or args.jsonl)
    eng = SearchEngine(root=args.target, extensions=_exts(args.ext), all_text=args.all_text)
    try:
        res = eng.search(args.pattern, mode=mode, ignore_case=args.ignore_case, regex=args.regex,
                         word=args.word, whole_line=args.whole_line, context=ctx,
                         before=before, after=after, max_results=args.max,
                         strip_accents=args.strip_accents)
    except Exception as e:  # regex inválida, etc.
        return _err(str(e), args.json or args.jsonl)

    files = sorted({r["path"] for r in res})
    if args.count:
        if args.json or args.jsonl:
            _emit_json({"ok": True, "count": len(res)})
        else:
            print(len(res))
    elif args.files_with_matches:
        if args.json or args.jsonl:
            _emit_json({"ok": True, "count": len(files), "files": files})
        else:
            print("\n".join(files))
    elif args.json:
        _emit_json({"ok": True, "count": len(res), "results": res})
    elif args.jsonl:
        _emit_jsonl(res)
    else:
        color = _color_ok(args)
        for i, r in enumerate(res):
            if i and (before or after):
                print(_c("--", "90", color))
            path = _c(r["path"], "35", color)
            for ln, text in r.get("context_before") or []:
                print(f"{path}-{ln}-{text}")
            line = r["line"]
            mt = r.get("matched_text")
            if color and mt:
                line = line.replace(mt, _c(mt, "1;31", True), 1)
            print(f"{path}:{_c(str(r['line_no']), '32', color)}:{line}")
            for ln, text in r.get("context_after") or []:
                print(f"{path}-{ln}-{text}")
    return EXIT_OK if res else EXIT_NONE


# ---------- index ----------

def _collect_files(paths: List[str], exts, all_text: bool) -> List[str]:
    from .textsearch.utils import discover_files
    out: List[str] = []
    for p in paths:
        if os.path.isfile(p):
            out.append(os.path.abspath(p))
        elif os.path.isdir(p):
            out.extend(os.path.abspath(f) for f in discover_files(p, extensions=exts, all_text=all_text))
        else:
            raise FileNotFoundError(p)
    return sorted(dict.fromkeys(out))


def cmd_index(args) -> int:
    from .service import SearchService
    as_json = args.json
    try:
        files = _collect_files(args.paths, _exts(args.ext), args.all_text)
        svc = SearchService(create=True, semantic=not args.no_semantic)
    except (FileNotFoundError, OSError) as e:
        return _err(str(e), as_json)
    if not files:
        return _err("no se encontraron ficheros de texto (¿falta --all-text o --ext?)", as_json)

    results, failed = [], 0
    for i, f in enumerate(files, 1):
        try:
            r = svc.index_path(f, max_chars=args.max_chars, overlap=args.overlap, force=args.force,
                               page_offset=args.page_offset)
        except Exception as e:
            failed += 1
            r = {"path": f, "error": str(e)}
        results.append(r)
        if not as_json:
            tag = "error: " + r["error"] if "error" in r else ("sin cambios" if r["skipped"] else f"{r['chunks']} chunks")
            if "error" not in r and r.get("pages"):
                tag += " · " + _pages_note(r)
            print(f"[{i}/{len(files)}] {f} — {tag}", file=sys.stderr)

    summary = {"ok": failed == 0, "home": str(svc.home), "files": len(files),
               "indexed": sum(1 for r in results if not r.get("skipped") and "error" not in r),
               "skipped": sum(1 for r in results if r.get("skipped")), "failed": failed,
               "semantic": svc.vector is not None}
    if as_json:
        _emit_json({**summary, "results": results})
    else:
        sem = "con semántica" if summary["semantic"] else "solo texto (instala chromadb para semántica)"
        print(f"{summary['indexed']} indexados, {summary['skipped']} sin cambios, "
              f"{failed} con error · {sem} · {svc.home}")
    return EXIT_ERR if failed else EXIT_OK


# ---------- search ----------

def cmd_search(args) -> int:
    from pydantic import ValidationError
    from .models import SearchRequest
    from .service import SearchService, SemanticUnavailable
    as_json = args.json or args.jsonl
    try:
        svc = SearchService(semantic=not args.no_semantic)
        req = SearchRequest(query=args.query, mode=args.mode, top_k=args.top_k, doc=args.doc)
        resp = svc.search(req, record_history=not args.no_history)
    except (FileNotFoundError, SemanticUnavailable) as e:
        return _err(str(e), as_json)
    except ValidationError as e:
        return _err(e.errors()[0]["msg"], as_json)

    results = [r.model_dump() for r in resp.results]
    if args.json:
        _emit_json({"ok": True, "query": resp.query, "mode": resp.mode, "count": resp.count,
                    "elapsed_ms": resp.elapsed_ms, "warnings": resp.warnings, "results": results})
    elif args.jsonl:
        _emit_jsonl(results)
    else:
        color = _color_ok(args)
        for w in resp.warnings:
            print(_c(f"aviso: {w}", "33", color), file=sys.stderr)
        for r in resp.results:
            head = f"{_rel(r.source)}:{r.line_start}-{r.line_end}"
            cite = cite_label(r.page_label)
            print(f"{_c(head, '35', color)}  {_c(cite, '32', color) + '  ' if cite else ''}"
                  f"{_c(f'[{r.mode} {r.score}]', '90', color)}")
            lines = [ln for ln in r.text.splitlines() if ln.strip()][:args.lines]
            for ln in lines:
                print("  " + (ln if len(ln) <= 160 else ln[:157] + "…"))
        print(_c(f"{resp.count} resultados · {resp.mode} · {resp.elapsed_ms} ms", "90", color),
              file=sys.stderr)
    return EXIT_OK if resp.count else EXIT_NONE


# ---------- page ----------

def cmd_page(args) -> int:
    from .service import SearchService
    try:
        res = SearchService(semantic=False).locate(args.quote, doc=args.doc, k=args.top_k)
    except FileNotFoundError as e:
        return _err(str(e), args.json)
    good = [d for d in res if d["coverage"] >= args.min_coverage]
    if args.json:
        _emit_json({"ok": True, "found": bool(good), "results": res})
    else:
        color = _color_ok(args)
        if not good:
            print("prag: no encontré esa cita con suficiente confianza"
                  + (f" (mejor coincidencia: {res[0]['coverage']:.0%})" if res else ""), file=sys.stderr)
        for d in good:
            cite = cite_label(d["page_label"]) or "(sin páginas: el texto no trae saltos de página)"
            where = f"{_rel(d['path'])}:{d['line_start']}-{d['line_end']}"
            print(f"{_c(cite, '1;32', color)}  {_c(where, '35', color)}  {_c(format(d['coverage'], '.0%'), '90', color)}")
            print("    " + d["excerpt"][:200])
    return EXIT_OK if good else EXIT_NONE


# ---------- status / history ----------

def cmd_status(args) -> int:
    from .paths import resolve_home
    from .service import SearchService
    try:
        home = resolve_home()
        svc = SearchService(home=home)
    except FileNotFoundError as e:
        return _err(str(e), args.json)
    docs = svc.db.list_documents()
    vec = svc.vector
    info = {"ok": True, "home": str(home), "documents": len(docs), "chunks": svc.db.count_chunks(),
            "semantic_available": svc.semantic_available,
            "vector_chunks": vec.count() if vec else None,
            "size_bytes": sum(f.stat().st_size for f in home.rglob("*") if f.is_file())}
    if args.json:
        _emit_json({**info, "docs": docs})
        return EXIT_OK
    from .textsearch.utils import human_size
    print(f"Índice:     {info['home']}  ({human_size(info['size_bytes'])})")
    print(f"Documentos: {info['documents']}   Chunks (texto): {info['chunks']}")
    print("Semántica:  " + (f"sí, {info['vector_chunks']} vectores" if vec else
                            "no (chromadb no instalado)"))
    for d in docs:
        print(f"  {d['chunks']:>6}  {d['path']}")
        if d.get("pages"):
            print(f"          {_pages_note({'pages': d['pages'], 'page_offset': d['page_offset'], 'offset_source': d['page_offset_source']})}")
    return EXIT_OK


def cmd_history(args) -> int:
    from .service import SearchService
    try:
        rows = SearchService().db.recent_history(args.n)
    except FileNotFoundError as e:
        return _err(str(e), args.json)
    data = [{"query": h.query, "mode": h.mode, "results": h.result_count,
             "timestamp": h.timestamp} for h in rows]
    if args.json:
        _emit_json({"ok": True, "history": data})
    else:
        for h in data:
            print(f"{h['timestamp']:%Y-%m-%d %H:%M}  {h['mode']:<8} {h['results']:>3}  {h['query']}")
    return EXIT_OK


# ---------- serve / repl ----------

def cmd_serve(args) -> int:
    try:
        import uvicorn
        from .paths import resolve_home
        os.environ["PRAG_HOME"] = str(resolve_home(create=True))
        if args.target:
            os.environ["SEARCH_TARGET"] = os.path.abspath(args.target)
        from .web.app import create_app_from_env
        app = create_app_from_env()
    except ImportError as e:
        return _err(f"falta una dependencia de la web ({e}). uv sync --extra web")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return EXIT_OK


def cmd_repl(args) -> int:
    from .textsearch.search_interactive import main as repl_main
    repl_main()
    return EXIT_OK


# ---------- parser ----------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="prag", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="COMANDO")

    def out_flags(p, jsonl=True):
        p.add_argument("--json", action="store_true", help="salida JSON (un objeto)")
        if jsonl:
            p.add_argument("--jsonl", action="store_true", help="un resultado JSON por línea")
        p.add_argument("--no-color", action="store_true")

    g = sub.add_parser("grep", help="búsqueda en streaming sin índice")
    g.add_argument("pattern")
    g.add_argument("target", nargs="?", default=".", help="fichero o directorio (por defecto .)")
    g.add_argument("-i", "--ignore-case", action="store_true")
    g.add_argument("-w", "--word", action="store_true", help="palabra completa")
    g.add_argument("-x", "--whole-line", action="store_true")
    g.add_argument("-E", "--regex", action="store_true", help="el patrón es una regex")
    g.add_argument("-z", "--fuzzy", action="store_true", help="búsqueda difusa (tolera errores)")
    g.add_argument("-C", "--context", type=int, default=0, metavar="N")
    g.add_argument("-A", "--after", type=int, default=None, metavar="N")
    g.add_argument("-B", "--before", type=int, default=None, metavar="N")
    g.add_argument("-m", "--max", type=int, default=None, help="máximo de resultados")
    g.add_argument("-c", "--count", action="store_true")
    g.add_argument("-l", "--files-with-matches", action="store_true")
    g.add_argument("--ext", help="extensiones separadas por coma (.md,.typ)")
    g.add_argument("--all-text", action="store_true", help="cualquier fichero de texto")
    g.add_argument("--strip-accents", action="store_true")
    out_flags(g)
    g.set_defaults(func=cmd_grep)

    ix = sub.add_parser("index", help="indexa ficheros o directorios (incremental)")
    ix.add_argument("paths", nargs="+")
    ix.add_argument("--max-chars", type=int, default=1000,
                    help="tamaño máximo de chunk en caracteres (1000; el embedding trunca ~1000)")
    ix.add_argument("--overlap", type=int, default=2, help="líneas compartidas entre chunks (2)")
    ix.add_argument("--force", action="store_true", help="reindexar aunque no hayan cambiado")
    ix.add_argument("--page-offset", type=int, default=None, metavar="N",
                    help="nº impreso = página del PDF − N (si no, se detecta del texto de pdftotext)")
    ix.add_argument("--ext")
    ix.add_argument("--all-text", action="store_true")
    ix.add_argument("--no-semantic", action="store_true", help="no calcular embeddings")
    out_flags(ix, jsonl=False)
    ix.set_defaults(func=cmd_index)

    s = sub.add_parser("search", help="búsqueda sobre el índice")
    s.add_argument("query")
    s.add_argument("--mode", choices=["text", "semantic", "hybrid"], default="hybrid")
    s.add_argument("-k", "--top-k", type=int, default=10)
    s.add_argument("--doc", help="solo documentos cuya ruta contenga esta cadena")
    s.add_argument("--lines", type=int, default=4, help="líneas de vista previa por resultado")
    s.add_argument("--no-semantic", action="store_true")
    s.add_argument("--no-history", action="store_true")
    out_flags(s)
    s.set_defaults(func=cmd_search)

    pg = sub.add_parser("page", help="en qué página está una cita")
    pg.add_argument("quote", help="frase copiada del libro (tolera reflujo, guiones y errores de OCR)")
    pg.add_argument("--doc", help="solo documentos cuya ruta contenga esta cadena")
    pg.add_argument("-k", "--top-k", type=int, default=3)
    pg.add_argument("--min-coverage", type=float, default=0.5,
                    help="fracción mínima de palabras de la cita encontradas (0.5)")
    out_flags(pg, jsonl=False)
    pg.set_defaults(func=cmd_page)

    st = sub.add_parser("status", help="estado del índice")
    out_flags(st, jsonl=False)
    st.set_defaults(func=cmd_status)

    h = sub.add_parser("history", help="consultas recientes")
    h.add_argument("-n", type=int, default=20)
    out_flags(h, jsonl=False)
    h.set_defaults(func=cmd_history)

    sv = sub.add_parser("serve", help="levanta la UI web")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=5001)
    sv.add_argument("--target", help="fichero a indexar al arrancar (si el índice está vacío)")
    sv.set_defaults(func=cmd_serve)

    r = sub.add_parser("repl", help="modo interactivo")
    r.set_defaults(func=cmd_repl)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        return EXIT_OK
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
