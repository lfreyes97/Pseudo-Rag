import json
import os
import shutil
import sqlite3

import pytest
from starlette.testclient import TestClient

from pseudo_rag.cli import main
from pseudo_rag.models import SearchRequest
from pseudo_rag.pages import (PageMap, cite_label, detect_offset, read_line_range,
                              read_paged_lines)
from pseudo_rag.service import SearchService
from pseudo_rag.web.app import create_app

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "pdftotext_libro.txt")


def write(tmp_path, text, name="libro.txt"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


@pytest.fixture
def libro(tmp_path):
    """Salida REAL de pdftotext: 15 páginas PDF; las 3 primeras sin numerar; pág. PDF 4 = impresa 1."""
    dst = tmp_path / "libro.txt"
    shutil.copy(FIXTURE, dst)
    return str(dst)


@pytest.fixture
def svc(tmp_path):
    return SearchService(home=tmp_path / ".prag", create=True, semantic=False)


# ---------- lectura de páginas ----------

def test_fixture_is_real_pdftotext_output():
    raw = open(FIXTURE, encoding="utf-8").read()
    assert raw.count("\f") == 15 and raw.endswith("\f")


def test_read_paged_lines_splits_on_form_feed(tmp_path):
    lines, starts = read_paged_lines(write(tmp_path, "a1\na2\n\fb1\n\fc1\nc2\n"))
    assert lines == ["a1", "a2", "b1", "c1", "c2"]
    assert starts == [(1, 1), (2, 3), (3, 4)]
    assert all("\f" not in l for l in lines)


def test_no_form_feeds_means_no_pages(tmp_path):
    lines, starts = read_paged_lines(write(tmp_path, "uno\ndos\n"))
    assert starts is None and lines == ["uno", "dos"]


def test_trailing_form_feed_does_not_create_a_phantom_page(tmp_path):
    lines, starts = read_paged_lines(write(tmp_path, "a\nb\n\f"))
    assert starts is None and lines == ["a", "b"]
    lines, starts = read_paged_lines(write(tmp_path, "a\n\fb\n\f"))
    assert starts == [(1, 1), (2, 2)] and lines == ["a", "b"]


def test_blank_pages_keep_the_count(tmp_path):
    lines, starts = read_paged_lines(write(tmp_path, "a\n\f\f\fb\n"))
    assert starts == [(1, 1), (4, 2)]
    assert PageMap(starts).page_of(2) == 4          # la página 4 es la de "b"


def test_crlf_files(tmp_path):
    p = tmp_path / "w.txt"
    p.write_bytes(b"a\r\nb\r\n\fc\r\n")
    lines, starts = read_paged_lines(str(p))
    assert lines == ["a", "b", "c"] and starts == [(1, 1), (2, 3)]


def test_real_output_has_15_pages_and_clean_lines():
    lines, starts = read_paged_lines(FIXTURE)
    assert len(starts) == 15 and all("\f" not in l for l in lines)


def test_line_count_is_stable_so_old_line_numbers_still_match(tmp_path):
    f = write(tmp_path, "a\nb\n\fc\nd\n")
    assert read_line_range(f, 3, 4) == ["c", "d"]
    assert read_line_range(f, 1, 2) == ["a", "b"]


# ---------- detección del desfase ----------

def test_detect_offset_on_real_pdftotext_output():
    lines, starts = read_paged_lines(FIXTURE)
    off, support, total = detect_offset(lines, starts)
    assert (off, total) == (3, 15) and support >= 10


def _book(n_pages, offset, footer="{}", unnumbered=()):
    out = []
    for p in range(1, n_pages + 1):
        body = f"texto de la pagina {p}\nmas texto\nmas texto\nmas texto\nmas texto"
        printed = p - offset
        if printed >= 1 and p not in unnumbered:
            body += "\n" + footer.format(printed)
        out.append(body + "\n")
    return "\f".join(out) + "\f"


def _parse(tmp_path, text):
    return read_paged_lines(write(tmp_path, text))


def test_detect_offset_with_dashed_numbers_and_gaps(tmp_path):
    lines, starts = _parse(tmp_path, _book(40, 6, "— {} —", unnumbered={10, 20, 30}))
    assert detect_offset(lines, starts)[0] == 6


def test_footnote_style_lines_are_not_page_numbers(tmp_path):
    lines, starts = _parse(tmp_path, _book(30, 0, "{}."))
    assert detect_offset(lines, starts) is None


def test_no_numbers_no_detection(tmp_path):
    lines, starts = _parse(tmp_path, _book(30, 99))
    assert detect_offset(lines, starts) is None


def test_too_little_support_is_rejected(tmp_path):
    lines, starts = _parse(tmp_path, _book(40, 0, unnumbered=set(range(1, 40))))
    assert detect_offset(lines, starts) is None


def test_ambiguous_numbering_is_rejected(tmp_path):
    # primera mitad con desfase 2 y segunda con desfase 9, con apoyo parecido: no hay ganador claro
    pages = []
    for p in range(1, 41):
        off = 2 if p <= 20 else 9
        pages.append(f"texto de la pagina {p}\nmas texto\nmas texto\nmas texto\n{p - off}\n")
    lines, starts = _parse(tmp_path, "\f".join(pages) + "\f")
    assert detect_offset(lines, starts) is None


def test_clear_winner_is_accepted_even_with_a_stray_second_offset(tmp_path):
    pages = []
    for p in range(1, 41):
        off = 2 if p <= 34 else 9           # 34 páginas con desfase 2 frente a 6 con otro
        pages.append(f"texto de la pagina {p}\nmas texto\nmas texto\nmas texto\n{p - off}\n")
    lines, starts = _parse(tmp_path, "\f".join(pages) + "\f")
    assert detect_offset(lines, starts)[0] == 2


# ---------- PageMap y etiquetas ----------

def test_pagemap_labels_and_ranges():
    pm = PageMap([(1, 1), (2, 10), (3, 20), (4, 30)], offset=1)
    assert pm.page_of(1) == 1 and pm.page_of(9) == 1 and pm.page_of(10) == 2 and pm.page_of(999) == 4
    assert [pm.label(p) for p in (1, 2, 3)] == ["pdf 1", "1", "2"]
    assert pm.range_label(12, 15) == (2, 2, "1")
    assert pm.range_label(15, 25) == (2, 3, "1–2")


def test_range_mixing_unnumbered_and_numbered_pages_is_cited_in_pdf_pages():
    pm = PageMap([(1, 1), (2, 10), (3, 20)], offset=1)      # pág. PDF 1 sin numerar; 2 -> "1"
    assert pm.range_label(5, 12) == (1, 2, "pdf 1–2")        # nunca "pdf 1–1"


def test_unknown_offset_never_pretends_to_be_a_printed_page():
    pm = PageMap([(1, 1), (2, 10), (3, 20)], offset=None)
    assert pm.label(2) == "pdf 2"
    assert pm.range_label(12, 25)[2] == "pdf 2–3"


def test_page_starts_in_window_prefers_last_page_on_ties():
    pm = PageMap([(1, 1), (2, 5), (3, 5), (4, 9)], offset=0)
    assert pm.page_starts_in(1, 20) == [(1, 1), (3, 5), (4, 9)]
    assert pm.page_starts_in(6, 8) == []


def test_cite_label():
    assert cite_label("134") == "p. 134"
    assert cite_label("134–135") == "pp. 134–135"
    assert cite_label("pdf 5") == "pdf 5"
    assert cite_label(None) == "" and cite_label("") == ""


# ---------- indexado con páginas ----------

def test_index_stores_pages_and_detects_offset(svc, libro):
    r = svc.index_path(libro, max_chars=300, overlap=1)
    assert r["pages"] == 15 and r["page_offset"] == 3 and r["offset_source"] == "auto"
    pm = svc.page_map(libro)
    assert pm.n_pages == 15 and pm.offset == 3


def test_results_carry_the_printed_page(svc, libro):
    svc.index_path(libro, max_chars=300, overlap=1)
    r = svc.search(SearchRequest(query="zafiro7", mode="text"))
    top = r.results[0]
    assert "7" in top.page_label and top.page_start is not None
    assert "zafiro7" in top.text


def test_chunk_text_never_contains_form_feeds(svc, libro):
    svc.index_path(libro)
    assert all("\f" not in c.text for c in svc.db.get_chunks())


def test_chunk_spanning_a_page_break_gets_a_page_range(svc, libro):
    svc.index_path(libro, max_chars=2000, overlap=0)        # chunks grandes: cruzan páginas
    labels = [r.page_label for r in svc.search(SearchRequest(query="relleno", mode="text", top_k=10)).results]
    assert any("–" in (l or "") for l in labels)


def test_text_without_page_breaks_has_no_page_fields(svc, tmp_path):
    f = write(tmp_path, "uno dos tres\ncuatro cinco\n", "plano.txt")
    r = svc.index_path(f)
    assert r["pages"] == 0
    res = svc.search(SearchRequest(query="cuatro", mode="text")).results[0]
    assert res.page_label is None and res.page_start is None


def test_unknown_offset_labels_are_pdf_pages(svc, tmp_path):
    text = "\f".join(f"pagina sin numero {i} zafiro{i}\n" + "relleno\n" * 4 for i in range(1, 8)) + "\f"
    f = write(tmp_path, text)
    r = svc.index_path(f)
    assert r["page_offset"] is None
    res = svc.search(SearchRequest(query="zafiro5", mode="text")).results[0]
    assert res.page_label.startswith("pdf")


def test_manual_offset_overrides_and_survives_reindex(svc, libro):
    svc.index_path(libro)
    r = svc.index_path(libro, page_offset=5)
    assert r["skipped"] is True and r["page_offset"] == 5 and r["offset_source"] == "manual"
    assert svc.page_map(libro).label(10) == "5"            # antes: 10 - 3 = 7
    again = svc.index_path(libro)                           # sin flag: no pisa el manual
    assert again["page_offset"] == 5 and again["offset_source"] == "manual"
    assert svc.index_path(libro, page_offset=0)["page_offset"] == 0   # 0 es un valor válido


def test_changing_the_file_refreshes_pages(svc, libro):
    svc.index_path(libro)
    with open(libro, "a", encoding="utf-8") as fh:
        fh.write("\f\nPagina extra al final.\n\f")
    r = svc.index_path(libro)
    assert r["skipped"] is False and r["pages"] == 16


def test_unchanged_file_still_populates_pages_for_old_indexes(tmp_path, libro):
    home = tmp_path / ".prag"
    s1 = SearchService(home=home, create=True, semantic=False)
    s1.index_path(libro)
    with s1.db.engine.begin() as c:                          # simula un índice anterior a las páginas
        c.exec_driver_sql("DELETE FROM pages")
        c.exec_driver_sql("UPDATE documents SET page_offset=NULL, page_offset_source=NULL")
    s2 = SearchService(home=home, semantic=False)
    assert s2.page_map(libro) is None
    r = s2.index_path(libro)
    assert r["skipped"] is True and r["pages"] == 15 and r["page_offset"] == 3


def test_old_schema_database_is_migrated(tmp_path):
    home = tmp_path / ".prag"
    home.mkdir()
    con = sqlite3.connect(home / "search.db")
    con.executescript("""
        CREATE TABLE documents (id INTEGER PRIMARY KEY, path VARCHAR(1024) UNIQUE NOT NULL,
                                title VARCHAR(256), content_hash VARCHAR(64), chunk_params VARCHAR(32),
                                created_at DATETIME);
        CREATE TABLE chunks (id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL,
                             line_start INTEGER NOT NULL, line_end INTEGER NOT NULL,
                             text TEXT NOT NULL, embedding_id VARCHAR(128));
        CREATE TABLE search_history (id INTEGER PRIMARY KEY, query VARCHAR(500) NOT NULL,
                                     mode VARCHAR(16) NOT NULL, result_count INTEGER, timestamp DATETIME);
    """)
    con.commit()
    con.close()
    SearchService(home=home, semantic=False)
    con = sqlite3.connect(home / "search.db")
    cols = {r[1] for r in con.execute("PRAGMA table_info(documents)")}
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"page_offset", "page_offset_source"} <= cols and "pages" in tables


