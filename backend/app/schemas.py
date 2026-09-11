from typing import Literal

from pydantic import BaseModel, Field, ConfigDict

Jurisdiction = Literal["india", "international"]

# The jurisdiction scope a query is answered under. This is a hard filter on
# retrieval, not a presentation flag: "IN" and "INTL" restrict which chunks
# are eligible before generation starts, and "BOTH" runs the two retrievals
# separately rather than blending them into one similarity ranking (see
# app/services/ai_service.py). The corpus is already tagged with these
# jurisdictions at ingest time -- ai/corpus.yaml's `jurisdiction` field is
# copied onto every chunk's Chroma metadata by ai/store.py -- so the scope
# maps straight onto that metadata and needs no re-ingestion.
Scope = Literal["IN", "INTL", "BOTH"]

# Scope code -> the `jurisdiction` value carried on chunk metadata.
SCOPE_JURISDICTION: dict[str, str] = {"IN": "india", "INTL": "international"}
# Scope code -> the label shown to the user and given to the generator.
SCOPE_LABEL: dict[str, str] = {"IN": "India", "INTL": "International"}
FormulationType = Literal[
    "classical", "proprietary", "new_drug",
    "phytopharmaceutical", "aahar", "cosmetic",
]
SourceOrganism = Literal["plant", "microbial", "animal", "mixed"]


class ClassificationRequest(BaseModel):
    formulation_type: FormulationType | None = None
    source_organism: SourceOrganism | None = None
    jurisdiction: Jurisdiction | None = None


ApplicantCategory = Literal[
    "indian_individual", "indian_entity", "foreign_controlled_entity",
    "non_resident_indian", "foreign_national",
]
ResourceOrigin = Literal["india", "outside_india", "mixed"]
ResourceCultivation = Literal["cultivated", "wild_collected", "mixed"]


class ComplianceFacts(BaseModel):
    """Facts the classifier cannot infer but the Biological Diversity Act
    turns on.

    All optional, all defaulting to None. None means "unknown" and produces
    a follow-up question in the response; it must never be read as False.
    Whether the applicant is a section 3(2) person is not something a
    question about a formulation can reveal, so the API has to be able to
    carry it separately and to admit when it has not been told.
    """
    applicant_category: ApplicantCategory | None = None
    resource_origin: ResourceOrigin | None = None
    resource_cultivation: ResourceCultivation | None = None
    practitioner_is_registered_ayush: bool | None = None
    uses_biological_material: bool | None = None
    uses_codified_tk: bool | None = None
    seeking_ipr: bool | None = None
    ipr_already_granted: bool | None = None
    intends_commercialisation: bool | None = None
    formulation_name: str | None = Field(default=None, max_length=200)
    ingredients: list[str] | None = Field(default=None, max_length=50)


class QueryRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=3, max_length=4000)
    classification: ClassificationRequest | None = None
    top_k: int = Field(default=5, ge=1, le=10)
    compliance_facts: ComplianceFacts | None = None
    # act_name strings (exact match, see ai/corpus.yaml's `access` field)
    # the requester consents to being answered from if retrieval matches a
    # licensed source. DPDP consent has to be for a specified purpose, so
    # this is a named list, not one blanket "yes to licensed content" flag.
    # No document in the corpus is currently licensed, so this is normally
    # empty — the gate exists for when one is added.
    consent_licensed_acts: list[str] = Field(default_factory=list, max_length=50)
    # Explicit source-language override, e.g. "hi", "ta" — see
    # ai/translation.py. Omit to auto-detect from the query text; the
    # detector is a Unicode-script heuristic (Devanagari, Tamil, ...), not
    # a language-ID model, so pass this when the caller actually knows the
    # language (a language picker in the UI, say).
    language: str | None = Field(default=None, max_length=10)
    # Jurisdiction scope. None means "not stated by the caller": the service
    # then falls back to classification.jurisdiction if that was given, and
    # to "BOTH" otherwise, so a client written before this field existed
    # keeps the behaviour it had.
    scope: Scope | None = None


