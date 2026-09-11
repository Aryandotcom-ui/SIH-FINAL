"""
person_c_generation/eval/eval_runner.py

Scores the system against test_questions.json on two axes.

Generation (default, offline)
    Runs generate_answer() over each question's fixture chunks and checks:
      1. Citation correctness — for an answerable question, the expected
         {act_name, section} pair must appear in the answer's citations.
      2. Abstention — for a deliberately unanswerable question, the answer
         must come back with abstained == True.

Retrieval (--retrieval, needs a built index)
    Runs the real query path against the real corpus and reports:
      1. Recall@k — for an answerable question, did the provision that
         governs it appear in the top k retrieved chunks at all? Recall,
         not precision: what matters for a citation-grounded answer is
         whether the right law was *available* to cite.
      2. Abstention accuracy — split into its two error directions,
         because they are not equally bad. Answering a question the corpus
         cannot support is the failure this project exists to prevent;
         abstaining on one it could have answered is a disappointment.

Two metrics, not six. nDCG and MRR are not reported because nothing here
computes a graded relevance judgement to compute them from, and a metric
whose inputs were invented is worse than no metric.

Usage:
    python -m ai.person_c_generation.eval.eval_runner              # generation, offline
    python -m ai.person_c_generation.eval.eval_runner --retrieval  # retrieval, needs an index
    python -m ai.person_c_generation.eval.eval_runner --live       # generation via a real model
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_PERSON_C_DIR = _THIS_DIR.parent
_REPO_ROOT = _PERSON_C_DIR.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_PERSON_C_DIR.parent))
sys.path.insert(0, str(_PERSON_C_DIR))

from shared.schema import MatchedChunk, RetrievalResult  # noqa: E402
from generate import generate_answer  # noqa: E402

TEST_QUESTIONS_PATH = _THIS_DIR / "test_questions.json"


def load_test_questions(path: Path = TEST_QUESTIONS_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_retrieval_result(q: dict) -> RetrievalResult:
    matched_chunks = [MatchedChunk.from_dict(c) for c in q["matched_chunks"]]
    return RetrievalResult(
        query=q["query"],
        matched_chunks=matched_chunks,
        confidence=q["confidence"],
        should_abstain=q["should_abstain"],
    )


def citation_matches(expected: dict, citations: list) -> bool:
    return any(
        c.act_name == expected["act_name"] and c.section == expected["section"]
        for c in citations
    )


def _pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:5.1f}%" if d else "    —"


def _by_category(rows: list[tuple[str, bool]]) -> None:
    """Per-category breakdown. An aggregate that hides a category scoring
    zero is an aggregate that lets it stay at zero."""
    buckets: dict[str, list[bool]] = defaultdict(list)
    for category, ok in rows:
        buckets[category].append(ok)
    print(f"\n  {'category':22s} {'passed':>10s}")
    for category in sorted(buckets):
        oks = buckets[category]
        print(f"  {category:22s} {sum(oks):3d}/{len(oks):<3d} {_pct(sum(oks), len(oks))}")


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def run_eval(mock: bool = True) -> int:
    questions = load_test_questions()
    passed = 0
    failures: list[tuple[str, str]] = []
    rows: list[tuple[str, bool]] = []

    for q in questions:
        answer = generate_answer(build_retrieval_result(q), mock=mock)

        if q["expect_abstain"]:
            ok = answer.abstained is True
            reason = "" if ok else f"expected abstain=True, got {answer.abstained}"
        else:
            ok = (not answer.abstained) and citation_matches(
                q["expected_citation"], answer.citations
            )
            if answer.abstained:
                reason = "model abstained but question was expected to be answerable"
            elif not ok:
                got = [(c.act_name, c.section) for c in answer.citations]
                reason = f"expected citation {q['expected_citation']} not found in {got}"
            else:
                reason = ""

        rows.append((q.get("category", "uncategorised"), ok))
        if ok:
            passed += 1
            print(f"[PASS] {q['id']}: {q['query'][:60]}")
        else:
            failures.append((q["id"], reason))
            print(f"[FAIL] {q['id']}: {q['query'][:60]}  -- {reason}")

    total = len(questions)
    print("\n" + "-" * 66)
    print(f"generation: {passed}/{total} passed  ({_pct(passed, total).strip()})")
    _by_category(rows)
    if failures:
        print("\nFailures:")
        for qid, reason in failures:
            print(f"  - {qid}: {reason}")

    return 0 if not failures else 1


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def _normalise_act(name: str | None) -> str:
    """Compare act names without tripping over a leading "The ".

    corpus.yaml treats act_name as an exact-match contract and this does
    NOT relax that — the store's own filter is still exact. It only stops
    the eval from reporting a miss when the question sheet and the manifest
    disagree on an article the retrieval never saw.
    """
    if not name:
        return ""
    lowered = name.strip().lower()
    return lowered[4:] if lowered.startswith("the ") else lowered


def run_retrieval_eval(top_k: int = 5) -> int:
    """Recall@k and abstention accuracy against the real index."""
    sys.path.insert(0, str(_REPO_ROOT))
    from ai.embedder import TfidfEmbedder, get_embedder
    from ai.person_b_retrieval.confidence import compute_confidence
    from ai.person_b_retrieval.schema import MatchedChunk as RetrMatchedChunk
    from ai.store import VectorStore

    chroma_path = _REPO_ROOT / "data" / "chroma"
    if not chroma_path.is_dir():
        print(
            "No index at data/chroma. Build one first:\n"
            "    python -m ai.cli data/pdfs --manifest ai/corpus.yaml --model tfidf",
            file=sys.stderr,
        )
        return 2

    artifact = chroma_path / TfidfEmbedder.ARTIFACT_NAME
    embedder = (
        TfidfEmbedder.load(str(chroma_path)) if artifact.is_file()
        else get_embedder("BAAI/bge-small-en-v1.5", device="cpu")
    )
    store = VectorStore(str(chroma_path), collection="ip_sakti_corpus")
    # Read from the backend settings rather than hardcoded: the module
    # default and the configured value differ in this repo, and the number
    # the eval reports has to be the one the API actually runs.
    try:
        sys.path.insert(0, str(_REPO_ROOT / "backend"))
        from app.config import settings as _settings
        threshold = _settings.abstain_threshold
    except Exception:
        threshold = 0.50

    questions = [q for q in load_test_questions() if q.get("retrieval")]
    answerable = [q for q in questions if not q["expect_abstain"]]
    unanswerable = [q for q in questions if q["expect_abstain"]]

    hits = 0
    rows: list[tuple[str, bool]] = []
    misses: list[tuple[str, str]] = []
    # Both error directions, kept apart on purpose: they are not the same
    # mistake and averaging them hides the one that matters.
    answered_when_it_should_not = []
    abstained_when_it_need_not = []

    print(f"Retrieval eval — top_k={top_k}, abstain threshold={threshold}, "
          f"embedder={getattr(embedder, 'name', '?')}\n")

    for q in questions:
        result = store.query(query=q["query"], embedder=embedder, top_k=top_k)
        matches = result["matches"]
        matched = [
            RetrMatchedChunk(
                chunk_id=m["chunk_id"], text=m["text"], act_name=m["act_name"],
                section=m["section"], jurisdiction=m["jurisdiction"],
                similarity_score=m["similarity_score"],
            )
            for m in matches
        ]
        # compute_confidence here judges whether the retrieved evidence
        # actually covers the subject of the question, not merely whether
        # the embeddings are close — so it needs the query text, and it
        # returns the abstention decision alongside the score rather than
        # leaving it to a separate threshold comparison.
        confidence, abstained = compute_confidence(
            query=q["query"], matched_chunks=matched, threshold=threshold,
        )

        if q["expect_abstain"]:
            ok = abstained
            if not ok:
                answered_when_it_should_not.append((q["id"], round(confidence, 3)))
            print(f"[{'PASS' if ok else 'FAIL'}] {q['id']} abstain "
                  f"(conf {confidence:.2f}): {q['query'][:52]}")
        else:
            want_act = _normalise_act(q["retrieval"]["expected_act"])
            want_sec = (q["retrieval"]["expected_section"] or "").strip().lower()
            ok = any(
                _normalise_act(m["act_name"]) == want_act
                and (m["section"] or "").strip().lower() == want_sec
                for m in matches
            )
            hits += ok
            if abstained:
                abstained_when_it_need_not.append((q["id"], round(confidence, 3)))
            if not ok:
                got = [f"{m['act_name']}|{m['section']}" for m in matches[:3]]
                misses.append((q["id"], f"wanted {q['retrieval']['expected_act']} "
                                        f"{q['retrieval']['expected_section']}; top: {got}"))
            print(f"[{'PASS' if ok else 'MISS'}] {q['id']} recall@{top_k} "
                  f"(conf {confidence:.2f}): {q['query'][:52]}")

        rows.append((q.get("category", "uncategorised"), ok))

    n_ans = len(answerable)
    n_un = len(unanswerable)
    correct_abstentions = n_un - len(answered_when_it_should_not)
    correct_answers = n_ans - len(abstained_when_it_need_not)

    print("\n" + "-" * 66)
    print(f"Recall@{top_k}                    {hits}/{n_ans}  {_pct(hits, n_ans)}")
    print(f"abstention accuracy         "
          f"{correct_abstentions + correct_answers}/{n_ans + n_un}  "
          f"{_pct(correct_abstentions + correct_answers, n_ans + n_un)}")
    print(f"  correctly abstained       {correct_abstentions}/{n_un}  "
          f"{_pct(correct_abstentions, n_un)}")
    print(f"  correctly answered        {correct_answers}/{n_ans}  "
          f"{_pct(correct_answers, n_ans)}")

    if answered_when_it_should_not:
        print("\n  answered when it should have abstained "
              "(the failure that matters):")
        for qid, conf in answered_when_it_should_not:
            print(f"    - {qid} at confidence {conf}")
    if abstained_when_it_need_not:
        print("\n  abstained when the corpus could have answered:")
        for qid, conf in abstained_when_it_need_not:
            print(f"    - {qid} at confidence {conf}")

    _by_category(rows)

    if misses:
        print("\nRecall misses:")
        for qid, reason in misses:
            print(f"  - {qid}: {reason}")

    # Reported, never gated. Retrieval quality depends on which embedder
    # built the index — the offline TF-IDF backend scores materially worse
    # than the neural one — so a threshold here would encode whichever
    # machine happened to run it. Read the numbers; do not let CI pretend
    # they are a pass/fail.
    return 0


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Score the citation/abstention eval suite.")
    parser.add_argument(
        "--live", action="store_true",
        help="Call a real model instead of MockLLM for the generation eval.",
    )
    parser.add_argument(
        "--retrieval", action="store_true",
        help="Score retrieval (Recall@k, abstention accuracy) against the built index.",
    )
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args(argv)

    if args.retrieval:
        sys.exit(run_retrieval_eval(top_k=args.top_k))
    sys.exit(run_eval(mock=not args.live))


if __name__ == "__main__":
    main()
