import { useState, useEffect, useCallback } from 'react';
import { Navigate, useLocation, Link } from 'react-router-dom';
import { api } from '../lib/api.js';
import { useAuth } from '../App.jsx';
import { Refresh, Check, X, Alert, Shield } from '../components/Icons.jsx';
import { Badge, Empty, Explain, Disclaimer, ErrorState } from '../components/Bits.jsx';

/* The review gate. Framed for the corpus maintainer: what changed upstream,
   what the classifier decided, and what still needs a human. Every control
   here posts to the real /api/v1/updates endpoints — approving actually runs
   the ingestion pipeline, so nothing on this screen is a gesture.

   The gate below is a courtesy, not the security boundary. The server
   rejects an unauthenticated decision regardless of what this component
   renders (see backend/app/auth.py); hiding the controls just means a
   reviewer finds out they need to sign in before typing a decision rather
   than after. */

const TIER = {
  auto_publish:       { tone: 'ok',   label: 'Auto-published', blurb: 'Small change on a trusted official source — ingested without waiting for a person.' },
  publish_then_audit: { tone: 'warn', label: 'Published, needs audit', blurb: 'Big enough to matter. Live already so the corpus doesn’t lag, but flagged for sign-off.' },
  mandatory_review:   { tone: 'stop', label: 'Held for review', blurb: 'Nothing ingested. A person decides before this reaches the corpus.' },
};

const TABS = [
  ['pending', 'Awaiting review', api.reviewPending],
  ['queued', 'Queued to ingest', api.reviewQueued],
  ['audit', 'Needs sign-off', api.reviewNeedsAudit],
  ['history', 'History', api.reviewHistory],
];

export default function Review() {
  const { identity, ready } = useAuth();
  const location = useLocation();

  // "Not signed in" and "we haven't checked the stored token yet" are
  // different states. Redirecting during the second one bounces a signed-in
  // reviewer to the login form on every reload.
  if (!ready) {
    return (
      <div className="shell" style={{ maxWidth: 720 }}>
        <div className="skeleton" style={{ height: 120 }} />
      </div>
    );
  }
  if (!identity) {
    return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />;
  }
  return <Console identity={identity} />;
}

