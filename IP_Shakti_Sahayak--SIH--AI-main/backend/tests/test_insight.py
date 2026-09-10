"""Knowledge Sources, status, Evidence and Product Assessment.

These four endpoints are the product's trust surface, so the tests are
mostly about what they must refuse to imply: that a missing score is a zero,
that an unanswered question is a clean bill of health, that a citation
nothing supports is verified.
"""

from pathlib import Path
import json
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import insight_routes  # noqa: E402
from app.api.insight_routes import _screening_status  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /corpus/documents
# ---------------------------------------------------------------------------

def test_corpus_library_lists_documents_and_counts(monkeypatch):
    class FakeService:
        def corpus_documents(self):
            return [
                {
                    "act_name": "The Patents Act, 1970", "file": "p.pdf",
                    "status": "ingested", "jurisdiction": "india",
                    "instrument_type": "statute", "effective_date": "1972-04-20",
                    "source_url": "https://example.test/patents", "access": "public",
                    "chunks": 12, "section_effective_dates": {},
                },
                {
                    "act_name": "The Cosmetics Rules, 2020", "file": "c.pdf",
                    "status": "ingested", "jurisdiction": "india",
                    "instrument_type": "rule", "effective_date": None,
                    "source_url": None, "access": "public",
                    "chunks": 4, "section_effective_dates": {},
                },
                {
                    "act_name": "The Designs Act, 2000", "file": "d.pdf",
                    "status": "pending", "jurisdiction": "india",
                    "instrument_type": "statute", "effective_date": None,
                    "source_url": None, "access": "public",
                    "chunks": 0, "section_effective_dates": {},
                },
            ]

    monkeypatch.setattr(insight_routes, "ai_service", FakeService())
    body = client.get("/api/v1/corpus/documents").json()
    assert body["total"] == 3
    assert body["ingested"] == 2
    assert body["pending"] == 1
    # Counted over ingested documents only — a pending entry has no text in
    # the index, so a missing link there is a different shortfall.
    assert body["with_source_url"] == 1


def test_documents_without_a_source_url_are_listed_not_hidden(monkeypatch):
    """The manifest's honest gap has to stay visible in the product. A
    library that quietly dropped unlinked documents would overstate how
    much of the corpus a reader can verify."""
    class FakeService:
        def corpus_documents(self):
            return [{
                "act_name": "The Cosmetics Rules, 2020", "file": "c.pdf",
                "status": "ingested", "jurisdiction": "india",
                "instrument_type": "rule", "effective_date": None,
                "source_url": None, "access": "public", "chunks": 4,
                "section_effective_dates": {},
            }]

    monkeypatch.setattr(insight_routes, "ai_service", FakeService())
    body = client.get("/api/v1/corpus/documents").json()
    assert len(body["documents"]) == 1
    assert body["documents"][0]["source_url"] is None


def test_corpus_library_reads_the_real_manifest():
    """No monkeypatch: the shipped corpus.yaml must actually parse."""
    body = client.get("/api/v1/corpus/documents").json()
    assert body["total"] > 0
    assert body["ingested"] > 0
    assert all(d["status"] in {"ingested", "pending", "unknown"} for d in body["documents"])


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------

def test_status_reports_the_active_embedder_not_the_configured_one(monkeypatch):
    """The embedder is chosen by the artifact beside the index, so these
    two can legitimately differ — and the difference is the point."""
    class FakeService:
        def status(self):
            return {
                "collection": "ip_sakti_corpus", "chunks": 40, "index_ready": True,
                "configured_embedding_model": "BAAI/bge-small-en-v1.5",
                "active_embedding_model": "tfidf-384",
                "embedding_dimension": 384, "embedding_is_fallback": True,
                "generation_mode": "mock", "llm_model": None,
                "translation_configured": False, "abstain_threshold": 0.2,
                "default_top_k": 5, "audit_entries": 3,
            }

    monkeypatch.setattr(insight_routes, "ai_service", FakeService())
    body = client.get("/api/v1/status").json()
    assert body["configured_embedding_model"] == "BAAI/bge-small-en-v1.5"
    assert body["active_embedding_model"] == "tfidf-384"
    assert body["embedding_is_fallback"] is True


def test_status_survives_a_broken_backend():
    """This is the endpoint you check when other things are failing. It
    must degrade to reporting the failure, not become another outage."""
    res = client.get("/api/v1/status")
    assert res.status_code == 200
    assert "index_ready" in res.json()


# ---------------------------------------------------------------------------
# GET /evidence/{audit_id}
# ---------------------------------------------------------------------------

def test_evidence_returns_404_for_an_unknown_id(monkeypatch):
    class FakeService:
        def evidence(self, audit_id):
            return None

    monkeypatch.setattr(insight_routes, "ai_service", FakeService())
    assert client.get("/api/v1/evidence/missing").status_code == 404


