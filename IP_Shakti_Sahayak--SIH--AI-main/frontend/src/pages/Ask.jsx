import { useState, useRef, useEffect } from 'react';
import {
  api, FORMULATION_TYPES, APPLICANT_CATEGORIES,
  RESOURCE_ORIGINS, CULTIVATION, SCOPES,
} from '../lib/api.js';
import { useCorpus, useScope } from '../App.jsx';
import {
  Send, Search, Chevron, Alert, Info, Check, Clock, Globe, Scale, Pin,
} from '../components/Icons.jsx';
import {
  Confidence, Disclose, Badge, Chip, Explain, Empty, Disclaimer,
  ErrorState, ScopeToggle, JurisdictionTag,
} from '../components/Bits.jsx';

const EXAMPLES = [
  'Can a classical Ayurvedic formulation be patented in India?',
  'Do I need NBA approval if I use a wild-collected herb?',
  'What does the PCT require for a national phase entry?',
  'What must I disclose about the origin of my plant material?',
];

export default function Ask() {
  const [q, setQ] = useState('');
  const [openFacts, setOpenFacts] = useState(false);
  const [facts, setFacts] = useState({});
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const { scope, setScope } = useScope();
  const { corpus } = useCorpus();
  const resultRef = useRef(null);
  const taRef = useRef(null);
  const inflight = useRef(null);

  // Autosize the composer rather than making the user scroll a 3-line box.
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 220) + 'px';
  }, [q]);

  // Abandon any in-flight request when this page goes away, so a late
  // response cannot set state on an unmounted component.
  useEffect(() => () => inflight.current?.abort(), []);

  const set = (k, v) => setFacts(f => ({ ...f, [k]: f[k] === v ? undefined : v }));

  async function run(query) {
    inflight.current?.abort();
    const ctrl = new AbortController();
    inflight.current = ctrl;

    setLoading(true);
    setResult(null);
    setError(null);

    const { formulation_type, ...rest } = facts;
    const complianceFacts = Object.fromEntries(
      Object.entries(rest).filter(([, v]) => v !== undefined)
    );

    try {
      const data = await api.ask({
        query,
        scope,
        // The jurisdiction now comes from the scope toggle, so the
        // classification carries only what the facts panel supplies.
        classification: { formulation_type },
        complianceFacts,
        signal: ctrl.signal,
      });
      setResult({ data, query });
      requestAnimationFrame(() =>
        resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      );
    } catch (err) {
      if (err.name === 'AbortError') return;
      setError(err);
    } finally {
      if (inflight.current === ctrl) {
        inflight.current = null;
        setLoading(false);
      }
    }
  }

  function submit(e) {
    e?.preventDefault();
    const query = q.trim();
    if (query.length < 3 || loading) return;
    run(query);
  }

  const activeScope = SCOPES.find(s => s.value === scope);

  return (
    <div className="shell" style={{ maxWidth: 940 }}>
      <div style={{ marginBottom: 26 }}>
        <span className="eyebrow">Ask</span>
        <h1 style={{ fontSize: 'clamp(30px, 4vw, 40px)', margin: '10px 0 10px' }}>
          What would you like to know?
        </h1>
        <p className="muted" style={{ fontSize: 16, maxWidth: '62ch' }}>
          Ask in plain words. You’ll get the answer, the sections it rests on, and any
          compliance duties your facts trigger.
        </p>
      </div>

      {/* The scope sits directly above the composer and stays visible: which
          legal system an answer is drawn from is part of the question, not a
          preference buried in a menu. */}
      <div className="scope-row">
        <span className="scope-label">
          Answer from
          <Explain>
            A hard filter on the search, not a display option. “Both” runs two separate
            searches and answers each on its own sources — an Indian statute and a treaty
            are never blended into one paragraph.
          </Explain>
        </span>
        <ScopeToggle
          value={scope}
          onChange={setScope}
          counts={corpus?.jurisdictions}
          disabled={loading}
        />
        <span className="spacer" />
        <span className="faint scope-hint">{activeScope?.hint}</span>
      </div>

      <form onSubmit={submit}>
        <div className="composer">
          <textarea
            ref={taRef}
            rows={2}
            value={q}
            onChange={e => setQ(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit(e); }}
            placeholder="e.g. Can I patent a formulation based on a classical text if I've changed the extraction process?"
            aria-label="Your question"
          />
          <div className="composer-bar">
            <span className="faint" style={{ fontSize: 12.5 }}>⌘↵ to send</span>
            <span className="spacer" />
            <button type="submit" className="btn btn-primary btn-sm" disabled={q.trim().length < 3 || loading}>
              {loading ? 'Searching…' : <>Ask <Send size={16} /></>}
            </button>
          </div>
        </div>
      </form>

      {!result && !loading && !error && (
        <div className="examples">
          {EXAMPLES.map(ex => (
            <button key={ex} className="example" onClick={() => { setQ(ex); taRef.current?.focus(); }}>
              {ex}
            </button>
          ))}
        </div>
      )}

      {/* Optional facts. Collapsed by default so the empty state stays
          inviting, but flagged as the thing that sharpens the answer. */}
      <div className="panel" style={{ marginTop: 18 }}>
        <button className="panel-head" aria-expanded={openFacts} onClick={() => setOpenFacts(o => !o)}>
          <Chevron dir={openFacts ? 'up' : 'down'} size={17} style={{ color: 'var(--text-faint)' }} />
          <span style={{ flex: 1 }}>
            <strong style={{ fontSize: 15, fontWeight: 600 }}>Tell it about your formulation</strong>
            <span className="faint" style={{ display: 'block', fontSize: 13.2, marginTop: 2 }}>
              Optional — but these are the facts that decide whether a biodiversity duty applies to you.
            </span>
          </span>
          {Object.values(facts).filter(Boolean).length > 0 && (
            <Badge tone="ok">{Object.values(facts).filter(Boolean).length} set</Badge>
          )}
        </button>

        {openFacts && (
          <div className="panel-body fade">
            <FactRow
              label="What kind of formulation is it?"
              hint="Classical means made to a formula set out in an authoritative classical text."
              options={FORMULATION_TYPES}
              value={facts.formulation_type}
              onPick={v => set('formulation_type', v)}
            />
            <FactRow
              label="Who is applying?"
              hint="Whether the applicant is a section 3(2) person changes which approval route applies."
              options={APPLICANT_CATEGORIES}
              value={facts.applicant_category}
              onPick={v => set('applicant_category', v)}
            />
            <FactRow
              label="Where did the biological material come from?"
              options={RESOURCE_ORIGINS}
              value={facts.resource_origin}
              onPick={v => set('resource_origin', v)}
            />
            <FactRow
              label="Was it cultivated or wild-collected?"
              hint="Cultivated medicinal plants can fall under a section 40 exemption; wild-collected generally do not."
              options={CULTIVATION}
              value={facts.resource_cultivation}
              onPick={v => set('resource_cultivation', v)}
            />
          </div>
        )}
      </div>

      <div ref={resultRef} style={{ scrollMarginTop: 88 }}>
        {loading && <Thinking scope={scope} />}
        {error && !loading && (
          <div style={{ marginTop: 26 }}>
            <ErrorState
              error={error}
              what="an answer"
              onRetry={() => run(q.trim() || result?.query || '')}
            />
          </div>
        )}
        {result && !loading && <Answer data={result.data} />}
      </div>

      {!result && !loading && !error && (
        <div style={{ marginTop: 40 }}>
          <Empty icon={<Search size={26} />} title="Nothing asked yet">
            Pick one of the examples above, or type your own question. Answers always come with the
            sections they rest on — and an honest “I can’t tell” when the corpus doesn’t cover it.
          </Empty>
        </div>
      )}
    </div>
  );
}

