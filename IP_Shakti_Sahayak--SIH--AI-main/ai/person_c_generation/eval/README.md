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

Measured on the offline TF-IDF index (1763 chunks, 17 documents), which is
what `./scripts/run.sh` builds by default.

| | |
|---|---|
| Generation | 37/37 (100%) |
| Recall@5 | 7/17 (41.2%) |
| Abstention accuracy | 17/22 (77.3%) |
| — correctly answered | 17/17 (100%) |
| — correctly abstained | **0/5 (0%)** |

### The zero is the finding

The system did not abstain on a single out-of-scope question. Asked about GST
rates, employment notice periods, company incorporation, customs duty or
criminal jurisdiction, it answered — at confidences of 0.48 to 0.65, well
above the 0.20 threshold.

This is not a threshold that needs raising. The two distributions overlap
completely:

```
answerable    n=17   0.41  0.53 0.55 0.58 0.60 0.60 0.64 0.64 0.67 … 0.90
unanswerable  n=5          0.48      0.54 0.56           0.64 0.65
```

The best accuracy any threshold can achieve on this set is 77.3% — exactly
what you get by always answering. With this embedder the confidence signal
carries no information for the answerable/unanswerable distinction, so no
tuning of `ABSTAIN_THRESHOLD` will help.

`ai/person_b_retrieval/confidence.py` already anticipated this in a comment:
the threshold is "tuned for the TF-IDF char n-gram stand-in embedder … expect
real embeddings to separate relevant/irrelevant queries far more cleanly."
This suite turns that expectation into a number.

**The neural comparison has not been run.** Building a BGE index requires
downloading model weights, which the environment this was measured in cannot
reach. Whether `BAAI/bge-small-en-v1.5` separates the two distributions is
therefore an open question, not a claim — re-run both passes after
`pip install sentence-transformers` and `./scripts/run.sh --rebuild` and
replace the table above with what you actually get.

Until then the honest statement, which `/about` now carries, is that on the
default offline configuration an answer about a topic outside Indian IP,
biodiversity, drugs, cosmetics or food law is unreliable regardless of the
confidence displayed next to it.

## Why this is not in CI

The retrieval pass needs an ingested corpus, and its numbers depend on which
embedder built it. A pass/fail threshold here would encode whichever machine
happened to run it. `.github/workflows/ci.yml` therefore runs the unit suite
and the corpus/ontology integrity check; this is a benchmark to run
deliberately and read, not a gate.
