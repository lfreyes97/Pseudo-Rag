"""Interfaz web (FastHTML + HTMX) sobre el mismo índice que usa el CLI.

- Búsqueda en vivo (HTMX) con degradación a formulario GET si no hay JavaScript.
- `/` también acepta ?query=… (enlaces, historial, recargar la página).
- Resaltado de términos, "mostrar más", visor de documento en la línea del resultado.
- Indexado en segundo plano con barra de progreso (`/index`).
"""

from __future__ import annotations

import os
import re
import threading
import unicodedata
from itertools import islice
from typing import Callable, List, Optional
from urllib.parse import urlencode

from fasthtml.common import *
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from ..models import SearchRequest
from ..pages import cite_label, read_line_range
from ..service import SearchService, SemanticUnavailable
from ..stopwords import STOPWORDS

# ---------- CSS (estilo Cursor: warm parchment) ----------
CSS = """
:root {
  --color-parchment: #f7f7f4;
  --color-bone: #f2f1ed;
  --color-linen: #e6e5e0;
  --color-stone: #cdcdc9;
  --color-mist: #a1a19f;
  --color-driftwood: #84847e;
  --color-ash: #7a7974;
  --color-ink: #26251e;
  --color-ember: #f54e00;
  --font-sans: 'Inter', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
  --font-serif: 'EB Garamond', 'Iowan Old Style', 'Palatino Linotype', ui-serif, Georgia, serif;
  --font-mono: ui-monospace, 'SFMono-Regular', Menlo, Monaco, Consolas, monospace;
}
* { box-sizing: border-box; }
html, body {
  background: var(--color-parchment);
  color: var(--color-ink);
  font-family: var(--font-sans);
  font-size: 16px;
  line-height: 1.5;
  margin: 0;
  -webkit-font-smoothing: antialiased;
}
.container { max-width: 1180px; margin: 0 auto; padding: 0 24px; }
h1, h2, h3 { font-weight: 400; letter-spacing: -0.02em; color: var(--color-ink); margin: 0; }
h1 { font-size: 36px; line-height: 1.2; letter-spacing: -0.72px; }
h2 { font-size: 26px; line-height: 1.25; letter-spacing: -0.312px; }
h3 { font-size: 22px; line-height: 1.3; letter-spacing: -0.11px; }
p { margin: 0 0 12px; }
a { color: var(--color-ember); text-decoration: none; transition: color 150ms cubic-bezier(0.4,0,0.2,1); }
a:hover { text-decoration: underline; }
code, .mono { font-family: var(--font-mono); font-size: 12px; color: var(--color-ash); }
small { color: var(--color-ash); font-size: 13px; }

/* Nav */
.nav {
  height: 52px;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 24px; background: transparent;
}
.nav .brand { font-weight: 500; font-size: 14px; color: var(--color-ink); }
.nav a { color: var(--color-ink); opacity: 0.6; font-size: 14px; margin: 0 12px; }
.nav a:hover { opacity: 1; text-decoration: none; }

/* Card */
.card {
  background: var(--color-bone);
  border: 1px solid color-mix(in oklab, var(--color-ink) 5%, transparent);
  border-radius: 4px;
  padding: 24px;
  box-shadow: rgba(0,0,0,0.14) 0px 28px 70px 0px, rgba(0,0,0,0.1) 0px 14px 32px 0px;
}
.card-flat { box-shadow: none; }

/* Buttons */
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: var(--font-sans); font-size: 14px; font-weight: 400;
  padding: 0.78em 1.35em 0.8em; border-radius: 4px; border: none;
  cursor: pointer; transition: background 150ms cubic-bezier(0.4,0,0.2,1), color 150ms;
  text-decoration: none;
}
.btn-primary { background: var(--color-ink); color: var(--color-parchment); }
.btn-primary:hover { background: #1a1914; color: var(--color-parchment); text-decoration: none; }
.btn-secondary { background: var(--color-linen); color: var(--color-ink); }
.btn-secondary:hover { background: #dddcd6; text-decoration: none; }
.btn-ghost { background: transparent; color: var(--color-ink); opacity: 0.6; padding: 6px 8px; }
.btn-ghost:hover { opacity: 1; text-decoration: none; }

/* Inputs */
input[type=text], input[type=number], select, textarea {
  font-family: var(--font-sans); font-size: 14px;
  padding: 10px 12px; border-radius: 4px;
  border: 1px solid color-mix(in oklab, var(--color-ink) 10%, transparent);
  background: var(--color-parchment); color: var(--color-ink);
  outline: none;
}
input:focus, select:focus { border-color: var(--color-ink); }
select { background: var(--color-parchment); }

/* Search form */
.search-form { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 24px 0; }
.search-form input[name=query] { flex: 1; min-width: 240px; }

/* Results */
.result-item {
  padding: 16px 0; border-bottom: 1px solid var(--color-stone);
}
.result-item:last-child { border-bottom: none; }
.result-meta { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; flex-wrap: wrap; }
.badge {
  font-family: var(--font-mono); font-size: 11px; color: var(--color-ash);
  background: var(--color-linen); padding: 2px 6px; border-radius: 4px;
}
.badge-mode { background: var(--color-ink); color: var(--color-parchment); }
.score { font-family: var(--font-mono); font-size: 12px; color: var(--color-driftwood); }
.result-text { font-size: 15px; line-height: 1.5; color: var(--color-ink); margin: 4px 0; }
.result-source { font-family: var(--font-mono); font-size: 12px; color: var(--color-ash); }

/* Status pill */
.status { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--color-driftwood); }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--color-ash); }
.dot.ok { background: var(--color-forest, #34785c); }
.dot.busy { background: var(--color-amber, #c08532); }

/* Footer */
.footer { margin-top: 64px; padding: 32px 0; border-top: 1px solid var(--color-stone); color: var(--color-ash); font-size: 13px; }

/* Lists */
ul.clean { list-style: none; padding: 0; margin: 0; }
ul.clean li { padding: 6px 0; font-size: 14px; color: var(--color-driftwood); }

/* Section spacing */
.section { margin: 48px 0; }
.hero { margin: 64px 0 48px; }
.hero h1 { max-width: 720px; }
.hero p { color: var(--color-driftwood); max-width: 640px; font-size: 17px; line-height: 1.5; }

/* ---- búsqueda en vivo, resultados ---- */
.search-form input[type=search] { flex: 1; min-width: 240px; font-family: var(--font-sans); font-size: 15px;
  padding: 10px 12px; border-radius: 4px; border: 1px solid color-mix(in oklab, var(--color-ink) 10%, transparent);
  background: var(--color-parchment); color: var(--color-ink); outline: none; }
.search-form input[type=search]:focus { border-color: var(--color-ink); }
.htmx-indicator { opacity: 0; transition: opacity 150ms; font-size: 13px; color: var(--color-ash); }
.htmx-request .htmx-indicator, .htmx-request.htmx-indicator { opacity: 1; }
.summary { color: var(--color-driftwood); font-size: 14px; margin: 0 0 12px; }
.notice { padding: 10px 14px; border-radius: 4px; background: var(--color-linen); font-size: 14px; margin: 12px 0; }
.notice-warn { border-left: 3px solid var(--color-amber, #c08532); }
.notice-error { border-left: 3px solid var(--color-ember); }
.notice-ok { border-left: 3px solid var(--color-forest, #34785c); }
.result-text { font-family: var(--font-sans); font-size: 14.5px; white-space: pre-wrap; word-break: break-word;
  margin: 6px 0 0; line-height: 1.5; }
mark { background: color-mix(in oklab, var(--color-ember) 22%, transparent); color: inherit; border-radius: 2px; padding: 0 1px; }
.badge-text { background: var(--color-linen); }
.badge-semantic { background: #dfe6f1; color: #2b3a55; }
.badge-hybrid { background: var(--color-ink); color: var(--color-parchment); }
.loc { font-family: var(--font-mono); font-size: 12px; }
.more { margin: 20px 0 0; }
.empty { padding: 28px; text-align: center; color: var(--color-driftwood); }
ul.clean li a { color: var(--color-ink); }
ul.clean li small { margin-left: 8px; }

/* ---- índice / progreso ---- */
progress { width: 100%; height: 10px; accent-color: var(--color-ember); }
table.docs { width: 100%; border-collapse: collapse; font-size: 14px; margin-top: 12px; }
table.docs th, table.docs td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--color-stone); }
table.docs td.num { text-align: right; font-family: var(--font-mono); font-size: 12px; }
.checkline { display: flex; gap: 6px; align-items: center; font-size: 14px; color: var(--color-driftwood); }

/* ---- visor de documento ---- */
.viewer { font-family: var(--font-mono); font-size: 12.5px; line-height: 1.55; background: var(--color-bone);
  border: 1px solid var(--color-stone); border-radius: 4px; padding: 8px 0; overflow-x: auto; }
.ln { display: flex; gap: 12px; padding: 0 12px; white-space: pre-wrap; word-break: break-word; }
.ln .n { color: var(--color-mist); min-width: 5ch; text-align: right; user-select: none; }
.ln.hit { background: color-mix(in oklab, var(--color-ember) 8%, transparent); }
.viewer-nav { display: flex; gap: 8px; margin: 12px 0; }
.pgbrk { margin: 6px 12px; padding: 2px 0; text-align: center; font-family: var(--font-mono); font-size: 11px;
  color: var(--color-forest, #34785c); border-top: 1px dashed var(--color-stone); border-bottom: 1px dashed var(--color-stone); }
.result-meta .page { font-family: var(--font-mono); font-size: 12px; font-weight: 600; color: var(--color-forest, #34785c); }

@media (prefers-color-scheme: dark) {
  :root {
    --color-parchment: #1c1b17; --color-bone: #24231e; --color-linen: #2e2d27; --color-stone: #3a3932;
    --color-mist: #6f6e68; --color-driftwood: #a09f98; --color-ash: #8d8c85; --color-ink: #ece9e0;
  }
  .btn-primary { background: var(--color-ink); color: var(--color-parchment); }
  .badge-semantic { background: #2a3a55; color: #cfdcf5; }
  .card { box-shadow: none; }
}
"""

