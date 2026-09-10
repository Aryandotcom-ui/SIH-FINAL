import { useState, useEffect, createContext, useContext, useCallback } from 'react';
import { Routes, Route, NavLink, Link, useLocation } from 'react-router-dom';
import Home from './pages/Home.jsx';
import Ask from './pages/Ask.jsx';
import Cases from './pages/Cases.jsx';
import Review from './pages/Review.jsx';
import { Leaf, Sun, Moon } from './components/Icons.jsx';
import { api, DEFAULT_SCOPE } from './lib/api.js';

const NAV = [
  { to: '/ask', label: 'Ask' },
  { to: '/cases', label: 'Patent cases' },
  { to: '/review', label: 'Corpus review' },
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

function useScopeState() {
  const [scope, setScope] = useState(() => {
    try { return sessionStorage.getItem('ipsakti-scope') || DEFAULT_SCOPE; }
    catch { return DEFAULT_SCOPE; }
  });
  useEffect(() => {
    try { sessionStorage.setItem('ipsakti-scope', scope); } catch {}
  }, [scope]);
  return [scope, setScope];
}

export default function App() {
  const [theme, setTheme] = useTheme();
  const [scope, setScope] = useScopeState();
  const [corpus, setCorpus] = useState(null);
  const [corpusError, setCorpusError] = useState(null);
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

              <button
                className="icon-btn"
                onClick={() => setTheme(t => (t === 'dark' ? 'light' : 'dark'))}
                aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
                title={theme === 'dark' ? 'Light theme' : 'Dark theme'}
              >
                {theme === 'dark' ? <Sun /> : <Moon />}
              </button>
              <Link to="/ask" className="btn btn-primary btn-sm" style={{ marginLeft: 4 }}>Ask a question</Link>
            </div>

            {/* The desktop nav collapses below 720px. Without this row the
                links would simply be unreachable on a phone, so the same
                destinations move to a scrollable strip rather than
                disappearing. */}
            <nav className="nav-mobile" aria-label="Sections">
              {NAV.map(n => <NavLink key={n.to} to={n.to}>{n.label}</NavLink>)}
            </nav>
          </header>

          <main className="main">
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/ask" element={<Ask />} />
              <Route path="/cases" element={<Cases />} />
              <Route path="/review" element={<Review />} />
            </Routes>
          </main>

          <footer className="footer">
            <div className="shell footer-grid">
              <span>IP-SAKTI Sahayak — citation-grounded guidance for Ayurvedic IP.</span>
              <span className="spacer" />
              <span>Informational only. Not legal advice.</span>
            </div>
          </footer>
        </div>
      </ScopeCtx.Provider>
    </CorpusCtx.Provider>
  );
}
