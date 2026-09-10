import { useState, useEffect, useCallback, useMemo } from 'react';
import { api } from '../lib/api.js';
import { Doc, Globe, Pin, Alert, Info, Check } from '../components/Icons.jsx';
import {
  Badge, Chip, Empty, ErrorState, Explain, Stat, JurisdictionTag, Disclaimer,
} from '../components/Bits.jsx';

/**
 * Knowledge Sources — the corpus, in the open.
 *
 * The claim this whole product rests on is that answers come from real
 * statutes rather than from a model's recollection of them. That claim is
 * only checkable if the corpus is browsable, so this page lists every
 * document the manifest names, including the two categories it would be
 * more flattering to hide:
 *
 *  - `pending` instruments, which the regulatory graph cites but whose text
 *    we do not hold. The duty exists in law either way; we simply cannot
 *    quote it. Showing these makes the gap between what the system reasons
 *    about and what it can cite visible instead of invisible.
 *  - ingested documents with no verified official link. Most of the corpus
 *    is in this state today. The row says "no public link" rather than
 *    omitting the document or linking somewhere plausible-looking.
 */

const FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'ingested', label: 'Ingested' },
  { value: 'pending', label: 'Awaiting text' },
  { value: 'india', label: 'India' },
  { value: 'international', label: 'International' },
  { value: 'nolink', label: 'No public link' },
];

