"""Utilidades compartidas para los scripts de búsqueda."""

from __future__ import annotations

import os
import re
import sys
import time
import json
import hashlib
from pathlib import Path
from typing import Iterable, Iterator, Optional, List, Dict, Tuple, Any


# ---------- Lectura eficiente de ficheros grandes ----------

def iter_lines(path: str, encoding: str = "utf-8", errors: str = "replace",
               chunk_size: int = 64 * 1024) -> Iterator[str]:
    """Itera líneas de un fichero de texto de forma eficiente (streaming).

    Funciona con ficheros de cualquier tamaño porque no los carga enteros en memoria.
    """
    with open(path, "r", encoding=encoding, errors=errors, buffering=chunk_size) as fh:
        for line in fh:
            yield line.rstrip("\n").rstrip("\r")


def count_lines(path: str, encoding: str = "utf-8", errors: str = "replace") -> int:
    n = 0
    with open(path, "r", encoding=encoding, errors=errors) as fh:
        for _ in fh:
            n += 1
    return n


def file_size(path: str) -> int:
    return os.path.getsize(path)


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# ---------- Descubrimiento de ficheros ----------

DEFAULT_EXTENSIONS = {
    # Texto plano
    ".txt", ".log", ".text",
    # Markdown / documentación
    ".md", ".markdown", ".mdown", ".mkd", ".rst", ".adoc", ".asciidoc", ".org",
    # Typst / LaTeX
    ".typ", ".tex", ".latex", ".bib",
    # Web
    ".html", ".htm", ".xhtml", ".xml", ".svg",
    # Datos estructurados
    ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".csv", ".tsv",
    # Código fuente (texto)
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".c", ".cpp", ".h",
    ".hpp", ".java", ".kt", ".swift", ".rb", ".php", ".sh", ".bash", ".zsh",
    ".sql", ".css", ".scss", ".less",
}


def is_text_file(path: str, sample_size: int = 8192) -> bool:
    """Detecta si un fichero es de texto leyendo una muestra inicial."""
    try:
        with open(path, "rb") as fh:
            sample = fh.read(sample_size)
    except OSError:
        return False
    if b"\x00" in sample:
        return False
    if not sample:
        return True
    # intentar decodificar como UTF-8 (con tolerancia)
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        try:
            sample.decode("latin-1")
            # heurística: muchos bytes de control => binario
            text_chars = bytes(range(32, 127)) + b"\n\r\t\f\b"
            nontext = sum(1 for b in sample if b not in text_chars)
            return nontext / len(sample) < 0.30
        except Exception:
            return False


def discover_files(root: str, extensions: Optional[Iterable[str]] = None,
                  recursive: bool = True, max_size: Optional[int] = None,
                  all_text: bool = False) -> List[str]:
    """Descubre ficheros de texto bajo un directorio.

    Si all_text=True, incluye cualquier fichero detectado como texto aunque su
    extensión no esté en la lista (útil para .typ, .md, .html y otros).
    """
    exts = None
    if extensions is not None:
        exts = {e.lower() if e.startswith(".") else "." + e.lower() for e in extensions}
    elif not all_text:
        exts = DEFAULT_EXTENSIONS

    result: List[str] = []
    if os.path.isfile(root):
        return [root]
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in {"node_modules", "__pycache__", "venv", ".venv", ".git"}]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            ext = os.path.splitext(fn)[1].lower()
            ok = False
            if exts is None or ext in exts:
                ok = True
            elif all_text and is_text_file(p):
                ok = True
            if ok:
                if max_size is None or os.path.getsize(p) <= max_size:
                    result.append(p)
        if not recursive:
            break
    return sorted(result)


# ---------- Resultado estándar ----------

class Match:
    __slots__ = ("path", "line_no", "line", "column", "matched_text", "context_before", "context_after")

    def __init__(self, path, line_no, line, column=0, matched_text="",
                 context_before=None, context_after=None):
        self.path = path
        self.line_no = line_no
        self.line = line
        self.column = column
        self.matched_text = matched_text
        self.context_before = context_before or []
        self.context_after = context_after or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "line_no": self.line_no,
            "line": self.line,
            "column": self.column,
            "matched_text": self.matched_text,
            "context_before": self.context_before,
            "context_after": self.context_after,
        }


# ---------- Formateo ----------

def format_match(m: Match, show_path: bool = True, color: bool = False) -> str:
    prefix = f"{m.path}:" if show_path else ""
    loc = f"{prefix}{m.line_no}"
    if m.column:
        loc += f":{m.column}"
    line = m.line
    if color and m.matched_text:
        line = line.replace(m.matched_text, f"\033[31;1m{m.matched_text}\033[0m", 1)
    out = f"{loc}: {line}"
    if m.context_before:
        for cb in m.context_before:
            out = f"{prefix}{cb[0]}- {cb[1]}\n" + out
    if m.context_after:
        for ca in m.context_after:
            out += f"\n{prefix}{ca[0]}+ {ca[1]}"
    return out


def print_matches(matches: List[Match], color: bool = True, max_results: Optional[int] = None):
    n = 0
    for m in matches:
        if max_results is not None and n >= max_results:
            print(f"... ({len(matches) - n} resultados más omitidos)")
            break
        print(format_match(m, color=color))
        n += 1
    print(f"\nTotal: {len(matches)} coincidencia(s).", file=sys.stderr)


# ---------- Hashing / caché ----------

def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_path_for(path: str, cache_dir: str = ".search_cache") -> str:
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, file_hash(path) + ".json")


# ---------- Normalización ----------

def normalize_text(s: str, casefold: bool = True, strip_accents: bool = False) -> str:
    if casefold:
        s = s.casefold()
    if strip_accents:
        import unicodedata
        s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s


def snippet(text: str, needle: str, width: int = 80) -> str:
    idx = text.find(needle)
    if idx < 0:
        return text[:width]
    start = max(0, idx - width // 2)
    end = min(len(text), idx + len(needle) + width // 2)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end] + suffix


if __name__ == "__main__":
    print("utils ok")
