import sqlite3

import pytest

from pseudo_rag.models import SearchRequest, SearchResult
from pseudo_rag.service import SearchService, SemanticUnavailable


def test_index_is_idempotent(svc, docs):
    a = svc.index_path(str(docs / "a.md"), max_chars=60, overlap=1, force=True)
    b = svc.index_path(str(docs / "a.md"), max_chars=60, overlap=1, force=True)
    assert a["chunks"] == b["chunks"] == svc.db.count_chunks()


def test_unchanged_file_is_skipped_and_change_reindexes(svc, docs):
    f = str(docs / "a.md")
    assert svc.index_path(f)["skipped"] is False
    assert svc.index_path(f)["skipped"] is True
    with open(f, "a", encoding="utf-8") as fh:
        fh.write("línea nueva\n")
    assert svc.index_path(f)["skipped"] is False
    assert svc.search(SearchRequest(query="nueva", mode="text")).count == 1


def test_chunking_params_change_reindexes(svc, docs):
    f = str(docs / "a.md")
    svc.index_path(f, max_chars=1000)
    assert svc.index_path(f, max_chars=1000)["skipped"] is True
    assert svc.index_path(f, max_chars=100)["skipped"] is False
    assert svc.index_path(f, max_chars=100, overlap=0)["skipped"] is False


def test_legacy_document_without_chunk_params_is_reindexed(svc, docs):
    f = str(docs / "a.md")
    svc.index_path(f)
    with svc.db.session() as s:
        from pseudo_rag.models import Document
        s.query(Document).update({Document.chunk_params: None})
        s.commit()
    assert svc.index_path(f)["skipped"] is False


def test_fts_matches_separate_words_not_exact_phrase(svc, docs):
    svc.index_path(str(docs / "b.txt"))
    r = svc.search(SearchRequest(query="grace covenant", mode="text"))
    assert r.count == 1 and r.results[0].mode == "text"


def test_fts_ignores_diacritics(svc, docs):
    svc.index_path(str(docs / "a.md"))
    assert svc.search(SearchRequest(query="seccion", mode="text")).count == 1


def test_fts_survives_special_characters(svc, docs):
    svc.index_path(str(docs / "a.md"))
    for q in ['"', "pacto AND (", "a*b", "NEAR(", "'; DROP TABLE chunks;--"]:
        svc.search(SearchRequest(query=q, mode="text"))  # no debe lanzar


def test_doc_filter(svc, docs):
    svc.index_path(str(docs / "a.md"))
    svc.index_path(str(docs / "b.txt"))
    r = svc.search(SearchRequest(query="covenant pacto", mode="text", doc="b.txt"))
    assert r.count == 1 and r.results[0].source.endswith("b.txt")


def test_history_is_recorded_and_can_be_disabled(svc, docs):
    svc.index_path(str(docs / "a.md"))
    svc.search(SearchRequest(query="pacto", mode="text"))
    svc.search(SearchRequest(query="gracia", mode="text"), record_history=False)
    assert [h.query for h in svc.db.recent_history(5)] == ["pacto"]


def test_hybrid_degrades_to_text_with_warning(svc, docs):
    svc.index_path(str(docs / "a.md"))
    r = svc.search(SearchRequest(query="pacto", mode="hybrid"))
    assert r.mode == "text" and r.warnings and r.count == 1


def test_semantic_without_chroma_raises(svc):
    with pytest.raises(SemanticUnavailable):
        svc.search(SearchRequest(query="x", mode="semantic"))


def test_reindex_after_missing_file_raises(svc, tmp_path):
    with pytest.raises(FileNotFoundError):
        svc.index_path(str(tmp_path / "nope.txt"))


# ---------- RRF ----------

def _r(id, mode, start, end, src="f"):
    return SearchResult(id=id, text="t", score=0.0, source=src, line_start=start, line_end=end, mode=mode)


def test_rrf_merges_text_hit_inside_semantic_chunk():
    out = SearchService._rrf([_r("s1", "semantic", 1, 30), _r("s2", "semantic", 31, 60),
                              _r("t1", "text", 31, 60)])
    assert out[0].id == "s2" and out[0].mode == "hybrid"
    assert out[0].score > out[1].score


def test_rrf_keeps_unmatched_text_hits_and_other_files_separate():
    out = SearchService._rrf([_r("s1", "semantic", 1, 30, "a"), _r("t1", "text", 1, 30, "b")])
    assert {r.id for r in out} == {"s1", "t1"}
    assert all(r.mode != "hybrid" for r in out)


def test_rrf_ignores_raw_score_scales():
    # un score textual enorme no debe imponerse: solo cuenta la posición
    big = _r("t1", "text", 100, 130).model_copy(update={"score": 999.0})
    out = SearchService._rrf([_r("s1", "semantic", 1, 30), big])
    assert out[0].id == "s1"


# ---------- migración de una BD antigua ----------