class CitationResponse(BaseModel):
    act_name: str
    section: str
    source_url: str | None = None


class SourceResponse(BaseModel):
    chunk_id: str
    act_name: str
    section: str
    jurisdiction: str
    similarity_score: float
    source_url: str | None = None


class ScopedAnswer(BaseModel):
    """One jurisdiction's answer, grounded only in that jurisdiction's chunks.

    A "BOTH" query produces two of these — two independently filtered
    retrievals and two independent generation calls — so a Patents Act
    clause and a PCT rule can never end up stitched into one paragraph or
    crowd each other out of a single similarity ranking. The UI renders them
    as separate labelled blocks for the same reason.
    """
    scope: Scope
    label: str
    answer_text: str
    citations: list[CitationResponse] = Field(default_factory=list)
    sources: list[SourceResponse] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    abstained: bool
    # False when the active embedder's similarity does not support a
    # meaningful confidence (the offline TF-IDF stand-in). The number is
    # still the real score; what is missing is any reason to read it as a
    # relevance probability. See AIService.confidence_calibrated.
    confidence_calibrated: bool = True
    generation: str | None = None
    # True when nothing in this jurisdiction matched well enough to answer
    # from. Distinct from a plain abstention only in what the UI can offer:
    # the other scope may well cover the question, so the message names it.
    insufficient: bool = False
    # True when there is no index at all, rather than an index that failed to
    # cover the question. An unbuilt corpus abstains on everything at 0%,
    # which is indistinguishable from a well-behaved out-of-scope answer
    # unless the response says which one happened — so it says.
    corpus_empty: bool = False


class QueryResponse(BaseModel):
    answer_text: str
    citations: list[CitationResponse]
    confidence: float = Field(ge=0, le=1)
    abstained: bool
    disclaimer: str
    sources: list[SourceResponse] = Field(default_factory=list)
    # Left loosely typed on purpose: the shape is owned by
    # ai/compliance and adding an obligation field should not require a
    # coordinated edit here. The AI-layer dataclasses are the contract.
    compliance: dict | None = None
    # act_names whose citation was withheld because retrieval matched a
    # licensed source the request had not consented to (see
    # consent_licensed_acts on QueryRequest and ai/audit.py). Empty in the
    # common case where nothing licensed matched.
    licensed_sources_withheld: list[str] = Field(default_factory=list)
    # The audit_log row id for this query (see ai/audit.py) — carried back
    # so a support/compliance flow can look the request up without a
    # separate correlation id scheme.
    audit_id: str | None = None
    # How answer_text was produced: "live" (a real model call), "mock" (no
    # GROQ_API_KEY configured, so the prose is a deterministic canned
    # stand-in — the citations, sources and compliance screening around it
    # are still real), or "none" (the system abstained, so no generation
    # ran at all). The UI must show this: canned prose passed off as a
    # generated answer is the failure mode this whole project exists to
    # avoid.
    generation: str | None = None
    # See ScopedAnswer.confidence_calibrated. Reported at both levels so a
    # caller reading only the flat fields still learns that the confidence
    # beside them is not a calibrated one.
    confidence_calibrated: bool = True
    # The language answer_text/disclaimer are in — the request's explicit
    # `language`, or the detected one. See ai/translation.py.
    language: str = "en"
    # False means answer_text/disclaimer are still English: no translation
    # backend is configured (ai.translation.NullTranslator) or the
    # translation attempt failed, not that the answer itself is wrong.
    translated: bool = True
    # The scope the answer was actually produced under, resolved from the
    # request. Echoed back so the UI can label the answer with what was
    # used rather than with whatever the toggle happens to say now.
    scope: Scope = "BOTH"
    # Per-jurisdiction answers. One entry for "IN"/"INTL", two for "BOTH".
    # The flat answer_text/citations/sources above stay populated for
    # callers that predate this field: they carry the same content, with
    # each jurisdiction's block explicitly headed.
    answers: list[ScopedAnswer] = Field(default_factory=list)


