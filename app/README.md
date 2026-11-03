# App web (FastHTML + HTMX)

La lógica vive en `pseudo_rag/web/app.py`; este directorio solo contiene el wrapper `main.py`
y los datos existentes (`search.db`, `chroma_db/`), que se usan como `PRAG_HOME`.

```bash
cd app && python main.py      # http://localhost:5001
# o, desde la raíz:  uv run prag serve [--port 5001] [--target FICHERO]
```

## Qué ofrece
- **Búsqueda en vivo** (HTMX, con retardo de 350 ms) y modos híbrida / textual / semántica.
  Sin JavaScript el formulario sigue funcionando (GET). `/` acepta `?query=…&mode=…&top_k=…`.
- **Resaltado** de los términos de la consulta (sin distinguir mayúsculas ni acentos) y botón
  «Mostrar más».
- **Visor** (`/doc`): abre el documento en la línea del resultado, con contexto y navegación.
  Solo abre ficheros que están en el índice.
- **Historial** clicable. Solo registra envíos explícitos (Enter / botón), no cada pulsación.
- **Índice** (`/index`): indexado en segundo plano con barra de progreso y lista de documentos.
  `/status` redirige aquí.
- `/` enfoca el cuadro de búsqueda; modo oscuro automático.

## Configuración
- `SEARCH_TARGET`: fichero a indexar al arrancar (incremental: no reindexa si no cambió).
- `SEARCH_ALLOWED_DIR`: directorio donde se permite indexar desde la UI (por defecto, el del
  target o el cwd).
- htmx se carga desde un CDN: sin conexión la búsqueda en vivo no funciona, pero sí el formulario.

Ver el README de la raíz para el CLI `prag`.
