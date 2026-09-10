import { Link } from 'react-router-dom';
import { Scale, Shield, Doc, Leaf, Check, Search, Flask, Pin } from '../components/Icons.jsx';
import { Badge, Disclaimer, Stat } from '../components/Bits.jsx';
import { useCorpus } from '../App.jsx';

/* The landing page carries the "understood by everyone" load: a vaidya or a
   small manufacturer arrives here not knowing what ABS is, or that section
   3(p) exists. Plain language first, terms of art introduced afterward. */

/* Four capabilities, one pipeline. Each is backed by a module that actually
   exists — nothing is listed here that the system cannot do, because a
   landing page claim is the cheapest possible thing to falsify and the most
   expensive to be caught on. */
const PILLARS = [
  {
    icon: <Flask size={22} />,
    title: 'Product classification',
    body: 'Say what your formulation is — classical, proprietary, phytopharmaceutical, food, cosmetic — and the system works out which regulatory regimes govern it before anything else runs.',
    code: 'ai/compliance · ai/shared/taxonomy.py',
    to: '/assess',
  },
  {
    icon: <Shield size={22} />,
    title: 'IP & regulatory mapping',
    body: 'A knowledge graph resolves which duties your specific facts trigger, which exemptions remove them, in what order they fall due, and which provision each one rests on.',
    code: 'ai/knowledge_graph · ai/patent_prep',
    to: '/cases',
  },
  {
    icon: <Scale size={22} />,
    title: 'Source-grounded retrieval',
    body: 'Answers are composed only from ingested statute text, filtered to your jurisdiction before ranking. Too weak a match produces an abstention rather than a confident guess.',
    code: 'ai/store.py · ai/embedder.py',
    to: '/sources',
  },
  {
    icon: <Doc size={22} />,
    title: 'Explainable guidance',
    body: 'Every answer carries the passages behind it, how closely each matched, whether each citation is actually supported by them, and an audit id you can look up afterwards.',
    code: 'ai/audit.py · citation validation',
    to: '/evidence',
  },
];

const STEPS = [
  { n: '01', t: 'Pick the law that applies', d: 'India, international frameworks, or both. The choice filters the search itself — a treaty can never be quoted at you as if it were Indian law, and “both” is answered twice, separately.' },
  { n: '02', t: 'The law is retrieved', d: 'Your question is matched against ingested statutes, rules and treaties — filtered to the jurisdiction you picked, and to your formulation type, before anything is searched.' },
  { n: '03', t: 'Obligations are screened', d: 'A regulatory knowledge graph works out which duties apply to your specific facts, which exemptions remove them, and in what order they fall due.' },
  { n: '04', t: 'You get a cited answer', d: 'With the sections quoted, a confidence reading, and an honest list of what the system still needs to know before it can be sure.' },
];

