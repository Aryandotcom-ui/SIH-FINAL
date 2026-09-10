"""The saved TF-IDF vectorizer is what makes query-time retrieval possible.

An ingest run in which nothing changed never fits the embedder — pipeline.py
fits only when there are dirty chunks — so a caller that saves unconditionally
replaces the fitted space the index was built with by an empty one. Nothing
fails at that moment: every query afterwards fails instead, far from the run
that caused it.
"""

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ai.embedder import TfidfEmbedder  # noqa: E402


def test_save_refuses_to_overwrite_a_good_artifact_with_an_unfitted_one(tmp_path):
    fitted = TfidfEmbedder(dimension=8)
    fitted.fit([
        "a patent shall not be granted for traditional knowledge",
        "approval of the national biodiversity authority is required",
        "the applicant shall disclose the source of the biological material",
        "an international application may claim priority",
    ])
    fitted.save(tmp_path)
    artifact = tmp_path / TfidfEmbedder.ARTIFACT_NAME
    good_size = artifact.stat().st_size
    assert good_size > 0

    # The state a no-op re-ingest leaves the embedder in.
    unfitted = TfidfEmbedder(dimension=8)
    assert not unfitted.fitted
    with pytest.raises(RuntimeError, match="refusing to save an unfitted"):
        unfitted.save(tmp_path)

    # The artifact on disk is untouched, and still usable for queries.
    assert artifact.stat().st_size == good_size
    reloaded = TfidfEmbedder.load(tmp_path)
    assert len(reloaded.encode_query(["can this be patented?"])[0]) == reloaded.dimension


def test_a_fitted_embedder_still_saves_and_round_trips(tmp_path):
    emb = TfidfEmbedder(dimension=8)
    emb.fit(["section three excludes traditional knowledge", "rule sixteen form seven"])
    emb.save(tmp_path)

    reloaded = TfidfEmbedder.load(tmp_path)
    assert reloaded.dimension == emb.dimension
    assert reloaded.encode_query(["traditional knowledge"]) == emb.encode_query(["traditional knowledge"])
