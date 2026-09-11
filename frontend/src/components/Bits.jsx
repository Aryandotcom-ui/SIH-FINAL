import { useState, useRef, useEffect } from 'react';
import { Chevron, Info, Alert, Plug, Refresh, Globe, Pin, Check } from './Icons.jsx';
import { SCOPES, LANGUAGES } from '../lib/api.js';

/** Small explanatory tooltip — this product is full of terms of art
 *  (abstention, ABS, TKDL) that a first-time user will not know. */
export function Explain({ children }) {
  const [open, setOpen] = useState(false);
  return (
    <span style={{ position: 'relative', display: 'inline-block' }}>
      <span
        className="info-dot"
        tabIndex={0}
        role="button"
        aria-label="What does this mean?"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >i</span>
      {open && (
        <span
          role="tooltip"
          className="fade"
          style={{
            position: 'absolute', bottom: 'calc(100% + 9px)', left: '50%',
            transform: 'translateX(-50%)', width: 260, zIndex: 60,
            background: 'var(--ink-900)', color: 'var(--paper)',
            padding: '11px 13px', borderRadius: 10, fontSize: 13,
            lineHeight: 1.5, fontWeight: 400, boxShadow: 'var(--shadow-lg)',
            textTransform: 'none', letterSpacing: 0,
          }}
        >{children}</span>
      )}
    </span>
  );
}

/** Accordion with a measured height transition (no layout jank). */
export function Disclose({ title, meta, children, defaultOpen = false, className = '' }) {
  const [open, setOpen] = useState(defaultOpen);
  const inner = useRef(null);
  const [h, setH] = useState(defaultOpen ? 'auto' : 0);

  useEffect(() => {
    if (!inner.current) return;
    setH(open ? inner.current.scrollHeight : 0);
  }, [open, children]);

  return (
    <div className={className}>
      <button className="source-head" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <Chevron dir={open ? 'up' : 'down'} size={17} style={{ color: 'var(--text-faint)', flexShrink: 0 }} />
        <span style={{ flex: 1, minWidth: 0 }}>{title}</span>
        {meta}
      </button>
      <div style={{ height: h, overflow: 'hidden', transition: 'height 260ms cubic-bezier(.2,.7,.3,1)' }}>
        <div ref={inner} className="source-body">{children}</div>
      </div>
    </div>
  );
}

/** Confidence as a visible meter. The number alone means nothing to a
 *  non-specialist, so it is always paired with a plain-language reading. */
export function Confidence({ value, abstained, calibrated = true }) {
  const pct = Math.round((value ?? 0) * 100);
  const band = abstained ? 'low' : pct >= 70 ? 'high' : pct >= 45 ? 'medium' : 'low';
  // An uncalibrated score is not a weak score, so it does not get a band
  // colour that implies one. It gets the warning colour and a reading that
  // says the number cannot be interpreted, because the alternative is a
  // green 74% that no one should have trusted.
  const color = !calibrated ? 'var(--warn)'
    : band === 'high' ? 'var(--ok)' : band === 'medium' ? 'var(--warn)' : 'var(--stop)';
  const note = !calibrated
    ? 'Running on the offline stand-in search backend, whose score does not indicate topical relevance — it rates unrelated questions as highly as real ones. Read the cited sources; do not read this number.'
    : {
      high: 'Strong match against the cited sources.',
      medium: 'Partial match — read the sources before relying on this.',
      low: 'Too weak to answer from. Treat nothing here as settled.',
    }[band];

  return (
    <div className="conf">
      <div className="conf-top">
        <span className="conf-label">
          Confidence
          <Explain>
            How closely the retrieved law matches your question — not how correct the answer is.
            Below the threshold the system abstains instead of guessing.
          </Explain>
        </span>
        <span className="conf-val" style={{ color }}>
          {calibrated ? `${pct}%` : `${pct}% uncalibrated`}
        </span>
      </div>
      <div className="conf-track">
        <div className="conf-fill" style={{ width: `${Math.max(pct, 2)}%`, background: color }} />
      </div>
      <p className="conf-note">{note}</p>
    </div>
  );
}