# ---------- localizar una cita ----------

def test_locate_finds_the_right_printed_page(svc, libro):
    svc.index_path(libro, max_chars=300, overlap=1)
    best = svc.locate("palabra zafiro9 texto de la pagina impresa 9")[0]
    assert best["page_label"] == "9" and best["coverage"] == 1.0


def test_locate_does_not_confuse_pages_that_differ_only_by_a_digit(svc, libro):
    svc.index_path(libro, max_chars=300, overlap=1)
    res = svc.locate("la analogia del ser y la palabra zafiro7", k=5)
    assert res[0]["page_label"] == "7" and res[0]["coverage"] == 1.0
    assert all(r["coverage"] < 1.0 for r in res[1:])


def test_locate_tolerates_ocr_typos(svc, libro):
    svc.index_path(libro, max_chars=300, overlap=1)
    best = svc.locate("La analogla del ser y la palabra zafiro7")[0]      # 'analogla' (OCR)
    assert best["page_label"] == "7" and best["coverage"] == 1.0


def test_locate_joins_words_hyphenated_across_lines_and_pages(svc, tmp_path):
    text = ("Primera pagina con texto de relleno suficiente.\nLa doctrina presupposi-\ntional de Van Til\n\f"
            "continua aqui con analogical thought y mas texto.\n2\n\f")
    f = write(tmp_path, text)
    svc.index_path(f, page_offset=0)
    best = svc.locate("La doctrina presuppositional de Van Til continua aqui")[0]
    assert best["coverage"] == 1.0
    assert best["page_label"] == "1–2"                          # la cita cruza el salto de página
    assert svc.locate("analogicai thought", k=1)[0]["coverage"] == 1.0   # typo de OCR


