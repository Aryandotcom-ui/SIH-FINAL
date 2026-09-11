import { useState, useEffect, useCallback } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../lib/api.js';
import { Search, Doc, Alert, Info, Globe, Pin } from '../components/Icons.jsx';
import {
  Badge, Disclose, Empty, ErrorState, Explain, Stat, VerifyMark,
  JurisdictionTag, Confidence,
} from '../components/Bits.jsx';

/**
 * Evidence — why one specific answer came out the way it did.
 *
 * Reached with ?audit_id=… from any answer. Everything here is read back
 * from the audit row written when that answer was given; nothing is
 * re-retrieved. Re-running the query today would rank it against today's
 * corpus, and showing that as the reason for an earlier answer would be a
 * fabrication with the shape of an explanation — which is precisely the
 * failure the rest of the system is built to avoid.
 *
 * Two consequences the page has to be honest about, and is:
 *
 *  - An answer given before per-chunk scores were recorded reports them as
 *    absent, not as zero.
 *  - A chunk a later re-ingest removed is marked as gone rather than
 *    quietly dropped from the list. "This answer rested on something the
 *    corpus no longer contains" is exactly what this page exists to show.
 *
 * The score shown per passage is the similarity the retriever recorded for
 * it at answer time. Retrieval here is hybrid — dense vector search over
 * Chroma combined with a BM25-style lexical pass (see ai/store.py) — and
 * the recorded score is the one that actually ranked the passage. Where a
 * component score was not written into the audit row it is reported as
 * absent rather than inferred, for the same reason the whole page exists.
 */

export default function Evidence() {
  const [params, setParams] = useSearchParams();
  const auditId = params.get('audit_id') ?? '';
  const [input, setInput] = useState(auditId);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => { setInput(auditId); }, [auditId]);

  const load = useCallback((id, signal) => {
    if (!id) { setData(null); setError(null); return; }
    setLoading(true);
    setError(null);
    api.evidence(id, { signal })
      .then(d => { if (!signal?.aborted) { setData(d); setError(null); } })
      .catch(err => {
        if (err.name === 'AbortError') return;
        setData(null);
        setError(err);
      })
      .finally(() => { if (!signal?.aborted) setLoading(false); });
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    load(auditId, ctrl.signal);
    return () => ctrl.abort();
  }, [auditId, load]);

  return (
    <div className="shell" style={{ maxWidth: 980 }}>
      <div style={{ marginBottom: 22 }}>
        <span className="eyebrow">Evidence</span>
        <h1 style={{ fontSize: 'clamp(30px, 4vw, 40px)', margin: '10px 0 10px' }}>
          Why did I get that answer?
        </h1>
        <p className="muted" style={{ fontSize: 16, maxWidth: '64ch' }}>
          Every answer carries an audit id. Paste it here — or follow the “View evidence” link on
          an answer — to see the passages it was built from, how closely each one matched, and
          whether every citation it made is actually supported by them.
        </p>
      </div>

      <form
        className="composer"
        onSubmit={e => {
          e.preventDefault();
          const id = input.trim();
          setParams(id ? { audit_id: id } : {});
        }}
      >
        <div className="composer-bar" style={{ borderTop: 0, padding: '12px 14px' }}>
          <input
            className="input mono"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="audit id, e.g. 3f2c1a80-…"
            aria-label="Audit id"
            style={{ flex: 1, minWidth: 0 }}
          />
          <button className="btn btn-primary btn-sm" type="submit" disabled={!input.trim() || loading}>
            {loading ? 'Loading…' : 'Look up'}
          </button>
        </div>
      </form>

      <div style={{ marginTop: 24 }}>
        {error && !loading && (
          <ErrorState error={error} what="that evidence" onRetry={() => load(auditId)} />
        )}
        {!auditId && !loading && !error && (
          <Empty icon={<Doc size={26} />} title="No answer selected">
            Ask something first, then follow the “View evidence” link on the answer. The id is
            printed under every answer too, if you would rather paste it.
          </Empty>
        )}
        {data && !loading && <Detail d={data} />}
      </div>
    </div>
  );
}

