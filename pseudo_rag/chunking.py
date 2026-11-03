"""Chunking por tamaño en caracteres, respetando párrafos y encabezados (solo stdlib).

Por qué caracteres y no líneas: el embedding por defecto de Chroma trunca a 256 tokens
(~1000 caracteres); un chunk mayor se indexa solo por su principio.

Reglas:
- Una línea más larga que `max_chars` se parte por frases (y, si hace falta, por palabras);
  todos sus trozos conservan el número de esa línea.
- Se corta *antes* de un encabezado (`= Título` de Typst, `# Título` de Markdown) y *después*
  de una línea en blanco, siempre que el chunk ya tenga un tamaño razonable.
- Cada chunk repite al inicio el final (contiguo) del anterior: hasta `overlap` unidades y
  `max_chars/4` caracteres.
- Los rangos son líneas 1-based inclusivas, sin líneas en blanco en los extremos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence, Tuple

CHUNKER_VERSION = 2
DEFAULT_MAX_CHARS = 1000
DEFAULT_OVERLAP = 2

_HEADING = re.compile(r"^(=+|#{1,6})\s+\S")


@dataclass(frozen=True)
class Chunk:
    start: int  # línea inicial (1-based)
    end: int    # línea final (1-based, inclusive)
    text: str


def params_signature(max_chars: int, overlap: int) -> str:
    """Identifica la configuración de chunking (incluye versión del algoritmo)."""
    return f"v{CHUNKER_VERSION}:{max_chars}:{overlap}"


_SENTENCE_END = re.compile(r"(?<=[.;:!?»”)])\s+")


def _split_long(text: str, max_chars: int) -> List[str]:
    """Parte un texto largo en trozos <= max_chars (por frases; por palabras si no hay otra)."""
    if len(text) <= max_chars:
        return [text]
    out: List[str] = []
    cur = ""
    for sent in _SENTENCE_END.split(text):
        while len(sent) > max_chars:
            cut = sent.rfind(" ", 0, max_chars)
            if cut <= 0:
                cut = max_chars
            if cur:
                out.append(cur)
                cur = ""
            out.append(sent[:cut])
            sent = sent[cut:].lstrip()
        if not sent:
            continue
        if cur and len(cur) + 1 + len(sent) > max_chars:
            out.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}" if cur else sent
    if cur:
        out.append(cur)
    return out


def chunk_lines(lines: Sequence[str], max_chars: int = DEFAULT_MAX_CHARS,
                overlap: int = DEFAULT_OVERLAP) -> List[Chunk]:
    if max_chars < 50:
        raise ValueError("max_chars debe ser >= 50")
    if overlap < 0:
        raise ValueError("overlap debe ser >= 0")

    # unidades = (nº de línea 1-based, texto); una línea larga produce varias unidades
    units: List[Tuple[int, str]] = []
    for i, line in enumerate(lines):
        for piece in _split_long(line, max_chars):
            units.append((i + 1, piece))

    min_soft = int(max_chars * 0.4)    # tamaño mínimo para cortar antes de un encabezado
    para_soft = int(max_chars * 0.6)   # tamaño mínimo para cortar tras un párrafo
    overlap_budget = max_chars // 4    # el solapamiento no puede ocupar más de esto

    chunks: List[Chunk] = []
    cur: List[int] = []   # índices en `units` del chunk en curso
    size = 0
    n_new = 0             # unidades añadidas desde el último corte (sin contar solapamiento)

    def flush() -> None:
        nonlocal cur, size, n_new
        a, b = 0, len(cur)
        while a < b and not units[cur[a]][1].strip():
            a += 1
        while b > a and not units[cur[b - 1]][1].strip():
            b -= 1
        kept = cur[a:b]
        if kept:
            chunks.append(Chunk(units[kept[0]][0], units[kept[-1]][0],
                                "\n".join(units[i][1] for i in kept)))
        # solapamiento: sufijo CONTIGUO del chunk, más corto que el chunk (garantiza avance)
        tail: List[int] = []
        used = 0
        body = cur[a:]                      # sin blancos iniciales, con los finales (contiguidad)
        limit = min(overlap, len(body) - 1)
        for i in reversed(body):
            cost = len(units[i][1]) + 1
            if len(tail) >= limit or used + cost > overlap_budget:
                break
            tail.insert(0, i)
            used += cost
        while tail and not units[tail[0]][1].strip():
            used -= len(units[tail[0]][1]) + 1
            tail.pop(0)
        cur, size, n_new = tail, used, 0

    for idx, (_, text) in enumerate(units):
        add = len(text) + 1
        if cur and n_new and size + add > max_chars:
            flush()
        elif cur and n_new and _HEADING.match(text) and size >= min_soft:
            flush()
        if cur and not n_new and size + add > max_chars:
            cur, size = [], 0          # el solapamiento no cabe junto a esta pieza: se descarta
        cur.append(idx)
        size += add
        n_new += 1
        if not text.strip() and size >= para_soft:
            flush()
    if cur and n_new:
        flush()
    return chunks