export function Badge({ tone = 'neutral', children, ...p }) {
  return <span className={`badge badge-${tone}`} {...p}>{children}</span>;
}

export function Chip({ active, children, ...p }) {
  return <button type="button" className="chip" aria-pressed={!!active} {...p}>{children}</button>;
}

export function Empty({ icon, title, children }) {
  return (
    <div className="empty">
      <div className="empty-ico">{icon}</div>
      <h3 style={{ fontSize: 19, marginBottom: 8 }}>{title}</h3>
      <p className="muted" style={{ maxWidth: '46ch', margin: '0 auto', fontSize: 14.6 }}>{children}</p>
    </div>
  );
}

export function Disclaimer({ children }) {
  return (
    <div className="disclaimer">
      <Info size={17} style={{ flexShrink: 0, marginTop: 1, color: 'var(--text-faint)' }} />
      <span>{children}</span>
    </div>
  );
}

/**
 * A failed request, said plainly.
 *
 * This replaces the sample-data fallback the app used to show. Inventing a
 * legal answer to cover for an unreachable backend is the exact failure this
 * project exists to prevent, so an unreachable backend now looks like one —
 * with the cause named and a retry to hand.
 */
export function ErrorState({ error, onRetry, what = 'this' }) {
  const kind = error?.kind ?? 'server';
  const title = {
    offline: 'Can’t reach the API',
    timeout: 'The API didn’t answer in time',
    notready: 'The corpus isn’t ready yet',
    auth: 'Your session has ended',
    forbidden: 'Your account can’t do that',
    server: `Couldn’t load ${what}`,
  }[kind];
  const help = {
    offline: (
      <>
        Nothing is answering at the API address. Start the backend with{' '}
        <code>./scripts/run.sh</code>, or check that <code>VITE_API_BASE</code>{' '}
        points at a running service.
      </>
    ),
    timeout: 'A free-tier server sleeps when idle and can take up to a minute to wake. It stays fast once it is up.',
    notready: (
      <>
        The API is running but its search index is missing. Build it with{' '}
        <code>./scripts/run.sh --rebuild</code>.
      </>
    ),
    auth: 'Sign in again to continue. Reviewer sessions end when the browser tab closes.',
    forbidden: 'You are signed in, but this action needs a higher role. Approving corpus updates needs REVIEWER; publishing them needs ADMIN.',
    server: 'The API answered with an error. The message it gave is below.',
  }[kind];

  return (
    <div className="errorstate" role="alert">
      <div className="errorstate-ico">
        {kind === 'offline' ? <Plug size={22} /> : <Alert size={22} />}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <h3 className="errorstate-title">{title}</h3>
        <p className="errorstate-help">{help}</p>
        {error?.message && <p className="errorstate-detail mono">{error.message}</p>}
      </div>
      {onRetry && (
        <button className="btn btn-ghost btn-sm" onClick={onRetry}>
          <Refresh size={15} /> Try again
        </button>
      )}
    </div>
  );
}

/**
 * The jurisdiction scope control.
 *
 * Deliberately a segmented control rather than a dropdown: which legal system
 * an answer came from is not a setting to go hunting for, and the selected one
 * has to be readable at a glance while you type. `counts` is the real corpus
 * count per jurisdiction, so a scope with nothing ingested says so instead of
 * looking merely unhelpful when it returns nothing.
 */
