from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app
from app.api import routes
from app.auth import Identity, auth_service

client = TestClient(app)


def auth_headers(role: str = "REVIEWER", username: str = "test-reviewer") -> dict[str, str]:
    """A bearer token for a caller at `role`.

    Issued through the real token path rather than by overriding the
    dependency, so these tests exercise signing and decoding too — the
    parts that would let a forged token through if they broke.
    """
    account_role = role.upper()
    auth_service._accounts = dict(auth_service.accounts)
    from app.auth import Account, hash_password

    auth_service._accounts[username] = Account(username, account_role, hash_password("x"))
    token, _ = auth_service.issue_token(Identity(username, account_role))
    return {"Authorization": f"Bearer {token}"}


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_query_validation():
    response = client.post("/api/v1/query", json={"query": "x"})
    assert response.status_code == 422


def test_corpus_status(monkeypatch):
    class FakeStore:
        class Collection:
            name = "ip_sakti_corpus"
        collection = Collection()

    class FakeService:
        store = FakeStore()

        def corpus_count(self):
            return 12

        def corpus_jurisdictions(self):
            return {"india": 9, "international": 3}

    monkeypatch.setattr(routes, "ai_service", FakeService())
    response = client.get("/api/v1/corpus")
    assert response.status_code == 200
    assert response.json() == {
        "collection": "ip_sakti_corpus",
        "chunks": 12,
        "jurisdictions": {"india": 9, "international": 3},
    }