def test_old_database_is_migrated_and_fts_rebuilt(tmp_path):
    home = tmp_path / ".prag"
    home.mkdir()
    con = sqlite3.connect(home / "search.db")
    con.executescript("""
        CREATE TABLE documents (id INTEGER PRIMARY KEY, path VARCHAR(1024) UNIQUE NOT NULL,
                                title VARCHAR(256), created_at DATETIME);
        CREATE TABLE chunks (id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL,
                             line_start INTEGER NOT NULL, line_end INTEGER NOT NULL,
                             text TEXT NOT NULL, embedding_id VARCHAR(128));
        CREATE TABLE search_history (id INTEGER PRIMARY KEY, query VARCHAR(500) NOT NULL,
                                     mode VARCHAR(16) NOT NULL, result_count INTEGER, timestamp DATETIME);
        INSERT INTO documents VALUES (1, '/x/old.txt', 'old.txt', NULL);
        INSERT INTO chunks VALUES (1, 1, 1, 3, 'texto antiguo con palabra rara', 'e1');
    """)
    con.commit()
    con.close()
    s = SearchService(home=home, semantic=False)
    r = s.search(SearchRequest(query="rara", mode="text"))
    assert r.count == 1 and r.results[0].source == "/x/old.txt"


# ---------- FTS: rowid == chunks.id, versión del esquema ----------

def test_fts_rowid_matches_chunk_id(svc, docs):
    svc.index_path(str(docs / "a.md"), max_chars=60, overlap=1)
    ids = {c.id for c in svc.db.get_chunks()}
    from sqlalchemy import text
    with svc.db.engine.connect() as c:
        fts = {r[0] for r in c.execute(text("SELECT rowid FROM chunks_fts"))}
    assert fts == ids


def test_outdated_fts_schema_is_rebuilt(tmp_path, docs):
    svc = SearchService(home=tmp_path / ".prag", create=True, semantic=False)
    svc.index_path(str(docs / "a.md"))
    from sqlalchemy import text
    with svc.db.engine.begin() as c:   # simula un índice de una versión anterior
        c.execute(text("DELETE FROM chunks_fts"))
        c.execute(text("PRAGMA user_version = 1"))
    svc2 = SearchService(home=tmp_path / ".prag", semantic=False)
    assert svc2.search(SearchRequest(query="pacto", mode="text")).count == 1


# ---------- solapamiento entre chunks ----------

def test_overlapping_chunks_do_not_repeat_the_same_passage(svc, tmp_path):
    f = tmp_path / "long.txt"
    f.write_text("\n".join(f"linea {i} con relleno de texto" for i in range(60))
                 + "\nla palabra zafiro aparece aqui\n"
                 + "\n".join(f"otra {i} con relleno de texto" for i in range(60)), encoding="utf-8")
    svc.index_path(str(f), max_chars=200, overlap=2)
    r = svc.search(SearchRequest(query="zafiro", mode="text", top_k=10))
    assert r.count == 1
    assert "zafiro" in r.results[0].text


def test_collapse_overlaps_keeps_best_ranked_and_distant_results():
    a = _r("a", "text", 1, 10)
    b = _r("b", "text", 5, 14)     # solapa 6/10 con a -> se descarta
    c = _r("c", "text", 10, 19)    # solapa 1/10 con a -> se conserva
    d = _r("d", "text", 1, 10, "otro")  # otro fichero -> se conserva
    out = SearchService._collapse_overlaps([a, b, c, d])
    assert [r.id for r in out] == ["a", "c", "d"]


def _rt(id, start, end, rows, src="f"):
    return SearchResult(id=id, text="\n".join(rows), score=0.0, source=src,
                        line_start=start, line_end=end, mode="text")


def test_collapse_drops_neighbour_that_only_matches_in_shared_lines():
    a = _rt("a", 1, 4, ["x", "x", "zafiro", "x"])
    b = _rt("b", 3, 6, ["zafiro", "x", "y", "y"])       # solo coincide en la línea 3 (compartida)
    assert [r.id for r in SearchService._collapse_overlaps([a, b], "zafiro")] == ["a"]


def test_collapse_keeps_neighbour_with_its_own_match():
    a = _rt("a", 1, 4, ["x", "x", "zafiro", "x"])
    b = _rt("b", 4, 7, ["x", "y", "zafiro", "y"])       # otro acierto fuera del solape
    assert [r.id for r in SearchService._collapse_overlaps([a, b], "zafiro")] == ["a", "b"]


def test_collapse_matching_ignores_accents_and_case():
    a = _rt("a", 1, 4, ["x", "x", "Sección", "x"])
    b = _rt("b", 3, 6, ["Sección", "x", "y", "y"])
    assert [r.id for r in SearchService._collapse_overlaps([a, b], "seccion")] == ["a"]


def test_rrf_prefers_exact_chunk_over_overlapping_one():
    # dos chunks semánticos contienen la línea del acierto; solo uno es el mismo chunk
    s1 = _r("sem:c1", "semantic", 1, 20)
    s2 = _r("sem:c2", "semantic", 15, 35)
    t = _r("text:c2", "text", 15, 35)
    out = SearchService._rrf([s1, s2, t])
    assert out[0].id == "sem:c2" and out[0].mode == "hybrid"