CSS += """
/* ---- UX: cabecera compacta, control segmentado, resultados con extracto ---- */
.hero { margin: 36px 0 24px; }
.hero h1 { font-size: 30px; }
.hero p { font-size: 15px; margin: 6px 0 0; }
.nav a.active { opacity: 1; font-weight: 500; }
kbd { font-family: var(--font-mono); font-size: 11px; padding: 1px 5px; border-radius: 3px;
  border: 1px solid var(--color-stone); background: var(--color-bone); }
.search-form { margin: 0 0 8px; }
.search-row { display: flex; gap: 8px; width: 100%; }
.search-row input[type=search] { flex: 1; min-width: 0; }
.opts { display: flex; gap: 14px; align-items: center; width: 100%; }
.seg { display: inline-flex; border: 1px solid var(--color-stone); border-radius: 6px; overflow: hidden; }
.seg label { padding: 6px 14px; font-size: 13px; cursor: pointer; color: var(--color-driftwood);
  position: relative; user-select: none; }
.seg label + label { border-left: 1px solid var(--color-stone); }
.seg input { position: absolute; opacity: 0; pointer-events: none; }
.seg label:has(input:checked) { background: var(--color-ink); color: var(--color-parchment); }
.seg label:has(input:focus-visible) { outline: 2px solid var(--color-ember); outline-offset: -2px; }
#search-form.htmx-request ~ #results { opacity: .5; transition: opacity 150ms; }
.search-form .grow { flex: 1; min-width: 240px; }

.card-flat.results { padding: 2px 20px; }
.result-item { padding: 14px 0; }
.result-meta { margin-bottom: 8px; }
.result-meta .loc { color: var(--color-ink); font-weight: 500; }
.result-meta .loc:hover { color: var(--color-ember); }
.result-meta .range { font-family: var(--font-mono); font-size: 12px; color: var(--color-ash); }
.snip { font-size: 14.5px; line-height: 1.5; }
.snip .ln { padding: 0; gap: 12px; white-space: normal; }
.snip .ln .n { min-width: 5ch; color: var(--color-mist); font-family: var(--font-mono); font-size: 11.5px;
  padding-top: 2px; }
.snip .gap { color: var(--color-mist); padding-left: calc(5ch + 12px); line-height: 1.1; }
details.full { margin-top: 8px; }
details.full > summary { cursor: pointer; font-size: 12.5px; color: var(--color-ash); }
details.full > summary:hover { color: var(--color-ink); }
details.full .snip { margin-top: 8px; padding-left: 10px; border-left: 2px solid var(--color-stone); }

ul.chips { list-style: none; padding: 0; margin: 10px 0 0; display: flex; flex-wrap: wrap; gap: 8px; }
ul.chips li { padding: 0; }
a.chip { display: inline-flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 999px;
  background: var(--color-bone); border: 1px solid var(--color-stone); color: var(--color-ink); font-size: 13.5px; }
a.chip:hover { border-color: var(--color-ink); text-decoration: none; }
a.chip small { margin: 0; font-size: 11px; color: var(--color-ash); }

@media (max-width: 640px) {
  .hero { margin: 20px 0 16px; }
  .hero h1 { font-size: 24px; }
  .hero p { display: none; }
  .container { padding: 0 16px; }
  .nav { padding: 0 16px; }
  .card-flat.results { padding: 0 14px; }
  .opts { flex-wrap: wrap; }
  .snip .ln .n { min-width: 4.5ch; }
}
"""

