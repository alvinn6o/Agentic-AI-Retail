"""RAGTool — retrieves SOP / policy docs from local embeddings store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import get_logger

logger = get_logger(__name__)


class RAGTool:
    """
    Simple local RAG over markdown/text documents in data/docs/.
    Embeddings are computed on first load and cached in-memory.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._chunks: list[dict[str, Any]] = []
        self._embeddings: np.ndarray | None = None
        self._model = None
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return

        docs_path = self.settings.docs_path
        if not docs_path.exists():
            logger.warning("rag_tool.docs_path_missing", path=str(docs_path))
            self._loaded = True
            return

        # Load and chunk documents
        chunks: list[dict[str, Any]] = []
        for doc_file in docs_path.glob("**/*.md"):
            text = doc_file.read_text(encoding="utf-8")
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            for i, para in enumerate(paragraphs):
                chunks.append({
                    "source": str(doc_file.relative_to(docs_path)),
                    "chunk_id": i,
                    "text": para,
                })

        if not chunks:
            logger.info("rag_tool.no_docs_found")
            self._loaded = True
            return

        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(self.settings.embedding_model)
            texts = [c["text"] for c in chunks]
            embeddings = model.encode(texts, show_progress_bar=False)
            self._chunks = chunks
            self._embeddings = embeddings
            self._model = model
            logger.info("rag_tool.loaded", num_chunks=len(chunks))
        except Exception as exc:
            logger.warning("rag_tool.embedding_failed", error=str(exc))

        self._loaded = True

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Return top-k relevant passages with source citations."""
        self._ensure_loaded()

        if not self._chunks or self._embeddings is None or self._model is None:
            return []

        query_vec = self._model.encode([query])
        # Cosine similarity
        norms = np.linalg.norm(self._embeddings, axis=1, keepdims=True)
        normed = self._embeddings / (norms + 1e-9)
        query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-9)
        scores = (normed @ query_norm.T).squeeze()

        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in top_indices:
            chunk = self._chunks[idx]
            results.append({
                "source": chunk["source"],
                "chunk_id": chunk["chunk_id"],
                "text": chunk["text"],
                "score": float(scores[idx]),
            })
        return results
