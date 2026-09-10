import { useState, useEffect, useCallback } from 'react';
import {
  api, FORMULATION_TYPES, APPLICANT_CATEGORIES,
  RESOURCE_ORIGINS, CULTIVATION,
} from '../lib/api.js';
import { Doc, Check, Alert, Chevron, Plus, X } from '../components/Icons.jsx';
import {
  Badge, Empty, Disclaimer, Explain, ErrorState, Chip,
} from '../components/Bits.jsx';

/* The case lifecycle, shown as a pipeline so a first-time user can see
   where a case is and what happens next without reading documentation.
   Every action on this page posts to ai/patent_prep through the API — the
   precheck is the same ABS screening the Ask page runs, and the form drafts
   are generated from the case's own intake. */
const STAGES = [
  { key: 'intake',     label: 'Intake' },
  { key: 'prechecked', label: 'Pre-checked' },
  { key: 'drafted',    label: 'Forms drafted' },
  { key: 'handed_off', label: 'With agent' },
];

const STATUS_TONE = {
  intake: 'neutral', prechecked: 'info', drafted: 'warn', handed_off: 'ok',
  filed: 'ok', granted: 'ok', rejected: 'stop',
};

/* The applicable-route questions. Each names the instrument that decides
   it, so a reader can go and check rather than take the framing on trust. */
const ROUTES = [
  { t: 'Patent', q: 'Is there an inventive step over what the classical texts already disclose — and does section 3(p) exclude it as traditional knowledge?', basis: 'Patents Act, 1970 · s.3(p), s.3(e)' },
  { t: 'Trade mark', q: 'Is the name distinctive, or is it the generic name of the formulation itself?', basis: 'Trade Marks Act, 1999' },
  { t: 'Design', q: 'Is there a novel shape, configuration or packaging worth protecting separately?', basis: 'Designs Act, 2000' },
  { t: 'Traditional knowledge', q: 'Is the formulation already recorded in the TKDL, where it will be cited against your application?', basis: 'TKDL · prior-art probe' },
  { t: 'Biodiversity', q: 'Does the biological material require approval before an IP right can be granted at all?', basis: 'Biological Diversity Act, 2002 · s.6' },
];

