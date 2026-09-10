# IP-SAKTI Sahayak — frontend

React + Vite interface for the IP-SAKTI Sahayak backend.

```bash
npm install
npm run dev          # http://localhost:5173
```

Vite proxies `/api` to `http://localhost:8000` (override with
`VITE_API_TARGET`), so the browser sees one origin and CORS never comes
up in development. To point at a deployed API instead, set
`VITE_API_BASE=https://your-host/api/v1`.

## Screens

| Route | Purpose |
|---|---|
| `/` | Landing — explains the product in plain language for someone who has never heard of section 3(p) or ABS |
| `/ask` | The core: question → cited answer, confidence, retrieved text, compliance obligations, open questions |
| `/cases` | Patent-prep lifecycle: intake → pre-check → drafted forms → agent handoff, with deadline tracking |
| `/review` | The auto-update review gate: what changed upstream and what needs a human |

## No sample-data fallback

Every call goes to the real API. There is no demo mode and no sample-data
fallback: a fabricated legal answer is the one failure this project exists
to prevent, and a UI that quietly substitutes invented content for an
unreachable backend is that failure with a friendlier face.

When a request fails, `src/lib/api.js` throws an `ApiError` carrying a
`kind` — `offline`, `timeout`, `notready` (the API is up but the corpus is
not ingested) or `server` — and the screen renders an `ErrorState` that
names the cause and offers a retry. Nothing that looks like an answer is
ever drawn from a failed request.

## Jurisdiction scope

The India / International / Both control above the composer is a **hard
filter on retrieval**, not a display option. It decides which chunks are
eligible before the search runs, and the corpus is already tagged for it:
`ai/corpus.yaml` gives every document a `jurisdiction`, which `ai/store.py`
copies onto each chunk's Chroma metadata at ingest.

"Both" is never one merged search. The backend runs two separately filtered
retrievals and two separate generation calls, and the UI renders them as two
labelled blocks — so an Indian statute and a treaty can never be stitched
into one paragraph, and neither can crowd the other out of a single
similarity ranking. Every citation also carries its own jurisdiction tag, so
which legal system you are reading is never ambiguous even inside a
single-scope answer.

The selection is per session (`sessionStorage`), not per message: once set it
stays until changed. It defaults to "Both" so nobody is forced to pick a
jurisdiction before they have typed anything.

## Design notes

- **Fonts are self-hosted** in `public/fonts` rather than loaded from the
  Google Fonts CDN — venue wifi shouldn't be a demo dependency, and it
  keeps first paint off the network. ~560 KB for Fraunces, Inter and Noto
  Sans Devanagari.
- **Provenance is the hero.** Confidence is a meter with a plain-language
  reading, not a bare number; every citation opens to the section text it
  came from; abstention is a first-class state with its own dignified
  treatment, not an error.
- **Terms of art are explained inline.** Small `i` markers cover
  abstention, ABS, TKDL, unverified deadline rules — a vaidya arriving
  here does not know these and shouldn't have to.
- Light and dark themes, `prefers-reduced-motion` respected, keyboard
  focus visible throughout.

## Known gaps

- **The review gate and case actions have no authentication in front of
  them.** Approve / reject / sign off / ingest all POST to the real
  endpoints, and the reviewer's name is typed into the form rather than
  taken from a session — so the identity recorded against a decision is
  only as trustworthy as whoever is sitting at the browser. These
  endpoints need auth before deployment.
- **Answers are only as good as the embedder.** The offline TF-IDF
  stand-in matches wording rather than meaning, so a low-confidence
  answer on an off-topic question is expected — see the root README's
  "Known limits".
- No auth flow; `decided_by` on the backend is unverified free text.
- Case creation and intake editing aren't built yet; `/cases` reads
  existing cases only.
