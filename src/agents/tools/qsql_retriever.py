"""Q-SQL retrieval (Vanna AI / OpenSearch-SQL style).

Loads BIRD train.parquet (or any parquet with `question`, `SQL`,
`evidence`, `db_id` columns), embeds the questions once with
all-MiniLM-L6-v2, caches the embedding matrix to disk, and serves
nearest-neighbour lookups at query time.

Cross-DB retrieval — BIRD's train and dev sets use disjoint database
sets by design, so same-DB neighbours don't exist for Mini-Dev
questions. The model learns BIRD-style SQL idioms (CAST AS REAL,
NULLIF, JOIN conventions) by analogy from training queries on other
schemas.

Singleton-style global instance: build_retriever() returns a cached
QSQLRetriever; tests can call _reset() between fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class QSQLExample:
    question: str
    sql: str
    evidence: str
    db_id: str
    score: float  # cosine similarity, 0–1


class QSQLRetriever:
    """Cross-DB nearest-neighbour retrieval over a Q-SQL pair corpus.

    Loads once, caches embeddings to disk under the same directory as
    the source parquet. Embedding model is the same all-MiniLM-L6-v2
    used elsewhere in the codebase so we don't double-pay GPU memory.
    """

    def __init__(self, parquet_path: Path, cache_dir: Path | None = None) -> None:
        self.parquet_path = Path(parquet_path)
        if not self.parquet_path.exists():
            raise FileNotFoundError(
                f"Q-SQL corpus parquet missing: {self.parquet_path}"
            )
        self.cache_dir = cache_dir or self.parquet_path.parent
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._df: pd.DataFrame | None = None
        self._embeddings: np.ndarray | None = None  # shape: (N, D), L2-normalised
        self._model: SentenceTransformer | None = None

    def _load_model(self) -> SentenceTransformer:
        if self._model is None:
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
        return self._model

    def _load_corpus(self) -> None:
        if self._df is not None and self._embeddings is not None:
            return
        df = pd.read_parquet(self.parquet_path)
        required = {"question", "SQL", "db_id"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(
                f"Q-SQL corpus missing required columns: {missing}"
            )
        if "evidence" not in df.columns:
            df["evidence"] = ""

        cache_file = self.cache_dir / f"{self.parquet_path.stem}.embeddings.npy"
        if cache_file.exists():
            embeddings = np.load(cache_file)
            if embeddings.shape[0] != len(df):
                logger.warning(
                    f"[QSQLRetriever] Cached embeddings shape "
                    f"{embeddings.shape} doesn't match corpus rows "
                    f"{len(df)} — re-embedding."
                )
                embeddings = self._embed_questions(df["question"].tolist())
                np.save(cache_file, embeddings)
        else:
            logger.info(
                f"[QSQLRetriever] Embedding {len(df)} training questions "
                f"(first run; result cached to {cache_file})"
            )
            embeddings = self._embed_questions(df["question"].tolist())
            np.save(cache_file, embeddings)

        self._df = df.reset_index(drop=True)
        self._embeddings = embeddings

    def _embed_questions(self, questions: list[str]) -> np.ndarray:
        model = self._load_model()
        # convert_to_numpy returns float32; normalize_embeddings=True
        # gives us cosine similarity via plain dot product.
        emb = model.encode(
            questions,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).astype(np.float32)
        return emb

    def retrieve(
        self,
        question: str,
        k: int = 3,
        min_score: float = 0.0,
        exclude_db_ids: Iterable[str] | None = None,
    ) -> list[QSQLExample]:
        """Return top-K cosine-similar Q-SQL pairs.

        Args:
            question: The user's natural-language question.
            k: Number of neighbours to return.
            min_score: Drop matches whose cosine similarity falls below
                this floor. Useful for filtering out off-topic
                neighbours when the question has no good analog in the
                corpus — those tend to mislead the model more than help.
            exclude_db_ids: If set, drop matches whose `db_id` is in
                this set. Useful for ensuring we never accidentally
                retrieve same-DB neighbours (would be contamination in
                BIRD's standard protocol).
        """
        if not question or k <= 0:
            return []
        self._load_corpus()
        assert self._df is not None and self._embeddings is not None

        model = self._load_model()
        q_emb = model.encode(
            [question],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).astype(np.float32)
        scores = (self._embeddings @ q_emb.T).ravel()

        # Argsort descending; overshoot k so we can filter then trim.
        excluded = set(exclude_db_ids or ())
        overshoot = k * 4 if (excluded or min_score > 0.0) else k
        idx = np.argpartition(-scores, min(overshoot, len(scores) - 1))[:overshoot]
        # Sort the overshoot window by exact score (argpartition isn't sorted)
        idx = idx[np.argsort(-scores[idx])]

        out: list[QSQLExample] = []
        for i in idx:
            score = float(scores[i])
            if score < min_score:
                # idx is sorted descending — once we're below the floor,
                # nothing further in this window can pass.
                break
            row = self._df.iloc[int(i)]
            if row["db_id"] in excluded:
                continue
            out.append(
                QSQLExample(
                    question=str(row["question"]),
                    sql=str(row["SQL"]),
                    evidence=str(row.get("evidence") or ""),
                    db_id=str(row["db_id"]),
                    score=score,
                )
            )
            if len(out) >= k:
                break
        return out


_retriever_cache: QSQLRetriever | None = None


def build_retriever(
    parquet_path: Path | None = None,
) -> QSQLRetriever:
    """Singleton-style accessor. First call loads + embeds; subsequent
    calls return the cached instance."""
    global _retriever_cache
    if _retriever_cache is not None:
        return _retriever_cache
    default_path = (
        Path(__file__).resolve().parents[3]
        / "bench"
        / "bird_data"
        / "train"
        / "train.parquet"
    )
    path = parquet_path or default_path
    _retriever_cache = QSQLRetriever(path)
    return _retriever_cache


def _reset() -> None:
    """Test helper: discard the cached retriever."""
    global _retriever_cache
    _retriever_cache = None


__all__ = ["QSQLRetriever", "QSQLExample", "build_retriever"]
