import { useState, useEffect, createContext, useContext, useCallback } from 'react';
import { Routes, Route, NavLink, Link, useLocation } from 'react-router-dom';
import Home from './pages/Home.jsx';
import Ask from './pages/Ask.jsx';
import Assess from './pages/Assess.jsx';
import Cases from './pages/Cases.jsx';
import Evidence from './pages/Evidence.jsx';
import Sources from './pages/Sources.jsx';
import About from './pages/About.jsx';
import Login from './pages/Login.jsx';
import Review from './pages/Review.jsx';
import { Leaf, Sun, Moon } from './components/Icons.jsx';
import { ScopeToggle, LanguageToggle } from './components/Bits.jsx';
import { api, auth, DEFAULT_SCOPE } from './lib/api.js';

/* The public nav mirrors how someone actually moves through the product:
   describe the product, see what applies to it, read the answer's evidence,
   ask a follow-up, check the corpus behind all of it. `/review` is
   deliberately absent — it is an operator console, reachable by URL and
   gated on a REVIEWER role, not a destination for a visitor. */
const NAV = [
  { to: '/assess', label: 'Product Assessment' },
  { to: '/cases', label: 'IP & Regulatory Analysis' },
  { to: '/evidence', label: 'Evidence' },
  { to: '/ask', label: 'Ask IP-SAKTI' },
  { to: '/sources', label: 'Knowledge Sources' },
  { to: '/about', label: 'About' },
];

/* Corpus status is app-wide: the jurisdiction toggle shows how much corpus
   sits behind each scope, and the landing page quotes the same figures. One
   fetch on mount serves both, and a failure leaves the numbers absent rather
   than inventing them. */
const CorpusCtx = createContext({ corpus: null, error: null, reload: () => {} });
export const useCorpus = () => useContext(CorpusCtx);

/* The jurisdiction scope is per session, not per message: once set it stays
   until changed, so nobody has to re-pick it every turn. Held here rather
   than in the Ask page so it survives navigating away and back. */
const ScopeCtx = createContext({ scope: DEFAULT_SCOPE, setScope: () => {} });
export const useScope = () => useContext(ScopeCtx);

/* The answer language, same reasoning. `null` means "detect it from the
   query text" — see LANGUAGES in lib/api.js. */
const LangCtx = createContext({ lang: null, setLang: () => {} });
export const useLang = () => useContext(LangCtx);

/* Who is signed in, if anyone. Anonymous is the normal state: the whole
   public product works without an account, and only the reviewer console
   needs one. */
const AuthCtx = createContext({ identity: null, ready: false, signIn: () => {}, signOut: () => {} });
export const useAuth = () => useContext(AuthCtx);

function useTheme() {
  const [theme, setTheme] = useState(
    () => localStorage.getItem('ipsakti-theme') ||
      (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('ipsakti-theme', theme); } catch {}
  }, [theme]);
  return [theme, setTheme];
}

/** A value that survives navigation but not the tab, persisted defensively
 *  so private-mode storage errors cannot take the app down. */
function useSessionState(key, fallback) {
  const [value, setValue] = useState(() => {
    try {
      const stored = sessionStorage.getItem(key);
      return stored === null ? fallback : JSON.parse(stored);
    } catch { return fallback; }
  });
  useEffect(() => {
    try { sessionStorage.setItem(key, JSON.stringify(value)); } catch {}
  }, [key, value]);
  return [value, setValue];
}

function useIdentity() {
  const [identity, setIdentity] = useState(null);
  // `ready` distinguishes "not signed in" from "we haven't checked yet".
  // Without it the reviewer console would flash a login form at someone who
  // is already signed in, on every reload.
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!auth.token) { setReady(true); return; }
    const ctrl = new AbortController();
    // A stored token proves nothing on its own — the account may have been
    // removed or the server restarted with a new signing secret. Ask.
    api.me({ signal: ctrl.signal })
      .then(me => { if (!ctrl.signal.aborted) setIdentity(me); })
      .catch(() => { auth.token = null; })
      .finally(() => { if (!ctrl.signal.aborted) setReady(true); });
    return () => ctrl.abort();
  }, []);

  return {
    identity,
    ready,
    signIn: setIdentity,
    signOut: () => { api.logout(); setIdentity(null); },
  };
}

