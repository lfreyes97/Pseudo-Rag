"""Conjunto de scripts para buscar textos en ficheros de texto extensos.

Módulos disponibles:
- search_basic: búsqueda literal de patrones.
- search_regex: búsqueda con expresiones regulares.
- search_fuzzy: búsqueda difusa (fuzzy) tolerante a errores.
- search_context: búsqueda con contexto de líneas circundantes.
- search_parallel: búsqueda paralela en múltiples ficheros.
- search_index: índice invertido para búsquedas rápidas.
- search_interactive: interfaz interactiva por consola.
- search_engine: API programática (SearchEngine) para pipelines de IA.
- pipeline: punto de entrada JSON (stdin/--config) para pipelines de IA.
- utils: utilidades compartidas.

Uso como biblioteca:
    from search_engine import SearchEngine
    eng = SearchEngine(root="/data", all_text=True)
    res = eng.search("pacto", mode="regex", ignore_case=True)
"""