def test_evidence_marks_unsupported_citations_unverified(tmp_path, monkeypatch):
    """A citation the retrieved chunks do not support is the exact failure
    this system exists to catch, so it is counted, never assumed away."""
    from app.services.ai_service import AIService
    from ai.audit import AuditLog

    service = AIService()
    service._audit = AuditLog(tmp_path / "audit.sqlite3")

    audit_id = service._audit.log_query(
        query_text="Can this be patented?",
        jurisdiction="india",
        formulation_type="proprietary",
        top_k=2,
        matched_chunk_ids=["c1"],
        confidence=0.71,
        should_abstain=False,
        citations=[
            {"act_name": "The Patents Act, 1970", "section": "Section 3(p)"},
            {"act_name": "Invented Act, 1999", "section": "Section 1"},
        ],
        retrieval_detail=[{
            "chunk_id": "c1", "act_name": "The Patents Act, 1970",
            "section": "Section 3(p)", "jurisdiction": "india",
            "similarity_score": 0.71, "source_url": None,
        }],
    )

    # No index in this test, so chunk text lookup finds nothing — which is
    # itself the "still_in_corpus is False" path.
    found = service.evidence(audit_id)
    assert found["citations_total"] == 2
    assert found["citations_verified"] == 1
    by_act = {c["act_name"]: c["verified"] for c in found["citations"]}
    assert by_act["The Patents Act, 1970"] is True
    assert by_act["Invented Act, 1999"] is False
    assert found["detail_recorded"] is True
    assert found["chunks"][0]["similarity_score"] == pytest.approx(0.71)


def test_evidence_distinguishes_unrecorded_scores_from_zero(tmp_path):
    """A row written before scores were recorded reports None, not 0.0.
    'Not recorded' and 'scored zero' are different claims about the same
    answer, and only one of them is true."""
    from app.services.ai_service import AIService
    from ai.audit import AuditLog

    service = AIService()
    service._audit = AuditLog(tmp_path / "audit.sqlite3")
    audit_id = service._audit.log_query(
        query_text="q", jurisdiction="india", formulation_type=None, top_k=1,
        matched_chunk_ids=["c9"], confidence=0.3, should_abstain=True,
        citations=[],
    )

    found = service.evidence(audit_id)
    assert found["detail_recorded"] is False
    assert found["chunks"][0]["chunk_id"] == "c9"
    assert found["chunks"][0]["similarity_score"] is None


def test_evidence_flags_chunks_no_longer_in_the_corpus(tmp_path):
    """'This answer cited something the corpus no longer contains' is
    exactly what an evidence view exists to make visible."""
    from app.services.ai_service import AIService
    from ai.audit import AuditLog

    service = AIService()
    service._audit = AuditLog(tmp_path / "audit.sqlite3")
    audit_id = service._audit.log_query(
        query_text="q", jurisdiction="india", formulation_type=None, top_k=1,
        matched_chunk_ids=["gone"], confidence=0.5, should_abstain=False,
        citations=[],
        retrieval_detail=[{"chunk_id": "gone", "act_name": "A", "section": "1",
                           "jurisdiction": "india", "similarity_score": 0.5}],
    )
    found = service.evidence(audit_id)
    assert found["chunks"][0]["still_in_corpus"] is False


# ---------------------------------------------------------------------------
# POST /assess — the GREEN / AMBER / RED bands
# ---------------------------------------------------------------------------

def test_assess_requires_something_to_screen():
    assert client.post("/api/v1/assess", json={}).status_code == 422


def test_blocking_obligation_is_red():
    band, reason = _screening_status({
        "triggered": True,
        "obligations": [{"blocks_grant": True}, {"blocks_grant": False}],
        "open_questions": [], "provisional": False,
    })
    assert band == "RED"
    assert "before an IP right" in reason


def test_non_blocking_obligations_are_amber():
    band, _ = _screening_status({
        "triggered": True,
        "obligations": [{"blocks_grant": False}],
        "open_questions": [], "provisional": False,
    })
    assert band == "AMBER"


def test_unanswered_critical_question_is_never_green():
    """The single most damaging thing this screen could show is a green
    light on a question that decides the answer. 'Nothing triggered' and
    'nothing triggered because nobody told us' must not share a colour."""
    band, reason = _screening_status({
        "triggered": False, "obligations": [],
        "open_questions": [{"importance": "critical", "question": "Where from?"}],
        "provisional": True,
    })
    assert band == "AMBER"
    assert "NOT a finding" in reason


def test_green_requires_both_nothing_triggered_and_enough_information():
    band, _ = _screening_status({
        "triggered": False, "obligations": [], "open_questions": [],
        "provisional": False,
    })
    assert band == "GREEN"


def test_a_screening_that_could_not_run_is_unknown_not_green():
    band, _ = _screening_status(None)
    assert band == "UNKNOWN"


def test_assess_runs_the_real_compliance_graph():
    """End to end against the shipped ontology: a foreign applicant seeking
    IP over an Indian biological resource must not come back GREEN."""
    res = client.post("/api/v1/assess", json={
        "classification": {"formulation_type": "proprietary"},
        "facts": {
            "uses_biological_material": True,
            "resource_origin": "india",
            "applicant_category": "foreign_national",
            "seeking_ipr": True,
        },
    })
    assert res.status_code == 200
    body = res.json()
    assert body["status"] in {"RED", "AMBER"}
    assert body["compliance"] is not None
    assert body["compliance"]["obligations"]


def test_assess_carries_citations_on_every_obligation():
    """An obligation without a provision to check it against is an
    assertion, not guidance."""
    res = client.post("/api/v1/assess", json={
        "classification": {"formulation_type": "proprietary"},
        "facts": {
            "uses_biological_material": True,
            "resource_origin": "india",
            "applicant_category": "foreign_national",
            "seeking_ipr": True,
        },
    })
    for obligation in res.json()["compliance"]["obligations"]:
        assert obligation["act_name"]
        assert obligation["section"]