export default function Cases() {
  const [cases, setCases] = useState(null);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async (signal, preferId) => {
    setError(null);
    try {
      const data = await api.cases({ signal });
      if (signal?.aborted) return;
      setCases(data);
      setSelectedId(prev => {
        const want = preferId ?? prev;
        return data.some(c => c.id === want) ? want : (data[0]?.id ?? null);
      });
    } catch (err) {
      if (err.name === 'AbortError') return;
      setCases(null);
      setError(err);
    }
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  const selected = cases?.find(c => c.id === selectedId) ?? null;

  return (
    <div className="shell">
      <div className="row-wrap" style={{ marginBottom: 26, alignItems: 'flex-start', gap: 16 }}>
        <div style={{ flex: 1, minWidth: 280 }}>
          <span className="eyebrow">IP &amp; regulatory analysis</span>
          <h1 style={{ fontSize: 'clamp(30px, 4vw, 40px)', margin: '10px 0 10px' }}>
            Which routes are open to you?
          </h1>
          <p className="muted" style={{ fontSize: 16, maxWidth: '66ch' }}>
            Patent, trade mark, design, traditional knowledge, biodiversity — each is a question to
            assess against your facts, not a conclusion to hand you. Open a formal case and it
            collects those facts once, runs the biodiversity and prior-art pre-checks against them,
            drafts the form content, and tracks the dates that follow.
          </p>
        </div>
        {cases && (
          <button className="btn btn-primary btn-sm" onClick={() => setCreating(true)}>
            <Plus size={16} /> Start a formal case
          </button>
        )}
      </div>

      {/* Presented as questions, deliberately. Which right is available
          turns on facts this page has not been given yet, and a list of
          confident-looking "you can file X" cards would be exactly the
          unearned certainty the rest of the product refuses. */}
      <div className="routes">
        {ROUTES.map(r => (
          <div className="route" key={r.t}>
            <strong className="route-t">{r.t}</strong>
            <p className="route-q">{r.q}</p>
            <span className="mono faint route-basis">{r.basis}</span>
          </div>
        ))}
      </div>

      {creating && (
        <NewCase
          onCancel={() => setCreating(false)}
          onCreated={async (id) => { setCreating(false); await load(undefined, id); }}
        />
      )}

      {!cases && !error && <div className="skeleton" style={{ height: 220, borderRadius: 18 }} />}

      {error && <ErrorState error={error} what="your cases" onRetry={() => load()} />}

      {cases?.length === 0 && !creating && (
        <Empty icon={<Doc size={26} />} title="No cases yet">
          A case collects your formulation’s facts once and carries them through pre-check,
          form drafting and deadline tracking.
          <span style={{ display: 'block', marginTop: 16 }}>
            <button className="btn btn-primary btn-sm" onClick={() => setCreating(true)}>
              <Plus size={16} /> Create the first case
            </button>
          </span>
        </Empty>
      )}

      {cases?.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,340px) minmax(0,1fr)', gap: 24, alignItems: 'start' }}
             className="cases-grid">
          <div className="list">
            {cases.map(c => (
              <button
                key={c.id}
                onClick={() => setSelectedId(c.id)}
                className="list-row"
                style={{
                  textAlign: 'left', cursor: 'pointer', width: '100%',
                  borderColor: selectedId === c.id ? 'var(--brand)' : undefined,
                  boxShadow: selectedId === c.id ? 'var(--shadow-md)' : undefined,
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 14.8, lineHeight: 1.35 }}>
                    {c.intake.invention_title || 'Untitled invention'}
                  </div>
                  <div className="faint" style={{ fontSize: 13, marginTop: 4 }}>
                    {c.intake.applicant_name || 'No applicant named'}
                  </div>
                  <div style={{ marginTop: 9 }}>
                    <Badge tone={STATUS_TONE[c.status] ?? 'neutral'}>
                      {c.status.replace(/_/g, ' ')}
                    </Badge>
                  </div>
                </div>
                <Chevron dir="down" size={16} style={{ transform: 'rotate(-90deg)', color: 'var(--text-faint)', flexShrink: 0 }} />
              </button>
            ))}
          </div>

          {selected && (
            <CaseDetail key={selected.id} c={selected} onChanged={(id) => load(undefined, id)} />
          )}
        </div>
      )}
    </div>
  );
}

/* Intake. Only the fields ai/patent_prep/intake.py actually reads are here:
   asking for anything the module cannot use would be a form that pretends to
   matter. Everything is optional at the API level, but the precheck reports
   what is missing rather than this form guessing. */
