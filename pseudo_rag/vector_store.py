"""Vector store basado en ChromaDB para búsqueda semántica."""

from __future__ import annotations

from typing import List, Dict, Any, Optional

import importlib.util


def chroma_available() -> bool:
    return importlib.util.find_spec("chromadb") is not None


class VectorStore:
    def __init__(self, persist_dir: str = "./chroma_db", collection: str = "chunks"):
        import chromadb
        from chromadb.config import Settings
        self.client = chromadb.PersistentClient(path=persist_dir,
                                             settings=Settings(anonymized_telemetry=False))
        self.collection = self.client.get_or_create_collection(
            name=collection,
            metadata={"hnsw:space": "cosine"},
        )

    def count(self) -> int:
        return self.collection.count()

    def add(self, ids: List[str], documents: List[str], metadatas: List[Dict[str, Any]]):
        if not ids:
            return
        self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def has_path(self, path: str) -> bool:
        return bool(self.collection.get(where={"path": path}, limit=1).get("ids"))

    def delete_path(self, path: str):
        """Elimina todos los chunks de un fichero (evita huérfanos al reindexar)."""
        self.collection.delete(where={"path": path})

    def query(self, text: str, top_k: int = 10) -> List[Dict[str, Any]]:
        if self.count() == 0:
            return []
        res = self.collection.query(query_texts=[text], n_results=top_k)
        out = []
        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        for i, _id in enumerate(ids):
            meta = metas[i] if i < len(metas) else {}
            out.append({
                "id": _id,
                "text": docs[i] if i < len(docs) else "",
                "metadata": meta,
                "distance": dists[i] if i < len(dists) else 1.0,
                "score": 1.0 - (dists[i] if i < len(dists) else 1.0),
            })
        return out

    def reset(self):
        try:
            self.client.delete_collection(self.collection.name)
        except Exception:
            pass
        self.collection = self.client.get_or_create_collection(
            name=self.collection.name,
            metadata={"hnsw:space": "cosine"},
        )
