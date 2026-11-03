"""Páginas a partir de texto de `pdftotext` (solo stdlib).

`pdftotext libro.pdf libro.txt` separa las páginas con un salto de página (`\\f`); NO uses
`-nopgbrk`. Las páginas son una capa sobre los números de línea: el índice y el chunker no
cambian; solo sabemos en qué línea empieza cada página y qué número impreso le corresponde.

- Página del PDF: 1-based, la cuenta de los `\\f`.
- Número impreso = página del PDF − desfase. El desfase se detecta leyendo los números sueltos
  que `pdftotext` deja en el pie/cabecera de cada página, o se fija con `--page-offset`.
- Sin desfase conocido, las etiquetas son «pdf N» para no hacer pasar una página de PDF por
  una página impresa.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter
from itertools import islice
from typing import List, Optional, Sequence, Tuple

Starts = List[Tuple[int, int]]   # [(página_pdf, línea_inicial)] ordenado

_NUMBER_LINE = re.compile(r"^[\W_]{0,4}(\d{1,4})[\W_]{0,4}$")
MIN_SUPPORT = 3
MIN_SUPPORT_FRAC = 0.3


def read_paged_lines(path: str) -> Tuple[List[str], Optional[Starts]]:
    """Líneas del fichero sin `\\f` y dónde empieza cada página (None si no hay saltos)."""
    lines: List[str] = []
    starts: Starts = [(1, 1)]
    page = 1
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for lineno, raw in enumerate(fh, 1):
            n = raw.count("\f")
            if n:
                page += n
                starts.append((page, lineno))
                raw = raw.replace("\f", "")
            lines.append(raw.rstrip("\n").rstrip("\r"))
    # el último `\f` del fichero no abre una página nueva: queda una línea vacía final
    if len(starts) > 1 and starts[-1][1] == len(lines) and lines and lines[-1] == "":
        starts.pop()
        lines.pop()
    if len(starts) == 1:
        return lines, None
    return lines, starts


def detect_offset(lines: Sequence[str], starts: Starts) -> Optional[Tuple[int, int, int]]:
    """(desfase, páginas que lo apoyan, páginas totales) o None si no es fiable.

    Candidatos: líneas que son solo un número (sin punto final, para no confundirlos con notas
    al pie «75.») entre las 3 primeras y las 3 últimas líneas no vacías de cada página.
    """
    votes: Counter = Counter()
    for idx, (page, ls) in enumerate(starts):
        le = starts[idx + 1][1] - 1 if idx + 1 < len(starts) else len(lines)
        body = [(i, lines[i - 1].strip()) for i in range(ls, le + 1) if lines[i - 1].strip()]
        edge = body[:3] + body[-3:]
        seen = set()
        for _, text in edge:
            if text.endswith("."):
                continue
            m = _NUMBER_LINE.match(text)
            if m and int(m.group(1)) >= 1:
                seen.add(page - int(m.group(1)))
        for d in seen:
            votes[d] += 1
    if not votes:
        return None
    ranked = votes.most_common(2)
    best, support = ranked[0]
    if support < max(MIN_SUPPORT, int(MIN_SUPPORT_FRAC * len(starts))):
        return None
    if len(ranked) > 1 and ranked[1][1] >= 0.8 * support:
        return None                      # ambiguo
    return best, support, len(starts)


def is_page_artifact(text: str) -> bool:
    """Línea en blanco o solo un número (pie/cabecera de página): no cuenta como contenido."""
    t = text.strip()
    return not t or (_NUMBER_LINE.match(t) is not None and not t.endswith("."))


class PageMap:
    """Línea → página, y página → etiqueta citable."""

    def __init__(self, starts: Starts, offset: Optional[int] = None):
        self.starts = sorted(starts, key=lambda s: (s[1], s[0]))
        self._lines = [s[1] for s in self.starts]
        self.offset = offset

    @property
    def n_pages(self) -> int:
        return max(p for p, _ in self.starts)

    def page_of(self, line: int) -> int:
        i = bisect_right(self._lines, line) - 1      # empate (páginas en blanco): la última
        return self.starts[max(i, 0)][0]

    def label(self, page: int) -> str:
        if self.offset is None:
            return f"pdf {page}"
        printed = page - self.offset
        return str(printed) if printed >= 1 else f"pdf {page}"

    def range_label(self, line_a: int, line_b: int) -> Tuple[int, int, str]:
        pa, pb = self.page_of(line_a), self.page_of(max(line_a, line_b))
        la, lb = self.label(pa), self.label(pb)
        if pa == pb:
            return pa, pb, la
        if la.startswith("pdf") or lb.startswith("pdf"):     # algún extremo sin nº impreso:
            return pa, pb, f"pdf {pa}–{pb}"                  # todo en páginas del PDF, sin mezclar
        return pa, pb, f"{la}–{lb}"

    def page_starts_in(self, lo: int, hi: int) -> List[Tuple[int, int]]:
        """[(página, línea)] de las páginas que empiezan dentro de [lo, hi] (para el visor)."""
        last_at_line = {}
        for page, line in self.starts:
            last_at_line[line] = page             # empate: gana la última página
        return [(p, ln) for ln, p in sorted(last_at_line.items()) if lo <= ln <= hi]


def cite_label(label: Optional[str]) -> str:
    """'134' -> 'p. 134'; '134–135' -> 'pp. 134–135'; 'pdf 5' -> 'pdf 5'."""
    if not label:
        return ""
    if label.startswith("pdf"):
        return label
    return ("pp. " if "–" in label else "p. ") + label


def read_line_range(path: str, lo: int, hi: int) -> List[str]:
    """Líneas lo..hi (1-based, inclusive) con la misma limpieza que `read_paged_lines`."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return [ln.replace("\f", "").rstrip("\n").rstrip("\r") for ln in islice(fh, max(lo, 1) - 1, hi)]
