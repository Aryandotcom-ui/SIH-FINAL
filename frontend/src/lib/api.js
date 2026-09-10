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
    // 'server'   — the API answered with an error
    this.kind = kind;
  }
}

/** Fetch with a timeout — a hung backend must not hang the UI forever. */
async function req(path, { method = 'GET', body, signal } = {}) {
  const ctrl = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; ctrl.abort(); }, TIMEOUT_MS);
  if (signal) signal.addEventListener('abort', () => ctrl.abort(), { once: true });

  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
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
    throw new ApiError(
      detail.detail || `${res.status} ${res.statusText}`,
      { status: res.status, kind: res.status === 503 ? 'notready' : 'server' },
    );
  }
  // An empty body is a legitimate answer, not a parse failure.
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

export const api = {
  corpus: ({ signal } = {}) => req('/corpus', { signal }),

  ask: ({ query, scope, classification, complianceFacts, topK = 5, signal }) =>
    req('/query', {
      method: 'POST',
      signal,
      body: {
        query,
        top_k: topK,
        scope,
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
