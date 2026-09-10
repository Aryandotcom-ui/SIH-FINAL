/**
 * Backend client for the IP-SAKTI Sahayak FastAPI service.
 *
 * Every call goes to the real API. There is no sample-data fallback: a
 * fabricated legal answer is the one failure this project exists to prevent,
 * and a UI that silently substitutes invented content for an unreachable
 * backend is that failure with a friendlier face. When a request fails it
 * throws an ApiError, and the calling screen says what went wrong and offers
 * a retry — the honest version of the same information.
 */

const BASE = import.meta.env.VITE_API_BASE ?? '/api/v1';
// Free hosting tiers sleep an idle service and take up to a minute to wake
// it, so a short timeout turns a cold start into a false "server is down".
// Overridable for a deployment that is always warm.
const TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS) || 60000;

/**
 * The operator's bearer token.
 *
 * Held in sessionStorage, not localStorage: a reviewer's session should not
 * outlive the browser tab. The reviewer console is the one surface that can
 * change what enters the corpus, and a token that survives until someone
 * thinks to log out is a token that survives a shared machine.
 */
const TOKEN_KEY = 'ipsakti-token';

export const auth = {
  get token() {
    try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
  },
  set token(value) {
    try {
      if (value) sessionStorage.setItem(TOKEN_KEY, value);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch { /* private mode — the session simply won't persist */ }
  },
};

/** A failed API call, carrying enough for the UI to explain itself. */
export class ApiError extends Error {
  constructor(message, { status = 0, kind = 'server' } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    // 'offline'  — the request never reached an API (nothing running, CORS,
    //              DNS, or a cold start that outlasted the timeout)
    // 'timeout'  — it reached one, but nothing came back in time
    // 'notready' — the API is up but the corpus is not ingested (503)
    // 'auth'     — not signed in, or the session expired (401)
    // 'forbidden'— signed in, but this role may not do that (403)
    // 'server'   — the API answered with an error
    this.kind = kind;
  }
}

/** Fetch with a timeout — a hung backend must not hang the UI forever. */
async function req(path, { method = 'GET', body, signal, form } = {}) {
  const ctrl = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; ctrl.abort(); }, TIMEOUT_MS);
  if (signal) signal.addEventListener('abort', () => ctrl.abort(), { once: true });

  const headers = {};
  // OAuth2's password grant is a form post, not JSON — that is the shape
  // FastAPI's OAuth2PasswordRequestForm parses, and matching it is what
  // makes the /docs "Authorize" button work against the same login.
  if (form !== undefined) headers['Content-Type'] = 'application/x-www-form-urlencoded';
  else if (body !== undefined) headers['Content-Type'] = 'application/json';
  const token = auth.token;
  if (token) headers.Authorization = `Bearer ${token}`;

  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      headers: Object.keys(headers).length ? headers : undefined,
      body: form !== undefined
        ? new URLSearchParams(form).toString()
        : body !== undefined ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
  } catch (err) {
    if (timedOut) {
      throw new ApiError(
        'The API did not respond in time. A free-tier server sleeps when idle and can take up to a minute to wake — try again.',
        { kind: 'timeout' },
      );
    }
    // A caller-initiated abort is not a failure to report: let it through so
    // an in-flight request replaced by a newer one stays silent.
    if (err.name === 'AbortError') throw err;
    throw new ApiError(
      'Could not reach the API. Check that the backend is running and that VITE_API_BASE points at it.',
      { kind: 'offline' },
    );
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    // Drop a token the server has stopped accepting, so the UI shows a
    // login form instead of retrying a dead session forever.
    if (res.status === 401) auth.token = null;
    const kind =
      res.status === 503 ? 'notready' :
      res.status === 401 ? 'auth' :
      res.status === 403 ? 'forbidden' : 'server';
    throw new ApiError(
      detail.detail || `${res.status} ${res.statusText}`,
      { status: res.status, kind },
    );
  }
  // An empty body is a legitimate answer, not a parse failure.
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