function FactRow({ label, hint, options, value, onPick }) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <div className="seg">
        {options.map(o => (
          <Chip key={o.value} active={value === o.value} onClick={() => onPick(o.value)} title={o.hint}>
            {o.label}
          </Chip>
        ))}
      </div>
      {hint && <p className="field-hint">{hint}</p>}
    </div>
  );
}

function Thinking({ scope }) {
  const steps = scope === 'BOTH'
    ? ['Searching Indian law', 'Searching international instruments', 'Screening obligations', 'Composing both answers']
    : ['Retrieving matching law', 'Screening obligations', 'Composing the answer'];
  const [i, setI] = useState(0);
  // A normal answer takes a few seconds. Past ten, the likeliest cause is a
  // free-tier server waking from sleep, which takes up to a minute — say so,
  // rather than leaving a spinner that looks like a hang.
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    setI(0);
    setSlow(false);
    const t = setInterval(() => setI(n => Math.min(n + 1, steps.length - 1)), 620);
    const s = setTimeout(() => setSlow(true), 10000);
    return () => { clearInterval(t); clearTimeout(s); };
  }, [scope, steps.length]);
  return (
    <div className="card fade" style={{ marginTop: 26 }}>
      <div className="thinking">
        <span className="pulse" />
        <span style={{ fontSize: 15, fontWeight: 500 }}>{steps[i]}…</span>
      </div>
      {slow && (
        <p className="faint" style={{ margin: '0 24px 4px', fontSize: 13.4 }}>
          Taking longer than usual — a free-tier server sleeps when idle and can
          take up to a minute to wake. It stays fast once it is up.
        </p>
      )}
      <div style={{ padding: '0 24px 24px', display: 'grid', gap: 10 }}>
        <div className="skeleton" style={{ height: 13, width: '92%' }} />
        <div className="skeleton" style={{ height: 13, width: '86%' }} />
        <div className="skeleton" style={{ height: 13, width: '64%' }} />
      </div>
    </div>
  );
}

