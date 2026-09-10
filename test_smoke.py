import requests
import json

BASE_URL = "http://127.0.0.1:8000/api/v1/query"


def run_test(name, query, scope="IN", classification=None):
    print("\n" + "=" * 80)
    print(name)
    print("=" * 80)
    print("Query:", query)
    print("Scope:", scope)

    payload = {
        "query": query,
        "top_k": 5,
        "scope": scope,
        "classification": classification,
        "compliance_facts": None,
        "consent_licensed_acts": [],
    }

    try:
        response = requests.post(
            BASE_URL,
            json=payload,
            timeout=120,
        )

        print("HTTP:", response.status_code)

        if response.status_code != 200:
            print(response.text)
            return

        data = response.json()

        print("\nANSWER:")
        print(data.get("answer_text"))

        print("\nCONFIDENCE:")
        print(data.get("confidence"))

        print("\nABSTAINED:")
        print(data.get("abstained"))

        print("\nSOURCES:")

        sources = data.get("sources", [])

        if not sources:
            print("  No sources returned.")

        for i, source in enumerate(sources, 1):
            print(
                f"  {i}. "
                f"{source.get('act_name')} | "
                f"{source.get('section')} | "
                f"score={source.get('similarity_score')} | "
                f"jurisdiction={source.get('jurisdiction')}"
            )

        return data

    except Exception as e:
        print("ERROR:", repr(e))


# ============================================================
# TEST 1 — Exact Section 3
# ============================================================

run_test(
    "TEST 1 — Exact Section 3",
    "What does Section 3 of the Patents Act, 1970 say?",
)


# ============================================================
# TEST 2 — Natural-language semantic retrieval
# ============================================================

run_test(
    "TEST 2 — Patentability / semantic retrieval",
    "What kinds of subject matter cannot be patented in India?",
)


# ============================================================
# TEST 3 — Exact Section 2
# ============================================================

run_test(
    "TEST 3 — Exact Section 2",
    "What does Section 2 of the Patents Act, 1970 say?",
)


# ============================================================
# TEST 4 — International retrieval
# ============================================================

run_test(
    "TEST 4 — International",
    "What are the international requirements for protecting traditional knowledge?",
    scope="INTL",
)


# ============================================================
# TEST 5 — BOTH + formulation classification
# ============================================================

run_test(
    "TEST 5 — BOTH + Classical formulation",
    "What legal considerations apply to protecting an Ayurvedic formulation?",
    scope="BOTH",
    classification={
        "formulation_type": "classical"
    },
)