function Detail({ d }) {
  const verifiedAll = d.citations_total > 0 && d.citations_verified === d.citations_total;
  const scored = d.chunks.filter(c => c.similarity_score != null);
  const best = scored.length ? Math.max(...scored.map(c => c.similarity_score)) : null;
  const missing = d.chunks.filter(c => !c.still_in_corpus).length;

  return (
    <div style={{ display: 'grid', gap: 22 }} className="fade">
      <div className="card" style={{ padding: '22px 24px' }}>
        <span className="eyebrow">The question asked</span>
        <p style={{ fontSize: 18, lineHeight: 1.5, margin: '9px 0 14px' }}>{d.query_text}</p>
        <div className="row-wrap" style={{ gap: 9 }}>
          {d.jurisdiction?.split(',').filter(Boolean).map(j => (
            <JurisdictionTag key={j} jurisdiction={j.trim()} />
          ))}
          {d.formulation_type && <Badge tone="neutral">{d.formulation_type}</Badge>}
          {d.abstained
            ? <Badge tone="info">Abstained</Badge>
            : <Badge tone="ok">Answered</Badge>}
          {d.llm_model && <Badge tone="neutral" className="mono">{d.llm_model}</Badge>}
        </div>
        {d.timestamp && (
          <p className="faint mono" style={{ fontSize: 12.4, marginTop: 14 }}>
            {d.audit_id} · {d.timestamp}
          </p>
        )}
      </div>

      {d.error && (
        <div className="notice notice-stop">
          <Alert size={17} style={{ flexShrink: 0 }} />
          <span><strong>This query failed.</strong> <span className="mono">{d.error}</span></span>
        </div>
      )}

      <div className="stat-strip">
        <Stat
          value={d.confidence != null ? `${Math.round(d.confidence * 100)}%` : null}
          label="retrieval confidence"
          hint="How closely the retrieved law matched the question — not how correct the answer is."
        />
        <Stat
          value={`${Math.round(d.abstain_threshold * 100)}%`}
          label="abstention threshold"
          hint="Below this the system refuses to answer rather than assembling something from weak matches."
        />
        <Stat value={d.chunks.length} label="passages retrieved" />
        <Stat
          value={d.citations_total ? `${d.citations_verified}/${d.citations_total}` : '0'}
          label="citations verified"
          hint="A citation counts as verified when the provision it names appears among the passages actually retrieved."
        />
      </div>

      {/* The single most important line on this page. */}
      {d.citations_total > 0 && (
        <div className={`notice ${verifiedAll ? 'notice-ok' : 'notice-stop'}`}>
          {verifiedAll
            ? <><Info size={17} style={{ flexShrink: 0 }} /><span>
                <strong>Every citation checks out.</strong> Each provision this answer named appears
                in the passages it actually retrieved.
              </span></>
            : <><Alert size={17} style={{ flexShrink: 0 }} /><span>
                <strong>{d.citations_total - d.citations_verified} citation(s) are not supported by the
                retrieved passages.</strong> Treat those as unverified and check the provision directly
                before relying on it.
              </span></>}
        </div>
      )}

      {d.confidence != null && (
        <div className="card" style={{ padding: '18px 22px' }}>
          <Confidence value={d.confidence} abstained={d.abstained} />
        </div>
      )}

      <section>
        <h2 className="sec-h">
          Citations made
          <Explain>
            Checked against the retrieved passages, not against the model's own claim to have read
            them. A citation nothing supports is the failure this project exists to catch.
          </Explain>
        </h2>
        {d.citations.length === 0 ? (
          <p className="muted" style={{ fontSize: 14.6 }}>
            {d.abstained
              ? 'None — the system abstained, so it cited nothing rather than reaching for something weak.'
              : 'None recorded for this answer.'}
          </p>
        ) : (
          <div className="cite-list">
            {d.citations.map((c, i) => (
              <div className="cite" key={`${c.act_name}-${c.section}-${i}`}>
                <span className="cite-n">{i + 1}</span>
                <div style={{ minWidth: 0 }}>
                  <div className="cite-act">{c.act_name}</div>
                  <div className="cite-sec">{c.section}</div>
                  <div style={{ marginTop: 5 }}><VerifyMark verified={c.verified} /></div>
                </div>
                {c.source_url && (
                  <a className="btn btn-ghost btn-sm" href={c.source_url} target="_blank" rel="noreferrer">
                    Official text
                  </a>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="sec-h">
          Passages retrieved
          {best != null && <Badge tone="neutral" style={{ marginLeft: 10 }}>best match {Math.round(best * 100)}%</Badge>}
        </h2>

        {!d.detail_recorded && (
          <div className="notice" style={{ marginBottom: 14 }}>
            <Info size={17} style={{ flexShrink: 0 }} />
            <span>
              This answer predates per-passage score recording, so the match scores were never
              written down. They are shown as absent rather than as zero — “not recorded” and
              “scored nothing” are different claims about this answer.
            </span>
          </div>
        )}

        {missing > 0 && (
          <div className="notice notice-stop" style={{ marginBottom: 14 }}>
            <Alert size={17} style={{ flexShrink: 0 }} />
            <span>
              <strong>{missing} passage(s) are no longer in the corpus.</strong> A later re-ingest
              removed or replaced them, so this answer rests partly on text the system would not
              retrieve today.
            </span>
          </div>
        )}

        {d.chunks.length === 0 ? (
          <p className="muted" style={{ fontSize: 14.6 }}>Nothing was retrieved for this query.</p>
        ) : (
          <div style={{ display: 'grid', gap: 10 }}>
            {d.chunks.map((c, i) => <Chunk key={c.chunk_id ?? i} c={c} rank={i + 1} />)}
          </div>
        )}
      </section>

      {d.licensed_acts_withheld?.length > 0 && (
        <div className="notice">
          <Info size={17} style={{ flexShrink: 0 }} />
          <span>
            <strong>Citations withheld:</strong> {d.licensed_acts_withheld.join(', ')}. These are
            licensed sources the request had not consented to, so they were removed from the
            response — the question was still answered from public sources.
          </span>
        </div>
      )}

      <div className="row-wrap" style={{ gap: 10 }}>
        <Link to="/ask" className="btn btn-ghost btn-sm"><Search size={15} /> Ask a follow-up</Link>
        <Link to="/sources" className="btn btn-ghost btn-sm"><Doc size={15} /> Browse the corpus</Link>
      </div>
    </div>
  );
}

function Chunk({ c, rank }) {
  const pct = c.similarity_score != null ? Math.round(c.similarity_score * 100) : null;
  return (
    <Disclose
      className={`source${c.still_in_corpus ? '' : ' source-gone'}`}
      title={
        <span style={{ display: 'flex', gap: 10, alignItems: 'baseline', minWidth: 0 }}>
          <span className="cite-n" style={{ flexShrink: 0 }}>{rank}</span>
          <span style={{ minWidth: 0 }}>
            <strong style={{ fontWeight: 600, fontSize: 14.6 }}>{c.act_name ?? 'Unknown instrument'}</strong>
            <span className="faint"> · {c.section ?? '—'}</span>
          </span>
        </span>
      }
      meta={
        <span className="row" style={{ gap: 8, flexShrink: 0 }}>
          {c.jurisdiction && <JurisdictionTag jurisdiction={c.jurisdiction} />}
          {/* An absent score reads as "not recorded", never as 0%. */}
          <span className="score" title="Cosine similarity against the question embedding">
            {pct != null ? `${pct}%` : 'not recorded'}
          </span>
        </span>
      }
    >
      {!c.still_in_corpus && (
        <p className="faint" style={{ marginBottom: 9 }}>
          <Alert size={13} style={{ verticalAlign: '-2px', color: 'var(--warn)' }} />{' '}
          This passage is no longer in the index, so its text cannot be shown.
        </p>
      )}
      {c.text
        ? <p style={{ whiteSpace: 'pre-wrap' }}>{c.text}</p>
        : <p className="faint">No text available for this passage.</p>}
      <div className="row-wrap" style={{ gap: 12, marginTop: 11 }}>
        <span className="mono faint" style={{ fontSize: 12.2 }}>{c.chunk_id}</span>
        {c.source_url && (
          <a href={c.source_url} target="_blank" rel="noreferrer" style={{ fontSize: 13 }}>
            Official text ↗
          </a>
        )}
      </div>
    </Disclose>
  );
}