class CorpusResponse(BaseModel):
    collection: str
    chunks: int
    # Chunk counts per jurisdiction, i.e. how much corpus each scope of the
    # toggle actually has behind it. Empty if the count could not be taken.
    jurisdictions: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Auto-update pipeline / review gate (ai/updates)
# ---------------------------------------------------------------------------

class ReviewQueueEntry(BaseModel):
    id: str
    source_name: str
    url: str
    act_name: str
    jurisdiction: str | None = None
    tier: str
    reason: str
    status: str
    needs_audit: bool
    created_at: str
    decided_at: str | None = None
    decided_by: str | None = None
    notes: str | None = None
    ingest_result: str | None = None


class ReviewDecisionRequest(BaseModel):
    """A reviewer's note on a decision — and nothing else.

    `decided_by` used to live here, as a free-text string the client chose.
    It is deliberately absent now: the identity written into the audit
    trail comes from the verified bearer token (see app/auth.py), and a
    field the server overrides would mislead the next person to read this
    schema into thinking the client still sets it.
    """
    notes: str | None = Field(default=None, max_length=2000)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str
    role: str


class IdentityResponse(BaseModel):
    username: str
    role: str


class CheckNowRequest(BaseModel):
    # Overrides settings.updates_auto_ingest for this one call only.
    # None (default) means "use the configured default".
    auto_ingest: bool | None = None


class CheckNowResponse(BaseModel):
    checked: int
    entries: list[dict]


class PublishResponse(BaseModel):
    ok: bool
    chunks: int | None = None
    embedder: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Patent preparation and tracking (ai/patent_prep) — separate from the RAG
# core; these fields mirror ai.patent_prep.intake.CaseIntake and
# ComplianceFacts/ClassificationRequest above verbatim on purpose, so no
# translation layer has to be kept in sync across the three.
# ---------------------------------------------------------------------------

class CaseIntakeRequest(BaseModel):
    applicant_name: str | None = None
    applicant_address: str | None = None
    inventors: list[str] = Field(default_factory=list, max_length=20)
    invention_title: str | None = None
    abstract: str | None = Field(default=None, max_length=5000)

    formulation_type: FormulationType | None = None
    source_organism: SourceOrganism | None = None
    jurisdiction: Jurisdiction | None = None
    applicant_category: ApplicantCategory | None = None
    practitioner_is_registered_ayush: bool | None = None
    resource_origin: ResourceOrigin | None = None
    resource_cultivation: ResourceCultivation | None = None
    uses_biological_material: bool | None = None
    uses_codified_tk: bool | None = None
    seeking_ipr: bool | None = None
    ipr_already_granted: bool | None = None
    intends_commercialisation: bool | None = None
    formulation_name: str | None = Field(default=None, max_length=200)
    ingredients: list[str] | None = Field(default=None, max_length=50)

    # ISO 8601 dates, e.g. "2025-01-15" — anchors for deadline tracking
    priority_date: str | None = None
    filing_date: str | None = None
    fer_issued_date: str | None = None
    grant_date: str | None = None


class CaseResponse(BaseModel):
    id: str
    intake: dict
    status: str
    precheck_result: dict | None = None
    forms_result: dict | None = None
    handoff_result: dict | None = None
    created_at: str
    updated_at: str


class CaseEventResponse(BaseModel):
    ts: str
    event: str
    detail: str | None = None


class CaseStatusUpdateRequest(BaseModel):
    status: str = Field(min_length=1, max_length=50)
    detail: str | None = Field(default=None, max_length=2000)


class HandoffRequest(BaseModel):
    recipient: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------------------
# Knowledge Sources, system status, Evidence, Product Assessment
#
# These four are read-only views over what the pipeline already produces.
# None of them introduces a second way to get an answer -- see
# app/services/ai_service.py.
# ---------------------------------------------------------------------------

