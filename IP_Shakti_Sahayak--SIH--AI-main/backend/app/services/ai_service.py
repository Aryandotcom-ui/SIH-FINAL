from __future__ import annotations

from dataclasses import asdict, replace
import logging
from pathlib import Path
import sys
import threading
from typing import Any

# The AI folder is a sibling of backend/, so add the repository root.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai.embedder import Embedder, get_embedder  # noqa: E402
from ai.person_b_retrieval.confidence import compute_confidence, decide_abstain  # noqa: E402
from ai.person_b_retrieval.schema import (  # noqa: E402
    Classification,
    MatchedChunk,
    RetrievalResult,
)
from ai.store import VectorStore  # noqa: E402
from ai.person_c_generation.generate import generate_answer  # noqa: E402
from ai.compliance import get_assessor  # noqa: E402
from ai.audit import AuditLog  # noqa: E402
from ai.translation import (  # noqa: E402
    Translator,
    get_translator,
    translate_answer_from_english,
    translate_query_to_english,
)

from ..config import settings  # noqa: E402
from ..schemas import SCOPE_JURISDICTION, SCOPE_LABEL  # noqa: E402


class AIService:
    """Application-facing adapter around the existing AI pipeline.

    The backend does not duplicate the team's RAG/generation logic. It
    converts HTTP input into the agreed AI shapes and returns a JSON-safe
    response for the frontend.
    """

    def __init__(self) -> None:
        self._embedder: Embedder | None = None
        self._store: VectorStore | None = None
        self._audit: AuditLog | None = None
        self._translator: Translator | None = None
        # FastAPI runs sync endpoints in a threadpool, so two requests that
        # arrive before the first one has finished building these run the
        # lazy initialisation concurrently. Chroma in particular does not
        # survive that: two PersistentClients opening the same directory at
        # once fail with whichever of several unrelated-looking errors the
        # race happens to produce ("Could not connect to tenant
        # default_tenant", "'RustBindingsAPI' object has no attribute
        # 'bindings'", a bare KeyError on the path). The symptom is that the
        # first couple of visitors after a cold start get a 503 and everyone
        # after them is fine, which reads as a flaky backend rather than as
        # a race. One lock per resource, double-checked, removes it.
        self._locks = {name: threading.Lock() for name in
                       ("embedder", "store", "audit", "translator")}

    @property
    def embedder(self) -> Embedder:
        """The embedder must be the one the index was built with.

        If a fitted TF-IDF vectorizer is sitting beside the Chroma index,
        that is definitive: the index was built from that vector space and
        encoding queries with anything else puts them in a different one,
        which degrades retrieval to noise without raising. So the artifact
        wins over the configured model name rather than the other way
        round.
        """
        if self._embedder is None:
            with self._locks["embedder"]:
                if self._embedder is None:
                    from ai.embedder import TfidfEmbedder
                    artifact = Path(settings.chroma_path) / TfidfEmbedder.ARTIFACT_NAME
                    if artifact.is_file():
                        logging.getLogger(__name__).info(
                            "loading TF-IDF vectorizer saved with the index (%s)", artifact
                        )
                        self._embedder = TfidfEmbedder.load(settings.chroma_path)
                    else:
                        self._embedder = get_embedder(
                            settings.embedding_model,
                            device=settings.embedding_device,
                        )
        return self._embedder

    @property
    def store(self) -> VectorStore:
        if self._store is None:
            with self._locks["store"]:
                if self._store is None:
                    self._store = VectorStore(
                        settings.chroma_path,
                        collection=settings.chroma_collection,
                    )
        return self._store

    @property
    def audit(self) -> AuditLog:
        if self._audit is None:
            with self._locks["audit"]:
                if self._audit is None:
                    self._audit = AuditLog(
                        settings.audit_db_path,
                        corpus_path=settings.corpus_manifest_path,
                    )
        return self._audit

    @property
    def translator(self) -> Translator:
        if self._translator is None:
            with self._locks["translator"]:
                if self._translator is None:
                    self._translator = get_translator(
                        settings.bhashini_api_key, settings.bhashini_user_id
                    )
        return self._translator

    def corpus_count(self) -> int:
        return self.store.count()

    def corpus_jurisdictions(self) -> dict[str, int]:
        """Chunk counts per jurisdiction — how much corpus each scope of the
        jurisdiction toggle actually has behind it.

        The UI shows these on the toggle, so a scope with nothing ingested
        reads as empty rather than as broken. Degrades to {} rather than
        raising: a count that could not be taken must not take down the
        corpus-status endpoint that the rest of the app polls for liveness.
        """
        counts: dict[str, int] = {}
        for scope, jurisdiction in SCOPE_JURISDICTION.items():
            try:
                got = self.store.collection.get(
                    where={"jurisdiction": jurisdiction}, include=[]
                )
                counts[jurisdiction] = len(got.get("ids") or [])
            except Exception:  # pragma: no cover - defensive
                logging.getLogger(__name__).exception(
                    "could not count %s chunks", jurisdiction
                )
        return counts

    def corpus_jurisdiction_values(self, sample: int = 2000) -> dict[str, int]:
        """The `jurisdiction` values actually present in the index, counted.

        corpus_jurisdictions() answers "how much does each scope have?", and
        so can only ever report the two values the scope filter looks for.
        This answers the different question a mis-tagged index raises —
        "then what IS in there?" — which is what turns a metadata mismatch
        from visible into diagnosable. Samples rather than scans: it exists
        to fill in an error message, and an exact count of a value that
        should not be there buys nothing over knowing that it is there.
        """
        try:
            got = self.store.collection.get(limit=sample, include=["metadatas"])
        except Exception:  # pragma: no cover - defensive
            logging.getLogger(__name__).exception("could not sample jurisdictions")
            return {}
        counts: dict[str, int] = {}
        for meta in got.get("metadatas") or []:
            value = (meta or {}).get("jurisdiction")
            key = "<missing>" if value is None else repr(value)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def retrieve(
        self,
        query: str,
        classification: Classification | None,
        top_k: int,
    ) -> tuple[RetrievalResult, dict[str, dict]]:
        """Query the persistent Chroma index and calculate the team's
        confidence/abstention result without rebuilding the entire corpus.
        """
        jurisdiction = classification.jurisdiction if classification else None
        formulation_type = classification.formulation_type if classification else None

        result = self.store.query(
            query=query,
            embedder=self.embedder,
            jurisdiction=jurisdiction,
            formulation_type=formulation_type,
            top_k=top_k,
        )

        matched = [
            MatchedChunk(
                chunk_id=item["chunk_id"],
                text=item["text"],
                act_name=item["act_name"],
                section=item["section"],
                jurisdiction=item["jurisdiction"],
                similarity_score=item["similarity_score"],
            )
            for item in result["matches"]
        ]
        confidence = compute_confidence(matched)
        should_abstain = decide_abstain(
            confidence, matched, threshold=settings.abstain_threshold
        )

        retrieval = RetrievalResult(
            query=query,
            matched_chunks=matched,
            confidence=confidence,
            should_abstain=should_abstain,
        )
        source_map = {item["chunk_id"]: item for item in result["matches"]}
        return retrieval, source_map

    def compliance(
        self,
        classification: Classification | None,
        facts: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """ABS screening off the same classification retrieval already used.

        Runs on every query rather than behind a separate endpoint. Someone
        who does not know section 6 of the Biological Diversity Act exists
        will never think to ask for an ABS check, and that person is exactly
        who the flag is for.

        Failure here degrades to None rather than propagating: a screening
        that could not run must not take down an answer the user can still
        use. The absent key is the signal; the API never emits an empty
        report that would render as "nothing to worry about".
        """
        if classification is None and not facts:
            return None
        try:
            assessor = get_assessor(str(REPO_ROOT / "ai" / "corpus.yaml"))
            report = assessor.assess_from_classification(
                classification, **(facts or {})
            )
            return report.to_dict()
        except Exception as exc:  # pragma: no cover - defensive
            logging.getLogger(__name__).exception("compliance screening failed: %s", exc)
            return None

    @staticmethod
    def resolve_scope(
        scope: str | None, classification: Classification | None
    ) -> str:
        """Which jurisdictions a query is answered from.

        An explicit scope wins. Absent one, a classification that already
        names a jurisdiction is honoured — that is how every caller written
        before the toggle existed passed this, and silently widening those
        to BOTH would change their answers. Otherwise BOTH: the default
        must not force a jurisdiction choice out of someone who has not
        been asked one.
        """
        if scope in SCOPE_JURISDICTION or scope == "BOTH":
            return scope
        if classification is not None and classification.jurisdiction:
            for code, jurisdiction in SCOPE_JURISDICTION.items():
                if classification.jurisdiction == jurisdiction:
                    return code
        return "BOTH"

    def _answer_for_scope(
        self,
        english_query: str,
        scope: str,
        classification: Classification | None,
        top_k: int,
        consented_acts: set[str] | None,
    ) -> dict[str, Any]:
        """Retrieve and generate within one jurisdiction, and nothing else.

        The jurisdiction is pushed down into the Chroma metadata filter, so
        chunks from the other jurisdiction are never eligible to be
        retrieved — the boundary is enforced before ranking, not by asking
        the model to be careful afterwards. The generator is then told which
        jurisdiction it is answering under and instructed not to reach
        outside it, which is the guardrail against the model's own training
        knowledge filling in what retrieval deliberately excluded.
        """
        jurisdiction = SCOPE_JURISDICTION[scope]
        label = SCOPE_LABEL[scope]

        # Carry the scope in as a Classification rather than as a separate
        # argument: retrieve() already reads its jurisdiction from there, so
        # the filter reaches the store by the path it always has.
        scoped = (
            replace(classification, jurisdiction=jurisdiction)
            if classification is not None
            else Classification(jurisdiction=jurisdiction)
        )
        retrieval, source_map = self.retrieve(english_query, scoped, top_k)

        insufficient = retrieval.should_abstain
        generation_mode = "none"

        if insufficient:
            # Nothing in this jurisdiction matched well enough. Do not let
            # the model fill the gap from its own knowledge — the whole
            # point of the filter is that an answer here would be
            # ungrounded. Name the other scope instead, since a question
            # with no Indian answer very often has an international one.
            other = "International" if scope == "IN" else "India"
            from ai.shared.schema import FinalAnswer

            final = FinalAnswer(
                answer_text=(
                    f"I don't have {label}-specific guidance on this in the "
                    f"corpus, so I can't answer it from {label} sources. "
                    f"Try the {other} scope, or Both."
                ),
                citations=[],
                confidence=retrieval.confidence,
                abstained=True,
                disclaimer="This is informational, not legal advice.",
            )
        else:
            # Without a key the LLM step cannot run. Falling back to the
            # deterministic MockLLM keeps retrieval, citations and the
            # compliance screening demonstrable — but a canned paragraph
            # presented as a generated answer would be precisely the
            # dishonesty this system exists to prevent, so the mode is
            # reported in the response and the UI must surface it.
            use_mock = not settings.groq_api_key
            final = generate_answer(
                retrieval,
                model=settings.llm_model,
                mock=use_mock,
                api_key=settings.groq_api_key,
                jurisdiction_label=label,
            )
            generation_mode = "mock" if use_mock else "live"

        # Keep source metadata from retrieval for the UI. Generation uses
        # the existing Shape-3/Shape-4 contract and therefore does not
        # change those team-owned field names.
        sources = []
        for c in retrieval.matched_chunks:
            meta = source_map.get(c.chunk_id, {})
            sources.append({
                "chunk_id": c.chunk_id,
                "act_name": c.act_name,
                "section": c.section,
                "jurisdiction": c.jurisdiction,
                "similarity_score": c.similarity_score,
                "source_url": meta.get("source_url"),
            })

        citations = []
        for c in final.citations:
            url = next(
                (s["source_url"] for s in sources
                 if s["act_name"] == c.act_name and s["section"] == c.section),
                None,
            )
            citations.append({
                "act_name": c.act_name,
                "section": c.section,
                "source_url": url,
            })

        # Withhold any citation/source drawn from a licensed act the
        # request hasn't consented to. See ai/audit.py — this never
        # touches retrieval itself (the model can still reason over a
        # licensed chunk's text), only what is disclosed in the response.
        gate = self.audit.gate_citations(
            {s["act_name"] for s in sources}, consented_acts=consented_acts
        )
        if gate.licensed_withheld:
            withheld = set(gate.licensed_withheld)
            sources = [s for s in sources if s["act_name"] not in withheld]
            citations = [c for c in citations if c["act_name"] not in withheld]

        return {
            "scope": scope,
            "label": label,
            "final": final,
            "retrieval": retrieval,
            "sources": sources,
            "citations": citations,
            "gate": gate,
            "generation": generation_mode,
            "insufficient": insufficient,
        }

    def answer(
        self,
        query: str,
        classification: Classification | None,
        top_k: int,
        compliance_facts: dict[str, Any] | None = None,
        consented_acts: set[str] | None = None,
        language: str | None = None,
        scope: str | None = None,
    ) -> dict[str, Any]:
        formulation_type = classification.formulation_type if classification else None
        resolved_scope = self.resolve_scope(scope, classification)

        # Compliance screening is about the applicant's own duties, not about
        # which corpus the answer was drawn from, so it runs on every query
        # whatever the scope — that is the entire point of it (see
        # compliance()'s docstring: the person who needs the ABS flag is the
        # one who does not know to ask for it). Before the jurisdiction moved
        # onto the scope, the UI always sent jurisdiction="india" on the
        # classification and that alone was enough to fire the screening. Now
        # that the scope carries the jurisdiction, fill it in here, or a query
        # with no formulation facts would silently get no screening at all.
        compliance_classification = (
            replace(classification, jurisdiction=classification.jurisdiction or "india")
            if classification is not None
            else Classification(jurisdiction="india")
        )

        # "BOTH" is two separately filtered retrievals and two separate
        # generation calls, never one merged call. Blending them would put a
        # Patents Act clause and a PCT rule in the same similarity ranking,
        # where one crowds the other out or the two get stitched into a
        # single incoherent paragraph across two legal systems.
        targets = ["IN", "INTL"] if resolved_scope == "BOTH" else [resolved_scope]

        # Retrieval filters on jurisdiction BEFORE ranking, so an index whose
        # chunks are not tagged with these exact values has nothing eligible
        # to return: no chunks scores 0.0, 0.0 is below the abstain
        # threshold, and every question on every scope comes back as a
        # confident-looking "0% confidence, I can't answer that". A broken
        # index reported as a settled I-don't-know is precisely the failure
        # this project exists to prevent, so say what is actually wrong.
        #
        # Only raise when the collection HAS content and none of it is
        # reachable through the scopes asked for. Two cases stay off this
        # path deliberately: an empty collection (nothing is ingested yet —
        # already a 503 from the embedder/corpus guards, and not a metadata
        # fault), and a scope that is empty while its sibling has content,
        # which the `insufficient` path below handles gracefully by naming
        # the other scope. A count that could not be taken leaves its key
        # absent rather than reading as 0, so a transient Chroma error can
        # never masquerade as a mis-tagged corpus.
        targeted = [SCOPE_JURISDICTION[t] for t in targets]
        counted = self.corpus_jurisdictions()
        if (
            self.corpus_count() > 0
            and all(j in counted for j in targeted)
            and all(counted[j] == 0 for j in targeted)
        ):
            present = self.corpus_jurisdiction_values()
            raise RuntimeError(
                f"the index holds {self.corpus_count()} chunks, but none are "
                f"tagged with the jurisdiction(s) this scope searches "
                f"({', '.join(targeted)}). The jurisdiction values actually in "
                f"the index are: {present or 'none readable'}. Retrieval filters "
                "on jurisdiction before ranking, so nothing can match and every "
                "query would report 0% confidence. Either nothing for this "
                "jurisdiction has been ingested yet, or the index predates the "
                "jurisdiction scope and is tagged with different values. Check "
                "the values above against ai/corpus.yaml, then rebuild with: "
                "./scripts/run.sh --rebuild"
            )

        # Translate to English before retrieval — ai/embedder.py's default
        # model is English-only, so this is what makes retrieval work at
        # all for a non-English query, not a UX nicety. See
        # ai/translation.py's module docstring. `language` here is the
        # caller-supplied or detected source language; retrieval and
        # generation run on the English text throughout, and the answer
        # translates back to this language at the very end.
        query_translation = translate_query_to_english(
            query, translator=self.translator, language=language
        )
        source_language = query_translation.source_lang
        english_query = query_translation.text

        try:
            parts = [
                self._answer_for_scope(
                    english_query, target, classification, top_k, consented_acts
                )
                for target in targets
            ]

            # Translate each block's prose back to the requester's language.
            # Never touches citations/sources — act_name is a legal
            # identifier, not prose, and translating it would break the
            # exact-match contract ai/corpus.yaml's header describes.
            answers = []
            translated_all = True
            for part in parts:
                rendered = translate_answer_from_english(
                    part["final"].answer_text,
                    translator=self.translator,
                    target_lang=source_language,
                )
                translated_all = translated_all and rendered.translated
                answers.append({
                    "scope": part["scope"],
                    "label": part["label"],
                    "answer_text": rendered.text,
                    "citations": part["citations"],
                    "sources": part["sources"],
                    "confidence": part["final"].confidence,
                    "abstained": part["final"].abstained,
                    "generation": part["generation"],
                    "insufficient": part["insufficient"],
                })

            disclaimer_translation = translate_answer_from_english(
                "This is informational, not legal advice.",
                translator=self.translator,
                target_lang=source_language,
            )

            # The flat fields below exist for callers that predate the
            # per-jurisdiction breakdown. For a single scope they are that
            # scope's answer verbatim; for BOTH they are the two blocks
            # under explicit headings — labelled, never run together into
            # one paragraph, for the same reason the UI keeps them apart.
            if len(answers) == 1:
                answer_text = answers[0]["answer_text"]
            else:
                answer_text = "\n\n".join(
                    f"{a['label']}\n{a['answer_text']}" for a in answers
                )

            citations = _dedupe_citations(answers)
            sources = _dedupe_sources(answers)
            abstained = all(a["abstained"] for a in answers)
            confidence = max((a["confidence"] for a in answers), default=0.0)
            # "live" beats "mock" beats "none": what the user needs to know
            # is whether ANY prose in front of them is a canned stand-in,
            # and the per-block generation field says which.
            modes = {a["generation"] for a in answers}
            generation = (
                "live" if "live" in modes
                else "mock" if "mock" in modes
                else "none"
            )
            withheld = sorted({
                act for part in parts for act in part["gate"].licensed_withheld
            })

            audit_id = self._log_query_safe(
                query_text=query,
                jurisdiction=",".join(SCOPE_JURISDICTION[t] for t in targets),
                formulation_type=formulation_type,
                top_k=top_k,
                matched_chunk_ids=[
                    c.chunk_id for part in parts
                    for c in part["retrieval"].matched_chunks
                ],
                confidence=confidence,
                should_abstain=abstained,
                citations=citations,
                gate=parts[0]["gate"] if parts else None,
                disclaimer_shown=True,
                llm_model=None if abstained else settings.llm_model,
            )

            return {
                "answer_text": answer_text,
                "citations": citations,
                "confidence": confidence,
                "abstained": abstained,
                "disclaimer": disclaimer_translation.text,
                "sources": sources,
                # Attached even when retrieval abstained. Abstention means the
                # corpus could not answer the question asked; it says nothing
                # about whether an ABS obligation applies, and those are
                # decided by the graph rather than by retrieval.
                "compliance": self.compliance(compliance_classification, compliance_facts),
                "licensed_sources_withheld": withheld,
                "audit_id": audit_id,
                # "live" (a real model call), "mock" (no API key configured —
                # the prose is canned, the citations and screening are not),
                # or "none" (abstained, so no generation happened).
                "generation": generation,
                "language": source_language,
                # False means the text above is still English because no
                # translation backend is configured or it failed — the
                # answer is still correct, just not delivered in the
                # requester's language. See ai/translation.py.
                "translated": translated_all,
                "scope": resolved_scope,
                "answers": answers,
            }
        except Exception as exc:
            # A query that blew up is exactly the kind of event an audit
            # trail exists to capture — log it (best-effort) and let the
            # caller's own error handling take it from here.
            self._log_query_safe(
                query_text=query,
                jurisdiction=",".join(SCOPE_JURISDICTION[t] for t in targets),
                formulation_type=formulation_type,
                top_k=top_k,
                matched_chunk_ids=[],
                confidence=None,
                should_abstain=True,
                citations=[],
                gate=None,
                disclaimer_shown=False,
                llm_model=None,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

    def _log_query_safe(self, **kwargs: Any) -> str | None:
        """Write an audit row without letting a logging failure take down
        the request it is trying to record. The absent audit_id is the
        signal something is wrong with the audit store itself, which is an
        operational problem to alert on, not a reason to refuse an answer
        the user can still use."""
        try:
            return self.audit.log_query(**kwargs)
        except Exception:  # pragma: no cover - defensive
            logging.getLogger(__name__).exception("audit logging failed")
            return None


def _dedupe_citations(answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Union of every block's citations, order preserved, duplicates dropped.

    A citation is identified by (act_name, section) — the same pair the
    corpus manifest treats as a contract — so the same provision reached
    from two jurisdictions is listed once.
    """
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for a in answers:
        for c in a["citations"]:
            key = (c["act_name"], c["section"])
            if key in seen:
                continue
            seen.add(key)
            out.append(c)
    return out


def _dedupe_sources(answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Union of every block's retrieved chunks, keyed by chunk_id."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for a in answers:
        for s in a["sources"]:
            if s["chunk_id"] in seen:
                continue
            seen.add(s["chunk_id"])
            out.append(s)
    return out


ai_service = AIService()
