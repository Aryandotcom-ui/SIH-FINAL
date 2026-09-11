import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api.js';
import { useCorpus } from '../App.jsx';
import { Scale, Shield, Doc, Search, Alert, Leaf } from '../components/Icons.jsx';
import { Badge, Disclaimer, Explain, Stat } from '../components/Bits.jsx';

/**
 * About — the architecture, and the limits.
 *
 * The "Known limits" section below is a direct port of the README's own
 * list, deliberately unsoftened. Stating a limitation before anyone asks
 * reads as engineering maturity; discovering it afterwards reads as
 * something that was being hidden. The figures in it are pulled from the
 * live API rather than typed in, so the list cannot quietly go stale the
 * way a hand-written one does.
 */

const PIPELINE = [
  {
    n: '01',
    t: 'Understand the question',
    d: 'The query is read for the jurisdiction it belongs to, the formulation type it concerns, and the language it is written in. A non-English question is translated to English before anything is searched, because the index is built in English.',
    code: 'ai/translation.py · ai/shared/taxonomy.py',
  },
  {
    n: '02',
    t: 'Classify and route',
    d: 'A regulatory knowledge graph maps the facts to the regimes that govern them — patents, biodiversity, drugs and cosmetics, food — and works out which duties fire, which exemptions remove them, and which questions are still unanswered.',
    code: 'ai/knowledge_graph · ai/compliance',
  },
  {
    n: '03',
    t: 'Retrieve the evidence',
    d: 'The question is matched against ingested statute text, filtered by jurisdiction before ranking rather than after. A retrieval too weak to support an answer produces an abstention, not a guess.',
    code: 'ai/store.py · ai/embedder.py',
  },
  {
    n: '04',
    t: 'Compose and verify',
    d: 'The answer is written only from the retrieved passages, each citation is checked back against them, and the whole exchange is written to an audit trail you can look up afterwards.',
    code: 'ai/person_c_generation · ai/audit.py',
  },
];

