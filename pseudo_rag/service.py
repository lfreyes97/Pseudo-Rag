"""Servicio de búsqueda: índice FTS5 (stdlib) + semántica opcional (ChromaDB)."""

from __future__ import annotations

import difflib
import hashlib
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .chunking import DEFAULT_MAX_CHARS, DEFAULT_OVERLAP, chunk_lines, params_signature
from .db import Database
from .pages import PageMap, cite_label, detect_offset, is_page_artifact, read_line_range, read_paged_lines
from .models import SearchRequest, SearchResponse, SearchResult
from .stopwords import STOPWORDS
from .paths import chroma_dir, db_url, resolve_home
from .vector_store import chroma_available


def _fold(text: str) -> str:
    """Minúsculas y sin diacríticos (coherente con el tokenizer de FTS)."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(ch))


class SemanticUnavailable(RuntimeError):
    pass


class SearchService:
    def __init__(self, home: Optional[Path] = None, create: bool = False, semantic: bool = True):
        self.home = Path(home) if home else resolve_home(create=create)
        if create:
            self.home.mkdir(parents=True, exist_ok=True)
        self.db = Database(db_url=db_url(self.home))
        self._vector = None
        self._page_maps: Dict[str, Optional[PageMap]] = {}
        self._want_semantic = semantic

    # ---------- Vector store (perezoso y opcional) ----------

    @property
    def semantic_available(self) -> bool:
        return self._want_semantic and chroma_available()

    @property
    def vector(self):
        """VectorStore o None si Chroma no está instalado / está desactivado."""
        if self._vector is None and self.semantic_available:
            from .vector_store import VectorStore
            self._vector = VectorStore(persist_dir=chroma_dir(self.home))
        return self._vector

    # ---------- Indexado ----------

    @staticmethod
    def _hash(path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()

    EMBED_BATCH = 64

    def index_path(self, path: str, max_chars: int = DEFAULT_MAX_CHARS,
                   overlap: int = DEFAULT_OVERLAP, force: bool = False,
                   progress: Optional[Callable[[str, int, int], None]] = None,
                   page_offset: Optional[int] = None) -> Dict[str, Any]:
        """Indexa un fichero. Si no cambió (contenido y chunking), lo salta salvo force.

        `progress(fase, hecho, total)` se llama durante el indexado (fases: "preparando",
        "embeddings", "listo"); sirve para mostrar una barra de progreso.

        Si el texto trae saltos de página (`\\f` de pdftotext) se guardan las páginas. `page_offset`
        fija el desfase (nº impreso = página del PDF − desfase); sin él se detecta, o se conserva
        el que se fijó a mano en una indexación anterior.
        """
        report = progress or (lambda *_: None)
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        report("preparando", 0, 0)
        lines, starts = read_paged_lines(path)
        digest = self._hash(path)
        sig = params_signature(max_chars, overlap)
        doc = self.db.upsert_document(path=path, title=os.path.basename(path))
        vec = self.vector
        pages_info = self._store_pages(doc, lines, starts, page_offset)   # barato: siempre
        if not force and doc.content_hash == digest and doc.chunk_params == sig:
            have_vectors = vec is None or vec.has_path(path)
            n = len(self.db.get_chunks(doc.id))
            if n and have_vectors:
                report("listo", n, n)
                return {"path": path, "chunks": n, "skipped": True, **pages_info}

        chunks = chunk_lines(lines, max_chars=max_chars, overlap=overlap)

        self.db.clear_chunks(doc.id)
        if vec is not None:
            vec.delete_path(path)

        rows = self.db.add_chunks(doc.id, [
            {"line_start": c.start, "line_end": c.end, "text": c.text} for c in chunks])
        if vec is not None and rows:
            total = len(rows)
            report("embeddings", 0, total)
            for i in range(0, total, self.EMBED_BATCH):
                batch = rows[i:i + self.EMBED_BATCH]
                vec.add(ids=[r.embedding_id for r in batch],
                        documents=[r.text for r in batch],
                        metadatas=[{"path": path, "line_start": r.line_start,
                                    "line_end": r.line_end} for r in batch])
                report("embeddings", min(i + self.EMBED_BATCH, total), total)
        self.db.set_document_meta(doc.id, digest, sig)
        report("listo", len(rows), len(rows))
        return {"path": path, "chunks": len(rows), "skipped": False, **pages_info}

    def _store_pages(self, doc, lines, starts, page_offset) -> Dict[str, Any]:
        self._page_maps.pop(doc.path, None)
        if starts is None:
            self.db.set_pages(doc.id, None, None, None)
            return {"pages": 0, "page_offset": None, "offset_source": None, "offset_support": None}
        support = None
        if page_offset is not None:
            offset, source = page_offset, "manual"
        elif doc.page_offset_source == "manual":
            offset, source = doc.page_offset, "manual"     # no pisar lo que fijó el usuario
        else:
            det = detect_offset(lines, starts)
            offset, source, support = (det[0], "auto", det[1]) if det else (None, None, None)
        self.db.set_pages(doc.id, starts, offset, source)
        return {"pages": len(starts), "page_offset": offset, "offset_source": source,
                "offset_support": support}

    # ---------- Páginas ----------

    def page_map(self, path: str) -> Optional[PageMap]:
        if path not in self._page_maps:
            data = self.db.get_pages(path)
            self._page_maps[path] = PageMap(data[0], data[1]) if data else None
        return self._page_maps[path]

    @staticmethod
    def _content_lines(r: SearchResult, terms: List[str]) -> tuple:
        """(línea_inicial, línea_final) de lo que importa del resultado, para citar su página.

        Los bordes del chunk pueden ser el pie de la página anterior o una línea en blanco; se
        usa la primera y la última línea con términos de la consulta o, si no hay (semántica),
        el chunk sin líneas en blanco ni números sueltos en los extremos."""
        rows = r.text.split("\n")
        if len(rows) != r.line_end - r.line_start + 1:       # texto no alineado con las líneas
            return r.line_start, r.line_end
        folded = [_fold(row) for row in rows]
        hits = [i for i, row in enumerate(folded) if any(t in row for t in terms)] if terms else []
        if hits:
            return r.line_start + hits[0], r.line_start + hits[-1]
        keep = [i for i, row in enumerate(rows) if not is_page_artifact(row)]
        if not keep:
            return r.line_start, r.line_end
        return r.line_start + keep[0], r.line_start + keep[-1]

    def _annotate_pages(self, results: List[SearchResult], query: str = "") -> List[SearchResult]:
        out = []
        terms = self._quote_terms(query) if query else []
        for r in results:
            pm = self.page_map(r.source)
            if pm is None:
                out.append(r)
                continue
            a, b = self._content_lines(r, terms)
            pa, pb, label = pm.range_label(a, b)
            out.append(r.model_copy(update={"page_start": pa, "page_end": pb, "page_label": label}))
        return out

    def index_file(self, path: str, max_chars: int = DEFAULT_MAX_CHARS) -> int:
        """Compatibilidad con la web: siempre reindexa."""
        return self.index_path(path, max_chars=max_chars, force=True)["chunks"]

    # ---------- Búsqueda ----------

    @staticmethod
    def _rrf(results: List[SearchResult], k: int = 60) -> List[SearchResult]:
        """Reciprocal Rank Fusion: combina por posición, no por score (escalas distintas).

        Un acierto textual dentro del rango de un chunk semántico se fusiona con él.
        """
        sem = [r for r in results if r.mode == "semantic"]
        txt = [r for r in results if r.mode == "text"]
        fused: Dict[str, SearchResult] = {}
        for rank, r in enumerate(sem, 1):
            fused[r.id] = r.model_copy(update={"score": 1.0 / (k + rank)})
        for rank, r in enumerate(txt, 1):
            contrib = 1.0 / (k + rank)
            host = fused.get("sem:" + r.id[len("text:"):])  # mismo chunk exacto
            if host is None:
                host = next((f for f in fused.values()
                             if f.mode in ("semantic", "hybrid") and f.source == r.source
                             and f.line_start <= r.line_start <= f.line_end), None)
            if host is not None:
                fused[host.id] = host.model_copy(
                    update={"score": host.score + contrib, "mode": "hybrid"})
            elif r.id not in fused:
                fused[r.id] = r.model_copy(update={"score": contrib})
        out = sorted(fused.values(), key=lambda x: x.score, reverse=True)
        return [x.model_copy(update={"score": round(x.score, 5)}) for x in out]

    @staticmethod
    def _collapse_overlaps(results: List[SearchResult], query: str = "",
                           min_frac: float = 0.5) -> List[SearchResult]:
        """Con solapamiento entre chunks, evita mostrar dos veces el mismo pasaje.

        Un resultado se descarta si comparte líneas con uno mejor clasificado del mismo
        fichero y además: (a) comparte >= min_frac de sus líneas, o (b) su parte propia (las
        líneas fuera del solape) no contiene ningún término de la consulta, es decir, solo
        coincidía por las líneas compartidas. Así un acierto distinto en un chunk contiguo se
        conserva.
        """
        terms = [t for t in (_fold(w) for w in re.findall(r"\w+", query)) if len(t) > 2]
        kept: List[SearchResult] = []
        for r in results:
            n_r = r.line_end - r.line_start + 1
            dup = False
            for k in kept:
                if k.source != r.source:
                    continue
                inter = min(k.line_end, r.line_end) - max(k.line_start, r.line_start) + 1
                if inter <= 0:
                    continue
                n_k = k.line_end - k.line_start + 1
                if inter / min(n_k, n_r) >= min_frac:
                    dup = True
                    break
                rows = r.text.split("\n")
                if terms and len(rows) == n_r:  # el texto está alineado con el rango de líneas
                    own = " ".join(
                        row for off, row in enumerate(rows)
                        if not (k.line_start <= r.line_start + off <= k.line_end))
                    if not any(t in _fold(own) for t in terms):
                        dup = True
                        break
            if not dup:
                kept.append(r)
        return kept

    def search(self, req: SearchRequest, record_history: bool = True) -> SearchResponse:
        t0 = time.time()
        warnings: List[str] = []
        mode = req.mode
        if mode in ("semantic", "hybrid") and self.vector is None:
            if mode == "semantic":
                raise SemanticUnavailable(
                    "Búsqueda semántica no disponible: instala chromadb (uv sync --extra semantic) y no uses --no-semantic")
            warnings.append("chromadb no instalado: se usó solo búsqueda textual")
            mode = "text"

        results: List[SearchResult] = []
        if mode in ("text", "hybrid"):
            for r in self.db.search_fts(req.query, limit=req.top_k * 2, doc=req.doc):
                results.append(SearchResult(
                    id=f"text:c{r['chunk_id']}",
                    text=r["text"], score=round(-r["rank"], 4), source=r["path"],
                    line_start=r["line_start"], line_end=r["line_end"], mode="text"))

        if mode in ("semantic", "hybrid"):
            fetch = req.top_k * (4 if req.doc else 2)
            for r in self.vector.query(req.query, top_k=fetch):
                meta = r["metadata"] or {}
                if req.doc and req.doc not in meta.get("path", ""):
                    continue
                results.append(SearchResult(
                    id=f"sem:{r['id']}", text=r["text"], score=round(r["score"], 4),
                    source=meta.get("path", ""), line_start=meta.get("line_start", 0),
                    line_end=meta.get("line_end", 0), mode="semantic"))

        if mode == "hybrid":
            ranked = self._rrf(results)
        else:
            seen, ranked = set(), []
            for r in results:
                if r.id not in seen:
                    seen.add(r.id)
                    ranked.append(r)
        final = self._annotate_pages(self._collapse_overlaps(ranked, req.query)[:req.top_k], req.query)

        elapsed = (time.time() - t0) * 1000
        if record_history:
            self.db.add_history(req.query, mode, len(final))
        return SearchResponse(query=req.query, mode=mode, count=len(final), results=final,
                              elapsed_ms=round(elapsed, 2), warnings=warnings)

    # ---------- Localizar una cita ----------

    @staticmethod
    def _quote_terms(quote: str) -> List[str]:
        words = [_fold(w) for w in re.findall(r"\w+", quote)]
        terms = [w for w in words if len(w) >= 3 and w not in STOPWORDS]
        return list(dict.fromkeys(terms or [w for w in words if len(w) >= 2]))

    @staticmethod
    def _approx(term: str, tokens) -> bool:
        """Coincidencia aproximada (errores de OCR). No se aplica a palabras con dígitos ni
        cortas: 'zafiro7' y 'zafiro3' no son la misma palabra."""
        if len(term) < 6 or any(ch.isdigit() for ch in term):
            return False
        return bool(difflib.get_close_matches(term, [t for t in tokens if not any(c.isdigit() for c in t)],
                                              1, 0.85))

    @staticmethod
    def _line_tokens(rows: List[str]) -> List[List[str]]:
        """Tokens por línea. Une las palabras partidas con guion al final de línea (OCR/
        pdftotext) sin perder las dos formas: 'presupposi-' + 'tional' -> también 'presuppositional'."""
        toks = [re.findall(r"\w+", _fold(r)) for r in rows]
        for i in range(len(rows) - 1):
            if rows[i].rstrip().endswith("-") and toks[i] and toks[i + 1]:
                toks[i].append(toks[i][-1] + toks[i + 1][0])
        return toks

    def locate(self, quote: str, doc: Optional[str] = None, k: int = 3,
               window: int = 4) -> List[Dict[str, Any]]:
        """Dónde está una cita: líneas y página(s) donde aparecen más palabras de `quote`.

        Tolera el reflujo de líneas, las palabras partidas con guion y pequeños errores de OCR
        (coincidencia aproximada). `coverage` es la fracción de palabras de la cita halladas.
        """
        terms = self._quote_terms(quote)
        if not terms:
            return []
        found: Dict[tuple, Dict[str, Any]] = {}
        for rank, cand in enumerate(self.db.search_fts(quote, limit=40, doc=doc)):
            path, lo, hi = cand["path"], cand["line_start"], cand["line_end"]
            try:
                rows = read_line_range(path, lo, hi)
            except OSError:
                rows = cand["text"].split("\n")
            if not rows:
                continue
            toks = self._line_tokens(rows)
            scored = []
            for i in range(len(rows)):
                win = set()
                for t in toks[i:i + window]:
                    win.update(t)
                scored.append((sum(1 for t in terms if t in win), i, win))
            scored.sort(key=lambda x: (-x[0], x[1]))
            best = None
            for exact, i, win in scored[:3]:           # aproximado solo en las mejores ventanas
                hit = {t for t in terms if t in win}
                for t in terms:
                    if t not in hit and self._approx(t, win):
                        hit.add(t)
                cov = len(hit) / len(terms)
                if best is None or cov > best[0]:
                    best = (cov, i, hit)
            cov, i, hit = best
            if cov <= 0:
                continue
            members = [j for j in range(i, min(i + window, len(rows)))
                       if any(t in toks[j] or (t in hit and self._approx(t, toks[j])) for t in terms)]
            first = lo + (members[0] if members else i)
            last = lo + (members[-1] if members else i)
            key = (path, first)
            item = {"path": path, "line_start": first, "line_end": last, "coverage": round(cov, 2),
                    "excerpt": " ".join(r.strip() for r in rows[(members[0] if members else i):
                                                              (members[-1] if members else i) + 1])[:300],
                    "page_start": None, "page_end": None, "page_label": None, "_rank": rank}
            pm = self.page_map(path)
            if pm is not None:
                item["page_start"], item["page_end"], item["page_label"] = pm.range_label(first, last)
            if key not in found or item["coverage"] > found[key]["coverage"]:
                found[key] = item
        out = sorted(found.values(), key=lambda d: (-d["coverage"], d["_rank"]))[:k]
        for d in out:
            d.pop("_rank")
        return out
