from pathlib import Path

from ai.embedder import get_embedder
from ai.store import VectorStore


QUERY = "What kinds of subject matter cannot be patented in India?"


embedder = get_embedder(
    "BAAI/bge-small-en-v1.5",
    device="cpu",
)

store = VectorStore(
    Path("data/chroma")
)

result = store.query(
    query=QUERY,
    embedder=embedder,
    jurisdiction="india",
    top_k=20,
)

print("\n" + "=" * 80)
print("DIRECT RETRIEVAL DEBUG")
print("=" * 80)
print("QUERY:", QUERY)
print("=" * 80)

for i, match in enumerate(result["matches"], 1):
    print(
        f"\n{i}. "
        f"{match['act_name']} | "
        f"{match['section']} | "
        f"score={match['similarity_score']:.6f}"
    )

    print("   chunk:", match["chunk_id"])

    text = match["text"].replace("\n", " ")
    print("   text:", text[:300])

print("\n" + "=" * 80)