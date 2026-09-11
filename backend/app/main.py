import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.auth_routes import router as auth_router
from .api.insight_routes import router as insight_router
from .api.patent_prep_routes import router as patent_prep_router
from .api.routes import router
from .api.updates_routes import router as updates_router
from .config import settings

log = logging.getLogger(__name__)


def _build_index_if_empty() -> None:
    """Ingest data/pdfs when the index has no chunks.

    Deliberately never fatal. A server that refuses to start because it
    could not ingest is worse than one that starts and says the index is
    missing — the second can still serve /status, /health and the corpus
    library, which is exactly what someone diagnosing this needs.
    """
    from pathlib import Path

    from .services.ai_service import ai_service

    try:
        if ai_service.corpus_count() > 0:
            return
    except Exception:
        log.exception("could not read the corpus count; skipping the index build")
        return

    pdf_dir = Path(settings.pdf_dir)
    pdfs = sorted(pdf_dir.glob("*.pdf")) if pdf_dir.is_dir() else []
    if not pdfs:
        log.error(
            "index is empty and no PDFs were found in %s — the API will abstain "
            "on every question until a corpus is ingested", pdf_dir,
        )
        return

    log.warning(
        "index is empty; ingesting %d PDF(s) from %s (about a minute) ...",
        len(pdfs), pdf_dir,
    )
    try:
        from ai.cli import main as ingest

        code = ingest([
            str(pdf_dir),
            "--manifest", settings.corpus_manifest_path,
            "--chroma-path", settings.chroma_path,
            "--sqlite-path", settings.sqlite_registry_path,
            "--model", "tfidf",
        ])
        if code != 0:
            log.error("index build exited with %s; the API will still start", code)
            return
        # The service may have cached an embedder resolved before the
        # artifact existed, so drop what it built against nothing.
        ai_service.reset_index_cache()
        log.warning("index built: %d chunks", ai_service.corpus_count())
    except Exception:
        log.exception("index build failed; the API will still start")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_build_index:
        _build_index_if_empty()

    scheduler = None
    if settings.updates_scheduler_enabled:
        from ai.updates.scheduler import start_scheduler

        scheduler = start_scheduler(
            interval_minutes=settings.updates_interval_minutes,
            sources_path=settings.updates_sources_path,
            watcher_db_path=settings.updates_watcher_db_path,
            queue_db_path=settings.updates_queue_db_path,
            stage_dir=settings.updates_stage_dir,
            manifest_path=settings.corpus_manifest_path,
            chroma_path=settings.chroma_path,
            chroma_collection=settings.chroma_collection,
            embedding_model=settings.embedding_model,
            embedding_device=settings.embedding_device,
            sqlite_registry_path=settings.sqlite_registry_path,
            auto_ingest=settings.updates_auto_ingest,
        )
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Backend API for IP-SAKTI Sahayak.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(router, prefix=settings.api_v1_prefix)
app.include_router(insight_router, prefix=settings.api_v1_prefix)
app.include_router(updates_router, prefix=settings.api_v1_prefix)
app.include_router(patent_prep_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["health"])
def health() -> dict:
    return {"status": "ok", "service": settings.app_name}