function NewCase({ onCancel, onCreated }) {
  const [form, setForm] = useState({
    invention_title: '', applicant_name: '', applicant_address: '',
    inventors: '', abstract: '', formulation_name: '', ingredients: '',
    priority_date: '', filing_date: '',
  });
  const [facts, setFacts] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));
  const pick = (k, v) => setFacts(f => ({ ...f, [k]: f[k] === v ? undefined : v }));

  const listOf = (s) => s.split(',').map(x => x.trim()).filter(Boolean);

  async function submit(e) {
    e.preventDefault();
    if (!form.invention_title.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const { id } = await api.createCase({
        invention_title: form.invention_title.trim(),
        applicant_name: form.applicant_name.trim() || null,
        applicant_address: form.applicant_address.trim() || null,
        inventors: listOf(form.inventors),
        abstract: form.abstract.trim() || null,
        formulation_name: form.formulation_name.trim() || null,
        ingredients: listOf(form.ingredients).length ? listOf(form.ingredients) : null,
        priority_date: form.priority_date || null,
        filing_date: form.filing_date || null,
        jurisdiction: 'india',
        ...facts,
      });
      await onCreated(id);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" style={{ padding: 24, marginBottom: 24 }} onSubmit={submit}>
      <div className="row-wrap" style={{ marginBottom: 16, gap: 10 }}>
        <h2 style={{ fontSize: 21, flex: 1 }}>New case</h2>
        <button type="button" className="icon-btn" onClick={onCancel} aria-label="Cancel">
          <X size={16} />
        </button>
      </div>

      <div className="form-grid">
        <Field label="Invention title" required>
          <input className="input" value={form.invention_title}
                 onChange={e => set('invention_title', e.target.value)}
                 placeholder="e.g. Process for a standardised Ashwagandha extract" required />
        </Field>
        <Field label="Applicant name">
          <input className="input" value={form.applicant_name}
                 onChange={e => set('applicant_name', e.target.value)} />
        </Field>
        <Field label="Applicant address">
          <input className="input" value={form.applicant_address}
                 onChange={e => set('applicant_address', e.target.value)} />
        </Field>
        <Field label="Inventors" hint="Comma-separated">
          <input className="input" value={form.inventors}
                 onChange={e => set('inventors', e.target.value)} placeholder="A. Sharma, B. Rao" />
        </Field>
        <Field label="Formulation name">
          <input className="input" value={form.formulation_name}
                 onChange={e => set('formulation_name', e.target.value)} />
        </Field>
        <Field label="Ingredients" hint="Comma-separated — used for the prior-art check">
          <input className="input" value={form.ingredients}
                 onChange={e => set('ingredients', e.target.value)} placeholder="Withania somnifera, ..." />
        </Field>
        <Field label="Priority date">
          <input className="input" type="date" value={form.priority_date}
                 onChange={e => set('priority_date', e.target.value)} />
        </Field>
        <Field label="Filing date">
          <input className="input" type="date" value={form.filing_date}
                 onChange={e => set('filing_date', e.target.value)} />
        </Field>
      </div>

      <Field label="Abstract" style={{ marginTop: 16 }}>
        <textarea className="input" rows={3} value={form.abstract}
                  onChange={e => set('abstract', e.target.value)} />
      </Field>

      <p className="eyebrow" style={{ marginTop: 22, marginBottom: 4 }}>
        The facts the pre-check turns on
        <Explain>
          These decide whether a biodiversity obligation applies. Left unset they become
          open questions on the precheck rather than being assumed away.
        </Explain>
      </p>
      <PickRow label="Formulation type" options={FORMULATION_TYPES}
               value={facts.formulation_type} onPick={v => pick('formulation_type', v)} />
      <PickRow label="Applicant category" options={APPLICANT_CATEGORIES}
               value={facts.applicant_category} onPick={v => pick('applicant_category', v)} />
      <PickRow label="Resource origin" options={RESOURCE_ORIGINS}
               value={facts.resource_origin} onPick={v => pick('resource_origin', v)} />
      <PickRow label="Cultivated or wild-collected" options={CULTIVATION}
               value={facts.resource_cultivation} onPick={v => pick('resource_cultivation', v)} />

      {error && <div style={{ marginTop: 16 }}><ErrorState error={error} what="the case" /></div>}

      <div className="row-wrap" style={{ gap: 10, marginTop: 22 }}>
        <button type="submit" className="btn btn-primary btn-sm" disabled={!form.invention_title.trim() || busy}>
          {busy ? 'Creating…' : 'Create case'}
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function Field({ label, hint, required, children, style }) {
  return (
    <label className="field" style={{ marginTop: 0, display: 'block', ...style }}>
      <span className="field-label">
        {label}{required && <span className="req"> *</span>}
      </span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

function PickRow({ label, options, value, onPick }) {
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
    </div>
  );
}

function CaseDetail({ c, onChanged }) {
  const [deadlines, setDeadlines] = useState(null);
  const [deadlineError, setDeadlineError] = useState(null);
  const [busy, setBusy] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [handoffTo, setHandoffTo] = useState('');
  const stageIdx = STAGES.findIndex(s => s.key === c.status);

  const loadDeadlines = useCallback((signal) => {
    setDeadlines(null);
    setDeadlineError(null);
    return api.caseDeadlines(c.id, { signal })
      .then(d => { if (!signal?.aborted) setDeadlines(d); })
      .catch(err => { if (err.name !== 'AbortError') setDeadlineError(err); });
  }, [c.id]);

  useEffect(() => {
    const ctrl = new AbortController();
    loadDeadlines(ctrl.signal);
    return () => ctrl.abort();
  }, [loadDeadlines]);

  async function act(kind, fn) {
    setBusy(kind);
    setActionError(null);
    try {
      await fn();
      await onChanged(c.id);
      await loadDeadlines();
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(null);
    }
  }

  const precheck = c.precheck_result;
  const forms = c.forms_result;

  return (
    <div style={{ display: 'grid', gap: 18 }} className="fade">
      <div className="card" style={{ padding: 24 }}>
        <h2 style={{ fontSize: 22, lineHeight: 1.25 }}>{c.intake.invention_title || 'Untitled invention'}</h2>
        <p className="muted" style={{ fontSize: 14.6, marginTop: 7 }}>
          {c.intake.applicant_name || 'No applicant named'}
          {c.intake.inventors?.length > 0 && <> · {c.intake.inventors.join(', ')}</>}
        </p>

        {/* Pipeline */}
        <div style={{ display: 'flex', gap: 0, marginTop: 24, alignItems: 'center' }}>
          {STAGES.map((s, i) => {
            const done = i <= stageIdx;
            return (
              <div key={s.key} style={{ flex: 1, display: 'flex', alignItems: 'center', minWidth: 0 }}>
                <div style={{ textAlign: 'center', flexShrink: 0 }}>
                  <div style={{
                    width: 30, height: 30, borderRadius: '50%', display: 'grid', placeItems: 'center',
                    margin: '0 auto 7px',
                    background: done ? 'var(--navy-700)' : 'var(--bg-sunken)',
                    color: done ? '#fff' : 'var(--text-faint)',
                    border: `1px solid ${done ? 'var(--navy-700)' : 'var(--border)'}`,
                    transition: 'all 240ms cubic-bezier(.2,.7,.3,1)',
                  }}>
                    {done ? <Check size={15} /> : <span style={{ fontSize: 12.5, fontWeight: 600 }}>{i + 1}</span>}
                  </div>
                  <div style={{ fontSize: 12.2, color: done ? 'var(--text)' : 'var(--text-faint)', fontWeight: done ? 600 : 400, whiteSpace: 'nowrap' }}>
                    {s.label}
                  </div>
                </div>
                {i < STAGES.length - 1 && (
                  <div style={{ flex: 1, height: 2, background: i < stageIdx ? 'var(--navy-700)' : 'var(--border)', margin: '0 6px', marginBottom: 20 }} />
                )}
              </div>
            );
          })}
        </div>

        <div className="row-wrap" style={{ gap: 9, marginTop: 22 }}>
          <button className="btn btn-ghost btn-sm" disabled={busy}
                  onClick={() => act('precheck', () => api.casePrecheck(c.id))}>
            {busy === 'precheck' ? 'Running…' : 'Run pre-check'}
          </button>
          <button className="btn btn-ghost btn-sm" disabled={busy}
                  onClick={() => act('draft', () => api.caseDraftForms(c.id))}>
            {busy === 'draft' ? 'Drafting…' : 'Draft form content'}
          </button>
        </div>
        {actionError && (
          <div style={{ marginTop: 14 }}>
            <ErrorState error={actionError} what="that step" />
          </div>
        )}
      </div>

      <div className="card" style={{ padding: 24 }}>
        <h3 style={{ fontSize: 17, marginBottom: 14 }}>The facts on file</h3>
        <dl className="kv" style={{ marginTop: 0, gap: '10px 20px' }}>
          <dt>Formulation</dt><dd>{c.intake.formulation_type ?? '—'}</dd>
          <dt>Applicant</dt><dd>{(c.intake.applicant_category ?? '—').replace(/_/g, ' ')}</dd>
          <dt>Resource origin</dt><dd>{(c.intake.resource_origin ?? '—').replace(/_/g, ' ')}</dd>
          <dt>Collection</dt><dd>{(c.intake.resource_cultivation ?? '—').replace(/_/g, ' ')}</dd>
          <dt>Priority date</dt><dd className="mono">{c.intake.priority_date ?? '—'}</dd>
          <dt>Filing date</dt><dd className="mono">{c.intake.filing_date ?? 'not filed'}</dd>
        </dl>
      </div>

      {precheck && (
        <div className="card" style={{ padding: 24 }}>
          <div className="row-wrap" style={{ gap: 10, marginBottom: 12 }}>
            <h3 style={{ fontSize: 17 }}>Pre-check</h3>
            <Badge tone={precheck.clear_to_draft ? 'ok' : 'warn'}>
              {precheck.clear_to_draft ? 'Clear to draft' : 'Not clear to draft'}
            </Badge>
          </div>

          {precheck.blocking?.length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <p className="eyebrow" style={{ marginBottom: 8 }}>Blocking obligations</p>
              <div style={{ display: 'grid', gap: 7 }}>
                {precheck.blocking.map((b, i) => (
                  <div key={i} className="row" style={{ gap: 9, fontSize: 14 }}>
                    <Alert size={14} style={{ color: 'var(--stop)', flexShrink: 0 }} /> {b}
                  </div>
                ))}
              </div>
            </div>
          )}

          {precheck.reasons_not_clear?.length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <p className="eyebrow" style={{ marginBottom: 8 }}>Why it isn’t clear yet</p>
              <ul className="reasons">
                {precheck.reasons_not_clear.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          )}

          {precheck.critical_open_questions?.length > 0 && (
            <div>
              <p className="eyebrow" style={{ marginBottom: 8 }}>Still needed</p>
              <div style={{ display: 'grid', gap: 9 }}>
                {precheck.critical_open_questions.map((q, i) => (
                  <div className="question" key={i}>
                    <span className="q-mark">?</span>
                    <p style={{ fontSize: 14.4, lineHeight: 1.5 }}>{q}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <div className="card" style={{ padding: 24 }}>
        <div className="row-wrap" style={{ gap: 10, marginBottom: 6 }}>
          <h3 style={{ fontSize: 17 }}>Deadlines</h3>
          <Explain>
            Computed from the dates on file. Rules marked “unverified” are this system’s best
            understanding of a procedural deadline and must be confirmed against the amended Rules
            before you rely on them.
          </Explain>
        </div>
        <p className="muted" style={{ fontSize: 13.8, marginBottom: 16 }}>
          A deadline with no anchor date simply hasn’t started yet — it’s listed so you can see what
          the tracking is waiting on.
        </p>

        {!deadlines && !deadlineError && <div className="skeleton" style={{ height: 130 }} />}
        {deadlineError && <ErrorState error={deadlineError} what="the deadlines" onRetry={() => loadDeadlines()} />}

        {deadlines?.length === 0 && (
          <p className="faint" style={{ fontSize: 14 }}>No deadline rules apply to this case yet.</p>
        )}

        {deadlines?.length > 0 && (
          <div className="list">
            {deadlines.map(d => {
              const tone = d.status === 'overdue' ? 'stop'
                : d.status === 'due_soon' ? 'warn'
                : d.status === 'anchor_unknown' ? 'neutral' : 'ok';
              const color = tone === 'stop' ? 'var(--stop)' : tone === 'warn' ? 'var(--warn)' : tone === 'ok' ? 'var(--ok)' : 'var(--ink-300)';
              const pct = d.days_remaining == null ? 0
                : Math.max(6, Math.min(100, 100 - (d.days_remaining / 1100) * 100));
              return (
                <div className="dl" key={d.rule_id}>
                  <span className="dl-date" style={{ color: d.due_date ? 'var(--text)' : 'var(--text-faint)' }}>
                    {d.due_date ?? '—'}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 14.4, fontWeight: 500, lineHeight: 1.35 }}>{d.label}</div>
                    <div className="faint mono" style={{ fontSize: 12.2, marginTop: 3 }}>
                      {d.legal_basis.act_name}, {d.legal_basis.section}
                    </div>
                    <div className="dl-bar" style={{ marginTop: 8 }}>
                      <span style={{ width: `${pct}%`, background: color }} />
                    </div>
                  </div>
                  <div style={{ textAlign: 'right', flexShrink: 0, display: 'grid', gap: 5, justifyItems: 'end' }}>
                    <Badge tone={tone}>
                      {d.status === 'anchor_unknown' ? 'not started'
                        : d.status === 'due_soon' ? `${d.days_remaining} days`
                        : d.status === 'overdue' ? 'overdue'
                        : `${d.days_remaining} days`}
                    </Badge>
                    {d.review_status === 'draft' && <Badge tone="warn">unverified</Badge>}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="card" style={{ padding: 24 }}>
        <h3 style={{ fontSize: 17, marginBottom: 12 }}>Draft form content</h3>

        {!forms && (
          <p className="muted" style={{ fontSize: 14.2 }}>
            Nothing drafted yet. “Draft form content” above generates Form 1 and Form 3 from this
            case’s intake — and Form 27 only once a grant date is on file, since a statement of
            working cannot exist before one.
          </p>
        )}

        {forms && (
          <div className="list">
            {Object.entries(forms).map(([id, f]) => (
              <FormDraft key={id} draft={f} />
            ))}
          </div>
        )}

        <div style={{ marginTop: 16 }}>
          <Disclaimer>
            Draft content is a preparation aid for a registered patent agent to transcribe onto the
            official form and verify — never file it as-is. Form 3’s foreign-filing disclosure is
            deliberately left blank: section 8 is strict-liability, and a guessed answer there can be
            fatal to the patent on its own.
          </Disclaimer>
        </div>
      </div>

      <div className="card" style={{ padding: 24 }}>
        <h3 style={{ fontSize: 17, marginBottom: 8 }}>Hand off to an agent</h3>
        <p className="muted" style={{ fontSize: 14, marginBottom: 14 }}>
          Bundles the intake, a fresh pre-check, the drafted forms and the deadlines into one package
          and records the handoff on the case. Sending it is a manual step outside this app.
        </p>
        <div className="row-wrap" style={{ gap: 10 }}>
          <input
            className="input"
            style={{ flex: 1, minWidth: 200 }}
            value={handoffTo}
            onChange={e => setHandoffTo(e.target.value)}
            placeholder="Agent name or firm"
          />
          <button
            className="btn btn-primary btn-sm"
            disabled={!handoffTo.trim() || busy}
            onClick={() => act('handoff', () => api.caseHandoff(c.id, { recipient: handoffTo.trim() }))}
          >
            {busy === 'handoff' ? 'Preparing…' : 'Prepare handoff'}
          </button>
        </div>
        {c.handoff_result && (
          <p className="faint" style={{ fontSize: 13, marginTop: 12 }}>
            Last prepared for <strong>{c.handoff_result.recipient}</strong>
            {c.handoff_result.prepared_at && <> on {new Date(c.handoff_result.prepared_at).toLocaleDateString()}</>}.
          </p>
        )}
      </div>
    </div>
  );
}

function FormDraft({ draft }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="source">
      <button className="source-head" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <Chevron dir={open ? 'up' : 'down'} size={17} style={{ color: 'var(--text-faint)', flexShrink: 0 }} />
        <Doc size={17} style={{ color: 'var(--brand)', flexShrink: 0 }} />
        <span style={{ flex: 1, minWidth: 0 }}>
          <strong style={{ fontSize: 14.6, fontWeight: 600 }}>{draft.form_id.replace(/_/g, ' ').toUpperCase()}</strong>
          <span className="faint" style={{ fontSize: 13.2, display: 'block', marginTop: 2 }}>{draft.title}</span>
        </span>
        <Badge tone="ok">drafted</Badge>
      </button>
      {open && (
        <div className="source-body fade">
          <pre className="form-render">{draft.rendered_text}</pre>
        </div>
      )}
    </div>
  );
}
