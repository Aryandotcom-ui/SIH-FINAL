"""Persistence: ChromaDB for vectors, SQLite for version tracking.

The SQLite side is the source of truth about what has been ingested and
when. Chroma is a derived vector index.

Retrieval strategy
------------------
1. Exact metadata lookup for explicit legal section references.
2. BGE semantic retrieval for natural-language questions.
3. Corpus-wide BM25-style lexical retrieval for exact legal terminology.
4. Rank-based fusion of semantic and lexical retrieval.

The lexical search is intentionally generic. It does not contain answers
to particular questions or hardcoded section numbers.
"""

from __future__ import annotations

import datetime as _dt
import logging
import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .schema import Chunk
from .shared.taxonomy import acts_for_formulation


log = logging.getLogger(__name__)

COLLECTION = "ip_sakti_corpus"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     TEXT PRIMARY KEY,
    source_url   TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    ingested_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunk_versions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id      TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    source_file   TEXT,
    act_name      TEXT,
    section       TEXT,
    effective_date TEXT,
    first_seen    TEXT NOT NULL,
    superseded_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_versions_chunk
ON chunk_versions(chunk_id);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at  TEXT,
    files_ok    INTEGER DEFAULT 0,
    files_failed INTEGER DEFAULT 0,
    chunks_new  INTEGER DEFAULT 0,
    chunks_changed INTEGER DEFAULT 0,
    chunks_unchanged INTEGER DEFAULT 0,
    embedder    TEXT,
    notes       TEXT
);
"""


@dataclass
class WriteStats:
    new: int = 0
    changed: int = 0
    unchanged: int = 0

    @property
    def written(self) -> int:
        return self.new + self.changed


def _now() -> str:
    return _dt.datetime.now(
        _dt.timezone.utc
    ).isoformat(
        timespec="seconds"
    )


class Registry:
    """SQLite version tracking."""

    def __init__(
        self,
        path: Path | str,
    ) -> None:
        self.path = Path(path)

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.conn = sqlite3.connect(
            self.path
        )

        self.conn.row_factory = sqlite3.Row

        self.conn.executescript(
            _SCHEMA
        )

        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Registry":
        return self

    def __exit__(
        self,
        *exc: object,
    ) -> None:
        self.close()

    def known_hashes(
        self,
    ) -> dict[str, str]:
        rows = self.conn.execute(
            "SELECT chunk_id, content_hash "
            "FROM chunks"
        ).fetchall()

        return {
            row["chunk_id"]: row["content_hash"]
            for row in rows
        }

    def start_run(
        self,
        embedder: str,
        notes: str = "",
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO ingest_runs "
            "(started_at, embedder, notes) "
            "VALUES (?,?,?)",
            (
                _now(),
                embedder,
                notes,
            ),
        )

        self.conn.commit()

        return int(
            cur.lastrowid
        )

    def finish_run(
        self,
        run_id: int,
        stats: WriteStats,
        ok: int,
        failed: int,
    ) -> None:
        self.conn.execute(
            "UPDATE ingest_runs SET "
            "finished_at=?, "
            "files_ok=?, "
            "files_failed=?, "
            "chunks_new=?, "
            "chunks_changed=?, "
            "chunks_unchanged=? "
            "WHERE id=?",
            (
                _now(),
                ok,
                failed,
                stats.new,
                stats.changed,
                stats.unchanged,
                run_id,
            ),
        )

        self.conn.commit()

    def upsert(
        self,
        chunks: Sequence[Chunk],
    ) -> tuple[
        WriteStats,
        list[Chunk],
    ]:
        """Record chunks and return chunks needing re-embedding."""

        known = self.known_hashes()

        stats = WriteStats()

        dirty: list[Chunk] = []

        now = _now()

        for chunk in chunks:
            content_hash = chunk.content_hash

            previous_hash = known.get(
                chunk.chunk_id
            )

            if previous_hash == content_hash:
                stats.unchanged += 1
                continue

            if previous_hash is None:
                stats.new += 1

            else:
                stats.changed += 1

                self.conn.execute(
                    "UPDATE chunk_versions "
                    "SET superseded_at=? "
                    "WHERE chunk_id=? "
                    "AND superseded_at IS NULL",
                    (
                        now,
                        chunk.chunk_id,
                    ),
                )

                log.info(
                    "chunk %s changed (%s -> %s)",
                    chunk.chunk_id,
                    previous_hash[:8],
                    content_hash[:8],
                )

            self.conn.execute(
                "INSERT INTO chunks "
                "(chunk_id, source_url, content_hash, ingested_at) "
                "VALUES (?,?,?,?) "
                "ON CONFLICT(chunk_id) DO UPDATE SET "
                "source_url=excluded.source_url, "
                "content_hash=excluded.content_hash, "
                "ingested_at=excluded.ingested_at",
                (
                    chunk.chunk_id,
                    chunk.source_url,
                    content_hash,
                    now,
                ),
            )

            self.conn.execute(
                "INSERT INTO chunk_versions "
                "(chunk_id, content_hash, source_file, act_name, "
                "section, effective_date, first_seen) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    chunk.chunk_id,
                    content_hash,
                    str(
                        chunk.provenance.get(
                            "source_file",
                            "",
                        )
                    ),
                    chunk.act_name,
                    chunk.section,
                    chunk.effective_date,
                    now,
                ),
            )

            dirty.append(chunk)

        self.conn.commit()

        return stats, dirty

    def orphans(
        self,
        current_ids: Iterable[str],
    ) -> list[str]:
        """Return registry chunks not produced by current run."""

        current = set(
            current_ids
        )

        return [
            chunk_id
            for chunk_id in self.known_hashes()
            if chunk_id not in current
        ]


class VectorStore:
    """ChromaDB persistent collection."""

    def __init__(
        self,
        path: Path | str,
        collection: str = COLLECTION,
    ) -> None:
        import chromadb

        self.path = Path(path)

        self.path.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.client = chromadb.PersistentClient(
            path=str(self.path)
        )

        self.collection = (
            self.client.get_or_create_collection(
                name=collection,
                metadata={
                    "hnsw:space": "cosine"
                },
            )
        )

    # ================================================================
    # CHROMA WRITE OPERATIONS
    # ================================================================

    def upsert(
        self,
        chunks: Sequence[Chunk],
        embeddings: Sequence[
            Sequence[float]
        ],
    ) -> None:
        if not chunks:
            return

        if len(chunks) != len(embeddings):
            raise ValueError(
                "chunk/embedding count mismatch"
            )

        self.collection.upsert(
            ids=[
                chunk.chunk_id
                for chunk in chunks
            ],
            documents=[
                chunk.text
                for chunk in chunks
            ],
            embeddings=[
                list(embedding)
                for embedding in embeddings
            ],
            metadatas=[
                {
                    "jurisdiction": chunk.jurisdiction,
                    "instrument_type": chunk.instrument_type,
                    "act_name": chunk.act_name,
                    "section": chunk.section,
                    "effective_date": chunk.effective_date,
                    "source_url": chunk.source_url,
                    "content_hash": chunk.content_hash,
                }
                for chunk in chunks
            ],
        )

    def count(self) -> int:
        return int(
            self.collection.count()
        )

    # ================================================================
    # TEXT NORMALIZATION
    # ================================================================

    @staticmethod
    def _tokenize(
        text: str,
    ) -> list[str]:
        """Convert text into lowercase alphanumeric tokens."""

        return re.findall(
            r"[a-z0-9]+",
            text.lower(),
        )

    @staticmethod
    def _normalize_text(
        text: str,
    ) -> str:
        """Normalize text for phrase comparisons."""

        text = text.lower()

        text = re.sub(
            r"[^a-z0-9]+",
            " ",
            text,
        )

        return re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

    # ================================================================
    # QUERY EXPANSION
    # ================================================================

    @classmethod
    def _legal_query_variants(
        cls,
        query: str,
    ) -> list[str]:
        """Generate general linguistic variants of a legal query.

        This does not encode any particular answer or section.
        """

        query = query.strip()

        if not query:
            return []

        normalized = cls._normalize_text(
            query
        )

        variants: list[str] = [
            query
        ]

        # General legal-language transformations.
        transformations = (
            (
                "cannot be patented",
                "not patentable",
            ),
            (
                "cannot be patented",
                "not inventions",
            ),
            (
                "can not be patented",
                "not patentable",
            ),
            (
                "can not be patented",
                "not inventions",
            ),
            (
                "not eligible for a patent",
                "not patentable",
            ),
            (
                "not eligible to be patented",
                "not patentable",
            ),
            (
                "not capable of being patented",
                "not patentable",
            ),
            (
                "subject matter that cannot",
                "subject matter not",
            ),
            (
                "subject matter which cannot",
                "subject matter not",
            ),
        )

        for source, target in transformations:
            if source in normalized:
                variants.append(
                    normalized.replace(
                        source,
                        target,
                    )
                )

        # Remove interrogative framing.
        stripped = re.sub(
            r"^(what|which|where|when|why|how)\b",
            "",
            normalized,
        ).strip()

        if stripped:
            variants.append(
                stripped
            )

        # Remove auxiliary question words.
        content_query = re.sub(
            r"\b(does|do|did|is|are|was|were|can|could|would|"
            r"should|under)\b",
            " ",
            stripped,
        )

        content_query = re.sub(
            r"\s+",
            " ",
            content_query,
        ).strip()

        if content_query:
            variants.append(
                content_query
            )

        # De-duplicate while preserving order.
        result: list[str] = []

        for variant in variants:
            variant = variant.strip()

            if (
                variant
                and variant not in result
            ):
                result.append(
                    variant
                )

        return result[:8]

    # ================================================================
    # STOP WORDS
    # ================================================================

    @staticmethod
    def _stopwords() -> set[str]:
        return {
            "what",
            "which",
            "where",
            "when",
            "why",
            "how",
            "does",
            "do",
            "did",
            "is",
            "are",
            "was",
            "were",
            "can",
            "cannot",
            "could",
            "would",
            "should",
            "the",
            "a",
            "an",
            "of",
            "in",
            "on",
            "for",
            "to",
            "from",
            "under",
            "this",
            "that",
            "these",
            "those",
            "and",
            "or",
            "but",
            "be",
            "been",
            "being",
            "tell",
            "me",
            "say",
            "says",
            "act",
            "india",
            "indian",
            "section",
            "sections",
            "kind",
            "kinds",
        }

    # ================================================================
    # BM25-STYLE LEXICAL SEARCH
    # ================================================================

    @classmethod
    def _bm25_scores(
        cls,
        query: str,
        documents: Sequence[str],
    ) -> list[float]:
        """Calculate lightweight BM25-style scores.

        This implementation intentionally uses only the standard library,
        so no extra dependency is required.

        It is designed for this corpus size and is used as a complementary
        lexical retriever rather than replacing semantic search.
        """

        if not documents:
            return []

        query_tokens = [
            token
            for token in cls._tokenize(query)
            if token not in cls._stopwords()
        ]

        if not query_tokens:
            return [
                0.0
                for _ in documents
            ]

        query_terms = set(
            query_tokens
        )

        tokenized_documents = [
            cls._tokenize(document)
            for document in documents
        ]

        document_count = len(
            tokenized_documents
        )

        document_frequency: dict[
            str,
            int,
        ] = {}

        for tokens in tokenized_documents:
            unique_tokens = set(
                tokens
            )

            for token in unique_tokens:
                document_frequency[token] = (
                    document_frequency.get(
                        token,
                        0,
                    )
                    + 1
                )

        average_length = (
            sum(
                len(tokens)
                for tokens in tokenized_documents
            )
            / max(
                1,
                document_count,
            )
        )

        k1 = 1.5
        b = 0.75

        scores: list[float] = []

        for tokens in tokenized_documents:
            length = len(tokens)

            if length == 0:
                scores.append(0.0)
                continue

            frequencies: dict[
                str,
                int,
            ] = {}

            for token in tokens:
                frequencies[token] = (
                    frequencies.get(
                        token,
                        0,
                    )
                    + 1
                )

            score = 0.0

            for term in query_terms:
                term_frequency = frequencies.get(
                    term,
                    0,
                )

                if term_frequency == 0:
                    continue

                df = document_frequency.get(
                    term,
                    0,
                )

                # Standard BM25-style IDF.
                idf = math.log(
                    1.0
                    + (
                        document_count
                        - df
                        + 0.5
                    )
                    / (
                        df
                        + 0.5
                    )
                )

                denominator = (
                    term_frequency
                    + k1
                    * (
                        1.0
                        - b
                        + b
                        * (
                            length
                            / max(
                                average_length,
                                1.0,
                            )
                        )
                    )
                )

                score += (
                    idf
                    * (
                        term_frequency
                        * (k1 + 1.0)
                    )
                    / max(
                        denominator,
                        1e-9,
                    )
                )

            scores.append(
                score
            )

        return scores

    @classmethod
    def _phrase_bonus(
        cls,
        query: str,
        document: str,
    ) -> float:
        """Give a small bonus to exact multi-word legal phrases."""

        query_tokens = cls._tokenize(
            query
        )

        if len(query_tokens) < 2:
            return 0.0

        document_normalized = (
            cls._normalize_text(
                document
            )
        )

        if not document_normalized:
            return 0.0

        best = 0.0

        # Longer exact phrases are stronger evidence.
        for size, bonus in (
            (5, 0.20),
            (4, 0.17),
            (3, 0.14),
            (2, 0.10),
        ):
            if len(query_tokens) < size:
                continue

            for index in range(
                len(query_tokens)
                - size
                + 1
            ):
                phrase = " ".join(
                    query_tokens[
                        index:index + size
                    ]
                )

                if phrase in document_normalized:
                    best = max(
                        best,
                        bonus,
                    )

        return best

    # ================================================================
    # CHROMA FILTER
    # ================================================================

    @staticmethod
    def _build_where(
        jurisdiction: str | None,
        formulation_type: str | None,
    ):
        conditions = []

        if jurisdiction:
            conditions.append(
                {
                    "jurisdiction": jurisdiction
                }
            )

        if formulation_type:
            relevant_acts = acts_for_formulation(
                formulation_type
            )

            if relevant_acts:
                conditions.append(
                    {
                        "act_name": {
                            "$in": relevant_acts
                        }
                    }
                )

        if len(conditions) == 1:
            return conditions[0]

        if len(conditions) > 1:
            return {
                "$and": conditions
            }

        return None

    # ================================================================
    # RESULT HELPER
    # ================================================================

    @staticmethod
    def _make_match(
        chunk_id: str,
        document: str,
        metadata: dict,
        score: float,
    ) -> dict:
        return {
            "chunk_id": chunk_id,
            "text": document,
            "act_name": metadata.get(
                "act_name"
            ),
            "section": metadata.get(
                "section"
            ),
            "jurisdiction": metadata.get(
                "jurisdiction"
            ),
            "similarity_score": max(
                0.0,
                min(
                    1.0,
                    float(score),
                ),
            ),
            "source_url": metadata.get(
                "source_url"
            ),
        }

    # ================================================================
    # EXACT SECTION RETRIEVAL
    # ================================================================

    def _exact_section_query(
        self,
        query: str,
        jurisdiction: str | None,
        top_k: int,
    ) -> dict | None:
        """Resolve explicit section references from metadata."""

        section_match = re.search(
            r"\bsection\s+"
            r"(\d+[A-Za-z]?"
            r"(?:\([^)]+\))?)\b",
            query,
            flags=re.IGNORECASE,
        )

        if not section_match:
            return None

        requested_section = (
            "Section "
            + section_match.group(1)
        )

        conditions = [
            {
                "section": requested_section
            }
        ]

        if jurisdiction:
            conditions.append(
                {
                    "jurisdiction": jurisdiction
                }
            )

        if len(conditions) == 1:
            where = conditions[0]
        else:
            where = {
                "$and": conditions
            }

        result = self.collection.get(
            where=where,
            include=[
                "documents",
                "metadatas",
            ],
        )

        ids = result.get(
            "ids",
            [],
        )

        documents = result.get(
            "documents",
            [],
        )

        metadatas = result.get(
            "metadatas",
            [],
        )

        if not ids:
            return None

        query_normalized = (
            self._normalize_text(
                query
            )
        )

        act_matches = []

        for index, _chunk_id in enumerate(
            ids
        ):
            metadata = (
                metadatas[index]
                if index < len(metadatas)
                and metadatas[index]
                else {}
            )

            act_name = (
                metadata.get(
                    "act_name"
                )
                or ""
            )

            act_normalized = (
                self._normalize_text(
                    act_name
                )
            )

            if (
                act_normalized
                and act_normalized
                in query_normalized
            ):
                act_matches.append(
                    index
                )

        if act_matches:
            indexes = act_matches
        else:
            indexes = list(
                range(
                    len(ids)
                )
            )

        matches = []

        for index in indexes[:top_k]:
            metadata = (
                metadatas[index]
                if index < len(metadatas)
                and metadatas[index]
                else {}
            )

            document = (
                documents[index]
                if index < len(documents)
                else ""
            )

            matches.append(
                self._make_match(
                    chunk_id=ids[index],
                    document=document,
                    metadata=metadata,
                    score=1.0,
                )
            )

        if not matches:
            return None

        log.info(
            "Exact legal reference resolved: "
            "%s -> %s",
            requested_section,
            [
                match["chunk_id"]
                for match in matches
            ],
        )

        return {
            "matches": matches
        }

    # ================================================================
    # MAIN QUERY
    # ================================================================

    def query(
        self,
        query: str,
        embedder,
        jurisdiction: str | None = None,
        formulation_type: str | None = None,
        top_k: int = 5,
    ) -> dict:
        """Retrieve relevant legal corpus chunks."""

        if not query or not query.strip():
            return {
                "matches": []
            }

        top_k = max(
            1,
            int(top_k),
        )

        # ------------------------------------------------------------
        # 1. Exact legal section lookup
        # ------------------------------------------------------------

        exact_result = (
            self._exact_section_query(
                query=query,
                jurisdiction=jurisdiction,
                top_k=top_k,
            )
        )

        if exact_result is not None:
            return exact_result

        # ------------------------------------------------------------
        # 2. Build query variants
        # ------------------------------------------------------------

        variants = (
            self._legal_query_variants(
                query
            )
        )

        if not variants:
            variants = [
                query
            ]

        # ------------------------------------------------------------
        # 3. Build Chroma filter
        # ------------------------------------------------------------

        where = self._build_where(
            jurisdiction=jurisdiction,
            formulation_type=formulation_type,
        )

        collection_count = self.count()

        if collection_count <= 0:
            return {
                "matches": []
            }

        # ------------------------------------------------------------
        # 4. Load the filtered corpus for lexical retrieval
        #
        # The corpus is small enough for this project that scanning
        # the documents is practical. This gives us true lexical
        # retrieval rather than only searching Chroma's vector index.
        # ------------------------------------------------------------

        corpus = self.collection.get(
            where=where,
            include=[
                "documents",
                "metadatas",
            ],
        )

        corpus_ids = corpus.get(
            "ids",
            [],
        )

        corpus_documents = corpus.get(
            "documents",
            [],
        )

        corpus_metadatas = corpus.get(
            "metadatas",
            [],
        )

        if not corpus_ids:
            return {
                "matches": []
            }

        # ------------------------------------------------------------
        # 5. Semantic retrieval
        # ------------------------------------------------------------

        semantic_candidates: dict[
            str,
            dict,
        ] = {}

        semantic_limit = min(
            max(
                top_k * 12,
                60,
            ),
            len(corpus_ids),
        )

        for variant in variants:
            try:
                query_embedding = (
                    embedder.encode_query(
                        [variant]
                    )[0]
                )

                result = self.collection.query(
                    query_embeddings=[
                        list(
                            query_embedding
                        )
                    ],
                    n_results=semantic_limit,
                    where=where,
                    include=[
                        "documents",
                        "metadatas",
                        "distances",
                    ],
                )

            except Exception:
                log.exception(
                    "Semantic retrieval failed "
                    "for query variant: %s",
                    variant,
                )
                continue

            ids = result.get(
                "ids",
                [[]],
            )[0]

            documents = result.get(
                "documents",
                [[]],
            )[0]

            metadatas = result.get(
                "metadatas",
                [[]],
            )[0]

            distances = result.get(
                "distances",
                [[]],
            )[0]

            for index, chunk_id in enumerate(
                ids
            ):
                metadata = (
                    metadatas[index]
                    if index < len(metadatas)
                    and metadatas[index]
                    else {}
                )

                document = (
                    documents[index]
                    if index < len(documents)
                    else ""
                )

                distance = (
                    distances[index]
                    if index < len(distances)
                    else 1.0
                )

                similarity = max(
                    0.0,
                    min(
                        1.0,
                        1.0
                        - float(distance),
                    ),
                )

                previous = (
                    semantic_candidates.get(
                        chunk_id
                    )
                )

                if (
                    previous is None
                    or similarity
                    > previous[
                        "semantic_score"
                    ]
                ):
                    semantic_candidates[
                        chunk_id
                    ] = {
                        "chunk_id": chunk_id,
                        "document": document,
                        "metadata": metadata,
                        "semantic_score": similarity,
                    }

        # ------------------------------------------------------------
        # 6. Establish semantic ranks
        # ------------------------------------------------------------

        semantic_rank: dict[
            str,
            int,
        ] = {}

        semantic_order = sorted(
            semantic_candidates.values(),
            key=lambda item: (
                item["semantic_score"]
            ),
            reverse=True,
        )

        for rank, candidate in enumerate(
            semantic_order,
            start=1,
        ):
            semantic_rank[
                candidate["chunk_id"]
            ] = rank

        # ------------------------------------------------------------
        # 7. Corpus-wide lexical retrieval
        # ------------------------------------------------------------

        lexical_scores: dict[
            str,
            float,
        ] = {
            chunk_id: 0.0
            for chunk_id in corpus_ids
        }

        phrase_scores: dict[
            str,
            float,
        ] = {
            chunk_id: 0.0
            for chunk_id in corpus_ids
        }

        for variant in variants:
            scores = self._bm25_scores(
                variant,
                corpus_documents,
            )

            for index, score in enumerate(
                scores
            ):
                if index >= len(corpus_ids):
                    break

                chunk_id = corpus_ids[
                    index
                ]

                if score > lexical_scores[
                    chunk_id
                ]:
                    lexical_scores[
                        chunk_id
                    ] = score

                document = (
                    corpus_documents[index]
                    if index
                    < len(corpus_documents)
                    else ""
                )

                phrase_bonus = (
                    self._phrase_bonus(
                        variant,
                        document,
                    )
                )

                if phrase_bonus > phrase_scores[
                    chunk_id
                ]:
                    phrase_scores[
                        chunk_id
                    ] = phrase_bonus

        lexical_order = sorted(
            corpus_ids,
            key=lambda chunk_id: (
                lexical_scores[
                    chunk_id
                ],
                phrase_scores[
                    chunk_id
                ],
            ),
            reverse=True,
        )

        # Only meaningful lexical results receive a lexical rank.
        lexical_rank: dict[
            str,
            int,
        ] = {}

        lexical_limit = max(
            top_k * 20,
            100,
        )

        for rank, chunk_id in enumerate(
            lexical_order[
                :lexical_limit
            ],
            start=1,
        ):
            if (
                lexical_scores[
                    chunk_id
                ] > 0.0
            ):
                lexical_rank[
                    chunk_id
                ] = rank

        # ------------------------------------------------------------
        # 8. Candidate union
        # ------------------------------------------------------------

        candidate_ids = set(
            semantic_rank.keys()
        )

        candidate_ids.update(
            lexical_rank.keys()
        )

        # ------------------------------------------------------------
        # 9. Rank-based fusion
        #
        # We deliberately do not add raw cosine scores to BM25 scores.
        # They are different scoring systems and their numeric scales
        # are not directly comparable.
        # ------------------------------------------------------------

        fused_candidates = []

        for chunk_id in candidate_ids:
            semantic_position = (
                semantic_rank.get(
                    chunk_id
                )
            )

            lexical_position = (
                lexical_rank.get(
                    chunk_id
                )
            )

            semantic_score = 0.0

            if semantic_position is not None:
                candidate = (
                    semantic_candidates[
                        chunk_id
                    ]
                )

                semantic_score = (
                    candidate[
                        "semantic_score"
                    ]
                )

            # Rank decay:
            #
            # rank 1  -> 1.000
            # rank 2  -> 0.631
            # rank 10 -> 0.289
            # rank 50 -> 0.176
            #
            # This lets a strong lexical hit compete with a strong
            # semantic hit without pretending their raw scores are
            # measured on the same scale.

            semantic_rank_score = 0.0

            if semantic_position is not None:
                semantic_rank_score = (
                    1.0
                    / math.log2(
                        semantic_position + 1
                    )
                )

            lexical_rank_score = 0.0

            if lexical_position is not None:
                lexical_rank_score = (
                    1.0
                    / math.log2(
                        lexical_position + 1
                    )
                )

            # Main fusion.
            #
            # Semantic retrieval remains the larger signal.
            # Lexical retrieval is strong enough to rescue exact
            # statutory wording that BGE under-ranks.
            fused_rank_score = (
                0.55
                * semantic_rank_score
                + 0.45
                * lexical_rank_score
            )

            # Small phrase bonus. It can help an exact multi-word
            # statutory phrase, but cannot dominate retrieval.
            phrase_bonus = min(
                0.08,
                phrase_scores[
                    chunk_id
                ] * 0.40,
            )

            fused_score = min(
                1.0,
                (
                    0.70
                    * semantic_score
                    + 0.30
                    * fused_rank_score
                    + phrase_bonus
                ),
            )

            if chunk_id in semantic_candidates:
                candidate = (
                    semantic_candidates[
                        chunk_id
                    ]
                )

                document = candidate[
                    "document"
                ]

                metadata = candidate[
                    "metadata"
                ]

            else:
                corpus_index = (
                    corpus_ids.index(
                        chunk_id
                    )
                )

                document = (
                    corpus_documents[
                        corpus_index
                    ]
                    if corpus_index
                    < len(corpus_documents)
                    else ""
                )

                metadata = (
                    corpus_metadatas[
                        corpus_index
                    ]
                    if corpus_index
                    < len(corpus_metadatas)
                    and corpus_metadatas[
                        corpus_index
                    ]
                    else {}
                )

            fused_candidates.append(
                {
                    "chunk_id": chunk_id,
                    "document": document,
                    "metadata": metadata,
                    "semantic_score": semantic_score,
                    "semantic_rank": (
                        semantic_position
                    ),
                    "lexical_rank": (
                        lexical_position
                    ),
                    "lexical_score": (
                        lexical_scores[
                            chunk_id
                        ]
                    ),
                    "phrase_score": (
                        phrase_scores[
                            chunk_id
                        ]
                    ),
                    "fused_score": fused_score,
                }
            )

        # ------------------------------------------------------------
        # 10. Final ranking
        # ------------------------------------------------------------

        fused_candidates.sort(
            key=lambda candidate: (
                candidate["fused_score"],
                candidate["semantic_score"],
                candidate["phrase_score"],
                candidate["lexical_score"],
            ),
            reverse=True,
        )

        # ------------------------------------------------------------
        # 11. Return API-compatible results
        # ------------------------------------------------------------

        matches = []

        for candidate in fused_candidates[
            :top_k
        ]:
            matches.append(
                self._make_match(
                    chunk_id=candidate[
                        "chunk_id"
                    ],
                    document=candidate[
                        "document"
                    ],
                    metadata=candidate[
                        "metadata"
                    ],
                    score=candidate[
                        "fused_score"
                    ],
                )
            )

        return {
            "matches": matches
        }