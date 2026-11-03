"""Acceso a base de datos SQLite para metadatos e historial."""

from __future__ import annotations

import re
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from .stopwords import STOPWORDS
from .models import Chunk, Document, Page, SearchHistory, get_engine, get_session_factory


class Database:
    def __init__(self, db_url: str = "sqlite:///search.db"):
        self.engine = get_engine(db_url)
        self.SessionFactory = get_session_factory(self.engine)
        self._init_fts()

    # ---------- Full-text (FTS5 + BM25) ----------

    FTS_VERSION = 2  # 2: rowid de FTS == chunks.id (permite emparejar con Chroma)

    def _init_fts(self) -> None:
        with self.engine.begin() as c:
            ver = c.execute(text("PRAGMA user_version")).scalar()
            if ver < self.FTS_VERSION:
                c.execute(text("DROP TABLE IF EXISTS chunks_fts"))
            c.execute(text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
                "text, path UNINDEXED, line_start UNINDEXED, line_end UNINDEXED, "
                "tokenize='unicode61 remove_diacritics 2')"))
            if ver < self.FTS_VERSION:  # reconstruir desde chunks con rowid = chunks.id
                c.execute(text(
                    "INSERT INTO chunks_fts(rowid, text, path, line_start, line_end) "
                    "SELECT c.id, c.text, d.path, c.line_start, c.line_end "
                    "FROM chunks c JOIN documents d ON d.id = c.document_id"))
                c.execute(text(f"PRAGMA user_version = {self.FTS_VERSION}"))

    @staticmethod
    def _fts_query(query: str) -> str:
        """Palabras sueltas entre comillas unidas con OR (BM25 ordena por relevancia).

        Se omiten las palabras vacías ("and", "de"...), salvo que la consulta sean solo
        palabras vacías: entonces se usan todas.
        """
        tokens = re.findall(r"\w+", query, flags=re.UNICODE)
        useful = [t for t in tokens if t.casefold() not in STOPWORDS]
        return " OR ".join(f'"{t}"' for t in (useful or tokens))

    def search_fts(self, query: str, limit: int = 10, doc: Optional[str] = None) -> List[dict]:
        q = self._fts_query(query)
        if not q:
            return []
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT rowid AS chunk_id, text, path, line_start, line_end, bm25(chunks_fts) AS rank "
                "FROM chunks_fts WHERE chunks_fts MATCH :q "
                + ("AND path LIKE :d " if doc else "") + "ORDER BY rank LIMIT :n"),
                {"q": q, "n": limit, **({"d": f"%{doc}%"} if doc else {})}).mappings().all()
        return [dict(r) for r in rows]

    def session(self) -> Session:
        return self.SessionFactory()

    def upsert_document(self, path: str, title: Optional[str] = None) -> Document:
        with self.session() as s:
            doc = s.query(Document).filter_by(path=path).first()
            if doc is None:
                doc = Document(path=path, title=title)
                s.add(doc)
                s.commit()
                s.refresh(doc)
            return doc

    def clear_chunks(self, document_id: int) -> None:
        with self.session() as s:
            doc = s.get(Document, document_id)
            s.query(Chunk).filter_by(document_id=document_id).delete()
            if doc is not None:
                s.execute(text("DELETE FROM chunks_fts WHERE path = :p"), {"p": doc.path})
            s.commit()

    def add_chunks(self, document_id: int, chunks: List[dict]) -> List[Chunk]:
        out = []
        with self.session() as s:
            doc = s.get(Document, document_id)
            for c in chunks:
                ch = Chunk(document_id=document_id, line_start=c["line_start"],
                           line_end=c["line_end"], text=c["text"])
                s.add(ch)
                out.append(ch)
            s.flush()  # asigna ch.id
            for ch in out:
                ch.embedding_id = f"c{ch.id}"
                s.execute(text(
                    "INSERT INTO chunks_fts(rowid, text, path, line_start, line_end) "
                    "VALUES (:i, :t, :p, :a, :b)"),
                    {"i": ch.id, "t": ch.text, "p": doc.path,
                     "a": ch.line_start, "b": ch.line_end})
            s.commit()
            for ch in out:
                s.refresh(ch)
        return out

    def get_chunks(self, document_id: Optional[int] = None) -> List[Chunk]:
        with self.session() as s:
            q = s.query(Chunk)
            if document_id is not None:
                q = q.filter_by(document_id=document_id)
            return q.all()

    def add_history(self, query: str, mode: str, result_count: int):
        with self.session() as s:
            s.add(SearchHistory(query=query, mode=mode, result_count=result_count))
            s.commit()

    def recent_history(self, limit: int = 20) -> List[SearchHistory]:
        with self.session() as s:
            return s.query(SearchHistory).order_by(SearchHistory.timestamp.desc()).limit(limit).all()

    # ---------- Documentos ----------

    def get_document(self, path: str) -> Optional[Document]:
        with self.session() as s:
            return s.query(Document).filter_by(path=path).first()

    def set_document_meta(self, document_id: int, content_hash: str, chunk_params: str) -> None:
        with self.session() as s:
            doc = s.get(Document, document_id)
            doc.content_hash = content_hash
            doc.chunk_params = chunk_params
            s.commit()

    def list_documents(self) -> List[dict]:
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT d.path, d.created_at, d.page_offset, d.page_offset_source, "
                "(SELECT count(*) FROM chunks k WHERE k.document_id = d.id) AS chunks, "
                "(SELECT count(*) FROM pages p WHERE p.document_id = d.id) AS pages "
                "FROM documents d ORDER BY d.path")).mappings().all()
        return [dict(r) for r in rows]

    def count_chunks(self) -> int:
        with self.engine.connect() as c:
            return c.execute(text("SELECT count(*) FROM chunks")).scalar()

    # ---------- Páginas ----------

    def set_pages(self, document_id: int, starts, offset, source) -> None:
        """Reemplaza las páginas de un documento (starts=None: el documento no tiene páginas)."""
        with self.session() as s:
            s.query(Page).filter_by(document_id=document_id).delete()
            if starts:
                s.add_all(Page(document_id=document_id, page=p, line_start=ln) for p, ln in starts)
            doc = s.get(Document, document_id)
            doc.page_offset = offset
            doc.page_offset_source = source
            s.commit()

    def get_pages(self, path: str):
        """([(página, línea)], desfase, origen_del_desfase) o None si el documento no tiene páginas."""
        with self.engine.connect() as c:
            doc = c.execute(text("SELECT id, page_offset, page_offset_source FROM documents WHERE path = :p"),
                            {"p": path}).first()
            if doc is None:
                return None
            rows = c.execute(text("SELECT page, line_start FROM pages WHERE document_id = :d "
                                  "ORDER BY line_start, page"), {"d": doc[0]}).all()
        if not rows:
            return None
        return [(r[0], r[1]) for r in rows], doc[1], doc[2]
