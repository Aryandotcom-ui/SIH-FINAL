# IP-SAKTI Sahayak

Multilingual, citation-grounded AI assistant for Ayurvedic intellectual
property and regulatory guidance.

Ask a question in plain language and get an answer that names the sections
it rests on, shows you their verbatim text, and screens your facts against
the access-and-benefit-sharing duties that Ayurvedic IP filings trigger —
the ones applicants usually do not know to ask about.

## Run it

You need Python 3.11+, Node 18+, and this repository. One command:

```bash
./scripts/run.sh
```

Then open **<http://localhost:5173>**.

That installs dependencies, builds the search index from `data/pdfs` (about
a minute, first run only), and starts the API and the web UI together.

> **Open the URL, not the file.** Double-clicking `frontend/index.html` in a
> file manager cannot work. The page is compiled by the dev server when it is
> requested, and a `file://` page has no origin from which to reach the API.
> There is no sample-data fallback: if the UI says it cannot reach the API,
> the backend is not running — start it with the command above.

Other options:

```bash
./scripts/run.sh --backend    # API only; docs at localhost:8000/docs
./scripts/run.sh --rebuild    # discard and rebuild the search index
```

### Generated answer wording is off by default

Set `GROQ_API_KEY` to have a model write the prose:

```bash
export GROQ_API_KEY=gsk_...
./scripts/run.sh
```

Without it the wording comes from a deterministic stand-in and every answer
is labelled **"Canned prose — no API key"** in the UI. Retrieval, citations,
confidence, deadlines and compliance screening are real either way; only the
sentence phrasing is affected. Passing canned text off as a generated answer
is the failure this project exists to prevent, so the label is not optional.

## Deploying it

The two halves deploy to different places, because they are different kinds
of thing. The UI is static files. The API is a long-running Python process
that memory-maps a ~200MB vector index — it cannot run as a serverless
function: Netlify Functions run JS/TS and Go rather than Python, and cap at
250MB unzipped, which the dependencies alone exceed.

**API — Render (free tier).** `render.yaml` is a blueprint: in the Render
dashboard choose New -> Blueprint and point it at this repository. It
installs the dependencies, builds the index from `data/pdfs` during the
build, and serves with uvicorn. Set two variables it deliberately does not
commit:

| Variable | Value |
|---|---|
| `CORS_ORIGINS` | your Netlify origin, no trailing slash, e.g. `https://your-site.netlify.app` |
| `GROQ_API_KEY` | optional; without it the prose is a labelled stand-in |

**UI — Netlify.** `netlify.toml` sets the build, the publish directory and
the single-page-app rewrite that makes `/ask` survive a reload. Set one
build variable, or every page will report that it cannot reach the API:

| Variable | Value |
|---|---|
| `VITE_API_BASE` | `https://<your-render-service>.onrender.com/api/v1` |

Deploy the API first: you need its URL for `VITE_API_BASE`, and it needs
the Netlify origin for `CORS_ORIGINS`, so the second deploy of each side is
the one that works.

### The free tier sleeps

Render's free tier stops an idle service and takes up to a minute to wake
it. The first request after a quiet spell is slow; every request after it
is not. The UI waits 60s and explains the delay after ten, so a cold start
reads as "starting" rather than "broken" — but someone clicking during a
demo still waits. Open the site once a few minutes beforehand.

## Jurisdiction scope

Every question is answered under a jurisdiction you pick: **India**,
**International**, or **Both**. This is a hard filter on retrieval, not a
label on the output — it decides which chunks are eligible before the
search runs.

The corpus is already tagged for it: each document's `jurisdiction` in
`ai/corpus.yaml` is copied onto every chunk's vector metadata at ingest, so
the filter is a `where` clause on the index rather than a post-hoc sort.

**"Both" is never one merged search.** It runs two separately filtered
retrievals and two separate generation calls, each grounded only in its own
jurisdiction and each told explicitly not to reach outside it — the
guardrail against the model topping an answer up from training knowledge
that retrieval deliberately excluded. The two answers are rendered as
separate labelled blocks, never run together, and every citation carries its
own jurisdiction tag.