class CorpusDocument(BaseModel):
    act_name: str | None = None
    file: str | None = None
    # "ingested" — the text is in the index and answers can cite it.
    # "pending"  — the knowledge graph cites this instrument but we do not
    #              hold the source. An obligation citing it still fires (the
    #              duty exists in law either way) but is reported as
    #              uncitable. Shown rather than hidden, because the gap
    #              between what we reason about and what we can quote is
    #              exactly what a reader should be able to check.
    status: str = "unknown"
    jurisdiction: str | None = None
    instrument_type: str | None = None
    effective_date: str | None = None
    # None means the manifest has no verified public link for this
    # document. The UI says so; it does not invent one.
    source_url: str | None = None
    access: str = "public"
    chunks: int = 0
    section_effective_dates: dict[str, str] = Field(default_factory=dict)


class CorpusLibraryResponse(BaseModel):
    documents: list[CorpusDocument] = Field(default_factory=list)
    total: int = 0
    ingested: int = 0
    pending: int = 0
    # How many ingested documents carry a verifiable official link. Exposed
    # as a number rather than left implicit so the shortfall is visible in
    # the product, not only in the README.
    with_source_url: int = 0


class StatusResponse(BaseModel):
    """What is running, as opposed to what is configured."""
    model_config = ConfigDict(extra="allow")

    collection: str | None = None
    chunks: int = 0
    index_ready: bool = False
    configured_embedding_model: str | None = None
    # The embedder is chosen by the artifact sitting beside the index, not
    # by the configured name — so these two can legitimately differ, and
    # the difference is worth showing.
    active_embedding_model: str | None = None
    embedding_dimension: int | None = None
    embedding_is_fallback: bool | None = None
    generation_mode: str = "mock"
    llm_model: str | None = None
    translation_configured: bool = False
    abstain_threshold: float = 0.0
    default_top_k: int = 5
    audit_entries: int | None = None


class EvidenceChunk(BaseModel):
    chunk_id: str | None = None
    act_name: str | None = None
    section: str | None = None
    jurisdiction: str | None = None
    # None means the score was not recorded for this row, which is not the
    # same claim as a score of zero.
    similarity_score: float | None = None
    source_url: str | None = None
    text: str | None = None
    # False means the chunk this answer was built on is no longer in the
    # index — a later re-ingest removed or replaced it.
    still_in_corpus: bool = True


class EvidenceCitation(BaseModel):
    act_name: str | None = None
    section: str | None = None
    source_url: str | None = None
    # True when the cited provision appears among the chunks actually
    # retrieved for this answer. A citation that does not is the failure
    # mode this whole system is built to catch, so it is counted, not
    # assumed away.
    verified: bool = False


class EvidenceResponse(BaseModel):
    audit_id: str
    timestamp: str | None = None
    query_text: str | None = None
    jurisdiction: str | None = None
    formulation_type: str | None = None
    top_k: int | None = None
    confidence: float | None = None
    abstained: bool = False
    abstain_threshold: float = 0.0
    llm_model: str | None = None
    error: str | None = None
    chunks: list[EvidenceChunk] = Field(default_factory=list)
    citations: list[EvidenceCitation] = Field(default_factory=list)
    citations_verified: int = 0
    citations_total: int = 0
    licensed_acts_withheld: list[str] = Field(default_factory=list)
    # False means this answer predates per-chunk score recording.
    detail_recorded: bool = True


class AssessmentRequest(BaseModel):
    """A product screening, without a retrieval question in front of it.

    Same inputs the Ask page collects behind its facts accordion; this
    gives them their own entry point rather than requiring the user to
    think of a question first. The screening is the graph-driven
    compliance layer, which is not retrieval — see
    ai/compliance/abs.py.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    classification: ClassificationRequest | None = None
    facts: ComplianceFacts | None = None


class AssessmentResponse(BaseModel):
    # Loosely typed for the same reason QueryResponse.compliance is: the
    # shape belongs to ai/compliance, and adding an obligation field should
    # not need a coordinated edit here.
    compliance: dict | None = None
    # GREEN / AMBER / RED, derived in the route from the report itself —
    # see app/api/assess_routes.py for exactly what each one means.
    status: str = "UNKNOWN"
    status_reason: str = ""
