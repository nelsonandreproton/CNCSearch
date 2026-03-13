"""Embedding generation and semantic similarity search."""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from ..config import Config
    from ..database.repository import Repository

logger = logging.getLogger(__name__)


class SearchService:
    def __init__(self, config: "Config", repo: "Repository") -> None:
        self.config = config
        self.repo = repo
        self._local_model = None  # lazy-loaded only if provider=local

    # ── Public API ────────────────────────────────────────────────────────────

    def embed_and_store(self, cantico_id: int, title: str, lyrics: str) -> None:
        """Generate embedding for title+lyrics and persist it."""
        text = f"{title}\n{lyrics}"
        emb = self._embed([text])[0]
        self.repo.update_embedding(cantico_id, _to_blob(emb))

    def reindex_all(self) -> int:
        """Re-generate embeddings for every cantico. Returns count processed."""
        canticos = self.repo.get_canticos()
        if not canticos:
            return 0

        texts = [f"{c.title}\n{c.lyrics}" for c in canticos]
        embeddings = self._embed(texts)

        for cantico, emb in zip(canticos, embeddings):
            self.repo.update_embedding(cantico.id, _to_blob(emb))

        logger.info("Reindexed %d canticos", len(canticos))
        return len(canticos)

    def search(
        self,
        query: str,
        top_n: int,
        min_similarity: float,
        moment_id: int | None = None,
    ) -> list[dict]:
        """
        Return top_n canticos most similar to query, above min_similarity.

        Each result: {id, title, sheet_url, moment_id, similarity (0-1)}
        """
        query_emb = self._embed([query])[0]
        rows = self.repo.get_all_for_search()

        results = []
        for cid, title, sheet_url, mid, blob in rows:
            if blob is None:
                continue
            if moment_id is not None and mid != moment_id:
                continue
            emb = _from_blob(blob)
            sim = _cosine_similarity(query_emb, emb)
            if sim >= min_similarity:
                results.append(
                    {
                        "id": cid,
                        "title": title,
                        "sheet_url": sheet_url,
                        "moment_id": mid,
                        "similarity": sim,
                    }
                )

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_n]

    # ── Embedding providers ───────────────────────────────────────────────────

    def _embed(self, texts: list[str]) -> list[np.ndarray]:
        if self.config.embedding_provider == "local":
            return self._embed_local(texts)
        return self._embed_jina(texts)

    def _embed_jina(self, texts: list[str]) -> list[np.ndarray]:
        import httpx

        response = httpx.post(
            "https://api.jina.ai/v1/embeddings",
            headers={"Authorization": f"Bearer {self.config.jina_api_key}"},
            json={
                "model": "jina-embeddings-v3",
                "input": texts,
                "task": "text-matching",
                "dimensions": 1024,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return [
            np.array(item["embedding"], dtype=np.float32)
            for item in data["data"]
        ]

    def _embed_local(self, texts: list[str]) -> list[np.ndarray]:
        if self._local_model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is not installed. "
                    "Add it to requirements.txt or run: pip install sentence-transformers>=3.0.0"
                ) from exc

            logger.info("Loading local embedding model (first time, may take a moment)…")
            self._local_model = SentenceTransformer(
                "paraphrase-multilingual-mpnet-base-v2"
            )
        embeddings = self._local_model.encode(texts, convert_to_numpy=True)
        return [emb.astype(np.float32) for emb in embeddings]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _to_blob(emb: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, emb)
    return buf.getvalue()


def _from_blob(blob: bytes) -> np.ndarray:
    return np.load(io.BytesIO(blob))