export function ScopeToggle({ value, onChange, counts, disabled, compact = false }) {
  return (
    <div className={`scope${compact ? ' scope-compact' : ''}`} role="group" aria-label="Jurisdiction scope">
      {SCOPES.map(sc => {
        const n = sc.jurisdiction
          ? counts?.[sc.jurisdiction]
          : Object.values(counts ?? {}).reduce((a, b) => a + b, 0) || undefined;
        return (
          <button
            key={sc.value}
            type="button"
            className="scope-opt"
            aria-pressed={value === sc.value}
            disabled={disabled}
            onClick={() => onChange(sc.value)}
            title={sc.hint}
          >
            {sc.value === 'INTL' ? <Globe size={14} /> : sc.value === 'IN' ? <Pin size={14} /> : null}
            {sc.label}
            {n != null && <span className="scope-n">{n}</span>}
          </button>
        );
      })}
    </div>
  );
}

/** Which legal system a citation belongs to, shown on the citation itself so
 *  it is never ambiguous even inside a single-jurisdiction answer. */
export function JurisdictionTag({ jurisdiction }) {
  if (!jurisdiction) return null;
  const intl = jurisdiction === 'international';
  return (
    <span className={`jtag ${intl ? 'jtag-intl' : 'jtag-in'}`}>
      {intl ? <Globe size={11} /> : <Pin size={11} />}
      {intl ? 'International' : 'India'}
    </span>
  );
}

/**
 * The answer language.
 *
 * Sits beside the jurisdiction toggle because it is the same kind of
 * control: both decide what the answer *is*, not how it looks. Leaving it
 * on EN is not the same as forcing English — the backend still detects a
 * Devanagari or Kannada query and answers in kind. Picking one only removes
 * the guess, which matters because the detector is a script heuristic and
 * cannot tell Hindi from Marathi.
 */
export function LanguageToggle({ value, onChange }) {
  return (
    <div className="lang" role="group" aria-label="Answer language">
      {LANGUAGES.map(l => (
        <button
          key={l.label}
          type="button"
          className="lang-opt"
          aria-pressed={value === l.value}
          onClick={() => onChange(l.value)}
          title={
            l.value === null
              ? 'English, or the script your question is written in'
              : `Answer in ${l.name}`
          }
        >
          {l.label}
        </button>
      ))}
    </div>
  );
}

/**
 * A GREEN / AMBER / RED screening result.
 *
 * The reason line is not decoration. GREEN here means both that no
 * obligation fired and that the screening had enough facts to mean it —
 * "nothing triggered" and "nothing triggered because nobody answered the
 * question that decides it" are different findings, and only the first is
 * green. See _screening_status in backend/app/api/insight_routes.py.
 */
export function StatusBand({ status, reason }) {
  const tone = {
    GREEN: { cls: 'ok', label: 'No obligations triggered' },
    AMBER: { cls: 'warn', label: 'Obligations or open questions' },
    RED: { cls: 'stop', label: 'Blocking obligations' },
    UNKNOWN: { cls: 'neutral', label: 'Could not be screened' },
  }[status] ?? { cls: 'neutral', label: 'Could not be screened' };

  return (
    <div className={`band band-${tone.cls}`} role="status">
      <span className="band-dot" aria-hidden="true" />
      <div style={{ minWidth: 0 }}>
        <strong className="band-title">{tone.label}</strong>
        <p className="band-reason">{reason}</p>
      </div>
      <span className="band-tag">{status}</span>
    </div>
  );
}

/** A labelled figure. Shows a dash, never a zero, for a number that has not
 *  arrived — on a page whose whole claim is that its numbers are real, an
 *  invented placeholder is the wrong thing to fake. */
export function Stat({ value, label, hint }) {
  return (
    <div className="stat">
      <div className="stat-n">{value ?? '—'}</div>
      <div className="stat-l">{label}{hint && <Explain>{hint}</Explain>}</div>
    </div>
  );
}

/** A verified/unverified marker for a single citation. */
export function VerifyMark({ verified }) {
  return verified
    ? <span className="vmark vmark-ok"><Check size={12} /> supported by a retrieved passage</span>
    : <span className="vmark vmark-no"><Alert size={12} /> not found in the retrieved passages</span>;
}