function Answer({ data }) {
  const c = data.compliance;
  const blocking = c?.obligations?.filter(o => o.blocks_grant) ?? [];
  // One block per jurisdiction the query was answered under. An older API
  // that predates the breakdown returns the flat fields only, so fall back
  // to a single block built from those rather than rendering nothing.
  const blocks = data.answers?.length ? data.answers : [{
    scope: data.scope ?? 'BOTH',
    label: data.scope === 'INTL' ? 'International' : 'India',
    answer_text: data.answer_text,
    citations: data.citations ?? [],
    sources: data.sources ?? [],
    confidence: data.confidence,
    confidence_calibrated: data.confidence_calibrated,
    abstained: data.abstained,
    generation: data.generation,
    insufficient: data.abstained,
  }];

  return (
    <div style={{ marginTop: 28, display: 'grid', gap: 22 }}>
      <div className="row-wrap" style={{ gap: 9 }}>
        <span className="eyebrow">Answered using</span>
        <Badge tone="neutral">
          {data.scope === 'BOTH'
            ? 'India and international, separately'
            : data.scope === 'INTL' ? 'International frameworks' : 'Indian law'}
        </Badge>
        {blocking.length > 0 && <Badge tone="stop">{blocking.length} blocking duties</Badge>}
        {data.language && data.language !== 'en' && (
          <Badge tone="neutral"><Globe size={13} /> {data.language.toUpperCase()}</Badge>
        )}
        {data.translated === false && data.language !== 'en' && (
          <Badge tone="warn">Not translated</Badge>
        )}
      </div>

      {blocks.map(b => <AnswerBlock key={b.scope} b={b} />)}

      {c && (
        <Section
          title="Compliance screening"
          sub={c.headline}
          badge={c.provisional ? <Badge tone="warn">Provisional · {Math.round(c.completeness * 100)}% complete</Badge> : null}
        >
          <div style={{ display: 'grid', gap: 12 }}>
            {c.obligations?.map(o => <Obligation key={o.id} o={o} />)}

            {c.inapplicable?.length > 0 && (
              <Disclose
                className="source"
                title={<span style={{ fontSize: 14.4 }}>Exemptions considered and <strong>not</strong> applied ({c.inapplicable.length})</span>}
                defaultOpen={false}
              >
                {c.inapplicable.map((x, i) => (
                  <div key={i} style={{ marginBottom: i < c.inapplicable.length - 1 ? 14 : 0 }}>
                    <strong style={{ fontWeight: 600, fontSize: 14.4, color: 'var(--text)' }}>{x.label}</strong>
                    <div className="mono faint" style={{ marginTop: 3 }}>{x.citation}</div>
                    <p style={{ marginTop: 6 }}>{x.note}</p>
                  </div>
                ))}
              </Disclose>
            )}

            {c.prior_art && (
              <div className="card" style={{ padding: '17px 19px' }}>
                <div className="row-wrap" style={{ gap: 10, marginBottom: 9 }}>
                  <Scale size={17} style={{ color: 'var(--text-faint)' }} />
                  <strong style={{ fontSize: 15, fontWeight: 600 }}>Prior-art exposure</strong>
                  <Badge tone={c.prior_art.risk === 'unknown' ? 'neutral' : c.prior_art.risk === 'medium' ? 'warn' : c.prior_art.risk === 'high' ? 'stop' : 'ok'}>
                    {c.prior_art.risk} risk
                  </Badge>
                  <Explain>
                    Checked against a traditional-knowledge index. A formulation already documented
                    there will be cited against your application under section 3(p).
                  </Explain>
                </div>
                <p className="muted" style={{ fontSize: 14.4, lineHeight: 1.6 }}>{c.prior_art.message}</p>
                {c.prior_art.hits?.length > 0 && (
                  <div style={{ marginTop: 11, display: 'grid', gap: 7 }}>
                    {c.prior_art.hits.map((h, i) => (
                      <div key={i} className="row" style={{ gap: 9, fontSize: 13.6 }}>
                        <Alert size={14} style={{ color: 'var(--warn)', flexShrink: 0 }} />
                        <strong style={{ fontWeight: 600 }}>{h.title}</strong>
                        <span className="faint">· {h.source}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {c.open_questions?.length > 0 && (
              <div style={{ display: 'grid', gap: 9 }}>
                <p className="eyebrow" style={{ marginTop: 6 }}>
                  Still needed to be sure
                  <Explain>
                    These facts decide whether a duty applies. Until they’re answered the screening is
                    marked provisional — an unanswered question is never read as “no obligation”.
                  </Explain>
                </p>
                {c.open_questions.map(qq => (
                  <div className="question" key={qq.field}>
                    <span className={`q-mark${qq.importance === 'critical' ? '' : ' clarifying'}`}>?</span>
                    <div>
                      <p style={{ fontSize: 14.6, lineHeight: 1.5 }}>{qq.question}</p>
                      <span className="faint" style={{ fontSize: 12.4 }}>
                        {qq.importance === 'critical' ? 'Decides a blocking obligation' : 'Refines the result'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <Disclaimer>{c.disclaimer}</Disclaimer>
          </div>
        </Section>
      )}

      <div className="row-wrap faint" style={{ fontSize: 12.6, gap: 14, paddingTop: 4 }}>
        <span>{data.disclaimer}</span>
        {data.audit_id && <span className="mono">audit · {data.audit_id}</span>}
      </div>
    </div>
  );
}

/**
 * One jurisdiction's answer, with its own citations and its own retrieved
 * text. Kept as a self-contained block rather than merged into a single
 * narrative: the two legal systems reach different conclusions often enough
 * that running them together would be a guess dressed as an answer.
 */
function AnswerBlock({ b }) {
  const intl = b.scope === 'INTL';
  return (
    <div className="answer-card rise">
      <div className="answer-head">
        <div style={{ flex: 1, minWidth: 220 }}>
          <div className="row" style={{ gap: 8 }}>
            {intl ? <Globe size={16} style={{ color: 'var(--text-faint)' }} />
                  : <Pin size={16} style={{ color: 'var(--text-faint)' }} />}
            <h2 className="answer-jur">
              {intl ? 'Under international frameworks' : 'Under Indian law'}
            </h2>
          </div>
          <div className="row-wrap" style={{ marginTop: 9, gap: 8 }}>
            {b.abstained
              ? <Badge tone="info">Abstained</Badge>
              : <Badge tone="ok"><Check size={14} /> Answered</Badge>}
            {b.generation === 'mock' && (
              <Badge tone="warn">
                Canned prose — no API key
                <Explain>
                  The retrieved sections, citations and compliance screening below are
                  real. Only the wording of the answer is a deterministic stand-in,
                  because no GROQ_API_KEY is configured. Set one to get a
                  generated answer.
                </Explain>
              </Badge>
            )}
          </div>
        </div>
        <Confidence value={b.confidence} abstained={b.abstained}
                    calibrated={b.confidence_calibrated !== false} />
      </div>

      <div className="answer-body">
        {b.abstained ? (
          <div className="abstain">
            <Info size={21} style={{ color: 'var(--info)', flexShrink: 0, marginTop: 2 }} />
            <div>
              <h4>
                {b.insufficient
                  ? `Nothing in the ${intl ? 'international' : 'Indian'} corpus covers this`
                  : 'The corpus doesn’t clearly answer this'}
              </h4>
              <p>{b.answer_text}</p>
              <p style={{ marginTop: 8 }}>
                Rather than assemble a confident-sounding paragraph from weak matches, the
                system stops here. Narrowing the question, or adding your formulation
                details above, often brings the right provisions into range.
              </p>
            </div>
          </div>
        ) : (
          <div className="answer-text">
            {b.answer_text.split('\n\n').map((p, i) => <p key={i}>{p}</p>)}
          </div>
        )}

        {b.citations?.length > 0 && (
          <div className="answer-sub">
            <h3 className="answer-sub-h">
              What this rests on
              <Explain>
                Each citation is a section actually retrieved from this jurisdiction —
                open a source below to read its text.
              </Explain>
            </h3>
            <div className="cite-list">
              {b.citations.map((ct, i) => {
                const src = b.sources?.find(s => s.act_name === ct.act_name && s.section === ct.section);
                const Wrapper = ct.source_url ? 'a' : 'div';
                return (
                  <Wrapper
                    key={`${ct.act_name}-${ct.section}-${i}`}
                    className="cite"
                    {...(ct.source_url ? { href: ct.source_url, target: '_blank', rel: 'noreferrer' } : {})}
                  >
                    <span className="cite-n">{i + 1}</span>
                    <span style={{ minWidth: 0, flex: 1 }}>
                      <span className="cite-act">{ct.act_name}</span>
                      <span className="cite-sec">
                        {ct.section}
                        {src && <> · match {(src.similarity_score * 100).toFixed(0)}%</>}
                        {!ct.source_url && <> · <span title="This section was retrieved from the ingested text; we just hold no public URL to link out to">no public link</span></>}
                      </span>
                    </span>
                    {/* The jurisdiction travels with the citation, so it is
                        never ambiguous which legal system you are reading —
                        even inside a single-scope answer. */}
                    <JurisdictionTag jurisdiction={src?.jurisdiction ?? (intl ? 'international' : 'india')} />
                  </Wrapper>
                );
              })}
            </div>
          </div>
        )}

        {b.sources?.length > 0 && (
          <div className="answer-sub">
            <h3 className="answer-sub-h">The retrieved text</h3>
            <p className="muted" style={{ fontSize: 13.8, margin: '0 0 12px' }}>
              Verbatim, so you can judge the answer instead of trusting it.
            </p>
            <div className="list">
              {b.sources.map(s => (
                <Disclose
                  key={s.chunk_id}
                  className="source"
                  title={<><strong style={{ fontWeight: 600, fontSize: 14.6 }}>{s.act_name}</strong>
                    <span className="faint" style={{ fontSize: 13.4 }}> · {s.section}</span></>}
                  meta={<span className="score">{(s.similarity_score * 100).toFixed(0)}%</span>}
                >
                  {s.text}
                </Disclose>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Obligation({ o }) {
  const tone = o.blocks_grant ? 'blocking' : o.severity === 'mandatory' ? 'mandatory' : '';
  return (
    <div className={`oblig ${tone}`}>
      <div className="oblig-head">
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="oblig-title">{o.label}</div>
          <div className="oblig-meta">
            {o.blocks_grant && <Badge tone="stop">Blocks grant</Badge>}
            <Badge tone={o.severity === 'mandatory' ? 'warn' : 'neutral'}>{o.severity}</Badge>
            {o.form && <Badge tone="neutral">{o.form}</Badge>}
            {o.review_status === 'draft' && <Badge tone="warn">Unverified rule</Badge>}
          </div>
        </div>
      </div>
      <div className="oblig-body">
        <p className="oblig-rationale">{o.rationale}</p>
        {o.amendment_note && (
          <p className="oblig-rationale" style={{ marginTop: 10, paddingLeft: 12, borderLeft: '2px solid var(--warn)' }}>
            <strong style={{ color: 'var(--warn)', fontWeight: 600 }}>Amendment note. </strong>
            {o.amendment_note}
          </p>
        )}
        <dl className="kv">
          <dt>Basis</dt><dd className="mono">{o.citation}</dd>
          {o.authority && <><dt>File with</dt><dd>{o.authority}</dd></>}
          {o.deadline && <><dt>When</dt><dd><span className="row" style={{ gap: 6 }}><Clock size={14} style={{ color: 'var(--text-faint)' }} />{o.deadline}</span></dd></>}
        </dl>
      </div>
    </div>
  );
}

function Section({ title, sub, badge, children }) {
  return (
    <section className="rise">
      <div style={{ marginBottom: 14 }}>
        <div className="row-wrap" style={{ gap: 10 }}>
          <h2 style={{ fontSize: 21 }}>{title}</h2>
          {badge}
        </div>
        {sub && <p className="muted" style={{ fontSize: 14.4, marginTop: 5, maxWidth: '70ch' }}>{sub}</p>}
      </div>
      {children}
    </section>
  );
}
