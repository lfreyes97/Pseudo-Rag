# Conjunto de scripts de búsqueda de texto

Scripts en Python para buscar textos en ficheros de texto extensos, optimizados
para no cargar ficheros completos en memoria (streaming).

## Scripts

| Script | Descripción |
|---|---|
| `search_basic.py` | Búsqueda literal, por palabra completa, línea completa, contar, listar ficheros. |
| `search_regex.py` | Expresiones regulares (incl. modo multilínea). |
| `search_fuzzy.py` | Búsqueda difusa (Levenshtein) tolerante a errores. |
| `search_context.py` | Búsqueda con contexto (-C/-A/-B) y agrupación de bloques. |
| `search_parallel.py` | Búsqueda paralela con multiprocessing. |
| `search_index.py` | Índice invertido: build / search. |
| `search_interactive.py` | REPL interactivo. |
| `utils.py` | Utilidades compartidas. |

## Formatos soportados

Por defecto se buscan ficheros de texto comunes: `.txt`, `.md`, `.typ`, `.html`,
`.tex`, `.rst`, `.json`, `.yaml`, `.csv`, código fuente, etc. (ver
`DEFAULT_EXTENSIONS` en `utils.py`).

Para incluir **cualquier fichero de texto** (aunque su extensión no esté en la
lista, p. ej. ficheros sin extensión o formatos nuevos), usa `--all-text`, que
detecta texto por contenido (ausencia de bytes nulos y decodificabilidad).

## Uso rápido

```bash
cd scripts
# búsqueda literal recursiva en md/typ/html/txt
python search_basic.py "pacto" ~/docs --all-text -i

# regex en ficheros Typst
python search_regex.py "=== .* ===" ~/docs --ext .typ

# contexto en Markdown
python search_context.py "## " ~/notes -C 2 --all-text

# paralelo
python search_parallel.py "password" /data --workers 8 --all-text

# índice
python search_index.py build /data --out idx.json --all-text
python search_index.py search "usuario" --index idx.json --show-line

# interactivo
python search_interactive.py
```

## Uso como pipeline de IA

Todos los scripts aceptan `--json` para salida estructurada (JSON) en lugar de
texto humano. Además hay un punto de entrada unificado `pipeline.py` que lee
configuración JSON (stdin o `--config`) y devuelve JSON:

```bash
# vía stdin
echo '{"root":"/data","pattern":"pacto","mode":"basic","all_text":true}' | python pipeline.py

# vía archivo
python pipeline.py --config busqueda.json --pretty

# script individual con JSON
python search_basic.py "pacto" /data --all-text --json
```

Uso como biblioteca Python:

```python
from search_engine import SearchEngine
eng = SearchEngine(root="/data", all_text=True)
res = eng.search("pacto", mode="regex", ignore_case=True, context=2)
# res: list[dict] con keys path, line_no, line, column, matched_text,
#      context_before, context_after
```

Esquema de configuración de `pipeline.py`: ver docstring en `pipeline.py`.

## Dependencias

Solo biblioteca estándar de Python 3.8+.

> La lógica ahora vive en `pseudo_rag/textsearch/`; estos scripts son wrappers con los mismos
> argumentos y siguen funcionando sin instalar nada. Para el índice y la búsqueda semántica, ver `prag` en el README raíz.
