import numpy as np
from pathlib import Path

from ai.embedder import get_embedder
from ai.store import VectorStore


QUERY = "What kinds of subject matter cannot be patented in India?"

SECTION_ID = "the-patents-act-1970--s3"


print("=" * 80)
print("SECTION 3 DIRECT EMBEDDING TEST")
print("=" * 80)

embedder = get_embedder(
    "BAAI/bge-small-en-v1.5",
    device="cpu",
)

store = VectorStore(
    Path("data/chroma")
)

# ------------------------------------------------------------
# Get Section 3 directly from Chroma
# ------------------------------------------------------------

result = store.collection.get(
    ids=[SECTION_ID],
    include=[
        "documents",
        "metadatas",
        "embeddings",
    ],
)

if not result.get("ids"):
    print("ERROR: Section 3 was not found in Chroma.")
    raise SystemExit(1)

section_text = result["documents"][0]
section_metadata = result["metadatas"][0]
section_embedding = np.array(
    result["embeddings"][0],
    dtype=float,
)

# ------------------------------------------------------------
# Embed the natural-language query
# ------------------------------------------------------------

query_embedding = np.array(
    embedder.encode_query([QUERY])[0],
    dtype=float,
)

# ------------------------------------------------------------
# Calculate cosine similarity directly
# ------------------------------------------------------------

query_norm = np.linalg.norm(query_embedding)
section_norm = np.linalg.norm(section_embedding)

similarity = float(
    np.dot(query_embedding, section_embedding)
    / (query_norm * section_norm)
)

print("\nQUERY:")
print(QUERY)

print("\nSECTION:")
print(section_metadata.get("section"))

print("ACT:")
print(section_metadata.get("act_name"))

print("\nBGE COSINE SIMILARITY:")
print(f"{similarity:.6f}")

print("\nSECTION TEXT:")
print(section_text[:2000])

print("\n" + "=" * 80)