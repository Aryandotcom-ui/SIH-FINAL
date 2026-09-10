"""Read-only views over what the pipeline already produced.

Knowledge Sources, system status, Evidence and Product Assessment all live
here. None of them is a second way to get an answer: three read data the
system has already computed, and the fourth (assess) calls the same
compliance screening that every query already runs, just without requiring
the user to think of a question first.

Keeping them out of routes.py is deliberate — routes.py owns the retrieval
and generation path, and a trust surface that could quietly start
generating would defeat its own purpose.
"""

from typing import Any

from fastapi import APIRouter, HTTPException

from ..schemas import (
    AssessmentRequest,
    AssessmentResponse,
    CorpusDocument,
    CorpusLibraryResponse,
    EvidenceResponse,
    StatusResponse,
)
from ..services.ai_service import ai_service
from ai.person_b_retrieval.schema import Classification

router = APIRouter(tags=["Insight"])


@router.get("/corpus/documents", response_model=CorpusLibraryResponse)
def corpus_documents() -> CorpusLibraryResponse:
    """The corpus library: every document the manifest lists.

    Includes `pending` entries — instruments the knowledge graph cites but
    whose text we do not hold. Hiding them would overstate what the system
    can quote, and the gap between what it reasons about and what it can
    cite is precisely what a reader should be able to check.
    """
    try:
        documents = ai_service.corpus_documents()
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"Corpus manifest unavailable: {exc}"
        ) from exc

    ingested = [d for d in documents if d.get("status") == "ingested"]
    return CorpusLibraryResponse(
        documents=[CorpusDocument(**d) for d in documents],
        total=len(documents),
        ingested=len(ingested),
        pending=sum(1 for d in documents if d.get("status") == "pending"),
        # Counted over ingested documents only: a `pending` entry has no
        # text in the index, so a missing link there is a different (and
        # much less interesting) shortfall than one on a document we are
        # actively answering from.
        with_source_url=sum(1 for d in ingested if d.get("source_url")),
    )


@router.get("/status", response_model=StatusResponse)
def status() -> StatusResponse:
    """What is actually running.

    Never 503s. This is the endpoint you check when something else is
    failing, so it degrades to reporting the failure rather than becoming
    another thing that is down.
    """
    return StatusResponse(**ai_service.status())


@router.get("/evidence/{audit_id}", response_model=EvidenceResponse)
def evidence(audit_id: str) -> EvidenceResponse:
    """Why one specific answer came out the way it did.

    Reads the audit row written at answer time; nothing is re-retrieved.
    Ranking the query again today would rank it against today's corpus,
    and showing that as the reason for an earlier answer would be a
    fabrication shaped like an explanation.
    """
    try:
        found = ai_service.evidence(audit_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Evidence lookup failed: {exc}") from exc
    if found is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No audit entry with that id. Entries are purged on the "
                "configured retention schedule, so an old link can expire."
            ),
        )
    return EvidenceResponse(**found)


def _screening_status(report: dict[str, Any] | None) -> tuple[str, str]:
    """Reduce a compliance report to GREEN / AMBER / RED.

    The bands are about what the user must *do*, not about how bad their
    situation is:

        RED    — at least one obligation blocks the grant of the IP right.
                 Something must be discharged before the application can
                 succeed.
        AMBER  — obligations apply but none blocks a grant, OR the
                 screening could not complete because a fact that decides
                 it is unknown.
        GREEN  — the graph fired nothing AND had enough information to
                 mean it.

    That last conjunction is the whole point. "Nothing triggered" and
    "nothing triggered because nobody told us the facts that decide it"
    must never share a colour: a green light on an unanswered critical
    question is the single most damaging thing this screen could show, and
    ComplianceReport.headline() already refuses to conflate the two.
    """
    if not report:
        return "UNKNOWN", "The screening could not be run."

    blocking = [o for o in report.get("obligations") or [] if o.get("blocks_grant")]
    if blocking:
        return "RED", (
            f"{len(blocking)} obligation(s) must be discharged before an IP right "
            "can be granted."
        )

    critical = [
        q for q in report.get("open_questions") or []
        if q.get("importance") == "critical"
    ]
    if report.get("triggered"):
        note = f"{len(report.get('obligations') or [])} regulatory obligation(s) apply."
        if critical:
            note += f" {len(critical)} question(s) below are still unanswered."
        return "AMBER", note

    if critical or report.get("provisional"):
        return "AMBER", (
            "Not enough information to screen this. This is NOT a finding that "
            "no obligations apply — the questions below decide it."
        )
    return "GREEN", "No biodiversity or IP-disclosure obligations were triggered."


@router.post("/assess", response_model=AssessmentResponse)
def assess(request: AssessmentRequest) -> AssessmentResponse:
    """Screen a product against the regulatory graph, with no question asked.

    This is the same `AIService.compliance()` path every query already
    runs. It is exposed on its own because the person who most needs an ABS
    flag is the one who does not know section 6 of the Biological Diversity
    Act exists, and therefore will never think to ask about it.
    """
    classification = None
    if request.classification:
        c = request.classification
        if any(v is not None for v in (c.formulation_type, c.source_organism, c.jurisdiction)):
            classification = Classification(
                formulation_type=c.formulation_type,
                source_organism=c.source_organism,
                jurisdiction=c.jurisdiction,
            )

    # exclude_none for the same reason routes.py does it: the compliance
    # layer distinguishes "unknown" (ask the user) from False, and an
    # explicitly serialised None would arrive where an absent key belongs.
    facts = request.facts.model_dump(exclude_none=True) if request.facts else None

    if classification is None and not facts:
        raise HTTPException(
            status_code=422,
            detail="Describe the product first — nothing was given to screen.",
        )

    # The graph's obligations are Indian biodiversity and IP-disclosure
    # duties, so the screening runs under India unless the caller named a
    # jurisdiction. Same default as the query path, for the same reason:
    # without it a submission carrying only facts would silently get no
    # screening at all.
    from dataclasses import replace

    scoped = (
        replace(classification, jurisdiction=classification.jurisdiction or "india")
        if classification is not None
        else Classification(jurisdiction="india")
    )

    report = ai_service.compliance(scoped, facts)
    band, reason = _screening_status(report)
    return AssessmentResponse(compliance=report, status=band, status_reason=reason)