def test_locate_has_low_coverage_for_unrelated_text(svc, libro):
    svc.index_path(libro)
    assert all(r["coverage"] < 0.5 for r in svc.locate("esto no aparece en ninguna parte del libro"))
    assert svc.locate("") == [] and svc.locate("a b") == []


def test_locate_doc_filter(svc, libro, tmp_path):
    other = write(tmp_path, "\f".join(f"otro libro palabra zafiro7 pagina {i}\n" for i in range(1, 6)) + "\f",
                  "otro.txt")
    svc.index_path(libro)
    svc.index_path(other, page_offset=0)
    only = svc.locate("palabra zafiro7", doc="otro.txt", k=5)
    assert only and all(r["path"].endswith("otro.txt") for r in only)


def test_locate_without_pages_returns_no_page(svc, tmp_path):
    f = write(tmp_path, "texto plano con la palabra rarisima\n", "plano.txt")
    svc.index_path(f)
    best = svc.locate("palabra rarisima")[0]
    assert best["page_label"] is None and best["line_start"] == 1


# ---------- CLI ----------

@pytest.fixture
def cli_env(tmp_path, monkeypatch, libro):
    monkeypatch.delenv("PRAG_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    return libro


def run(capsys, *argv):
    rc = main(list(argv))
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_cli_index_reports_detected_offset(capsys, cli_env):
    rc, _, err = run(capsys, "index", cli_env, "--no-semantic")
    assert rc == 0 and "15 páginas, desfase 3 (detectado" in err


def test_cli_index_json_has_page_info(capsys, cli_env):
    _, out, _ = run(capsys, "index", cli_env, "--no-semantic", "--json")
    r = json.loads(out)["results"][0]
    assert r["pages"] == 15 and r["page_offset"] == 3 and r["offset_source"] == "auto"


def test_cli_page_offset_flag_and_status(capsys, cli_env):
    run(capsys, "index", cli_env, "--no-semantic", "--page-offset", "2")
    rc, out, _ = run(capsys, "status")
    assert "desfase 2 (fijado a mano)" in out


def test_cli_search_shows_page_in_human_and_json_output(capsys, cli_env):
    run(capsys, "index", cli_env, "--no-semantic", "--max-chars", "300")
    _, out, _ = run(capsys, "search", "zafiro7", "--mode", "text", "--no-color")
    assert "p. 7" in out or "pp. 6–7" in out or "pp. 7–8" in out
    _, out, _ = run(capsys, "search", "zafiro7", "--mode", "text", "--json")
    first = json.loads(out)["results"][0]
    assert first["page_label"] and first["page_start"] and "page_end" in first


def test_cli_page_command_and_exit_codes(capsys, cli_env):
    run(capsys, "index", cli_env, "--no-semantic", "--max-chars", "300")
    rc, out, _ = run(capsys, "page", "palabra zafiro9 texto de la pagina impresa 9", "--no-color")
    assert rc == 0 and out.splitlines()[0].startswith("p. 9")
    rc, out, err = run(capsys, "page", "frase que no esta en el libro para nada")
    assert rc == 1 and "no encontré" in err
    rc, out, _ = run(capsys, "page", "palabra zafiro9", "--json")
    data = json.loads(out)
    assert rc == 0 and data["found"] and data["results"][0]["page_label"] == "9"


def test_cli_page_without_index_is_error(capsys, tmp_path, monkeypatch):
    monkeypatch.delenv("PRAG_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    rc, _, err = run(capsys, "page", "algo")
    assert rc == 2 and "No hay índice" in err


# ---------- web ----------

@pytest.fixture
def web(tmp_path, libro):
    svc = SearchService(home=tmp_path / ".prag", create=True, semantic=False)
    svc.index_path(libro, max_chars=300, overlap=1)
    return TestClient(create_app(svc, allowed_dir=str(tmp_path), autoindex=False)), svc, libro


def test_web_results_show_the_page(web):
    client, _, _ = web
    html = client.get("/results", params={"query": "zafiro7", "mode": "text"}).text
    assert 'class="page"' in html and ("p. 7" in html or "pp. " in html)


def test_web_viewer_shows_page_separators_and_page_in_header(web):
    client, _, libro = web
    html = client.get("/doc", params={"path": libro, "start": 50, "end": 50, "lo": 1, "hi": 90}).text
    assert 'class="pgbrk"' in html and "— p. 1 —" in html
    assert "p. 7" in html or "pp. " in html          # cabecera con la página del resultado
    assert "\f" not in html


def test_web_index_page_lists_pages_and_offset(web):
    client, _, _ = web
    html = client.get("/index").text
    assert "15 · desfase 3 (detectado)" in html


# ---------- la página citada es la de lo encontrado, no la de los bordes del chunk ----------

def test_page_label_ignores_footer_and_blank_lines_at_chunk_edges(svc, libro):
    svc.index_path(libro, max_chars=300, overlap=1)
    r = svc.search(SearchRequest(query="zafiro7 analogia", mode="text")).results[0]
    # el chunk empieza con el pie "6" de la página anterior, pero lo hallado está en la impresa 7
    assert r.page_label == "7"


def test_semantic_style_result_without_hits_trims_edge_artifacts(svc, libro):
    svc.index_path(libro, max_chars=300, overlap=1)
    base = svc.search(SearchRequest(query="zafiro7", mode="text")).results[0]
    sem_like = base.model_copy(update={"mode": "semantic"})
    out = svc._annotate_pages([sem_like], query="")          # sin términos: se recortan los bordes
    assert out[0].page_label in ("7", "6–7", "7–8")           # nunca una página inventada
    assert out[0].page_start is not None


def test_hits_on_two_pages_give_a_range(svc, libro):
    svc.index_path(libro, max_chars=2000, overlap=0)
    r = svc.search(SearchRequest(query="zafiro2 zafiro3", mode="text")).results[0]
    assert "–" in r.page_label


def test_is_page_artifact():
    from pseudo_rag.pages import is_page_artifact
    for t in ("", "   ", "7", " 12 ", "— 134 —"):
        assert is_page_artifact(t)
    for t in ("75.", "texto", "Capítulo 7"):
        assert not is_page_artifact(t)
