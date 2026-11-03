# Pseudo-RAG

Búsqueda de texto en ficheros grandes, en tres capas:

| Capa | Comando | Requiere |
|---|---|---|
| Streaming sin índice (grep, regex, fuzzy, contexto) | `prag grep` | solo biblioteca estándar |
| Índice FTS5 + BM25 | `prag index` / `prag search --mode text` | `sqlalchemy`, `pydantic` |
| Semántica (ChromaDB) y RRF híbrido | `prag search --mode semantic\|hybrid` | extra `[semantic]` |

Si falta `chromadb`, `hybrid` cae a texto con un aviso; `semantic` da error claro.

## Entorno (uv)

```bash
uv sync --all-extras          # crea .venv con todo (semántica + web + pytest)
uv sync                       # solo el núcleo (grep, index, search en texto) + pytest
uv run prag grep -i pacto ~/docs --all-text
uv run pytest

uv tool install --all-extras -e .   # opcional: `prag` disponible globalmente
```

`uv.lock` fija las versiones; `.python-version` fija Python. Extras: `semantic` (chromadb),
`web` (fasthtml + uvicorn), `all`.
Sin instalar nada: `PYTHONPATH=. python -m pseudo_rag ...` o los scripts de `scripts/`.

## Uso

```bash
prag grep -i "pacto" ~/docs --all-text            # sin índice
prag grep -E "^== .*" notas.typ -C 2              # regex + contexto
prag grep -z "covennt" libro.txt                  # difuso
prag index ~/docs --all-text                      # crea .prag/ aquí; reindexa solo lo que cambió
prag index libro.txt --max-chars 800 --overlap 3  # ajustar el chunking
prag search "common grace" -k 5                   # híbrida por defecto
prag search "pacto" --mode text --doc bibliografia
prag status | prag history
prag serve --port 5001                            # UI web sobre el mismo índice
prag repl
```

## Para pipelines / agentes

`--json` (un objeto) o `--jsonl` (un resultado por línea), en `grep` y `search`.
Errores en JSON: `{"ok": false, "error": "..."}`. Las rutas del JSON son absolutas.

Códigos de salida (como grep): `0` hay resultados · `1` sin resultados · `2` error.

## Páginas (texto de `pdftotext`)

El flujo pensado: PDF → `pdftotext` → `prag`. Las páginas viajan dentro del propio texto, así que
no hace falta etiquetar nada a mano.

```bash
pdftotext libro.pdf libro.txt            # NO uses -nopgbrk: el salto de página (\f) marca las páginas
prag index libro.txt                     # detecta el desfase de numeración
prag index libro.txt --page-offset 12    # o fíjalo (nº impreso = página del PDF − 12); se conserva
prag search "analogy of being" --doc libro        # resultados con «p. 134» / «pp. 134–135»
prag page "frase copiada del libro" --doc libro   # en qué página está una cita
prag status                              # páginas y desfase de cada documento
```

- **Página impresa = página del PDF − desfase.** El desfase se detecta con los números sueltos que
  `pdftotext` deja en el pie o la cabecera de cada página (hace falta que un tercio de las páginas
  lo confirme y que no haya otro desfase casi igual de votado). Si no es fiable, se avisa y las
  páginas se citan como «pdf N» para no hacer pasar una página de PDF por una impresa; entonces usa
  `--page-offset`.
- **Qué página se cita:** la de las líneas que contienen los términos de la consulta, no la de los
  bordes del chunk (que pueden ser el pie de la página anterior). Si el rango incluye páginas sin
  numerar, se cita en páginas del PDF.
- `prag page` tolera que la cita venga con otro reflujo de líneas, palabras partidas con guion al
  final de línea y errores de OCR (no así dígitos: `zafiro7` y `zafiro3` son distintas). Sale con
  código 1 si la coincidencia es débil (`--min-coverage`, 0.5 por defecto).
- Un texto **sin** `\f` se indexa igual, pero sin páginas. Si tu conversión los elimina (como pasó
  con `bibliografia.typ`), vuelve a generar el `.txt` desde el PDF.
- En la web: «p. N» en cada resultado y separadores de página en el visor.

## Chunking

Los chunks se miden en **caracteres** (`--max-chars`, 1000 por defecto), no en líneas: el
embedding por defecto de Chroma trunca a 256 tokens (~1000 caracteres), y un chunk más
largo solo se indexa por su principio. Reglas (`pseudo_rag/chunking.py`):

- se corta antes de un encabezado (`= Título` de Typst, `# Título` de Markdown) y tras un
  párrafo, cuando el chunk ya tiene un tamaño razonable;
- una línea más larga que el máximo se parte por frases (conserva su número de línea);
- cada chunk repite al inicio las últimas `--overlap` líneas (2) del anterior;
- en los resultados, chunks vecinos que repiten el mismo pasaje se colapsan en uno.

Cambiar `--max-chars`/`--overlap` (o la versión del algoritmo) reindexa el fichero aunque no
haya cambiado. Los índices creados con el chunking anterior (por líneas) se reindexan solos
la próxima vez que ejecutes `prag index`.

## Carpeta de datos

`.prag/` (`search.db` + `chroma_db/`), buscada hacia arriba desde el cwd como `.git/`,
o `PRAG_HOME`. El CLI y la web comparten el índice. `app/` también vale como `PRAG_HOME`
(es lo que usa `app/main.py`, así se conservan los datos anteriores).

## Estructura

```
pseudo_rag/
  textsearch/   motor de grep en streaming (stdlib)   ← scripts/ son wrappers de esto
  chunking.py   partición en chunks (stdlib)
  pages.py      páginas a partir de los \\f de pdftotext, desfase, etiquetas (stdlib)
  service.py    indexado incremental, búsqueda, RRF
  db.py         SQLite + FTS5       vector_store.py  Chroma (opcional)
  cli.py        comando prag        web/app.py       UI FastHTML
scripts/        wrappers con los mismos argumentos de siempre
app/main.py     wrapper de la web (usa app/ como PRAG_HOME)
```

Web: ver `app/README.md` (búsqueda en vivo, visor, indexado con progreso).
