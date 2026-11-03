#!/usr/bin/env python3
"""Interfaz interactiva de búsqueda en consola (estilo REPL).

Permite cambiar patrón, directorio, opciones y ejecutar búsquedas sin salir.
Comandos:
    :pattern TEXTO        cambiar patrón
    :dir RUTA             cambiar directorio/fichero
    :regex on|off
    :case on|off
    :context N
    :ext .txt,.log
    :max N
    :help
    :quit
    (cualquier otra línea se trata como patrón a buscar)
"""

from __future__ import annotations

import os
import sys
from typing import List

from .utils import discover_files
from .search_basic import search_file as basic_search
from .search_regex import search_file as regex_search
from .search_context import search_file as context_search


class Session:
    def __init__(self):
        self.pattern = ""
        self.target = "."
        self.regex = False
        self.ignore_case = True
        self.context = 0
        self.ext = None
        self.all_text = False
        self.max_results = 50
        self.files: List[str] = []

    def refresh_files(self):
        if os.path.isfile(self.target):
            self.files = [self.target]
        else:
            exts = [e.strip() for e in self.ext.split(",")] if self.ext else None
            self.files = discover_files(self.target, extensions=exts, all_text=self.all_text)

    def run(self, pattern: str = None):
        if pattern is not None:
            self.pattern = pattern
        if not self.pattern:
            print("Patrón vacío. Usa :pattern TEXTO")
            return
        self.refresh_files()
        all_matches = []
        for f in self.files:
            if self.regex:
                try:
                    ms = regex_search(f, self.pattern, flags=0 if not self.ignore_case else 0)
                    # aplicar ignore_case manualmente recreando flags
                    import re
                    flags = re.IGNORECASE if self.ignore_case else 0
                    ms = regex_search(f, self.pattern, flags=flags)
                except Exception as e:
                    print(f"Error regex: {e}")
                    return
            elif self.context and self.context > 0:
                ms = context_search(f, self.pattern, before=self.context, after=self.context,
                                   regex=False, ignore_case=self.ignore_case)
            else:
                ms = basic_search(f, self.pattern, ignore_case=self.ignore_case)
            all_matches.extend(ms)

        # imprimir
        shown = 0
        for m in all_matches:
            if shown >= self.max_results:
                print(f"... ({len(all_matches) - shown} más)")
                break
            print(f"{m.path}:{m.line_no}: {m.line}")
            shown += 1
        print(f"\n[{len(all_matches)} coincidencia(s) en {len(self.files)} fichero(s)]")


HELP = """Comandos:
  :pattern TEXTO     establecer patrón de búsqueda
  :dir RUTA          directorio o fichero objetivo
  :regex on|off      activar/desactivar regex
  :case on|off       ignorar mayúsculas (on=ignorar)
  :context N         líneas de contexto (0=sin contexto)
  :ext .txt,.log     filtrar extensiones
  :max N             máximo de resultados mostrados
  :files             listar ficheros objetivo
  :help              esta ayuda
  :quit              salir
  (línea normal)     se usa como patrón y se busca inmediatamente
"""


def main():
    sess = Session()
    print("Búsqueda interactiva. Escribe :help para ayuda.")
    while True:
        try:
            line = input("search> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.startswith(":"):
            parts = line[1:].split(None, 1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""
            if cmd in ("quit", "exit", "q"):
                break
            elif cmd == "help":
                print(HELP)
            elif cmd == "pattern":
                sess.pattern = arg
                print(f"Patrón: {sess.pattern!r}")
            elif cmd == "dir":
                sess.target = arg or "."
                sess.refresh_files()
                print(f"Objetivo: {sess.target} ({len(sess.files)} ficheros)")
            elif cmd == "regex":
                sess.regex = arg.lower() in ("on", "1", "true", "yes")
                print(f"Regex: {sess.regex}")
            elif cmd == "case":
                sess.ignore_case = arg.lower() in ("on", "1", "true", "yes")
                print(f"Ignorar mayúsculas: {sess.ignore_case}")
            elif cmd == "context":
                sess.context = int(arg) if arg else 0
                print(f"Contexto: {sess.context}")
            elif cmd == "ext":
                sess.ext = arg or None
                sess.refresh_files()
                print(f"Extensiones: {sess.ext}")
            elif cmd == "alltext":
                sess.all_text = arg.lower() in ("on", "1", "true", "yes")
                sess.refresh_files()
                print(f"All-text: {sess.all_text} ({len(sess.files)} ficheros)")
            elif cmd == "max":
                sess.max_results = int(arg) if arg else 50
                print(f"Máx resultados: {sess.max_results}")
            elif cmd == "files":
                for f in sess.files[:50]:
                    print(f)
                if len(sess.files) > 50:
                    print(f"... y {len(sess.files)-50} más")
            else:
                print(f"Comando desconocido: {cmd}. Usa :help")
        else:
            sess.run(line)


if __name__ == "__main__":
    main()