export default function App() {
  const [theme, setTheme] = useTheme();
  const [scope, setScope] = useSessionState('ipsakti-scope', DEFAULT_SCOPE);
  const [lang, setLang] = useSessionState('ipsakti-lang', null);
  const [corpus, setCorpus] = useState(null);
  const [corpusError, setCorpusError] = useState(null);
  const session = useIdentity();
  const { pathname } = useLocation();

  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);

  const loadCorpus = useCallback((signal) => {
    setCorpusError(null);
    return api.corpus({ signal })
      .then(data => { if (!signal?.aborted) setCorpus(data); })
      .catch(err => {
        if (err.name === 'AbortError') return;
        setCorpus(null);
        setCorpusError(err);
      });
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    loadCorpus(ctrl.signal);
    return () => ctrl.abort();
  }, [loadCorpus]);

  return (
    <CorpusCtx.Provider value={{ corpus, error: corpusError, reload: () => loadCorpus() }}>
      <ScopeCtx.Provider value={{ scope, setScope }}>
        <LangCtx.Provider value={{ lang, setLang }}>
          <AuthCtx.Provider value={session}>
            <div className="app">
              <header className="topbar">
                <div className="shell topbar-inner">
                  <Link to="/" className="brand">
                    <span className="brand-mark"><Leaf size={21} style={{ color: '#fff' }} /></span>
                    <span>
                      <span className="brand-name">IP-SAKTI Sahayak</span>
                      <span className="brand-sub" style={{ display: 'block' }}>Ayurvedic IP guidance</span>
                    </span>
                  </Link>

                  <nav className="nav">
                    {NAV.map(n => <NavLink key={n.to} to={n.to}>{n.label}</NavLink>)}
                  </nav>

                  <span className="spacer" />

                  {/* Jurisdiction and language sit in the header rather than
                      inside one page: both change what an answer *is*, not
                      how it looks, so they belong where they are visible on
                      every screen that produces one. */}
                  <div className="topbar-controls">
                    <ScopeToggle
                      value={scope}
                      onChange={setScope}
                      counts={corpus?.jurisdictions}
                      compact
                    />
                    <LanguageToggle value={lang} onChange={setLang} />
                  </div>

                  <button
                    className="icon-btn"
                    onClick={() => setTheme(t => (t === 'dark' ? 'light' : 'dark'))}
                    aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
                    title={theme === 'dark' ? 'Light theme' : 'Dark theme'}
                  >
                    {theme === 'dark' ? <Sun /> : <Moon />}
                  </button>
                </div>

                {/* The desktop nav collapses below 980px. Without this row the
                    links would simply be unreachable on a phone, so the same
                    destinations move to a scrollable strip rather than
                    disappearing. */}
                <nav className="nav-mobile" aria-label="Sections">
                  {NAV.map(n => <NavLink key={n.to} to={n.to}>{n.label}</NavLink>)}
                </nav>

                {/* The header controls wrap under the nav on narrow screens
                    for the same reason: a jurisdiction the user cannot see
                    is a jurisdiction they will not notice is wrong. */}
                <div className="topbar-controls-mobile">
                  <ScopeToggle value={scope} onChange={setScope} counts={corpus?.jurisdictions} compact />
                  <LanguageToggle value={lang} onChange={setLang} />
                </div>
              </header>

              <main className="main">
                <Routes>
                  <Route path="/" element={<Home />} />
                  <Route path="/ask" element={<Ask />} />
                  <Route path="/assess" element={<Assess />} />
                  <Route path="/cases" element={<Cases />} />
                  <Route path="/evidence" element={<Evidence />} />
                  <Route path="/sources" element={<Sources />} />
                  <Route path="/about" element={<About />} />
                  <Route path="/login" element={<Login />} />
                  <Route path="/review" element={<Review />} />
                </Routes>
              </main>

              <footer className="footer">
                <div className="shell footer-grid">
                  <span>IP-SAKTI Sahayak — citation-grounded guidance for Ayurvedic IP.</span>
                  <span className="spacer" />
                  <Link to="/about" className="footer-link">About &amp; known limits</Link>
                  <span>Informational only. Not legal advice.</span>
                </div>
              </footer>
            </div>
          </AuthCtx.Provider>
        </LangCtx.Provider>
      </ScopeCtx.Provider>
    </CorpusCtx.Provider>
  );
}