def test_query_success(monkeypatch):
    class FakeService:
        def answer(self, query, classification, top_k, compliance_facts=None,
                   consented_acts=None, language=None, scope=None):
            assert query == "Can this be patented?"
            assert classification is not None
            assert classification.formulation_type == "classical"
            assert classification.jurisdiction == "india"
            assert top_k == 3
            return {
                "answer_text": "See Section 3.",
                "citations": [{
                    "act_name": "The Patents Act, 1970",
                    "section": "Section 3",
                    "source_url": "https://example.test/patents",
                }],
                "confidence": 0.82,
                "abstained": False,
                "disclaimer": "This is informational, not legal advice.",
                "sources": [{
                    "chunk_id": "c1",
                    "act_name": "The Patents Act, 1970",
                    "section": "Section 3",
                    "jurisdiction": "india",
                    "similarity_score": 0.82,
                    "source_url": "https://example.test/patents",
                }],
            }

    monkeypatch.setattr(routes, "ai_service", FakeService())
    response = client.post(
        "/api/v1/query",
        json={
            "query": "Can this be patented?",
            "classification": {
                "formulation_type": "classical",
                "jurisdiction": "india",
            },
            "top_k": 3,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer_text"] == "See Section 3."
    assert body["abstained"] is False
    assert body["sources"][0]["section"] == "Section 3"


def test_cors_origins_can_be_loaded_from_comma_separated_env(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("CORS_ORIGINS", "http://a.test,http://b.test")
    configured = Settings()
    assert configured.cors_origins == ["http://a.test", "http://b.test"]


def test_abstain_threshold_is_configurable(monkeypatch):
    from app.services.ai_service import AIService

    service = AIService()

    class FakeEmbedder:
        def encode_query(self, texts):
            return [[1.0, 0.0]]

    class FakeCollection:
        name = "ip_sakti_corpus"

        def query(self, **kwargs):
            return {
                "ids": [["c1"]],
                "documents": [["patent novelty"]],
                "metadatas": [[{
                    "act_name": "The Patents Act, 1970",
                    "section": "Section 3",
                    "jurisdiction": "india",
                    "source_url": "https://example.test",
                }]],
                "distances": [[0.85]],
            }

    class FakeStore:
        collection = FakeCollection()

        def query(self, **kwargs):
            return {
                "matches": [{
                    "chunk_id": "c1",
                    "text": "patent novelty",
                    "act_name": "The Patents Act, 1970",
                    "section": "Section 3",
                    "jurisdiction": "india",
                    "similarity_score": 0.15,
                    "source_url": "https://example.test",
                }]
            }

    service._embedder = FakeEmbedder()
    service._store = FakeStore()
    monkeypatch.setattr("app.services.ai_service.settings.abstain_threshold", 0.10)

    retrieval, _ = service.retrieve("patent novelty", None, 1)
    assert retrieval.confidence == 0.15
    assert retrieval.should_abstain is False


def test_configured_groq_key_is_forwarded_to_generation(monkeypatch):
    from app.services import ai_service as service_module

    captured = {}

    def fake_generate_answer(retrieval, model, mock, api_key=None, jurisdiction_label=None):
        captured["api_key"] = api_key
        from ai.shared.schema import FinalAnswer
        return FinalAnswer(
            answer_text="ok", citations=[], confidence=retrieval.confidence,
            abstained=False, disclaimer="This is informational, not legal advice."
        )

    class FakeService(service_module.AIService):
        def retrieve(self, query, classification, top_k):
            from ai.person_b_retrieval.schema import MatchedChunk, RetrievalResult
            chunk = MatchedChunk(
                chunk_id="c1", text="source", act_name="Act", section="1",
                jurisdiction="India", similarity_score=0.9
            )
            r = RetrievalResult(query=query, matched_chunks=[chunk], confidence=0.9, should_abstain=False)
            return r, {"c1": {"source_url": "https://example.com"}}

    monkeypatch.setattr(service_module, "generate_answer", fake_generate_answer)
    monkeypatch.setattr(service_module.settings, "groq_api_key", "test-key")
    result = FakeService().answer("test", None, 1, scope="IN")

    assert captured["api_key"] == "test-key"
    assert result["answer_text"] == "ok"


# ---------------------------------------------------------------------------
# ai/translation.py wiring — the multilingual request/response edge
# ---------------------------------------------------------------------------

def test_answer_translates_query_and_answer_for_hindi(monkeypatch):
    from app.services import ai_service as service_module

    captured = {}

    def fake_generate_answer(retrieval, model, mock, api_key=None, jurisdiction_label=None):
        captured["retrieval_query"] = retrieval.query  # what the LLM saw
        from ai.shared.schema import FinalAnswer
        return FinalAnswer(
            answer_text="Yes, it can be patented.", citations=[],
            confidence=retrieval.confidence, abstained=False,
            disclaimer="This is informational, not legal advice.",
        )

    class FakeService(service_module.AIService):
        def retrieve(self, query, classification, top_k):
            captured["retrieve_query"] = query
            from ai.person_b_retrieval.schema import MatchedChunk, RetrievalResult
            chunk = MatchedChunk(
                chunk_id="c1", text="source", act_name="The Patents Act, 1970",
                section="3", jurisdiction="india", similarity_score=0.9,
            )
            r = RetrievalResult(query=query, matched_chunks=[chunk],
                                 confidence=0.9, should_abstain=False)
            return r, {"c1": {"source_url": "https://example.com"}}

    monkeypatch.setattr(service_module, "generate_answer", fake_generate_answer)
    result = FakeService().answer(
        "क्या यह पेटेंट हो सकता है?", None, 1, language="hi", scope="IN"
    )

    assert result["language"] == "hi"
    # No Bhashini credentials configured in tests -> NullTranslator ->
    # translated=False, text stays English rather than being fabricated.
    assert result["translated"] is False
    assert result["answer_text"] == "Yes, it can be patented."
    # Retrieval and generation both ran on the (untranslated, since no
    # backend) query -- the point being it's the SAME text passed through
    # to both, not that it changed language here.
    assert captured["retrieve_query"] == captured["retrieval_query"]
    # Citations are never touched by translation.
    assert result["citations"] == [] or all(
        "act_name" in c for c in result["citations"]
    )


def test_answer_english_query_is_untranslated_and_flagged_translated_true(monkeypatch):
    from app.services import ai_service as service_module

    def fake_generate_answer(retrieval, model, mock, api_key=None, jurisdiction_label=None):
        from ai.shared.schema import FinalAnswer
        return FinalAnswer(
            answer_text="Yes.", citations=[], confidence=retrieval.confidence,
            abstained=False, disclaimer="This is informational, not legal advice.",
        )

    class FakeService(service_module.AIService):
        def retrieve(self, query, classification, top_k):
            from ai.person_b_retrieval.schema import MatchedChunk, RetrievalResult
            chunk = MatchedChunk(
                chunk_id="c1", text="source", act_name="Act", section="1",
                jurisdiction="india", similarity_score=0.9,
            )
            r = RetrievalResult(query=query, matched_chunks=[chunk],
                                 confidence=0.9, should_abstain=False)
            return r, {"c1": {"source_url": "https://example.com"}}

    monkeypatch.setattr(service_module, "generate_answer", fake_generate_answer)
    result = FakeService().answer("Can this be patented?", None, 1, scope="IN")

    assert result["language"] == "en"
    assert result["translated"] is True  # trivial identity, not a degraded case
    assert result["answer_text"] == "Yes."


def test_query_endpoint_accepts_language_field(monkeypatch):
    from app.api import routes

    captured = {}

    class FakeService:
        def answer(self, query, classification, top_k, compliance_facts=None,
                   consented_acts=None, language=None, scope=None):
            captured["language"] = language
            return {
                "answer_text": "ok", "citations": [], "confidence": 0.5,
                "abstained": False, "disclaimer": "d", "sources": [],
                "language": language or "en", "translated": True,
            }

    monkeypatch.setattr(routes, "ai_service", FakeService())
    response = client.post(
        "/api/v1/query", json={"query": "क्या यह पेटेंट हो सकता है?", "language": "hi"}
    )
    assert response.status_code == 200
    assert captured["language"] == "hi"
    assert response.json()["language"] == "hi"


# ---------------------------------------------------------------------------
# /api/v1/updates — auto-update pipeline review gate
# ---------------------------------------------------------------------------

def test_updates_pending_lists_entries(monkeypatch):
    from app.api import updates_routes

    class FakeUpdatesService:
        def pending(self):
            return [{
                "id": "e1", "source_name": "src", "url": "https://example.test/a.pdf",
                "act_name": "The Patents Act, 1970", "jurisdiction": "india",
                "tier": "mandatory_review", "reason": "first time seen",
                "status": "pending", "needs_audit": False,
                "created_at": "2026-01-01T00:00:00+00:00", "decided_at": None,
                "decided_by": None, "notes": None, "ingest_result": None,
            }]

    monkeypatch.setattr(updates_routes, "updates_service", FakeUpdatesService())
    response = client.get("/api/v1/updates/pending")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == "e1"
    assert body[0]["status"] == "pending"


def test_updates_approve_success(monkeypatch):
    from app.api import updates_routes

    class FakeUpdatesService:
        def approve(self, entry_id, *, decided_by, notes=None):
            assert entry_id == "e1"
            # The identity is the authenticated one, never the body.
            assert decided_by == "test-reviewer"
            assert notes == "ok"

    monkeypatch.setattr(updates_routes, "updates_service", FakeUpdatesService())
    response = client.post(
        "/api/v1/updates/e1/approve",
        json={"notes": "ok"},
        headers=auth_headers("REVIEWER"),
    )
    assert response.status_code == 200
    assert response.json() == {
        "id": "e1", "status": "approved", "decided_by": "test-reviewer",
    }


def test_updates_approve_conflict_returns_409(monkeypatch):
    from app.api import updates_routes
    from ai.updates.queue import ReviewQueueError

    class FakeUpdatesService:
        def approve(self, entry_id, *, decided_by, notes=None):
            raise ReviewQueueError(f"entry {entry_id!r} is already approved")

    monkeypatch.setattr(updates_routes, "updates_service", FakeUpdatesService())
    response = client.post(
        "/api/v1/updates/e1/approve", json={}, headers=auth_headers("REVIEWER")
    )
    assert response.status_code == 409


def test_updates_publish_missing_entry_returns_404(monkeypatch):
    from app.api import updates_routes

    class FakeUpdatesService:
        def publish_entry(self, entry_id):
            raise ValueError(f"no review-queue entry {entry_id!r}")

    monkeypatch.setattr(updates_routes, "updates_service", FakeUpdatesService())
    response = client.post(
        "/api/v1/updates/missing/publish", headers=auth_headers("ADMIN", "test-admin")
    )
    assert response.status_code == 404


def test_updates_check_now_returns_summary(monkeypatch):
    from app.api import updates_routes

    class FakeUpdatesService:
        def check_now(self, *, auto_ingest=None):
            return {"checked": 2, "entries": [
                {"id": "e1", "tier": "mandatory_review"},
                {"id": "e2", "tier": "auto_publish"},
            ]}

    monkeypatch.setattr(updates_routes, "updates_service", FakeUpdatesService())
    response = client.post(
        "/api/v1/updates/check-now", json={}, headers=auth_headers("ADMIN", "test-admin")
    )
    assert response.status_code == 200
    body = response.json()
    assert body["checked"] == 2
    assert len(body["entries"]) == 2


# ---------------------------------------------------------------------------
# /api/v1/patent-cases — patent preparation and tracking
# ---------------------------------------------------------------------------

def test_patent_cases_create_and_get(monkeypatch):
    from app.api import patent_prep_routes

    class FakeService:
        def create_case(self, intake_dict):
            assert intake_dict["applicant_name"] == "Jane Doe"
            return "case-1"

        def get_case(self, case_id):
            assert case_id == "case-1"
            return {
                "id": "case-1", "intake": {"applicant_name": "Jane Doe"},
                "status": "intake", "precheck_result": None, "forms_result": None,
                "handoff_result": None, "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }

    monkeypatch.setattr(patent_prep_routes, "patent_prep_service", FakeService())
    response = client.post("/api/v1/patent-cases", json={
        "applicant_name": "Jane Doe", "inventors": ["Jane Doe"],
        "invention_title": "A formulation",
    })
    assert response.status_code == 200
    assert response.json() == {"id": "case-1", "status": "intake"}

    response = client.get("/api/v1/patent-cases/case-1")
    assert response.status_code == 200
    assert response.json()["status"] == "intake"


def test_patent_cases_get_missing_returns_404(monkeypatch):
    from app.api import patent_prep_routes
    from ai.patent_prep.tracker import CaseNotFound

    class FakeService:
        def get_case(self, case_id):
            raise CaseNotFound(f"no case {case_id!r}")

    monkeypatch.setattr(patent_prep_routes, "patent_prep_service", FakeService())
    response = client.get("/api/v1/patent-cases/missing")
    assert response.status_code == 404


def test_patent_cases_precheck(monkeypatch):
    from app.api import patent_prep_routes

    class FakeService:
        def precheck(self, case_id):
            assert case_id == "case-1"
            return {"clear_to_draft": True, "reasons_not_clear": [], "blocking": [],
                     "critical_open_questions": [], "compliance": {}}

    monkeypatch.setattr(patent_prep_routes, "patent_prep_service", FakeService())
    response = client.post("/api/v1/patent-cases/case-1/precheck")
    assert response.status_code == 200
    assert response.json()["clear_to_draft"] is True


def test_patent_cases_draft_forms(monkeypatch):
    from app.api import patent_prep_routes

    class FakeService:
        def draft_forms(self, case_id):
            return {"form_1": {"form_id": "Form 1"}, "form_3": {"form_id": "Form 3"}}

    monkeypatch.setattr(patent_prep_routes, "patent_prep_service", FakeService())
    response = client.post("/api/v1/patent-cases/case-1/draft-forms")
    assert response.status_code == 200
    assert set(response.json()) == {"form_1", "form_3"}


def test_patent_cases_deadlines(monkeypatch):
    from app.api import patent_prep_routes

    class FakeService:
        def deadlines(self, case_id):
            return [{"rule_id": "convention_priority", "status": "upcoming"}]

    monkeypatch.setattr(patent_prep_routes, "patent_prep_service", FakeService())
    response = client.get("/api/v1/patent-cases/case-1/deadlines")
    assert response.status_code == 200
    assert response.json()[0]["rule_id"] == "convention_priority"


def test_patent_cases_handoff(monkeypatch):
    from app.api import patent_prep_routes

    class FakeService:
        def handoff(self, case_id, *, recipient, notes=None):
            assert recipient == "agent@example.test"
            return {"generated_at": "2026-01-01", "intake": {}, "precheck": {},
                     "forms": {}, "deadlines": [], "handoff_notes": []}

    monkeypatch.setattr(patent_prep_routes, "patent_prep_service", FakeService())
    response = client.post(
        "/api/v1/patent-cases/case-1/handoff",
        json={"recipient": "agent@example.test", "notes": "ready"},
    )
    assert response.status_code == 200
    assert "handoff_notes" in response.json()


def test_patent_cases_update_status(monkeypatch):
    from app.api import patent_prep_routes

    class FakeService:
        def update_status(self, case_id, status, *, detail=None):
            assert status == "filed"

    monkeypatch.setattr(patent_prep_routes, "patent_prep_service", FakeService())
    response = client.post(
        "/api/v1/patent-cases/case-1/status", json={"status": "filed"}
    )
    assert response.status_code == 200
    assert response.json() == {"id": "case-1", "status": "filed"}


# ---------------------------------------------------------------------------
# Jurisdiction scope — the hard retrieval filter behind the India /
# International / Both toggle
# ---------------------------------------------------------------------------

def _scope_service(monkeypatch, captured):
    """An AIService whose retrieval is recorded rather than run, so a test can
    assert on what jurisdiction filter each call went out with."""
    from app.services import ai_service as service_module

    def fake_generate_answer(retrieval, model, mock, api_key=None, jurisdiction_label=None):
        captured.setdefault("labels", []).append(jurisdiction_label)
        from ai.shared.schema import FinalAnswer
        return FinalAnswer(
            answer_text=f"Answer for {jurisdiction_label}.",
            citations=[],
            confidence=retrieval.confidence,
            abstained=False,
            disclaimer="This is informational, not legal advice.",
        )

    class FakeService(service_module.AIService):
        def retrieve(self, query, classification, top_k):
            captured.setdefault("jurisdictions", []).append(
                classification.jurisdiction if classification else None
            )
            from ai.person_b_retrieval.schema import MatchedChunk, RetrievalResult
            chunk = MatchedChunk(
                chunk_id=f"c-{classification.jurisdiction}", text="source",
                act_name="Act", section="1",
                jurisdiction=classification.jurisdiction, similarity_score=0.9,
            )
            r = RetrievalResult(query=query, matched_chunks=[chunk],
                                confidence=0.9, should_abstain=False)
            return r, {chunk.chunk_id: {"source_url": None}}

    monkeypatch.setattr(service_module, "generate_answer", fake_generate_answer)
    return FakeService()


def test_scope_both_runs_two_separately_filtered_retrievals(monkeypatch):
    captured = {}
    result = _scope_service(monkeypatch, captured).answer("q", None, 1, scope="BOTH")

    # Two calls, one per jurisdiction — never one merged call, which is what
    # would let the two legal systems compete in a single ranking.
    assert captured["jurisdictions"] == ["india", "international"]
    assert captured["labels"] == ["India", "International"]
    assert result["scope"] == "BOTH"
    assert [a["scope"] for a in result["answers"]] == ["IN", "INTL"]
    # The flat answer_text carries both, under headings, never run together.
    assert "India" in result["answer_text"]
    assert "International" in result["answer_text"]


def test_scope_single_filters_to_that_jurisdiction_only(monkeypatch):
    captured = {}
    result = _scope_service(monkeypatch, captured).answer("q", None, 1, scope="INTL")

    assert captured["jurisdictions"] == ["international"]
    assert captured["labels"] == ["International"]
    assert result["scope"] == "INTL"
    assert len(result["answers"]) == 1
    assert result["answer_text"] == "Answer for International."


def test_scope_falls_back_to_classification_jurisdiction(monkeypatch):
    """A caller written before the toggle existed passed the jurisdiction on
    the classification. Widening those queries to BOTH would change their
    answers, so an unset scope honours the classification."""
    from ai.person_b_retrieval.schema import Classification

    captured = {}
    service = _scope_service(monkeypatch, captured)
    result = service.answer("q", Classification(jurisdiction="india"), 1)

    assert captured["jurisdictions"] == ["india"]
    assert result["scope"] == "IN"


def test_scope_defaults_to_both_when_nothing_says_otherwise(monkeypatch):
    captured = {}
    result = _scope_service(monkeypatch, captured).answer("q", None, 1)
    assert result["scope"] == "BOTH"
    assert captured["jurisdictions"] == ["india", "international"]


def test_empty_scope_retrieval_names_the_other_scope_instead_of_guessing(monkeypatch):
    """Low-similarity retrieval inside the selected scope must not be topped
    up by the model — it must say so and point at the scope that may cover
    the question."""
    from app.services import ai_service as service_module

    def exploding_generate_answer(*a, **kw):  # pragma: no cover - must not run
        raise AssertionError("generation ran despite insufficient retrieval")

    class FakeService(service_module.AIService):
        def retrieve(self, query, classification, top_k):
            from ai.person_b_retrieval.schema import RetrievalResult
            return RetrievalResult(query=query, matched_chunks=[],
                                   confidence=0.0, should_abstain=True), {}

    monkeypatch.setattr(service_module, "generate_answer", exploding_generate_answer)
    result = FakeService().answer("budapest treaty deposit", None, 1, scope="IN")

    block = result["answers"][0]
    assert block["insufficient"] is True
    assert block["abstained"] is True
    assert block["generation"] == "none"
    assert "International" in block["answer_text"]
    assert result["abstained"] is True


def test_query_endpoint_passes_scope_through(monkeypatch):
    from app.api import routes

    captured = {}

    class FakeService:
        def answer(self, query, classification, top_k, compliance_facts=None,
                   consented_acts=None, language=None, scope=None):
            captured["scope"] = scope
            return {
                "answer_text": "ok", "citations": [], "confidence": 0.5,
                "abstained": False, "disclaimer": "d", "sources": [],
                "scope": scope or "BOTH", "answers": [],
            }

    monkeypatch.setattr(routes, "ai_service", FakeService())
    response = client.post("/api/v1/query", json={"query": "can I patent this?", "scope": "INTL"})
    assert response.status_code == 200
    assert captured["scope"] == "INTL"
    assert response.json()["scope"] == "INTL"


def test_query_endpoint_rejects_an_unknown_scope():
    response = client.post("/api/v1/query", json={"query": "anything at all", "scope": "MARS"})
    assert response.status_code == 422


def test_jurisdiction_rule_is_injected_into_the_prompt():
    from ai.person_c_generation.generate import build_prompt, jurisdiction_rule
    from ai.person_b_retrieval.schema import MatchedChunk, RetrievalResult

    retrieval = RetrievalResult(
        query="q",
        matched_chunks=[MatchedChunk("c1", "text", "Act", "1", "india", 0.9)],
        confidence=0.9, should_abstain=False,
    )
    template = "{jurisdiction_rule}\nSOURCES:\n{chunks}\nQUESTION:\n{query}"

    prompt = build_prompt(template, retrieval, "India")
    assert "under India law only" in prompt
    assert "any other jurisdiction" in prompt

    # No label -> no rule, and no leftover placeholder in the prompt.
    assert jurisdiction_rule(None) == ""
    assert "{jurisdiction_rule}" not in build_prompt(template, retrieval)


def test_lazy_resources_are_built_once_under_concurrent_requests(monkeypatch):
    """FastAPI runs sync endpoints in a threadpool, so simultaneous first
    requests race the lazy initialisation. Chroma does not survive two
    PersistentClients opening the same directory at once — the symptom is a
    503 for the first couple of visitors after a cold start and success for
    everyone after. Build exactly once, however many callers arrive."""
    import threading
    from app.services.ai_service import AIService

    service = AIService()
    builds = []
    barrier = threading.Barrier(8)

    class SlowStore:
        def __init__(self):
            # Widen the window a real constructor leaves open.
            builds.append(1)
            threading.Event().wait(0.02)

    monkeypatch.setattr("app.services.ai_service.VectorStore", lambda *a, **k: SlowStore())

    stores = []

    def hit():
        barrier.wait()
        stores.append(service.store)

    threads = [threading.Thread(target=hit) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(builds) == 1, f"store was constructed {len(builds)} times"
    assert len({id(s) for s in stores}) == 1, "callers got different store instances"


def test_compliance_screening_runs_even_with_no_facts_and_no_classification(monkeypatch):
    """The ABS screening exists for the applicant who does not know to ask for
    it, so it must fire on every query — including one that supplied no
    formulation facts at all. Before the jurisdiction moved onto the scope,
    the UI always sent jurisdiction="india" and that is what kept this alive;
    nothing in the request carries it now, so the service has to."""
    from app.services import ai_service as service_module

    captured = {}

    def fake_generate_answer(retrieval, model, mock, api_key=None, jurisdiction_label=None):
        from ai.shared.schema import FinalAnswer
        return FinalAnswer(answer_text="ok", citations=[], confidence=0.9,
                           abstained=False, disclaimer="d")

    class FakeService(service_module.AIService):
        def retrieve(self, query, classification, top_k):
            from ai.person_b_retrieval.schema import MatchedChunk, RetrievalResult
            chunk = MatchedChunk("c1", "text", "Act", "1", "india", 0.9)
            return RetrievalResult(query=query, matched_chunks=[chunk],
                                   confidence=0.9, should_abstain=False), {"c1": {}}

        def compliance(self, classification, facts):
            captured["jurisdiction"] = classification.jurisdiction if classification else None
            return {"headline": "screened"}

    monkeypatch.setattr(service_module, "generate_answer", fake_generate_answer)
    result = FakeService().answer("can I patent this?", None, 1, scope="INTL")

    assert captured["jurisdiction"] == "india"
    assert result["compliance"] == {"headline": "screened"}