export default function Home() {
  const { corpus } = useCorpus();
  const j = corpus?.jurisdictions;

  /* The corpus figures come from /api/v1/corpus rather than being written
     into the page. A number typed into marketing copy drifts from the index
     the moment a document is added, and on a page whose whole claim is that
     its citations are real, a stale figure is the wrong thing to fake. Until
     the count arrives, the tile shows a dash rather than a placeholder. */
  const STATS = [
    [corpus ? corpus.chunks.toLocaleString() : null, 'passages of law indexed'],
    [j ? j.india?.toLocaleString() ?? '0' : null, 'from Indian instruments'],
    [j ? j.international?.toLocaleString() ?? '0' : null, 'from international ones'],
    ['3(p)', 'the section most applicants miss'],
  ];

  return (
    <>
      <section className="shell hero">
        <div className="hero-grid">
          <div className="rise">
            <span className="hero-badge">Smart India Hackathon 2026 · Working prototype</span>
            <h1 style={{ marginTop: 14 }}>
              Know where your formulation stands — <em>before</em> you file.
            </h1>
            <p className="hero-lede">
              Ask a plain question about patenting an Ayurvedic formulation and get an answer grounded in
              the actual sections of the law — Indian, international, or both, answered separately —
              along with the biodiversity and disclosure obligations most applicants only discover
              after a refusal.
            </p>
            <div className="hero-cta">
              <Link to="/assess" className="btn btn-primary">
                <Shield size={18} /> Assess my product
              </Link>
              <Link to="/ask" className="btn btn-ghost">
                <Search size={18} /> Ask IP-SAKTI
              </Link>
            </div>
            <p className="trust-line">
              Evidence-grounded · Citation-first · Confidence-aware ·{' '}
              <span className="faint">Information support, not legal advice.</span>
            </p>
          </div>

          {/* A miniature of a real answer — shows the product in one glance. */}
          <div className="hero-panel rise" style={{ animationDelay: '90ms' }}>
            <p className="hero-panel-q">
              “Can a traditional Ayurvedic formulation be patented?”
            </p>
            <div className="row" style={{ gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
              <Badge tone="neutral"><Pin size={12} /> Under Indian law</Badge>
              <Badge tone="stop">2 blocking duties</Badge>
            </div>
            <p style={{ fontSize: 14.6, lineHeight: 1.6, color: 'var(--text-muted)' }}>
              Unlikely as such — section 3(p) excludes an invention that is, in effect, traditional
              knowledge. A novel process over that base may still qualify…
            </p>
            <div style={{ marginTop: 14, paddingTop: 13, borderTop: '1px solid var(--border)' }}>
              {[['1', 'The Patents Act, 1970', 'Section 3(p)'], ['2', 'Biological Diversity Act, 2002', 'Section 6']].map(([n, act, sec]) => (
                <div key={n} className="row" style={{ gap: 10, marginTop: 8 }}>
                  <span className="cite-n" style={{ width: 22, height: 22, fontSize: 11 }}>{n}</span>
                  <span style={{ fontSize: 13.4, minWidth: 0 }}>
                    <strong style={{ fontWeight: 600 }}>{act}</strong>
                    <span className="faint"> · {sec}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="shell">
        <div className="stat-strip">
          {STATS.map(([n, l]) => <Stat key={l} value={n} label={l} />)}
        </div>
      </section>

      <section className="shell section">
        <div className="section-head">
          <h2>Four capabilities, one pipeline</h2>
          <p>
            Built for the practitioner, small manufacturer or research collective who knows their
            formulation but not the statute book. Each capability below is one stage of the same
            run — not four separate tools bolted together.
          </p>
        </div>
        <div className="features features-4">
          {PILLARS.map((p, i) => (
            <Link
              to={p.to}
              className="feature feature-link rise"
              key={p.title}
              style={{ animationDelay: `${i * 70}ms` }}
            >
              <div className="feature-ico">{p.icon}</div>
              <h3>{p.title}</h3>
              <p>{p.body}</p>
              {/* Naming the module is not decoration: it is the claim that
                  this capability is a thing you can go and read, rather
                  than a line of copy. */}
              <span className="mono faint feature-code">{p.code}</span>
            </Link>
          ))}
        </div>
      </section>

      <section className="shell section">
        <div className="principle">
          <h2 className="principle-h">The model doesn’t invent the law.</h2>
          <p className="principle-p">
            It retrieves the law and explains it. Every guardrail in this system follows from that
            one decision — the jurisdiction filter that runs before ranking, the threshold below
            which it abstains, the check that every citation is actually supported by a retrieved
            passage, the audit trail behind each answer.
          </p>
          <Link to="/about" className="btn btn-ghost btn-sm">How it works</Link>
        </div>

        <div className="section-head" style={{ marginTop: 40 }}>
          <h2>How an answer is put together</h2>
          <p>Four steps, and you can inspect the evidence at every one of them.</p>
        </div>
        <div style={{ display: 'grid', gap: 14 }}>
          {STEPS.map((s, i) => (
            <div className="card rise" key={s.n} style={{ padding: '22px 24px', animationDelay: `${i * 60}ms` }}>
              <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
                <span style={{
                  flexShrink: 0, width: 38, height: 38, borderRadius: 12,
                  display: 'grid', placeItems: 'center',
                  background: 'var(--bg-sunken)', border: '1px solid var(--border)',
                  fontFamily: 'var(--font-display)', fontSize: 17, fontWeight: 600,
                  color: 'var(--brand-text)',
                }}>{s.n}</span>
                <div>
                  <h3 style={{ fontSize: 18, marginBottom: 6 }}>{s.t}</h3>
                  <p className="muted" style={{ fontSize: 14.8, lineHeight: 1.62, maxWidth: '68ch' }}>{s.d}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="shell section">
        <div className="card" style={{ padding: 32, display: 'grid', gap: 20 }}>
          <div className="row" style={{ gap: 12 }}>
            <span className="feature-ico" style={{ margin: 0, width: 38, height: 38 }}><Flask size={19} /></span>
            <h2 style={{ fontSize: 24 }}>What it will not do</h2>
          </div>
          <div className="features" style={{ gap: 16 }}>
            {[
              ['It won’t guess.', 'When retrieval is too weak, the answer is an explicit abstention — not a confident-sounding paragraph built on nothing.'],
              ['It won’t hide its sources.', 'Every citation opens to the section text it came from, so you can judge the answer rather than trust it.'],
              ['It won’t replace your agent.', 'Filing decisions, form mechanics and anything adversarial belong with a registered patent agent. This gets you to that conversation prepared.'],
            ].map(([t, d]) => (
              <div key={t}>
                <h3 style={{ fontSize: 16.5, marginBottom: 7 }}>{t}</h3>
                <p className="muted" style={{ fontSize: 14.4, lineHeight: 1.6 }}>{d}</p>
              </div>
            ))}
          </div>
          <Disclaimer>
            Automated regulatory screening is informational only. Every obligation must be confirmed
            against the bare text of the cited provision, and with a registered patent agent or
            counsel, before it is acted on.
          </Disclaimer>
        </div>
      </section>

      <section className="shell section">
        <div style={{
          borderRadius: 'var(--r-xl)', padding: '44px 36px', textAlign: 'center',
          background: 'linear-gradient(150deg, var(--navy-700), var(--navy-900))',
          boxShadow: 'var(--shadow-lg)', color: '#fff',
        }}>
          <Leaf size={34} style={{ color: 'var(--turmeric-400)', marginBottom: 14 }} />
          <h2 style={{ color: '#fff', fontSize: 'clamp(25px, 3.6vw, 34px)', marginBottom: 12 }}>
            Start with the question you actually have.
          </h2>
          <p style={{ color: 'rgba(255,255,255,.82)', maxWidth: '52ch', margin: '0 auto 26px', fontSize: 16.5, lineHeight: 1.6 }}>
            No account, no jargon. Ask in plain words and see exactly which law the answer rests on.
          </p>
          <div className="row-wrap" style={{ gap: 12, justifyContent: 'center' }}>
            <Link to="/ask" className="btn btn-accent">
              <Search size={18} /> Ask a question
            </Link>
            <Link to="/sources" className="btn btn-onbrand">
              <Doc size={18} /> See the sources first
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
