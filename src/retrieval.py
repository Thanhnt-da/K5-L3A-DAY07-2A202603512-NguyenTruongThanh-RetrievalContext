"""Day 7 retrieval methods over the Day 6 PostgreSQL + pgvector index (strategy B rows).

Methods (each returns chunks in the Day 7 contract: id, text, source_id, source, page, metadata, score, rank):
- dense    : OpenAI text-embedding-3-small query vector, exact cosine ranking in pgvector (Day 6 index)
- lexical  : PostgreSQL full-text search, English stemming, question words OR-ed, ranked by ts_rank_cd
- hybrid   : Reciprocal Rank Fusion of dense and lexical rankings (weight w on dense, 1-w on lexical)
A chapter filter (strategy C) is applied in SQL when given. Errors are raised, never replaced by fake results.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

INDEX_STRATEGY = "B"            # Day 6 paragraph chunks, one page per chunk
EMBED_MODEL = "text-embedding-3-small"
DIMENSIONS = 1536
SOURCE_ID = "openstax-sociology-3e"
COLS = "chunk_id, document_id, source, page, page_end, printed_page, chapter, section, section_title, content"
FILTERABLE = {"chapter": "chapter", "section": "section"}


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.8g}" for x in v) + "]"


class Day6Index:
    """Connection to the Day 6 table + OpenAI query embeddings (cached in Day 6's embedding_cache)."""

    def __init__(self, database_url: str | None = None, strategy: str = INDEX_STRATEGY) -> None:
        self.url = database_url or os.getenv("DATABASE_URL")
        if not self.url:
            raise RuntimeError("DATABASE_URL missing (.env)")
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY missing (.env)")
        self.strategy = strategy
        self.client = OpenAI(max_retries=5, timeout=60)
        self.embed_tokens = 0
        self.embed_calls = 0
        with self._conn() as conn:
            n = conn.execute("SELECT count(*) FROM chunks WHERE strategy = %s", (strategy,)).fetchone()[0]
            dims = conn.execute("SELECT atttypmod FROM pg_attribute WHERE attrelid = 'chunks'::regclass "
                                "AND attname = 'embedding'").fetchone()[0]
        if n == 0:
            raise RuntimeError(f"Day 6 index has no rows for strategy {strategy}")
        if dims != DIMENSIONS:
            raise RuntimeError(f"index is vector({dims}), query model gives {DIMENSIONS}")
        self.size = n

    def _conn(self) -> psycopg.Connection:
        return psycopg.connect(self.url, connect_timeout=5)

    # ---------------------------------------------------------------- embeddings
    def embed(self, text: str) -> list[float]:
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        with self._conn() as conn:
            row = conn.execute("SELECT embedding::text FROM embedding_cache WHERE model = %s AND text_hash = %s",
                               (EMBED_MODEL, key)).fetchone()
            if row:
                return json.loads(row[0])
            resp = self.client.embeddings.create(model=EMBED_MODEL, input=[text])
            self.embed_calls += 1
            self.embed_tokens += resp.usage.total_tokens
            vec = resp.data[0].embedding
            if len(vec) != DIMENSIONS:
                raise RuntimeError(f"expected {DIMENSIONS} dims, got {len(vec)}")
            conn.execute("INSERT INTO embedding_cache (model, text_hash, embedding) VALUES (%s, %s, %s::vector) "
                         "ON CONFLICT DO NOTHING", (EMBED_MODEL, key, _vec(vec)))
            return vec

    # ---------------------------------------------------------------- helpers
    def _where(self, filters: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
        where, params = ["strategy = %(strategy)s"], {"strategy": self.strategy}
        for i, (k, v) in enumerate((filters or {}).items()):
            if k not in FILTERABLE:
                raise ValueError(f"filter {k!r} not allowed")
            where.append(f"{FILTERABLE[k]} = %(f{i})s")
            params[f"f{i}"] = v
        return " AND ".join(where), params

    def _rows(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            names = [d.name for d in cur.description]
            return [dict(zip(names, r)) for r in cur.fetchall()]

    @staticmethod
    def _to_contract(rows: list[dict[str, Any]], method: str) -> list[dict[str, Any]]:
        out = []
        for rank, r in enumerate(rows, start=1):
            out.append({"id": r["chunk_id"], "text": r["content"], "source_id": r["document_id"],
                        "source": r["source"], "page": r["page"], "rank": rank, "method": method,
                        "score": float(r["score"]),
                        "metadata": {"chapter": r["chapter"], "section": r["section"],
                                     "section_title": r["section_title"], "printed_page": r["printed_page"],
                                     **{k: r[k] for k in ("dense_rank", "lexical_rank") if k in r}}})
        return out

    # ---------------------------------------------------------------- methods
    def dense(self, query: str, top_k: int = 3, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        where, params = self._where(filters)
        params.update(qv=_vec(self.embed(query)), k=top_k)
        sql = (f"SELECT {COLS}, 1 - (embedding <=> %(qv)s::vector) AS score FROM chunks WHERE {where} "
               "ORDER BY embedding <=> %(qv)s::vector, chunk_id LIMIT %(k)s")
        return self._to_contract(self._rows(sql, params), "dense")

    def lexical(self, query: str, top_k: int = 3, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        where, params = self._where(filters)
        params.update(qt=query, k=top_k)
        sql = (f"WITH q AS (SELECT NULLIF(replace(plainto_tsquery('english', %(qt)s)::text, '&', '|'), '')::tsquery AS tsq) "
               f"SELECT {COLS}, ts_rank_cd(content_tsv, q.tsq) AS score FROM chunks, q "
               f"WHERE {where} AND q.tsq IS NOT NULL AND content_tsv @@ q.tsq "
               "ORDER BY score DESC, chunk_id LIMIT %(k)s")
        return self._to_contract(self._rows(sql, params), "lexical")

    def hybrid(self, query: str, top_k: int = 3, filters: dict[str, Any] | None = None,
               dense_weight: float = 0.5, candidates: int = 50, rrf_k: int = 60) -> list[dict[str, Any]]:
        if not 0 <= dense_weight <= 1:
            raise ValueError("dense_weight must be in [0, 1]")
        dense = self.dense(query, candidates, filters)
        lexical = self.lexical(query, candidates, filters)
        fused: dict[str, dict[str, Any]] = {}
        for weight, results, key in ((dense_weight, dense, "dense_rank"), (1 - dense_weight, lexical, "lexical_rank")):
            for r in results:
                entry = fused.setdefault(r["id"], {**r, "fused": 0.0, "metadata": dict(r["metadata"])})
                entry["fused"] += weight / (rrf_k + r["rank"])
                entry["metadata"][key] = r["rank"]
        ranked = sorted(fused.values(), key=lambda r: (-r["fused"], r["id"]))[:top_k]
        for rank, r in enumerate(ranked, start=1):
            r.update(rank=rank, method="hybrid", score=round(r["fused"], 6))
            r.pop("fused")
        return ranked

    def search(self, method: str, query: str, top_k: int = 3, filters: dict[str, Any] | None = None,
               **options) -> list[dict[str, Any]]:
        if method == "dense":
            return self.dense(query, top_k, filters)
        if method == "lexical":
            return self.lexical(query, top_k, filters)
        if method == "hybrid":
            return self.hybrid(query, top_k, filters, **options)
        raise ValueError(f"unknown method {method!r}")
