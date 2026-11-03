"""Modelos Pydantic y SQLAlchemy para la app de búsqueda."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field
from sqlalchemy import Column, inspect, text as sql_text, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker


# ---------- Pydantic (validación de entrada/salida) ----------

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    mode: str = Field(default="hybrid", pattern="^(text|semantic|hybrid)$")
    top_k: int = Field(default=10, ge=1, le=100)
    ignore_case: bool = True
    doc: Optional[str] = Field(default=None, max_length=1024)  # filtra por subcadena de ruta


class SearchResult(BaseModel):
    id: str
    text: str
    score: float
    source: str
    line_start: int
    line_end: int
    mode: str
    page_start: Optional[int] = None    # página del PDF (1-based)
    page_end: Optional[int] = None
    page_label: Optional[str] = None    # p. impresa ('134', '134–135') o 'pdf N' si no se conoce el desfase


class SearchResponse(BaseModel):
    query: str
    mode: str
    count: int
    results: List[SearchResult]
    elapsed_ms: float
    warnings: List[str] = Field(default_factory=list)


class IndexRequest(BaseModel):
    path: str
    max_chars: int = Field(default=1000, ge=100, le=4000)


# ---------- SQLAlchemy (persistencia) ----------

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    path = Column(String(1024), unique=True, nullable=False)
    title = Column(String(256))
    content_hash = Column(String(64))
    chunk_params = Column(String(32))  # firma del chunking (ver chunking.params_signature)
    page_offset = Column(Integer)      # nº impreso = página del PDF − page_offset (NULL: desconocido)
    page_offset_source = Column(String(8))  # 'auto' | 'manual'
    created_at = Column(DateTime, default=_now)
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    line_start = Column(Integer, nullable=False)
    line_end = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    embedding_id = Column(String(128))
    document = relationship("Document", back_populates="chunks")


class Page(Base):
    """Dónde empieza cada página (los `\\f` de pdftotext) dentro de un documento."""
    __tablename__ = "pages"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    page = Column(Integer, nullable=False)        # página del PDF, 1-based
    line_start = Column(Integer, nullable=False)  # primera línea de la página


class SearchHistory(Base):
    __tablename__ = "search_history"

    id = Column(Integer, primary_key=True)
    query = Column(String(500), nullable=False)
    mode = Column(String(16), nullable=False)
    result_count = Column(Integer, default=0)
    timestamp = Column(DateTime, default=_now)


def get_engine(db_url: str = "sqlite:///search.db"):
    engine = create_engine(db_url, echo=False, future=True)
    Base.metadata.create_all(engine)
    _migrate(engine)
    return engine


def _migrate(engine) -> None:
    """create_all no altera tablas existentes: añade las columnas nuevas si faltan."""
    cols = {c["name"] for c in inspect(engine).get_columns("documents")}
    with engine.begin() as c:
        if "content_hash" not in cols:
            c.execute(sql_text("ALTER TABLE documents ADD COLUMN content_hash VARCHAR(64)"))
        if "chunk_params" not in cols:
            c.execute(sql_text("ALTER TABLE documents ADD COLUMN chunk_params VARCHAR(32)"))
        if "page_offset" not in cols:
            c.execute(sql_text("ALTER TABLE documents ADD COLUMN page_offset INTEGER"))
        if "page_offset_source" not in cols:
            c.execute(sql_text("ALTER TABLE documents ADD COLUMN page_offset_source VARCHAR(8)"))


def get_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