If nothing in the selected jurisdiction matches well enough, the system says
so and names the other scope rather than generating an ungrounded answer —
"I don't have India-specific guidance on this in the corpus… try the
International scope, or Both."

## What is in the box

| Path | What it does |
|---|---|
| `ai/` | PDF extraction, sectioning, chunking, embedding, retrieval, abstention |
| `ai/compliance/` | Defeasible ABS / IP obligation graph; obligations suppressed by exemptions |
| `ai/patent_prep/` | Intake, prior-art precheck, Form 1/3/27 drafts, deadline tracking |
| `ai/updates/` | Source watcher and tiered review gate for amended law |
| `ai/audit.py` | DPDP-aligned audit trail and licensed-source citation gate |
| `ai/translation.py` | Bhashini translation; retrieval always runs on English. The source language is auto-detected from the query script — there is no language picker in the UI |
| `backend/` | FastAPI service over the above |
| `frontend/` | React web UI (Vite), proxied to the API in development |
| `data/pdfs/` | The 17-document legal corpus (statutes, rules, treaties, guidelines) |

The search index (`data/chroma/`) is **not** in version control. It is
derived from `data/pdfs` and rebuilds in about a minute, so it is generated
rather than versioned.

## Tests

```bash
python3 -m pytest -q
```

## Known limits

These are real and worth knowing before you rely on anything here.

- **13 of the 17 corpus documents have no `source_url`**, so their citations
  cannot link out to the official text. The UI marks these "no public link".
  They are fully ingested and quoted verbatim; there is just no verified URL
  on file. Filling these in needs a machine that can reach the official
  sites.
- **The offline embedder is lexical.** `--model tfidf` is character-ngram
  TF-IDF, so it matches wording rather than meaning: a question phrased far
  from the statute's language can retrieve the wrong Act. It exists so the
  system runs with no model download. For better retrieval, install
  `sentence-transformers`, uncomment it in `ai/requirements.txt`, and rebuild
  with `./scripts/run.sh --rebuild` — queries must be encoded in the same
  space as the chunks, so switching embedders *requires* a rebuild.
- **Abstention does not currently fire for out-of-scope questions.** Measured,
  not estimated: over the 22 retrieval-scored questions in
  `ai/person_c_generation/eval`, the system answered all five deliberately
  out-of-scope ones (GST rates, company incorporation, customs duty...) rather
  than abstaining. The cause is a threshold set below where the signal
  separates, not broken machinery: answerable questions score 0.597-0.906 and
  unanswerable ones 0.200-0.723, so raising `abstain_threshold` from 0.20
  toward 0.50-0.60 would catch 3 of the 5 at no measured cost to the 17
  answerable. That change has not been made on a five-question sample - see
  `ai/person_c_generation/eval/README.md` before moving it. Note that
  `backend/app/config.py` (0.20) and `ai/person_b_retrieval/confidence.py`
  (0.50) currently disagree about the default.
- **Retrieval is hybrid, and Recall@5 is 58.8%.** Dense vector search plus a
  BM25-style lexical pass (`ai/store.py`); the lexical stage is worth about 17
  points of recall over dense-only on this corpus. The remaining misses are
  mostly a neighbouring provision of the right Act outranking the governing
  one, so read the passages on the Evidence view rather than trusting the
  ranking. There is no cross-encoder rerank stage.
- **Deadlines marked "unverified"** come from rules whose current figures
  were not confirmed against amended text; the request-for-examination
  window in particular changed in 2024. Confirm before relying on any date.
- **Nothing here is legal advice.** Every obligation must be checked against
  the bare text of the cited provision and with a registered patent agent.

## Licence and disclaimer

Informational only. Not legal advice. The corpus consists of public legal
instruments; each document's provenance is recorded in `ai/corpus.yaml`.