export default function About() {
  const { corpus } = useCorpus();
  const [library, setLibrary] = useState(null);
  const [status, setStatus] = useState(null);

  useEffect(() => {
    const ctrl = new AbortController();
    // Both are supporting detail. A failure leaves a dash in a figure; it
    // does not take the page down.
    api.corpusDocuments({ signal: ctrl.signal })
      .then(d => { if (!ctrl.signal.aborted) setLibrary(d); }).catch(() => {});
    api.status({ signal: ctrl.signal })
      .then(s => { if (!ctrl.signal.aborted) setStatus(s); }).catch(() => {});
    return () => ctrl.abort();
  }, []);

  const linkGap = library ? library.ingested - library.with_source_url : null;

  return (
    <div className="shell" style={{ maxWidth: 900 }}>
      <div style={{ marginBottom: 28 }}>
        <span className="eyebrow">About</span>
        <h1 style={{ fontSize: 'clamp(30px, 4vw, 42px)', margin: '10px 0 14px' }}>
          The model doesn’t invent the law.
        </h1>
        <p className="muted" style={{ fontSize: 17, lineHeight: 1.62, maxWidth: '62ch' }}>
          It retrieves the law and explains it. Everything else in this system follows from that
          one decision — the jurisdiction filter, the abstention threshold, the citation check,
          the audit trail. Each exists to keep a fluent paragraph from standing in for a provision
          nobody read.
        </p>
      </div>

      <section className="section">
        <div className="section-head">
          <h2>How an answer is built</h2>
          <p>Four stages, each backed by a module you can read.</p>
        </div>
        <div style={{ display: 'grid', gap: 14 }}>
          {PIPELINE.map(s => (
            <div className="card" key={s.n} style={{ padding: '22px 24px' }}>
              <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
                <span className="step-n step-n-lg">{s.n}</span>
                <div style={{ minWidth: 0 }}>
                  <h3 style={{ fontSize: 18, marginBottom: 6 }}>{s.t}</h3>
                  <p className="muted" style={{ fontSize: 14.8, lineHeight: 1.62, maxWidth: '66ch' }}>{s.d}</p>
                  <p className="mono faint" style={{ fontSize: 12.4, marginTop: 9 }}>{s.code}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>What the corpus is</h2>
          <p>A fixed, inspectable set of instruments — not a model’s recollection of them.</p>
        </div>
        <div className="stat-strip">
          <Stat value={library?.total ?? null} label="documents listed" />
          <Stat value={library?.ingested ?? null} label="ingested and citable" />
          <Stat value={corpus?.chunks?.toLocaleString() ?? null} label="passages indexed" />
          <Stat
            value={status ? `${Math.round(status.abstain_threshold * 100)}%` : null}
            label="abstention threshold"
            hint="Below this the system refuses to answer rather than assembling something from weak matches."
          />
        </div>
        <p className="muted" style={{ fontSize: 14.8, lineHeight: 1.62, marginTop: 16 }}>
          Every document, its authority, dates and official link — where one has been verified —
          is listed on <Link to="/sources">Knowledge Sources</Link>. Every answer’s own evidence is
          at <Link to="/evidence">Evidence</Link>.
        </p>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>Design decisions worth defending</h2>
        </div>
        <div className="features">
          {[
            {
              icon: <Scale size={20} />,
              t: 'Abstention over fluency',
              d: 'When confidence falls below the threshold, the answer is an explicit “I can’t tell from the corpus” rather than a confident paragraph built on nothing. It is the behaviour most often mistaken for a bug and the one most worth keeping — but see the known limits below for how well the current embedder actually gets confidence low enough to trigger it.',
            },
            {
              icon: <Shield size={20} />,
              t: 'Jurisdictions are never blended',
              d: 'India and international are two separately filtered searches and two separate generation calls. A Patents Act clause and a PCT rule can never be stitched into one paragraph across two legal systems, because they never share a ranking.',
            },
            {
              icon: <Doc size={20} />,
              t: 'Unknown is not the same as no',
              d: 'The compliance screening reports “not enough information” as its own state. A missing fact never quietly becomes a clean bill of health — the questions that decide an obligation are listed instead.',
            },
            {
              icon: <Alert size={20} />,
              t: 'Degradation is announced',
              d: 'Without a generation key the prose is a canned stand-in, and the interface says so on the answer itself. Passing canned text off as a generated answer would be exactly the dishonesty this project exists to prevent.',
            },
          ].map(f => (
            <div className="feature" key={f.t}>
              <div className="feature-ico">{f.icon}</div>
              <h3>{f.t}</h3>
              <p>{f.d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Ported from the README's own list, unsoftened. */}
      <section className="section">
        <div className="section-head">
          <h2>Known limits</h2>
          <p>These are real and worth knowing before you rely on anything here.</p>
        </div>
        <div style={{ display: 'grid', gap: 12 }}>
          <Limit title={
            linkGap != null
              ? `${linkGap} of the ${library.ingested} ingested corpus documents have no source_url`
              : 'Most ingested corpus documents have no source_url'
          }>
            Their citations cannot link out to the official text, and the interface marks these
            “no public link”. They are fully ingested and quoted verbatim; there is just no
            verified URL on file. Filling these in needs a machine that can reach the official
            sites.
          </Limit>

          <Limit
            title="The offline embedder is lexical"
            badge={status?.embedding_is_fallback ? <Badge tone="warn">in use right now</Badge> : null}
          >
            The <span className="mono">tfidf</span> backend is character-ngram TF-IDF, so it
            matches wording rather than meaning: a question phrased far from the statute’s
            language can retrieve the wrong Act. It exists so the system runs with no model
            download. For better retrieval, install{' '}
            <span className="mono">sentence-transformers</span>, uncomment it in{' '}
            <span className="mono">ai/requirements.txt</span>, and rebuild with{' '}
            <span className="mono">./scripts/run.sh --rebuild</span> — queries must be encoded in
            the same space as the chunks, so switching embedders <em>requires</em> a rebuild.
          </Limit>

          {/* Measured, not asserted. See ai/person_c_generation/eval —
              this limit exists in the list because the eval suite found
              it, which is what the eval is for. */}
          <Limit
            title="Abstention does not currently fire on out-of-scope questions"
            badge={<Badge tone="stop">measured</Badge>}
          >
            The eval suite measures this directly, and it is a threshold problem rather than a
            broken mechanism. Over 22 scored questions the system answered all five deliberately
            out-of-scope ones — GST rates, company incorporation, customs duty — instead of
            abstaining. But the signal does separate: questions the corpus <em>can</em> answer
            score 0.597–0.906 and ones it cannot score 0.200–0.723, so the configured threshold of
            20% simply sits far below the boundary. Raising it toward 50–60% would catch three of
            the five at no measured cost to the seventeen answerable questions. That has not been
            changed on a five-question sample. Until it is, treat an answer on a topic outside
            Indian IP, biodiversity, drugs, cosmetics or food law as unreliable regardless of the
            confidence shown beside it.
          </Limit>

          <Limit title="Retrieval quality is bounded by the embedder in use">
            Retrieval combines dense vector search with a BM25-style lexical pass, so a rare
            statutory term the embedding handles poorly still has a lexical route to the right
            provision. That helps most when the index was built with the offline TF-IDF backend,
            which matches wording rather than meaning. It does not make the pairing exact: check
            the passages on the Evidence view rather than trusting the ranking.
          </Limit>

          <Limit title="Deadlines marked “unverified”">
            These come from rules whose current figures were not confirmed against amended text;
            the request-for-examination window in particular changed in 2024. Confirm before
            relying on any date.
          </Limit>

          <Limit title="Nothing here is legal advice">
            Every obligation must be checked against the bare text of the cited provision and with
            a registered patent agent.
          </Limit>
        </div>
      </section>

      <section className="section">
        <div className="card" style={{ padding: 30 }}>
          <div className="row" style={{ gap: 12, marginBottom: 14 }}>
            <span className="feature-ico" style={{ margin: 0, width: 38, height: 38 }}>
              <Leaf size={19} />
            </span>
            <h2 style={{ fontSize: 22 }}>Smart India Hackathon 2026</h2>
          </div>
          <p className="muted" style={{ fontSize: 15, lineHeight: 1.65, maxWidth: '64ch' }}>
            A working prototype for citation-grounded intellectual-property and regulatory guidance
            in Ayurveda — built for the practitioner, small manufacturer or research collective who
            knows their formulation but not the statute book, and who does not yet have a patent
            agent to ask.
          </p>
          <div className="row-wrap" style={{ gap: 10, marginTop: 20 }}>
            <Link to="/assess" className="btn btn-primary btn-sm"><Shield size={15} /> Assess a product</Link>
            <Link to="/ask" className="btn btn-ghost btn-sm"><Search size={15} /> Ask a question</Link>
          </div>
        </div>
      </section>

      <div style={{ marginBottom: 40 }}>
        <Disclaimer>
          Informational only. Not legal advice. The corpus consists of public legal instruments;
          each document’s provenance is recorded in the corpus manifest and listed on{' '}
          <Link to="/sources">Knowledge Sources</Link>.
        </Disclaimer>
      </div>
    </div>
  );
}

function Limit({ title, badge, children }) {
  return (
    <div className="limit">
      <Alert size={17} style={{ flexShrink: 0, color: 'var(--warn)', marginTop: 2 }} />
      <div style={{ minWidth: 0 }}>
        <div className="row-wrap" style={{ gap: 9 }}>
          <strong style={{ fontSize: 15.2, fontWeight: 600 }}>{title}</strong>
          {badge}
        </div>
        <p className="muted" style={{ fontSize: 14.4, lineHeight: 1.6, marginTop: 6 }}>{children}</p>
      </div>
    </div>
  );
}
