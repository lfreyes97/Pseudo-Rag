import time

import pytest
from starlette.testclient import TestClient

from pseudo_rag.service import SearchService
from pseudo_rag.web.app import create_app, highlight, query_terms, term_regex


@pytest.fixture
def web(tmp_path, docs):
    svc = SearchService(home=tmp_path / ".prag", create=True, semantic=False)
    app = create_app(svc, allowed_dir=str(docs), target="", autoindex=False)
    return TestClient(app), svc, docs, app


def index(svc, docs):
    for f in docs.iterdir():
        svc.index_path(str(f))


# ---------- resaltado ----------

def test_query_terms_drop_stopwords_and_short_words():
    assert query_terms("Calvin and the de la gracia al") == ["calvin", "gracia"]
    assert query_terms("Sección sección") == ["seccion"]


def test_term_regex_is_accent_and_case_insensitive():
    rx = term_regex(query_terms("seccion"))
    assert rx.search("Otra SECCIÓN aquí") and rx.search("sección")
    assert term_regex([]) is None


def test_highlight_wraps_matches_in_mark():
    parts = highlight("el pacto y el Pacto", term_regex(["pacto"]))
    assert [getattr(p, "tag", p) for p in parts] == ["el ", "mark", " y el ", "mark", ""]


# ---------- página principal y búsqueda ----------

def test_home_without_index_shows_empty_state(web):
    client, *_ = web
    r = client.get("/")
    assert r.status_code == 200
    assert "Aún no hay documentos indexados" in r.text
    assert 'name="query"' in r.text and "htmx" in r.text.lower()


def test_search_page_highlights_terms_and_links_to_viewer(web):
    client, svc, docs, _ = web
    index(svc, docs)
    r = client.get("/", params={"query": "pacto", "mode": "text"})
    assert r.status_code == 200
    assert "<mark>pacto</mark>" in r.text
    assert "/doc?" in r.text and "badge-text" in r.text


def test_highlight_ignores_accents_in_page(web):
    client, svc, docs, _ = web
    index(svc, docs)
    r = client.get("/results", params={"query": "seccion", "mode": "text"})
    assert "<mark>sección</mark>" in r.text.lower()


def test_results_html_is_escaped(web):
    client, svc, docs, _ = web
    (docs / "x.txt").write_text("<script>alert(1)</script> pacto <img src=x onerror=1>", encoding="utf-8")
    svc.index_path(str(docs / "x.txt"))
    r = client.get("/results", params={"query": "pacto", "mode": "text"})
    assert "<script>alert(1)" not in r.text and "<img src=x" not in r.text
    assert "&lt;script&gt;" in r.text


def test_live_search_does_not_pollute_history_but_submit_does(web):
    client, svc, docs, _ = web
    index(svc, docs)
    client.get("/results", params={"query": "pac", "mode": "text"},
               headers={"HX-Request": "true", "HX-Trigger": "q"})
    assert svc.db.recent_history(5) == []
    r = client.get("/results", params={"query": "pacto", "mode": "text"},
                   headers={"HX-Request": "true", "HX-Trigger": "search-form"})
    assert [h.query for h in svc.db.recent_history(5)] == ["pacto"]
    assert "query=pacto" in r.headers["hx-replace-url"]


def test_history_items_are_clickable_links(web):
    client, svc, docs, _ = web
    index(svc, docs)
    client.get("/", params={"query": "covenant", "mode": "text"})
    home = client.get("/")
    assert 'href="/?query=covenant&amp;mode=text"' in home.text


def test_semantic_unavailable_is_a_friendly_notice_not_an_error(web):
    client, svc, docs, _ = web
    index(svc, docs)
    r = client.get("/results", params={"query": "pacto", "mode": "semantic"})
    assert r.status_code == 200 and "no está disponible" in r.text


def test_hybrid_without_chroma_shows_warning(web):
    client, svc, docs, _ = web
    index(svc, docs)
    r = client.get("/results", params={"query": "pacto", "mode": "hybrid"})
    assert "notice-warn" in r.text and "chromadb" in r.text


def test_invalid_query_is_a_notice(web):
    client, svc, docs, _ = web
    index(svc, docs)
    r = client.get("/results", params={"query": "x" * 600})
    assert r.status_code == 200 and "Consulta no válida" in r.text


def test_top_k_is_clamped_and_show_more_button(web, tmp_path):
    client, svc, docs, _ = web
    (docs / "many.txt").write_text("\n\n".join(f"palabra zafiro {i}" for i in range(40)), encoding="utf-8")
    svc.index_path(str(docs / "many.txt"), max_chars=60, overlap=0)
    r = client.get("/results", params={"query": "zafiro", "mode": "text", "top_k": 5})
    assert 'id="more"' in r.text and "top_k=15" in r.text
    r2 = client.get("/results", params={"query": "zafiro", "mode": "text", "top_k": 99999},
                    headers={"HX-Trigger": "more"})
    assert r2.status_code == 200 and 'hx-swap-oob="true"' in r2.text