export const api = {
  corpus: ({ signal } = {}) => req('/corpus', { signal }),

  // --- read-only views over what the pipeline already produced -----------
  corpusDocuments: ({ signal } = {}) => req('/corpus/documents', { signal }),
  status: ({ signal } = {}) => req('/status', { signal }),
  evidence: (auditId, { signal } = {}) =>
    req(`/evidence/${encodeURIComponent(auditId)}`, { signal }),
  assess: ({ classification, facts, signal }) =>
    req('/assess', {
      method: 'POST',
      signal,
      body: {
        classification: classification && Object.values(classification).some(Boolean)
          ? classification : null,
        facts: facts && Object.keys(facts).length ? facts : null,
      },
    }),

  // --- operator session --------------------------------------------------
  login: async (username, password) => {
    const data = await req('/auth/login', {
      method: 'POST',
      form: { username, password, grant_type: 'password' },
    });
    auth.token = data.access_token;
    return data;
  },
  me: ({ signal } = {}) => req('/auth/me', { signal }),
  logout: () => { auth.token = null; },

  ask: ({ query, scope, classification, complianceFacts, language, topK = 5, signal }) =>
    req('/query', {
      method: 'POST',
      signal,
      body: {
        query,
        top_k: topK,
        scope,
        // null means "work it out from the query text". The backend's
        // detector is a Unicode-script heuristic, so an explicit choice
        // from the header picker is strictly better information — but only
        // when the user actually made one.
        language: language || null,
        classification: classification && Object.values(classification).some(Boolean)
          ? classification : null,
        compliance_facts: complianceFacts && Object.keys(complianceFacts).length
          ? complianceFacts : null,
        consent_licensed_acts: [],
      },
    }),

  // --- patent cases ------------------------------------------------------
  cases: ({ signal } = {}) => req('/patent-cases', { signal }),
  createCase: (intake) => req('/patent-cases', { method: 'POST', body: intake }),
  caseDetail: (id, { signal } = {}) => req(`/patent-cases/${id}`, { signal }),
  caseDeadlines: (id, { signal } = {}) => req(`/patent-cases/${id}/deadlines`, { signal }),
  casePrecheck: (id) => req(`/patent-cases/${id}/precheck`, { method: 'POST', body: {} }),
  caseDraftForms: (id) => req(`/patent-cases/${id}/draft-forms`, { method: 'POST', body: {} }),
  caseHandoff: (id, { recipient, notes }) =>
    req(`/patent-cases/${id}/handoff`, {
      method: 'POST',
      body: { recipient, notes: notes || null },
    }),

  // --- corpus review gate ------------------------------------------------
  reviewPending: ({ signal } = {}) => req('/updates/pending', { signal }),
  reviewQueued: ({ signal } = {}) => req('/updates/queued', { signal }),
  reviewHistory: ({ signal } = {}) => req('/updates/history', { signal }),
  reviewNeedsAudit: ({ signal } = {}) => req('/updates/needs-audit', { signal }),
  reviewCheckNow: () => req('/updates/check-now', { method: 'POST', body: {} }),
  // The decision body carries notes only. Who decided comes from the
  // bearer token server-side and cannot be set from here — see
  // backend/app/auth.py.
  reviewApprove: (id, decision) => req(`/updates/${id}/approve`, { method: 'POST', body: decision }),
  reviewReject: (id, decision) => req(`/updates/${id}/reject`, { method: 'POST', body: decision }),
  reviewClearAudit: (id, decision) => req(`/updates/${id}/clear-audit`, { method: 'POST', body: decision }),
  reviewPublish: (id) => req(`/updates/${id}/publish`, { method: 'POST', body: {} }),
};

/**
 * The jurisdiction scope.
 *
 * This is a hard filter on retrieval, not a display option: it decides which
 * chunks are eligible before the search runs. "Both" is answered as two
 * separately filtered searches and two separate generation calls rather than
 * one blended ranking, so an Indian statute and a treaty can never be
 * stitched into a single paragraph across two legal systems. See
 * backend/app/services/ai_service.py.
 */
export const SCOPES = [
  { value: 'IN', label: 'India', jurisdiction: 'india', hint: 'Indian statutes, rules and guidelines only' },
  { value: 'INTL', label: 'International', jurisdiction: 'international', hint: 'Treaties and international instruments only' },
  { value: 'BOTH', label: 'Both', jurisdiction: null, hint: 'Answered separately under each, never merged' },
];

// Nothing is asked of the user before they have typed anything, so the
// default covers everything rather than forcing a jurisdiction choice.
export const DEFAULT_SCOPE = 'BOTH';

export const FORMULATION_TYPES = [
  { value: 'classical', label: 'Classical', hint: 'Made to a formula in an authoritative classical text' },
  { value: 'proprietary', label: 'Proprietary', hint: 'Your own formulation, not from a classical text' },
  { value: 'phytopharmaceutical', label: 'Phytopharmaceutical', hint: 'Purified plant extract with defined constituents' },
  { value: 'new_drug', label: 'New drug', hint: 'Regulated as a new drug' },
  { value: 'aahar', label: 'Ayurveda Aahar', hint: 'Sold as a food, not a medicine' },
  { value: 'cosmetic', label: 'Cosmetic', hint: 'Sold as a cosmetic' },
];

export const APPLICANT_CATEGORIES = [
  { value: 'indian_individual', label: 'Indian citizen' },
  { value: 'indian_entity', label: 'Indian company' },
  { value: 'foreign_controlled_entity', label: 'Indian company, foreign-controlled' },
  { value: 'non_resident_indian', label: 'Non-resident Indian' },
  { value: 'foreign_national', label: 'Foreign national or company' },
];

export const RESOURCE_ORIGINS = [
  { value: 'india', label: 'From India' },
  { value: 'outside_india', label: 'Outside India' },
  { value: 'mixed', label: 'Both' },
];

export const CULTIVATION = [
  { value: 'cultivated', label: 'Cultivated' },
  { value: 'wild_collected', label: 'Wild-collected' },
  { value: 'mixed', label: 'Both' },
];

/**
 * The answer language.
 *
 * `null` means "detect it from the query text" — the backend falls back to
 * a Unicode-script heuristic (Devanagari, Kannada, ...) when no explicit
 * language is sent. That heuristic is the default rather than the only
 * option because it cannot tell Hindi from Marathi, and a picker can.
 *
 * Translation only actually happens when a Bhashini backend is configured;
 * without one the answer comes back in English with `translated: false`,
 * and the UI says so rather than pretending the choice took effect.
 */
export const LANGUAGES = [
  { value: null, label: 'EN', name: 'English' },
  { value: 'hi', label: 'हिन्दी', name: 'Hindi' },
  { value: 'kn', label: 'ಕನ್ನಡ', name: 'Kannada' },
];