JS = """
document.addEventListener('keydown', function (e) {
  var tag = document.activeElement.tagName;
  if (e.key === '/' && !/^(INPUT|TEXTAREA|SELECT)$/.test(tag)) {
    var q = document.querySelector('input[name=query]');
    if (q) { e.preventDefault(); q.focus(); q.select(); }
  }
});
document.addEventListener('input', function (e) {   // nueva consulta => volver a 10 resultados
  if (e.target && e.target.name === 'query') {
    var k = document.getElementById('top_k'); if (k) k.value = 10;
  }
});
window.addEventListener('load', function () {       // visor: centrar el resultado
  var h = document.getElementById('hit');
  if (h) h.scrollIntoView({block: 'center'});
});
"""

MODE_LABEL = {"hybrid": "híbrida", "text": "texto", "semantic": "semántica"}
MAX_TOP_K = 100
MORE_STEP = 10
VIEW_CONTEXT = 25      # líneas de contexto alrededor del resultado en el visor
VIEW_PAGE = 100        # líneas que añade "anteriores"/"siguientes"
VIEW_MAX = 400


# ---------- resaltado (insensible a mayúsculas y acentos) ----------

_ACCENTS = {"a": "aáàäâãÁÀÄÂÃ", "e": "eéèëêÉÈËÊ", "i": "iíìïîÍÌÏÎ", "o": "oóòöôõÓÒÖÔÕ",
            "u": "uúùüûÚÙÜÛ", "n": "nñÑ", "c": "cçÇ"}


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(ch))