def test_no_results_message(web):
    client, svc, docs, _ = web
    index(svc, docs)
    assert "Sin resultados" in client.get("/results", params={"query": "qqqqzzzz", "mode": "text"}).text


def test_without_javascript_the_form_still_works(web):
    client, *_ = web
    html = client.get("/").text
    assert 'action="/"' in html and 'method="get"' in html


# ---------- visor ----------

def test_viewer_shows_lines_with_highlight_and_hit_range(web):
    client, svc, docs, _ = web
    index(svc, docs)
    path = str(docs / "a.md")
    r = client.get("/doc", params={"path": path, "start": 3, "end": 3, "q": "Cristo"})
    assert r.status_code == 200
    assert 'class="ln hit"' in r.text and "<mark>Cristo</mark>" in r.text


def test_viewer_refuses_paths_not_in_the_index(web):
    client, svc, docs, _ = web
    index(svc, docs)
    for p in ("/etc/passwd", str(docs / "a.md") + "/../b.txt", "../../etc/hosts"):
        r = client.get("/doc", params={"path": p})
        assert r.status_code == 404, p
        assert "root:" not in r.text


def test_viewer_pagination_links(web, tmp_path):
    client, svc, docs, _ = web
    f = docs / "big.txt"
    f.write_text("\n".join(f"linea {i}" for i in range(1, 401)), encoding="utf-8")
    svc.index_path(str(f))
    r = client.get("/doc", params={"path": str(f), "start": 200, "end": 200})
    assert "líneas anteriores" in r.text and "líneas siguientes" in r.text
    r = client.get("/doc", params={"path": str(f), "start": 1, "end": 1, "lo": 1, "hi": 50})
    assert "líneas anteriores" not in r.text


# ---------- indexado desde la UI ----------

def wait_job(app, timeout=20):
    t = time.time()
    while app.state_job.snapshot()["running"] and time.time() - t < timeout:
        time.sleep(0.05)
    assert not app.state_job.snapshot()["running"]


def test_index_post_rejects_path_outside_allowed_dir(web, tmp_path):
    client, svc, docs, _ = web
    outside = tmp_path / "secreto.txt"
    outside.write_text("contenido privado", encoding="utf-8")
    r = client.post("/index", data={"path": str(outside)}, follow_redirects=False)
    assert r.status_code == 200 and "Ruta no permitida" in r.text
    assert svc.db.count_chunks() == 0


def test_index_post_rejects_symlink_escape(web, tmp_path):
    client, svc, docs, _ = web
    secret = tmp_path / "secreto.txt"
    secret.write_text("privado", encoding="utf-8")
    (docs / "link.txt").symlink_to(secret)
    r = client.post("/index", data={"path": str(docs / "link.txt")}, follow_redirects=False)
    assert "Ruta no permitida" in r.text and svc.db.count_chunks() == 0


def test_index_post_missing_file(web):
    client, svc, docs, _ = web
    r = client.post("/index", data={"path": str(docs / "nada.txt")}, follow_redirects=False)
    assert "No existe el fichero" in r.text


