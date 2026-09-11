import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import {
  api, FORMULATION_TYPES, APPLICANT_CATEGORIES,
  RESOURCE_ORIGINS, CULTIVATION,
} from '../lib/api.js';
import { Shield, Search, Check, Scale, Alert, Clock } from '../components/Icons.jsx';
import {
  Badge, Chip, Explain, Disclaimer, ErrorState, StatusBand, Empty,
} from '../components/Bits.jsx';

/**
 * Product Assessment.
 *
 * The same regulatory screening every question already runs, given its own
 * front door. That is the entire justification for this page existing: the
 * person who most needs to be told about section 6 of the Biological
 * Diversity Act is the person who does not know it exists, and who will
 * therefore never type a question that surfaces it. Requiring a question
 * first put the check behind the knowledge it was meant to supply.
 *
 * No retrieval runs here. The screening is graph-driven (ai/compliance over
 * ai/knowledge_graph), so it answers from rules and citations rather than
 * from similarity — which is why it can be certain enough to say RED, and
 * why it says AMBER rather than GREEN the moment a deciding fact is
 * missing.
 */

/* Yes/no facts the graph turns on. Three states, not two: unanswered is a
   real answer here and must never collapse into "no". The whole failure
   this screen guards against is an unasked question reading as a clean
   bill of health. */
const TOGGLES = [
  {
    key: 'uses_biological_material',
    label: 'Does the formulation use biological material?',
    hint: 'Any plant, animal or microbial ingredient — including a common kitchen spice.',
  },
  {
    key: 'uses_codified_tk',
    label: 'Is it based on codified traditional knowledge?',
    hint: 'A formula set out in an authoritative classical text, or recorded in the TKDL.',
  },
  {
    key: 'seeking_ipr',
    label: 'Are you seeking a patent or other IP right?',
    hint: 'Section 6 of the Biological Diversity Act bites at the point an IP right is sought.',
  },
  {
    key: 'intends_commercialisation',
    label: 'Do you intend to commercialise it?',
  },
  {
    key: 'practitioner_is_registered_ayush',
    label: 'Is the practitioner a registered AYUSH practitioner?',
    hint: 'Registered practitioners fall under a narrower exemption than manufacturers.',
  },
  {
    key: 'ipr_already_granted',
    label: 'Has an IP right already been granted?',
    hint: 'Changes whether the obligation is a precondition or a post-grant duty.',
  },
];

const STEPS = [
  { n: '01', t: 'Describe the product', d: 'Formulation type and who is applying.' },
  { n: '02', t: 'Say where the material came from', d: 'Origin and whether it was cultivated.' },
  { n: '03', t: 'Answer what decides the duties', d: 'Six yes/no facts the regulatory graph turns on.' },
  { n: '04', t: 'Read the screening', d: 'Obligations, exemptions, citations, and what is still unknown.' },
];

