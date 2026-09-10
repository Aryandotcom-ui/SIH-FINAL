import { useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { api } from '../lib/api.js';
import { useAuth } from '../App.jsx';
import { Shield, Info } from '../components/Icons.jsx';
import { Badge, Disclaimer } from '../components/Bits.jsx';

/**
 * Operator sign-in.
 *
 * Only the corpus review console needs this. Everything a visitor came for
 * — asking, assessing, reading evidence, browsing sources — works signed
 * out, and there is no account to create: this is a small console for a
 * handful of named reviewers, configured server-side.
 *
 * The page does not hint at valid usernames, and the server returns one
 * message for both "no such user" and "wrong password", because which of
 * the two it was is exactly what an attacker is trying to learn.
 */
export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const { identity, signIn, signOut } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = params.get('next') || '/review';

  async function submit(e) {
    e.preventDefault();
    if (!username.trim() || !password || busy) return;
    setBusy(true);
    setError(null);
    try {
      const me = await api.login(username.trim(), password);
      signIn({ username: me.username, role: me.role });
      // Never keep the password in component state past the exchange.
      setPassword('');
      navigate(next, { replace: true });
    } catch (err) {
      setError(err);
      setPassword('');
    } finally {
      setBusy(false);
    }
  }

  if (identity) {
    return (
      <div className="shell" style={{ maxWidth: 460 }}>
        <div className="card" style={{ padding: 30, display: 'grid', gap: 16 }}>
          <div className="row" style={{ gap: 11 }}>
            <span className="feature-ico" style={{ margin: 0, width: 36, height: 36 }}>
              <Shield size={18} />
            </span>
            <div>
              <strong style={{ fontSize: 16 }}>Signed in as {identity.username}</strong>
              <div style={{ marginTop: 4 }}><Badge tone="ok">{identity.role}</Badge></div>
            </div>
          </div>
          <div className="row-wrap" style={{ gap: 10 }}>
            <Link to="/review" className="btn btn-primary btn-sm">Open the review console</Link>
            <button className="btn btn-ghost btn-sm" onClick={signOut}>Sign out</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="shell" style={{ maxWidth: 460 }}>
      <div style={{ marginBottom: 20 }}>
        <span className="eyebrow">Reviewer access</span>
        <h1 style={{ fontSize: 30, margin: '10px 0 8px' }}>Sign in</h1>
        <p className="muted" style={{ fontSize: 15, lineHeight: 1.55 }}>
          Only needed to approve or reject corpus updates. Asking questions, assessing a product
          and browsing the sources need no account.
        </p>
      </div>

      <form className="card" style={{ padding: 26, display: 'grid', gap: 16 }} onSubmit={submit}>
        <label className="field" style={{ margin: 0 }}>
          <span className="field-label">Username</span>
          <input
            className="input"
            value={username}
            onChange={e => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </label>

        <label className="field" style={{ margin: 0 }}>
          <span className="field-label">Password</span>
          <input
            className="input"
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        {error && (
          <p className="decide-error" role="alert">
            {error.kind === 'offline'
              ? 'Could not reach the API. Check that the backend is running.'
              : error.message}
          </p>
        )}

        <button
          className="btn btn-primary"
          type="submit"
          disabled={busy || !username.trim() || !password}
        >
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>

      <div style={{ marginTop: 18 }}>
        <Disclaimer>
          Your session ends when this browser tab closes. Whatever you approve or reject is
          recorded against this account in the audit trail — the name on a decision comes from
          this sign-in and cannot be set by the browser.
        </Disclaimer>
      </div>
    </div>
  );
}