function Console({ identity }) {
  const [tab, setTab] = useState('pending');
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [checking, setChecking] = useState(false);
  const [notice, setNotice] = useState(null);

  const load = useCallback((signal) => {
    setRows(null);
    setError(null);
    const fetcher = TABS.find(t => t[0] === tab)[2];
    return fetcher({ signal })
      .then(data => { if (!signal?.aborted) setRows(data); })
      .catch(err => {
        if (err.name === 'AbortError') return;
        setError(err);
      });
  }, [tab]);

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  /* One real watch cycle, run synchronously against the configured sources.
     This reaches out to the actual URLs in ai/updates/sources.yaml, so it can
     legitimately fail on a machine with no network — which is reported, not
     swallowed. */
  async function checkNow() {
    setChecking(true);
    setNotice(null);
    try {
      const res = await api.reviewCheckNow();
      setNotice({
        tone: 'ok',
        text: res.checked === 0
          ? 'Checked every configured source. Nothing has changed upstream.'
          : `Checked ${res.checked} source${res.checked === 1 ? '' : 's'}; ${res.entries.length} queue entr${res.entries.length === 1 ? 'y' : 'ies'} resulted.`,
      });
      await load();
    } catch (err) {
      setNotice({ tone: 'stop', text: `Check failed: ${err.message}` });
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="shell" style={{ maxWidth: 980 }}>
      <div className="session-bar">
        <Shield size={16} style={{ color: 'var(--text-faint)', flexShrink: 0 }} />
        <span style={{ fontSize: 13.6 }}>
          Signed in as <strong>{identity.username}</strong>
        </span>
        <Badge tone={identity.role === 'ADMIN' ? 'ok' : 'neutral'}>{identity.role}</Badge>
        {identity.role === 'REVIEWER' && (
          <span className="faint" style={{ fontSize: 12.8 }}>
            Ingestion needs ADMIN
          </span>
        )}
        <span className="spacer" />
        <Link to="/login" className="btn btn-ghost btn-sm">Session</Link>
      </div>

      <div style={{ marginBottom: 24 }}>
        <span className="eyebrow">Corpus review</span>
        <h1 style={{ fontSize: 'clamp(30px, 4vw, 40px)', margin: '10px 0 10px' }}>
          What changed in the law
        </h1>
        <p className="muted" style={{ fontSize: 16, maxWidth: '68ch' }}>
          Sources are watched for changes. How each change is handled depends on how much is at stake —
          a small edit to a trusted portal publishes itself; anything touching a critical Act waits for
          a person.
          <Explain>
            A byte-level diff can tell that something changed, never whether a comma moved or section 6
            was rewritten. So severity is decided by the source’s declared risk, not the size of the diff.
          </Explain>
        </p>
      </div>

      <div className="features" style={{ gap: 14, marginBottom: 22 }}>
        {Object.entries(TIER).map(([k, t]) => (
          <div className="feature" key={k} style={{ padding: 20 }}>
            <Badge tone={t.tone}>{t.label}</Badge>
            <p className="muted" style={{ fontSize: 13.8, lineHeight: 1.58, marginTop: 11 }}>{t.blurb}</p>
          </div>
        ))}
      </div>

      <div className="row-wrap" style={{ gap: 10, marginBottom: 18 }}>
        <button className="btn btn-ghost btn-sm" onClick={checkNow} disabled={checking}>
          <Refresh size={15} /> {checking ? 'Checking sources…' : 'Check sources now'}
        </button>
        <span className="faint" style={{ fontSize: 12.6 }}>
          Runs one watch cycle against the configured sources immediately, instead of waiting for the schedule.
        </span>
      </div>

      {notice && (
        <div className={`notice notice-${notice.tone}`} role="status" style={{ marginBottom: 18 }}>
          {notice.tone === 'ok' ? <Check size={16} /> : <Alert size={16} />}
          <span>{notice.text}</span>
        </div>
      )}

      <div className="tabs" role="tablist">
        {TABS.map(([k, l]) => (
          <button key={k} role="tab" className="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>

      {!rows && !error && <div className="skeleton" style={{ height: 160, borderRadius: 14 }} />}

      {error && <ErrorState error={error} what="the review queue" onRetry={() => load()} />}

      {rows?.length === 0 && (
        <Empty icon={<Check size={26} />} title="Nothing waiting">
          {tab === 'pending'
            ? 'No upstream change is currently held for a decision.'
            : tab === 'queued'
              ? 'Nothing is cleared and waiting to be ingested.'
              : tab === 'audit'
                ? 'Everything published on the audit tier has been signed off.'
                : 'No changes have been processed yet.'}
        </Empty>
      )}

      {rows?.length > 0 && (
        <div className="list">
          {rows.map(r => (
            <ReviewRow key={r.id} r={r} onDone={() => load()} />
          ))}
        </div>
      )}

      <div style={{ marginTop: 26 }}>
        <Disclaimer>
          Every decision here is recorded against <strong>{identity.username}</strong> in the audit
          trail, taken from your signed-in session — the browser cannot set that name. Approving
          records a decision; ingestion is always a separate, explicit step, and needs the ADMIN
          role.
        </Disclaimer>
      </div>
    </div>
  );
}

function ReviewRow({ r, onDone }) {
  const t = TIER[r.tier] ?? { tone: 'neutral', label: r.tier };
  const [busy, setBusy] = useState(null);
  const [failed, setFailed] = useState(null);
  const [notes, setNotes] = useState('');

  /* There is no "your name" field any more, and its absence is the point.
     decided_by used to be typed here and sent in the body, which meant the
     audit trail recorded whatever the client claimed. The server now takes
     it from the bearer token and ignores the body entirely, so a field here
     would be theatre — and nothing gates the buttons on it either. */

  async function act(kind, fn) {
    setBusy(kind);
    setFailed(null);
    try {
      await fn();
      await onDone();
    } catch (err) {
      setFailed(err.message);
    } finally {
      setBusy(null);
    }
  }

  // Notes only. Who decided is the token holder, resolved server-side.
  const decision = () => ({ notes: notes.trim() || null });

  return (
    <div className="card rise" style={{ padding: '19px 21px' }}>
      <div className="row-wrap" style={{ gap: 10, marginBottom: 10 }}>
        <Badge tone={t.tone}>{t.label}</Badge>
        {r.needs_audit && <Badge tone="warn">sign-off pending</Badge>}
        {r.status && r.status !== 'pending' && <Badge tone="neutral">{r.status.replace(/_/g, ' ')}</Badge>}
        <span className="spacer" />
        <span className="faint mono" style={{ fontSize: 12.2 }}>
          {new Date(r.created_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}
        </span>
      </div>

      <div style={{ fontWeight: 600, fontSize: 15.4, lineHeight: 1.35 }}>{r.act_name}</div>
      <div className="faint" style={{ fontSize: 13, marginTop: 4, wordBreak: 'break-all' }}>{r.url}</div>

      <p className="muted" style={{ fontSize: 13.8, marginTop: 11, paddingLeft: 12, borderLeft: '2px solid var(--border-strong)', lineHeight: 1.55 }}>
        {r.reason}
      </p>

      {r.decided_by && (
        <p className="faint" style={{ fontSize: 12.6, marginTop: 9 }}>
          Decided by {r.decided_by}
          {r.decided_at && <> on {new Date(r.decided_at).toLocaleDateString()}</>}
          {r.notes && <> — “{r.notes}”</>}
        </p>
      )}
      {r.ingest_result && (
        <p className="faint mono" style={{ fontSize: 12.4, marginTop: 6 }}>ingest · {r.ingest_result}</p>
      )}

      {(r.status === 'pending' || r.needs_audit || r.status === 'approved' || r.status === 'queued_for_ingest') && (
        <div className="decide">
          <div className="decide-fields">
            <label className="decide-field" style={{ gridColumn: '1 / -1' }}>
              <span className="field-label">Notes</span>
              <input
                className="input"
                value={notes}
                onChange={e => setNotes(e.target.value)}
                placeholder="Optional"
              />
            </label>
          </div>

          <div className="row-wrap" style={{ gap: 9, marginTop: 12 }}>
            {r.status === 'pending' && (
              <>
                <button
                  className="btn btn-primary btn-sm"
                  disabled={!!busy}
                  onClick={() => act('approve', () => api.reviewApprove(r.id, decision()))}
                >
                  <Check size={15} /> {busy === 'approve' ? 'Approving…' : 'Approve'}
                </button>
                <button
                  className="btn btn-ghost btn-sm"
                  disabled={!!busy}
                  onClick={() => act('reject', () => api.reviewReject(r.id, decision()))}
                >
                  <X size={15} /> {busy === 'reject' ? 'Rejecting…' : 'Reject'}
                </button>
              </>
            )}

            {(r.status === 'approved' || r.status === 'queued_for_ingest') && (
              <button
                className="btn btn-primary btn-sm"
                disabled={busy}
                onClick={() => act('publish', () => api.reviewPublish(r.id))}
              >
                {busy === 'publish' ? 'Ingesting…' : 'Ingest into the corpus'}
              </button>
            )}

            {r.needs_audit && (
              <button
                className="btn btn-ghost btn-sm"
                disabled={!!busy}
                onClick={() => act('audit', () => api.reviewClearAudit(r.id, decision()))}
              >
                <Check size={15} /> {busy === 'audit' ? 'Signing off…' : 'Sign off'}
              </button>
            )}

            <span className="faint" style={{ fontSize: 12.4 }}>
              {r.status === 'pending'
                ? 'Approving records the decision; ingestion is a separate, explicit step.'
                : r.needs_audit
                  ? 'Already live — signing off closes the audit flag.'
                  : 'Runs the same ingestion pipeline as a manual run.'}
            </span>
          </div>

          {failed && (
            <p className="decide-error" role="alert">
              <Alert size={14} /> {failed}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
