# Evaluation

Two scored passes over `test_questions.json` (37 questions).

```bash
# Generation — offline, no index and no API key needed
python -m ai.person_c_generation.eval.eval_runner

# Retrieval — needs a built index (./scripts/run.sh builds one)
python -m ai.person_c_generation.eval.eval_runner --retrieval
```

## What is measured, and what is not

**Generation** scores two things against each question's fixture chunks:
citation correctness (the provision that governs the question must appear in
the answer's citations) and abstention (a deliberately unanswerable question
must come back abstained).

**Retrieval** runs the real query path against the real corpus and reports
**Recall@5** and **abstention accuracy**. Recall rather than precision: for a
citation-grounded answer what matters is whether the governing provision was
*available* to cite at all.

Abstention accuracy is split into its two error directions, because they are
not the same mistake. Answering a question the corpus cannot support is the
failure this project exists to prevent. Abstaining on one it could have
answered is a disappointment.

Two metrics, not six. nDCG and MRR are absent because nothing here produces
the graded relevance judgements they would be computed from, and a metric
whose inputs were invented is worse than no metric at all.

## The question set

37 questions across 8 categories: patentability (8), biological resources and
ABS (7), traditional knowledge (3), international instruments (4), temporal
(2), labelling (2), geographical indications (1), and 10 deliberately
unanswerable.

The 22 questions added beyond the original 15 carry their fixture chunk text
straight from the built index rather than a hand-written paraphrase, so the
generation pass is scored against text the system will actually see. The five
new unanswerable questions carry the real top matches the index returns for
them, at their real scores — so the abstention case is scored against what
retrieval genuinely produces for an out-of-scope question rather than against
a strawman.

The original 15 sit out the retrieval pass (`"retrieval": null`). Their
expected citations use short-form act names — `Patents Act, 1970`, section
`3(p)` — that predate the corpus manifest's exact strings and its
section-level chunking, so scoring them for recall would measure that
mismatch rather than retrieval.

## Results as of this commit

Measured on the offline TF-IDF index (1763 chunks, 17 documents) built with
`python -m ai.cli data/pdfs --manifest ai/corpus.yaml --model tfidf`, against
this repo's hybrid retrieval (dense vector search plus the BM25-style lexical
pass in `ai/store.py`), at the configured `abstain_threshold = 0.20`.

| | |
|---|---|
| Generation | 37/37 (100%) |
| Recall@5 | 10/17 (58.8%) |
| Abstention accuracy | 17/22 (77.3%) |
| - correctly answered | 17/17 (100%) |
| - correctly abstained | **0/5 (0%)** |

### Recall

58.8%. For reference, the same 22 questions score **41.2%** against a
dense-only retriever with no lexical pass, so the BM25 stage is worth about
17 points of recall on this corpus. Not a solved problem: most of the seven
misses are a neighbouring provision of the *right* Act outranking the
governing one - q21 returns the Preamble instead of s.19, q32 returns s.82
instead of s.11.

### Abstention - the actionable finding

The system did not abstain on a single out-of-scope question. Asked about GST
rates, employment notice, company incorporation, customs duty or criminal
jurisdiction, it answered.

But unlike a dense-only retriever, **the two distributions here are
separable**:

```
answerable    n=17   0.597 ... 0.906     (minimum 0.597)
unanswerable  n=5    0.200  0.552  0.563  0.714  0.723
```

Accuracy by threshold, on this set:

| threshold | accuracy | correctly abstained | correctly answered |
|---|---|---|---|
| **0.20** (configured today) | 77.3% | 0/5 | 17/17 |
| 0.50 (this module's own default) | 81.8% | 1/5 | 17/17 |
| 0.597 (best on this sample) | 90.9% | 3/5 | 17/17 |

So the machinery works and the signal now carries real information - the
configured threshold simply sits far below where the separation is. **Raising
`abstain_threshold` from 0.20 toward 0.50-0.60 would catch out-of-scope
questions at no measured cost to the answerable ones.**

That change has deliberately **not** been made here. 0.597 is the minimum of
17 answerable observations, so picking it exactly is fitting the sample, and
five unanswerable questions is a thin basis for moving a safety threshold on
a legal-guidance system. Widen the unanswerable set, then choose.

Note also that `backend/app/config.py` sets `abstain_threshold = 0.20` while
`ai/person_b_retrieval/confidence.py` declares `ABSTAIN_THRESHOLD = 0.50`.
The application's value wins wherever it is passed. They should agree.

### Not measured

The neural embedder. Building a `BAAI/bge-small-en-v1.5` index needs model
weights the measuring environment could not download. Every number above is
the offline TF-IDF backend; expect all of them to move with a real embedding
model, and re-run both passes rather than assuming the direction.

## Why this is not in CI

The retrieval pass needs an ingested corpus and its numbers depend on which
embedder built it, so a pass/fail threshold here would encode whichever
machine happened to run it. `.github/workflows/ci.yml` runs the unit suite and
the corpus/ontology integrity check; this is a benchmark to run deliberately
and read, not a gate.
