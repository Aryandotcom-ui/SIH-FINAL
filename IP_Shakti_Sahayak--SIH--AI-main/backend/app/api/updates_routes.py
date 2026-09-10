from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ..auth import Identity, require_role
from ..schemas import (
    CheckNowRequest,
    CheckNowResponse,
    PublishResponse,
    ReviewDecisionRequest,
    ReviewQueueEntry,
)
from ..services.updates_service import updates_service

router = APIRouter(prefix="/updates", tags=["Updates"])

# Reading the queue is not gated: what the system is proposing to ingest is
# exactly the kind of thing that should be inspectable, and the entries are
# public regulatory documents. Deciding is gated — see below.
Reviewer = Annotated[Identity, Depends(require_role("REVIEWER"))]
Admin = Annotated[Identity, Depends(require_role("ADMIN"))]


@router.get("/pending", response_model=list[ReviewQueueEntry])
def list_pending() -> list[ReviewQueueEntry]:
    """MANDATORY_REVIEW items awaiting a human's approve/reject decision."""
    return [ReviewQueueEntry(**e) for e in updates_service.pending()]


@router.get("/queued", response_model=list[ReviewQueueEntry])
def list_queued() -> list[ReviewQueueEntry]:
    """AUTO_PUBLISH / PUBLISH_THEN_AUDIT items the classifier cleared but
    that have not been ingested yet (the normal state when
    updates_auto_ingest is off)."""
    return [ReviewQueueEntry(**e) for e in updates_service.queued_for_ingest()]


@router.get("/needs-audit", response_model=list[ReviewQueueEntry])
def list_needs_audit() -> list[ReviewQueueEntry]:
    """Already-published PUBLISH_THEN_AUDIT items awaiting the
    after-the-fact human sign-off that tier promises."""
    return [ReviewQueueEntry(**e) for e in updates_service.needs_audit()]


@router.get("/history", response_model=list[ReviewQueueEntry])
def list_history(limit: int = 50) -> list[ReviewQueueEntry]:
    return [ReviewQueueEntry(**e) for e in updates_service.history(limit=limit)]


@router.post("/check-now", response_model=CheckNowResponse)
def check_now(request: CheckNowRequest, identity: Admin) -> CheckNowResponse:
    """Run one watch cycle synchronously. Useful for an on-demand refresh
    rather than waiting for the schedule.

    ADMIN rather than REVIEWER: this makes the process fetch external URLs
    on demand, which is an outbound network action against third-party
    government sites, not a judgement about a document already in hand.
    """
    try:
        result = updates_service.check_now(auto_ingest=request.auto_ingest)
        return CheckNowResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"check-now failed: {exc}") from exc


@router.post("/{entry_id}/approve")
def approve(entry_id: str, request: ReviewDecisionRequest, identity: Reviewer) -> dict:
    # decided_by comes from the verified token, never from the body. An
    # audit trail that records whatever name the client typed records
    # nothing.
    try:
        updates_service.approve(entry_id, decided_by=identity.username, notes=request.notes)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": entry_id, "status": "approved", "decided_by": identity.username}


@router.post("/{entry_id}/reject")
def reject(entry_id: str, request: ReviewDecisionRequest, identity: Reviewer) -> dict:
    try:
        updates_service.reject(entry_id, decided_by=identity.username, notes=request.notes)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": entry_id, "status": "rejected", "decided_by": identity.username}


@router.post("/{entry_id}/clear-audit")
def clear_audit(entry_id: str, request: ReviewDecisionRequest, identity: Reviewer) -> dict:
    try:
        updates_service.clear_audit(entry_id, decided_by=identity.username, notes=request.notes)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": entry_id, "needs_audit": False, "decided_by": identity.username}


@router.post("/{entry_id}/publish", response_model=PublishResponse)
def publish(entry_id: str, identity: Admin) -> PublishResponse:
    """Run the real ingestion pipeline for one approved or
    queued_for_ingest entry. This is the explicit trigger an operator
    uses when updates_auto_ingest is off (the default) — approval alone
    never silently ingests anything.

    ADMIN, because this is the step that actually changes what every
    future answer is grounded in.
    """
    try:
        result = updates_service.publish_entry(entry_id)
        return PublishResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