def query_terms(query: str) -> List[str]:
    """Términos útiles de la consulta (sin palabras vacías ni de menos de 3 letras)."""
    seen, out = set(), []
    for w in re.findall(r"\w+", query):
        f = _fold(w)
        if len(f) >= 3 and f not in STOPWORDS and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def term_regex(terms: List[str]) -> Optional["re.Pattern[str]"]:
    if not terms:
        return None
    parts = []
    for t in terms:
        parts.append("".join(f"[{re.escape(_ACCENTS[ch])}]" if ch in _ACCENTS else re.escape(ch)
                             for ch in t))
    return re.compile("|".join(parts), re.IGNORECASE)


def highlight(text: str, rx) -> list:
    """Lista de str y <mark>; FastHTML escapa el texto, así que es seguro."""
    if rx is None:
        return [text]
    out, pos = [], 0
    for m in rx.finditer(text):
        if m.start() > pos:
            out.append(text[pos:m.start()])
        out.append(Mark(m.group(0)))
        pos = m.end()
    out.append(text[pos:])
    return out


# ---------- trabajo de indexado en segundo plano ----------

class IndexJob:
    """Un único indexado a la vez; el estado se consulta desde /index/panel."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.path = ""
        self.phase = ""
        self.done = 0
        self.total = 0
        self.error: Optional[str] = None
        self.result: Optional[dict] = None

    def snapshot(self) -> dict:
        with self.lock:
            return {"running": self.running, "path": self.path, "phase": self.phase,
                    "done": self.done, "total": self.total, "error": self.error,
                    "result": self.result}

    def start(self, service: SearchService, path: str, max_chars: int, force: bool) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running, self.path = True, path
            self.phase, self.done, self.total = "preparando", 0, 0
            self.error, self.result = None, None

        def progress(phase: str, done: int, total: int) -> None:
            with self.lock:
                self.phase, self.done, self.total = phase, done, total

        def run() -> None:
            try:
                res = service.index_path(path, max_chars=max_chars, force=force, progress=progress)
                with self.lock:
                    self.result = res
            except Exception as e:  # se muestra en la UI
                with self.lock:
                    self.error = str(e)
            finally:
                with self.lock:
                    self.running = False

        threading.Thread(target=run, daemon=True).start()
        return True


# ---------- aplicación ----------

def create_app(service: SearchService, allowed_dir: Optional[str] = None, target: str = "",
               autoindex: bool = True):
    """Construye la app. `allowed_dir` limita qué ficheros se pueden indexar desde la UI."""
    allowed = os.path.realpath(allowed_dir or (os.path.dirname(target) if target else os.getcwd()))
    job = IndexJob()

    def is_allowed(path: str) -> bool:
        real = os.path.realpath(path)
        return real == allowed or real.startswith(allowed + os.sep)

    def display(path: str) -> str:
        try:
            rel = os.path.relpath(path, allowed)
        except ValueError:
            return path
        return path if rel.startswith("..") else rel

    def indexed_paths() -> set:
        return {d["path"] for d in service.db.list_documents()}

    # --- layout ---
    def layout(title: str, body, active: str = ""):
        def link(label, href, key):
            return A(label, href=href, cls="active" if key == active else "")
        nav = Nav(cls="nav")(
            Div(cls="container", style="display:flex;align-items:center;justify-content:space-between;width:100%;")(
                Span("Pseudo-RAG", cls="brand"),
                Div(link("Buscar", "/", "search"), link("Índice", "/index", "index")),
            ))
        footer = Footer(cls="footer")(Div(cls="container")(
            P("Pseudo-RAG · ", Kbd("/"), " enfoca la búsqueda")))
        return (Title(f"{title} · Pseudo-RAG"), nav, Main(cls="container")(body), footer)

    app, rt = fast_app(
        pico=False, surreal=False, title="Pseudo-RAG",
        hdrs=(Style(CSS), Script(JS)),
        key_fname=str(service.home / ".sesskey"),
        static_path=str(service.home / "static"),   # no servir ficheros del directorio actual
        exception_handlers={
            404: lambda req, exc: layout("No encontrado", Div(
                H2("No encontrado"), P(getattr(exc, "detail", "") or "La página no existe."),
                A("← Volver", href="/", cls="btn btn-secondary"))),
        })

    # --- búsqueda ---
    def search_form(query: str, mode: str, top_k: int):
        return Form(
            cls="search-form", id="search-form", action="/", method="get",
            hx_get="/results", hx_target="#results", hx_swap="innerHTML", hx_sync="this:replace",
            hx_indicator="#spin",
            hx_trigger="input changed delay:350ms from:find input[name=query], "
                       "change from:find input[name=mode], submit")(
            Div(cls="search-row")(
                Input(id="q", type="search", name="query", value=query, autofocus=True,
                      autocomplete="off", placeholder="Escribe tu consulta…"),
                Button("Buscar", type="submit", cls="btn btn-primary")),
            Div(cls="opts")(
                Div(cls="seg", role="radiogroup", aria_label="Modo de búsqueda")(
                    *[Label(Input(type="radio", name="mode", value=v, checked=(v == mode)), label,
                            title=tip)
                      for v, label, tip in (
                          ("hybrid", "Híbrida", "Texto exacto + significado, fusionados"),
                          ("text", "Texto", "Palabras exactas (BM25)"),
                          ("semantic", "Semántica", "Por significado (embeddings)"))]),
                Span("Buscando…", id="spin", cls="htmx-indicator")),
            Input(id="top_k", name="top_k", type="hidden", value=str(top_k)),
        )

    def empty_state():
        """Pantalla sin consulta: estado del índice e historial clicable."""
        n_chunks = service.db.count_chunks()
        if n_chunks == 0:
            return Div(cls="card card-flat empty")(
                P("Aún no hay documentos indexados."),
                A("Indexar un documento", href="/index", cls="btn btn-primary"))
        docs = service.db.list_documents()
        sem = "con búsqueda semántica" if service.semantic_available else "solo texto (sin chromadb)"
        seen, hist = set(), []
        for h in service.db.recent_history(40):        # sin repetir (consulta, modo)
            key = (h.query.strip().casefold(), h.mode)
            if key not in seen:
                seen.add(key)
                hist.append(h)
        items = [Li(A(h.query, Small(MODE_LABEL.get(h.mode, h.mode)), cls="chip", title=f"{h.result_count} resultados",
                      href="/?" + urlencode({"query": h.query, "mode": h.mode})))
                 for h in hist[:10]]
        return Div(
            P(f"{len(docs)} documento(s) · {n_chunks} chunks · {sem}", cls="summary"),
            Div(cls="section", style="margin-top:32px;")(
                H3("Historial reciente"),
                Ul(*items, cls="chips") if items else P("Sin historial.", cls="summary")))

    def snippet(r, rx, max_rows: int = 6):
        """Extracto de un resultado: las líneas con coincidencias (y su vecina) en vez del chunk
        entero; el resto queda en un <details>. Devuelve (extracto, desplegable | None)."""
        rows = r.text.split("\n")
        aligned = len(rows) == r.line_end - r.line_start + 1   # el texto coincide con el rango
        nums = [r.line_start + i if aligned else (r.line_start if i == 0 else None)
                for i in range(len(rows))]
        useful = [i for i, row in enumerate(rows) if row.strip()]
        if len(useful) <= max_rows:
            pick = useful
        else:
            hits = [i for i in useful if rx is not None and rx.search(rows[i])] or useful[:1]
            chosen = []
            for i in hits:
                pos = useful.index(i)
                for j in useful[max(0, pos - 1):pos + 2]:
                    if j not in chosen:
                        chosen.append(j)
                if len(chosen) >= max_rows:
                    break
            pick = sorted(chosen)[:max_rows]

        def render(idx_list):
            out, prev = [], None
            for i in idx_list:
                if prev is not None and i - prev > 1 and len(idx_list) < len(useful):
                    out.append(Div("⋯", cls="gap"))
                out.append(Div(cls="ln")(Span("" if nums[i] is None else str(nums[i]), cls="n"),
                                         Span(*highlight(rows[i], rx))))
                prev = i
            return Div(*out, cls="snip")

        extra = None
        if len(pick) < len(useful):
            extra = Details(Summary(f"Ver el chunk completo ({len(useful)} líneas)"), render(useful),
                            cls="full")
        return render(pick), extra

    def results_view(query: str, mode: str, top_k: int, record: bool, more_clicked: bool = False):
        if not query.strip():
            return empty_state()
        try:
            req = SearchRequest(query=query, mode=mode, top_k=top_k)
        except ValidationError as e:
            msg = e.errors()[0].get("msg", "consulta no válida")
            return Div(P(f"Consulta no válida: {msg}", cls="notice notice-error"))
        try:
            resp = service.search(req, record_history=record)
        except SemanticUnavailable:
            return Div(P("La búsqueda semántica no está disponible (falta chromadb). "
                         "Prueba el modo textual o instala el extra: uv sync --extra semantic.",
                         cls="notice notice-error"))
        except Exception as e:
            return Div(P(f"No se pudo buscar: {e}", cls="notice notice-error"))

        rx = term_regex(query_terms(query))
        items = []
        for r in resp.results:
            view = "/doc?" + urlencode({"path": r.source, "start": r.line_start,
                                        "end": r.line_end, "q": query}) + "#hit"
            name = display(r.source)
            if os.path.isabs(name):
                name = os.path.basename(name)
            rng = (f"L{r.line_start}" if r.line_start == r.line_end
                   else f"L{r.line_start}–{r.line_end}")
            shown, extra = snippet(r, rx)
            items.append(Div(cls="result-item")(
                Div(cls="result-meta")(
                    Span(MODE_LABEL.get(r.mode, r.mode), cls=f"badge badge-{r.mode}",
                         title=f"puntuación {r.score}"),
                    A(name, href=view, cls="loc", title=f"{r.source} — abrir en el visor"),
                    Span(cite_label(r.page_label), cls="page") if r.page_label else "",
                    Span(rng, cls="range")),
                shown, extra or ""))
        parts = [P(f"{resp.count} resultado(s) · modo {MODE_LABEL.get(resp.mode, resp.mode)} · "
                f"{resp.elapsed_ms:.0f} ms", cls="summary")]
        parts += [P(w, cls="notice notice-warn") for w in resp.warnings]
        if items:
            parts.append(Div(cls="card card-flat results")(*items))
            if resp.count >= top_k and top_k < MAX_TOP_K:
                nxt = min(top_k + MORE_STEP, MAX_TOP_K)
                qs = urlencode({"query": query, "mode": mode, "top_k": nxt})
                parts.append(Div(cls="more")(Button(
                    f"Mostrar {nxt - top_k} más", id="more", cls="btn btn-secondary",
                    hx_get=f"/results?{qs}", hx_target="#results", hx_swap="innerHTML")))
        else:
            parts.append(Div(cls="card card-flat empty")(P("Sin resultados.")))
        if more_clicked:   # mantener sincronizado el campo del formulario
            parts.append(Input(id="top_k", name="top_k", type="hidden", value=str(top_k),
                               hx_swap_oob="true"))
        return Div(*parts)

    @rt("/", methods=["get"])
    def home(query: str = "", mode: str = "hybrid", top_k: int = 10):
        top_k = max(1, min(top_k, MAX_TOP_K))
        return layout("Buscar", Div(
            Div(cls="hero")(H1("Búsqueda híbrida de texto"),
                            P("Texto exacto (FTS5/BM25) y semántica (embeddings), fusionados con RRF.")),
            search_form(query, mode, top_k),
            Div(id="results")(results_view(query, mode, top_k, record=True))), active="search")

    @rt("/results", methods=["get"])
    def results(htmx: HtmxHeaders, query: str = "", mode: str = "hybrid", top_k: int = 10):
        top_k = max(1, min(top_k, MAX_TOP_K))
        trig = htmx.trigger or ""
        # el historial solo registra envíos explícitos, no cada pulsación del modo "en vivo"
        record = trig in ("search-form", "")
        frag = results_view(query, mode, top_k, record=record, more_clicked=(trig == "more"))
        url = "/?" + urlencode({"query": query, "mode": mode, "top_k": top_k}) if query.strip() else "/"
        return frag, HtmxResponseHeaders(replace_url=url)

    # --- visor de documento ---
    @rt("/doc", methods=["get"])
    def viewer(path: str, start: int = 1, end: int = 1, q: str = "",
            lo: Optional[int] = None, hi: Optional[int] = None):
        if path not in indexed_paths():
            raise HTTPException(404, "Ese documento no está en el índice.")
        start, end = max(1, start), max(start, end)
        lo = max(1, lo if lo is not None else start - VIEW_CONTEXT)
        hi = hi if hi is not None else end + VIEW_CONTEXT
        hi = min(hi, lo + VIEW_MAX)
        try:
            rows = read_line_range(path, lo, hi)
        except OSError as e:
            return layout("Documento", Div(H2("No se pudo abrir el fichero"),
                                           P(str(e), cls="notice notice-error")))
        rx = term_regex(query_terms(q))
        first_hit = max(lo, start)
        pm = service.page_map(path)
        breaks = ({ln: p for p, ln in pm.page_starts_in(lo, lo + len(rows))} if pm else {})
        lines = []
        for i, row in enumerate(rows):
            n = lo + i
            if n in breaks and n != 1:
                lines.append(Div(f"— {cite_label(pm.label(breaks[n]))} —", cls="pgbrk"))
            lines.append(Div(cls="ln hit" if start <= n <= end else "ln",
                             **({"id": "hit"} if n == first_hit and start <= first_hit <= end else {}))(
                             Span(str(n), cls="n"), Span(*highlight(row, rx))))

        def nav_link(label, a, b):
            return A(label, cls="btn btn-secondary", href="/doc?" + urlencode(
                {"path": path, "start": start, "end": end, "q": q, "lo": a, "hi": b}))
        nav = []
        if lo > 1:
            nav.append(nav_link(f"↑ {VIEW_PAGE} líneas anteriores", max(1, lo - VIEW_PAGE), hi))
        if len(rows) >= hi - lo + 1:
            nav.append(nav_link(f"↓ {VIEW_PAGE} líneas siguientes", lo, hi + VIEW_PAGE))
        back = A("← Resultados", cls="btn btn-ghost",
                 href="/?" + urlencode({"query": q}) if q else "/")
        return layout("Documento", Div(
            H3(display(path)),
            P(f"Líneas {lo}–{lo + len(rows) - 1} · resultado en {start}–{end}"
              + (f" · {cite_label(pm.range_label(start, end)[2])}" if pm else ""), cls="summary"),
            Div(cls="viewer-nav")(back, *nav),
            Div(cls="viewer")(*lines),
            Div(cls="viewer-nav")(*nav)))

    # --- índice ---
    def job_panel():
        s = job.snapshot()
        poll = dict(hx_get="/index/panel", hx_trigger="every 1s", hx_swap="outerHTML") if s["running"] else {}
        if s["running"]:
            pct = Progress(value=str(s["done"]), max=str(s["total"])) if s["total"] else Progress()
            label = f"{s['phase']}… {s['done']}/{s['total']}" if s["total"] else f"{s['phase']}…"
            body = [P(f"Indexando {display(s['path'])}", cls="summary"), pct, Small(label)]
        elif s["error"]:
            body = [P(f"Error: {s['error']}", cls="notice notice-error")]
        elif s["result"]:
            r = s["result"]
            msg = "sin cambios" if r["skipped"] else "indexado"
            pages = f", {r['pages']} páginas" if r.get("pages") else ""
            body = [P(f"{display(r['path'])}: {msg} ({r['chunks']} chunks{pages}).", cls="notice notice-ok")]
        else:
            body = []
        return Div(*body, id="job", **poll)

    def index_page(error: str = ""):
        docs = service.db.list_documents()
        sem = "activa" if service.semantic_available else "no disponible (chromadb no instalado)"
        def pages_cell(d):
            if not d.get("pages"):
                return "—"
            if d.get("page_offset") is None:
                return f"{d['pages']} · desfase desconocido"
            how = "manual" if d.get("page_offset_source") == "manual" else "detectado"
            return f"{d['pages']} · desfase {d['page_offset']} ({how})"
        rows = [Tr(Td(A(display(d["path"]), href="/doc?" + urlencode({"path": d["path"]}))),
                   Td(pages_cell(d), cls="num"), Td(str(d["chunks"]), cls="num")) for d in docs]
        return layout("Índice", Div(
            H2("Índice"),
            P(f"{len(docs)} documento(s) · {service.db.count_chunks()} chunks · búsqueda semántica {sem}",
              cls="summary"),
            P(error, cls="notice notice-error") if error else "",
            Form(cls="search-form", action="/index", method="post")(
                Input(name="path", type="text", value=target, placeholder="ruta del fichero", required=True,
                      cls="grow"),
                Input(name="max_chars", type="number", value="1000", min="100", max="4000",
                      step="100", title="Tamaño máximo del chunk (caracteres)", style="width:100px;"),
                Label(Input(name="force", type="checkbox", value="1"), " Forzar", cls="checkline"),
                Button("Indexar", type="submit", cls="btn btn-primary")),
            Small(f"Solo se admiten ficheros dentro de {allowed}"),
            job_panel(),
            Table(Thead(Tr(Th("Documento"), Th("Páginas", style="text-align:right"), Th("Chunks", style="text-align:right"))), Tbody(*rows),
                  cls="docs") if rows else P("Sin documentos indexados.", cls="summary")), active="index")

    @rt("/index", methods=["get"])
    def index_get():
        return index_page()

    @rt("/index", methods=["post"])
    def index_post(path: str = "", max_chars: int = 1000, force: str = ""):
        path = os.path.abspath(path) if path else ""
        if not path or not is_allowed(path):
            return index_page("Ruta no permitida (fuera del directorio autorizado).")
        if not os.path.isfile(path):
            return index_page(f"No existe el fichero: {path}")
        max_chars = max(100, min(max_chars, 4000))
        if not job.start(service, path, max_chars, force=bool(force)):
            return index_page("Ya hay un indexado en curso.")
        return RedirectResponse("/index", status_code=303)

    @rt("/index/panel", methods=["get"])
    def index_panel():
        return job_panel()

    @rt("/status", methods=["get"])
    def status():
        return RedirectResponse("/index", status_code=307)

    if autoindex and target and os.path.isfile(target):
        job.start(service, target, max_chars=1000, force=False)

    app.state_job = job   # acceso desde los tests
    return app


def create_app_from_env():
    service = SearchService(create=True)
    target = os.path.abspath(os.environ["SEARCH_TARGET"]) if os.environ.get("SEARCH_TARGET") else ""
    return create_app(service, allowed_dir=os.environ.get("SEARCH_ALLOWED_DIR"), target=target)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app_from_env(), host="127.0.0.1", port=5001)