export default function Sources() {
  const [library, setLibrary] = useState(null);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');

  const load = useCallback((signal) => {
    setLoading(true);
    setError(null);
    return Promise.all([
      api.corpusDocuments({ signal }),
      // Status is supporting detail, not the point of the page: if it
      // fails the library still renders.
      api.status({ signal }).catch(() => null),
    ])
      .then(([docs, st]) => {
        if (signal?.aborted) return;
        setLibrary(docs);
        setStatus(st);
      })
      .catch(err => {
        if (err.name === 'AbortError') return;
        setLibrary(null);
        setError(err);
      })
      .finally(() => { if (!signal?.aborted) setLoading(false); });
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  const documents = library?.documents ?? [];
  const shown = useMemo(() => documents.filter(d => {
    if (filter === 'all') return true;
    if (filter === 'nolink') return d.status === 'ingested' && !d.source_url;
    if (filter === 'india' || filter === 'international') return d.jurisdiction === filter;
    return d.status === filter;
  }), [documents, filter]);

  const linkGap = library ? library.ingested - library.with_source_url : 0;

  return (
    <div className="shell" style={{ maxWidth: 1040 }}>
      <div style={{ marginBottom: 22 }}>
        <span className="eyebrow">Knowledge sources</span>
        <h1 style={{ fontSize: 'clamp(30px, 4vw, 40px)', margin: '10px 0 10px' }}>
          Everything the answers come from.
        </h1>
        <p className="muted" style={{ fontSize: 16, maxWidth: '64ch' }}>
          No opaque model memory — a fixed set of statutes, rules, treaties and guidelines, listed
          here with what we hold of each. Where we have not verified an official link, the row
          says so rather than pointing you somewhere that looks plausible.
        </p>
      </div>

      {error && !loading && (
        <ErrorState error={error} what="the corpus" onRetry={() => load()} />
      )}

      {library && (
        <>
          <div className="stat-strip">
            <Stat value={library.total} label="documents listed" />
            <Stat
              value={library.ingested}
              label="ingested and citable"
              hint="The text is in the index, so an answer can quote and cite it."
            />
            <Stat
              value={library.pending}
              label="cited but not held"
              hint="The regulatory graph relies on these instruments, but we do not have the source text — so an obligation resting on one is reported as uncitable rather than quietly dropped."
            />
            <Stat
              value={status?.chunks ?? null}
              label="passages indexed"
            />
          </div>

          {linkGap > 0 && (
            <div className="notice" style={{ marginTop: 18 }}>
              <Info size={17} style={{ flexShrink: 0 }} />
              <span>
                <strong>{linkGap} of {library.ingested} ingested documents have no verified official
                link yet.</strong> Their text is in the corpus and answers cite them normally; we
                simply have not confirmed a stable public URL. Rather than fabricate one, those
                rows are marked. Filter by <em>No public link</em> to see exactly which.
              </span>
            </div>
          )}

          {status && <IndexHealth status={status} />}

          <div className="row-wrap" style={{ gap: 8, margin: '22px 0 14px' }}>
            {FILTERS.map(f => (
              <Chip key={f.value} active={filter === f.value} onClick={() => setFilter(f.value)}>
                {f.label}
              </Chip>
            ))}
            <span className="spacer" />
            <span className="faint" style={{ fontSize: 13.2 }}>
              {shown.length} of {documents.length}
            </span>
          </div>

          {shown.length === 0 ? (
            <Empty icon={<Doc size={26} />} title="Nothing under that filter">
              Every document matching this filter is absent from the corpus manifest.
            </Empty>
          ) : (
            <div className="doc-grid">
              {shown.map(d => <Document key={`${d.act_name}-${d.file}`} d={d} />)}
            </div>
          )}

          <div style={{ marginTop: 26 }}>
            <Disclaimer>
              A document being in the corpus means its text can be quoted and cited — not that the
              corpus is complete, or current as of today. Check the effective dates, and confirm
              anything you act on against the official text.
            </Disclaimer>
          </div>
        </>
      )}

      {loading && !library && (
        <div style={{ display: 'grid', gap: 10, marginTop: 20 }}>
          {[0, 1, 2, 3].map(i => <div className="skeleton" key={i} style={{ height: 84 }} />)}
        </div>
      )}
    </div>
  );
}

/**
 * What is actually running the search.
 *
 * The embedder is picked by which artifact sits beside the index, not by
 * the configured model name, so those two can legitimately differ. When the
 * gated fallback is in use, retrieval quality is materially lower and
 * saying so is the honest move — a user comparing two answers deserves to
 * know they came out of different vector spaces.
 */
function IndexHealth({ status }) {
  return (
    <div className="card" style={{ padding: '18px 22px', marginTop: 18 }}>
      <div className="row-wrap" style={{ gap: 10, marginBottom: 12 }}>
        <strong style={{ fontSize: 15, fontWeight: 600 }}>Index health</strong>
        {status.index_ready
          ? <Badge tone="ok"><Check size={13} /> Ready</Badge>
          : <Badge tone="stop">Not built</Badge>}
        {status.embedding_is_fallback && (
          <Badge tone="warn">
            Fallback embeddings
            <Explain>
              The index was built with the offline TF-IDF backend rather than the neural model.
              It runs anywhere with no downloads, but retrieval is measurably weaker. Rebuild
              with sentence-transformers installed for full quality.
            </Explain>
          </Badge>
        )}
        {status.generation_mode === 'mock' && (
          <Badge tone="warn">
            Canned prose
            <Explain>
              No generation API key is configured, so answer wording is a deterministic stand-in.
              The retrieved passages, citations and compliance screening around it are real.
            </Explain>
          </Badge>
        )}
      </div>
      <div className="kv">
        <Row k="Collection" v={status.collection} mono />
        <Row k="Active embedding model" v={status.active_embedding_model ?? 'not loaded'} mono />
        {status.configured_embedding_model !== status.active_embedding_model && (
          <Row k="Configured model" v={status.configured_embedding_model} mono />
        )}
        <Row k="Vector dimension" v={status.embedding_dimension ?? '—'} />
        <Row k="Abstention threshold" v={`${Math.round(status.abstain_threshold * 100)}%`} />
        <Row k="Answers logged" v={status.audit_entries ?? '—'} />
      </div>
    </div>
  );
}

function Row({ k, v, mono }) {
  return (
    <div className="kv-row">
      <span className="faint">{k}</span>
      <span className={mono ? 'mono' : undefined}>{v}</span>
    </div>
  );
}

function Document({ d }) {
  const pending = d.status === 'pending';
  return (
    <article className={`doc${pending ? ' doc-pending' : ''}`}>
      <div className="doc-head">
        <h3 className="doc-title">{d.act_name}</h3>
        <div className="row-wrap" style={{ gap: 7 }}>
          <JurisdictionTag jurisdiction={d.jurisdiction} />
          {d.instrument_type && <Badge tone="neutral">{d.instrument_type}</Badge>}
          {pending
            ? <Badge tone="warn">
                Text not held
                <Explain>
                  The regulatory graph cites this instrument, so an obligation resting on it still
                  fires — the duty exists in law whether or not we hold the PDF. But we cannot quote
                  it, so it is reported as uncitable rather than silently dropped.
                </Explain>
              </Badge>
            : <Badge tone="ok">{d.chunks} passages</Badge>}
        </div>
      </div>

      <div className="doc-meta">
        {d.effective_date && <span>In force from {d.effective_date}</span>}
        {Object.keys(d.section_effective_dates ?? {}).length > 0 && (
          <span>
            {Object.keys(d.section_effective_dates).length} amended section(s) dated
            <Explain>
              A parent Act's commencement is not the date every section took its current form.
              These per-section dates are what lets an as-of question be answered against the law
              as it actually stood.
            </Explain>
          </span>
        )}
        {d.access === 'licensed' && <Badge tone="warn">Licensed</Badge>}
      </div>

      <div className="doc-foot">
        {d.source_url ? (
          <a href={d.source_url} target="_blank" rel="noreferrer" className="doc-link">
            Official text ↗
          </a>
        ) : (
          <span className="faint" style={{ fontSize: 13 }}>
            <Alert size={13} style={{ verticalAlign: '-2px' }} /> No verified public link
          </span>
        )}
        {d.file && <span className="mono faint" style={{ fontSize: 12 }}>{d.file}</span>}
      </div>
    </article>
  );
}