export default function Assess() {
  const [classification, setClassification] = useState({});
  const [facts, setFacts] = useState({});
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const resultRef = useRef(null);
  const inflight = useRef(null);

  useEffect(() => () => inflight.current?.abort(), []);

  const pick = (k, v) =>
    setClassification(c => ({ ...c, [k]: c[k] === v ? undefined : v }));
  const setFact = (k, v) =>
    setFacts(f => ({ ...f, [k]: f[k] === v ? undefined : v }));

  const answered =
    Object.values(classification).filter(v => v !== undefined).length +
    Object.values(facts).filter(v => v !== undefined).length;

  async function run() {
    inflight.current?.abort();
    const ctrl = new AbortController();
    inflight.current = ctrl;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await api.assess({
        classification: {
          formulation_type: classification.formulation_type ?? null,
          source_organism: classification.source_organism ?? null,
        },
        facts: Object.fromEntries(
          Object.entries(facts).filter(([, v]) => v !== undefined)
        ),
        signal: ctrl.signal,
      });
      setResult(data);
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

  return (
    <div className="shell" style={{ maxWidth: 940 }}>
      <div style={{ marginBottom: 24 }}>
        <span className="eyebrow">Product assessment</span>
        <h1 style={{ fontSize: 'clamp(30px, 4vw, 40px)', margin: '10px 0 10px' }}>
          What applies to your formulation?
        </h1>
        <p className="muted" style={{ fontSize: 16, maxWidth: '64ch' }}>
          Answer what you know. You will get the biodiversity and disclosure obligations your
          facts trigger, the exemptions that remove them, the provision behind each one — and an
          explicit list of what is still unknown, because an unanswered question is never read
          here as “no obligation”.
        </p>
      </div>

      <div className="steps-strip">
        {STEPS.map(s => (
          <div className="step-mini" key={s.n}>
            <span className="step-n">{s.n}</span>
            <div>
              <strong>{s.t}</strong>
              <span className="faint">{s.d}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="panel" style={{ marginTop: 22 }}>
        <div className="panel-body">
          <FactRow
            label="What kind of formulation is it?"
            hint="Classical means made to a formula set out in an authoritative classical text."
            options={FORMULATION_TYPES}
            value={classification.formulation_type}
            onPick={v => pick('formulation_type', v)}
          />
          <FactRow
            label="Who is applying?"
            hint="Whether the applicant is a section 3(2) person changes which approval route applies."
            options={APPLICANT_CATEGORIES}
            value={facts.applicant_category}
            onPick={v => setFact('applicant_category', v)}
          />
          <FactRow
            label="Where did the biological material come from?"
            options={RESOURCE_ORIGINS}
            value={facts.resource_origin}
            onPick={v => setFact('resource_origin', v)}
          />
          <FactRow
            label="Was it cultivated or wild-collected?"
            hint="Cultivated medicinal plants can fall under a section 40 exemption; wild-collected generally do not."
            options={CULTIVATION}
            value={facts.resource_cultivation}
            onPick={v => setFact('resource_cultivation', v)}
          />

          <div className="field">
            <span className="field-label">
              And these
              <Explain>
                Each of these decides at least one obligation. Leaving one unanswered is fine —
                it comes back as an open question rather than being assumed either way.
              </Explain>
            </span>
            <div style={{ display: 'grid', gap: 10 }}>
              {TOGGLES.map(t => (
                <YesNo
                  key={t.key}
                  label={t.label}
                  hint={t.hint}
                  value={facts[t.key]}
                  onPick={v => setFact(t.key, v)}
                />
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="row-wrap" style={{ gap: 12, marginTop: 18, alignItems: 'center' }}>
        <button className="btn btn-primary" onClick={run} disabled={loading || answered === 0}>
          {loading ? 'Screening…' : <><Shield size={17} /> Screen this product</>}
        </button>
        {answered > 0 && <Badge tone="neutral">{answered} answered</Badge>}
        <span className="spacer" />
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => { setClassification({}); setFacts({}); setResult(null); setError(null); }}
          disabled={loading || (answered === 0 && !result)}
        >
          Clear
        </button>
      </div>

      <div ref={resultRef} style={{ scrollMarginTop: 88, marginTop: 26 }}>
        {error && !loading && (
          <ErrorState error={error} what="the screening" onRetry={run} />
        )}
        {result && !loading && <Screening result={result} />}
        {!result && !loading && !error && (
          <Empty icon={<Shield size={26} />} title="Nothing screened yet">
            Answer whatever you can above. Even two or three facts are usually enough to tell you
            whether a biodiversity approval stands between you and a grant.
          </Empty>
        )}
      </div>
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

/**
 * Three states, and the third one is the point.
 *
 * "Not answered" is selected by default and stays a live option, so leaving
 * a fact unknown is a choice the user can see they made rather than a
 * silent default. The graph treats unknown as unknown; a two-state control
 * would have to pick one, and picking "no" is how a screening quietly turns
 * green on a question nobody asked.
 */
function YesNo({ label, hint, value, onPick }) {
  return (
    <div className="yesno">
      <div style={{ minWidth: 0, flex: 1 }}>
        <span className="yesno-label">{label}</span>
        {hint && <span className="yesno-hint">{hint}</span>}
      </div>
      <div className="seg" style={{ flexShrink: 0 }}>
        <Chip active={value === true} onClick={() => onPick(true)}>Yes</Chip>
        <Chip active={value === false} onClick={() => onPick(false)}>No</Chip>
        <Chip active={value === undefined} onClick={() => onPick(undefined)} title="Leave this unknown">
          Not sure
        </Chip>
      </div>
    </div>
  );
}

function Screening({ result }) {
  const c = result.compliance;
  const blocking = c?.obligations?.filter(o => o.blocks_grant) ?? [];
  const critical = c?.open_questions?.filter(q => q.importance === 'critical') ?? [];

  return (
    <div style={{ display: 'grid', gap: 20 }} className="fade">
      <StatusBand status={result.status} reason={result.status_reason} />

      {c?.headline && (
        <p className="lede-note">{c.headline}</p>
      )}

      <div className="row-wrap" style={{ gap: 9 }}>
        {c?.provisional && (
          <Badge tone="warn">
            Provisional · {Math.round((c.completeness ?? 0) * 100)}% complete
            <Explain>
              The screening ran on the facts it has. Until the questions below are answered it
              cannot rule an obligation out — only report that it did not fire on what it knows.
            </Explain>
          </Badge>
        )}
        {blocking.length > 0 && <Badge tone="stop">{blocking.length} blocking</Badge>}
        {c?.regimes?.map(r => <Badge key={r} tone="neutral">{r}</Badge>)}
      </div>

      {c?.obligations?.length > 0 && (
        <section>
          <h2 className="sec-h">What applies to you</h2>
          <div style={{ display: 'grid', gap: 12 }}>
            {c.obligations.map(o => <Obligation key={o.id} o={o} />)}
          </div>
        </section>
      )}

      {c?.uncitable_acts?.length > 0 && (
        <div className="notice">
          <Alert size={17} style={{ flexShrink: 0, color: 'var(--warn)' }} />
          <span>
            <strong>Cited but not quotable.</strong> The duty above rests on{' '}
            {c.uncitable_acts.join(', ')} — the law applies, but we do not hold that text in the
            corpus yet, so we cannot show you the provision. Check it directly.
          </span>
        </div>
      )}

      {c?.exemptions?.length > 0 && (
        <section>
          <h2 className="sec-h">Exemptions that applied</h2>
          <div style={{ display: 'grid', gap: 10 }}>
            {c.exemptions.map((x, i) => (
              <div className="card" key={i} style={{ padding: '15px 18px' }}>
                <div className="row-wrap" style={{ gap: 9 }}>
                  <Check size={16} style={{ color: 'var(--ok)' }} />
                  <strong style={{ fontSize: 14.8, fontWeight: 600 }}>{x.label}</strong>
                  {x.citation && <span className="mono faint">{x.citation}</span>}
                </div>
                {x.note && <p className="muted" style={{ fontSize: 14.2, marginTop: 7 }}>{x.note}</p>}
              </div>
            ))}
          </div>
        </section>
      )}

      {c?.open_questions?.length > 0 && (
        <section>
          <h2 className="sec-h">
            Still needed to be sure
            {critical.length > 0 && <Badge tone="warn" style={{ marginLeft: 10 }}>{critical.length} decide a blocking duty</Badge>}
          </h2>
          <div style={{ display: 'grid', gap: 9 }}>
            {c.open_questions.map(q => (
              <div className="question" key={q.field}>
                <span className={`q-mark${q.importance === 'critical' ? '' : ' clarifying'}`}>?</span>
                <div>
                  <p style={{ fontSize: 14.6, lineHeight: 1.5 }}>{q.question}</p>
                  <span className="faint" style={{ fontSize: 12.4 }}>
                    {q.importance === 'critical' ? 'Decides a blocking obligation' : 'Refines the result'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {c?.prior_art && (
        <section>
          <h2 className="sec-h">Prior-art exposure</h2>
          <div className="card" style={{ padding: '17px 19px' }}>
            <div className="row-wrap" style={{ gap: 10, marginBottom: 9 }}>
              <Scale size={17} style={{ color: 'var(--text-faint)' }} />
              <Badge tone={
                c.prior_art.risk === 'unknown' ? 'neutral' :
                c.prior_art.risk === 'medium' ? 'warn' :
                c.prior_art.risk === 'high' ? 'stop' : 'ok'
              }>{c.prior_art.risk} risk</Badge>
            </div>
            <p className="muted" style={{ fontSize: 14.4, lineHeight: 1.6 }}>{c.prior_art.message}</p>
          </div>
        </section>
      )}

      <div className="card" style={{ padding: '20px 22px', display: 'grid', gap: 14 }}>
        <strong style={{ fontSize: 15.5, fontWeight: 600 }}>Where to go from here</strong>
        <div className="row-wrap" style={{ gap: 10 }}>
          <Link to="/ask" className="btn btn-ghost btn-sm">
            <Search size={15} /> Ask about one of these duties
          </Link>
          <Link to="/cases" className="btn btn-ghost btn-sm">
            <Clock size={15} /> Start a formal case
          </Link>
        </div>
      </div>

      {c?.disclaimer && <Disclaimer>{c.disclaimer}</Disclaimer>}
    </div>
  );
}

function Obligation({ o }) {
  return (
    <div className={`oblig${o.blocks_grant ? ' oblig-block' : ''}`}>
      <div className="oblig-head">
        <div style={{ minWidth: 0, flex: 1 }}>
          <h3 className="oblig-title">{o.label}</h3>
          <div className="oblig-meta mono">{o.citation}</div>
        </div>
        {o.blocks_grant
          ? <Badge tone="stop">Blocks grant</Badge>
          : <Badge tone="warn">{o.severity}</Badge>}
      </div>
      <div className="oblig-body">
        {o.rationale && <p className="oblig-rationale">{o.rationale}</p>}
        {o.amendment_note && (
          <p className="faint" style={{ fontSize: 13.2, marginTop: 7 }}>{o.amendment_note}</p>
        )}
        <div className="row-wrap" style={{ gap: 14, marginTop: 11, fontSize: 13.2 }}>
          {o.authority && <span className="faint">Authority · {o.authority}</span>}
          {o.deadline && <span className="faint">Due · {o.deadline}</span>}
          {o.form && <span className="faint">Form · {o.form}</span>}
          {o.review_status && o.review_status !== 'reviewed' && (
            <Badge tone="neutral">{o.review_status}</Badge>
          )}
        </div>
      </div>
    </div>
  );
}