def test_index_post_runs_in_background_and_reports_result(web):
    client, svc, docs, app = web
    r = client.post("/index", data={"path": str(docs / "a.md")}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/index"
    wait_job(app)
    panel = client.get("/index/panel").text
    assert "indexado" in panel and "every 1s" not in panel   # el sondeo se detiene al terminar
    assert svc.db.count_chunks() > 0
    r2 = client.post("/index", data={"path": str(docs / "a.md")}, follow_redirects=False)
    wait_job(app)
    assert "sin cambios" in client.get("/index/panel").text


def test_panel_polls_only_while_running(web):
    client, svc, docs, app = web
    job = app.state_job
    with job.lock:
        job.running, job.phase, job.done, job.total, job.path = True, "embeddings", 3, 10, str(docs / "a.md")
    html = client.get("/index/panel").text
    assert "every 1s" in html and "<progress" in html and "3/10" in html
    with job.lock:
        job.running = False


def test_second_index_while_running_is_refused(web):
    client, svc, docs, app = web
    with app.state_job.lock:
        app.state_job.running = True
    r = client.post("/index", data={"path": str(docs / "a.md")}, follow_redirects=False)
    assert "Ya hay un indexado en curso" in r.text
    with app.state_job.lock:
        app.state_job.running = False


def test_index_error_is_reported_in_panel(web, monkeypatch):
    client, svc, docs, app = web
    monkeypatch.setattr(svc, "index_path", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    client.post("/index", data={"path": str(docs / "a.md")}, follow_redirects=False)
    wait_job(app)
    assert "boom" in client.get("/index/panel").text


def test_status_redirects_to_index(web):
    client, *_ = web
    r = client.get("/status", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/index"


def test_autoindex_on_startup(tmp_path, docs):
    svc = SearchService(home=tmp_path / ".prag", create=True, semantic=False)
    app = create_app(svc, allowed_dir=str(docs), target=str(docs / "a.md"))
    wait_job(app)
    assert svc.db.count_chunks() > 0


# ---------- seguridad del servidor ----------

def test_does_not_serve_files_from_cwd_or_write_sesskey_there(tmp_path, docs, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    (work / "secret.txt").write_text("TOPSECRET", encoding="utf-8")
    (work / "data.json").write_text('{"k": "TOPSECRET"}', encoding="utf-8")
    monkeypatch.chdir(work)
    svc = SearchService(home=tmp_path / ".prag", create=True, semantic=False)
    client = TestClient(create_app(svc, allowed_dir=str(docs), autoindex=False))
    for name in ("secret.txt", "data.json"):
        r = client.get("/" + name)
        assert "TOPSECRET" not in r.text
    assert not (work / ".sesskey").exists()


# ---------- UX: extracto, plegado, control de modo, historial ----------

def _long_doc(docs, svc):
    rows = [f"relleno numero {i} sin interes" for i in range(40)]
    rows[20] = "aqui aparece la palabra zafiro en medio"
    f = docs / "largo.txt"
    f.write_text("\n".join(rows), encoding="utf-8")
    svc.index_path(str(f), max_chars=2000, overlap=0)   # un solo chunk de 40 líneas
    return f


def test_long_result_shows_snippet_around_match_and_folds_the_rest(web):
    client, svc, docs, _ = web
    _long_doc(docs, svc)
    html = client.get("/results", params={"query": "zafiro", "mode": "text"}).text
    assert "<mark>zafiro</mark>" in html
    assert "Ver el chunk completo (40 líneas)" in html and "<details" in html
    # el extracto no vuelca las 40 líneas fuera del desplegable
    before_details = html.split("<details")[0]
    assert before_details.count('class="ln"') <= 6
    assert ">21<" in before_details            # número de línea de la coincidencia (índice 20)


def test_short_result_has_no_fold(web):
    client, svc, docs, _ = web
    index(svc, docs)
    html = client.get("/results", params={"query": "covenant", "mode": "text"}).text
    assert "<details" not in html


def test_snippet_shows_line_numbers_aligned_with_the_file(web):
    client, svc, docs, _ = web
    _long_doc(docs, svc)
    html = client.get("/results", params={"query": "zafiro", "mode": "text"}).text
    head = html.split("<details")[0]
    assert 'class="range">L1–40<' in head


def test_mode_is_a_segmented_control_and_selected_mode_is_kept(web):
    client, *_ = web
    html = client.get("/", params={"mode": "text"}).text
    assert html.count('type="radio"') == 3
    assert 'value="text" checked' in html or 'checked value="text"' in html
    assert 'name="top_k"' in html and 'type="hidden"' in html


def test_badges_are_in_spanish_but_keep_class(web):
    client, svc, docs, _ = web
    index(svc, docs)
    html = client.get("/results", params={"query": "pacto", "mode": "text"}).text
    assert ">texto<" in html and "badge-text" in html and "modo texto" in html


def test_viewer_marks_first_hit_line_for_scroll(web):
    client, svc, docs, _ = web
    index(svc, docs)
    r = client.get("/doc", params={"path": str(docs / "a.md"), "start": 2, "end": 3})
    assert r.text.count('id="hit"') == 1
    assert "#hit" in client.get("/results", params={"query": "pacto", "mode": "text"}).text


def test_viewer_without_hit_in_window_has_no_anchor(web):
    client, svc, docs, _ = web
    index(svc, docs)
    r = client.get("/doc", params={"path": str(docs / "a.md"), "start": 500, "end": 500, "lo": 1, "hi": 3})
    assert 'id="hit"' not in r.text


def test_history_chips_are_deduplicated(web):
    client, svc, docs, _ = web
    index(svc, docs)
    for _ in range(3):
        client.get("/", params={"query": "covenant", "mode": "text"})
    client.get("/", params={"query": "pacto", "mode": "text"})
    home = client.get("/").text
    assert home.count('class="chip"') == 2        # una por consulta distinta
