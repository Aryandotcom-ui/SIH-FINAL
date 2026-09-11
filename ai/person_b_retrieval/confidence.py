import re
from typing import Sequence


# Words that do not carry much evidence about the subject of a legal question.
STOPWORDS = {
    "a", "an", "the", "i", "me", "my", "we", "our", "you", "your",
    "can", "could", "would", "should", "may", "might",
    "is", "are", "am", "be", "been", "being",
    "do", "does", "did",
    "what", "which", "who", "when", "where", "how", "why",
    "to", "of", "for", "in", "on", "at", "by", "with", "from",
    "and", "or", "but", "if", "then",
    "it", "this", "that", "these", "those",
    "tell", "please", "kind", "kinds",
}


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[a-zA-Z0-9]+", text)
        if token.lower() not in STOPWORDS
        and len(token) > 2
    }


# The default abstention threshold for this module. The application passes
# its own configured value (settings.abstain_threshold) rather than relying
# on this, so the two can legitimately differ — but a caller that does not
# pass one should get a single named default, not two literals that can
# drift apart.
ABSTAIN_THRESHOLD = 0.50


def compute_confidence(
    query: str,
    matched_chunks,
    threshold: float = ABSTAIN_THRESHOLD,
) -> tuple[float, bool]:
    """
    Confidence measures whether the retrieved evidence actually covers
    the subject of the question, not merely whether the embeddings
    are semantically similar.

    Returns:
        (confidence, should_abstain)
    """

    if not matched_chunks:
        return 0.0, True

    # ---------------------------------------------------------
    # 1. Base retrieval confidence
    # ---------------------------------------------------------
    similarities = [
        max(0.0, min(1.0, float(chunk.similarity_score)))
        for chunk in matched_chunks
    ]

    top_score = similarities[0]

    # Agreement between the best few sources.
    if len(similarities) >= 2:
        agreement = sum(similarities[:3]) / min(3, len(similarities))
    else:
        agreement = top_score

    base_confidence = (
        0.70 * top_score +
        0.30 * agreement
    )

    # ---------------------------------------------------------
    # 2. Evidence coverage
    # ---------------------------------------------------------
    query_terms = _tokens(query)

    if not query_terms:
        coverage = 1.0
    else:
        retrieved_text = " ".join(
            str(chunk.text)
            for chunk in matched_chunks[:5]
        ).lower()

        covered_terms = sum(
            1 for term in query_terms
            if term in retrieved_text
        )

        coverage = covered_terms / len(query_terms)

    # ---------------------------------------------------------
    # 3. Combine similarity + evidence coverage
    # ---------------------------------------------------------
    confidence = (
        0.55 * base_confidence +
        0.45 * coverage
    )

    # ---------------------------------------------------------
    # 4. Critical safety rule:
    # If the query contains important subject terms that the
    # retrieved evidence does not mention, do NOT allow a
    # high similarity score to produce high confidence.
    # ---------------------------------------------------------
    if query_terms and coverage < 0.50:
        confidence = min(confidence, 0.35)

    if query_terms and coverage < 0.34:
        confidence = min(confidence, 0.20)

    confidence = max(0.0, min(1.0, confidence))

    should_abstain = confidence < threshold

    return round(confidence, 4), should_abstain
def decide_abstain(confidence: float, threshold: float = ABSTAIN_THRESHOLD) -> bool:
    """Return True when confidence is too low to answer reliably."""
    return confidence < threshold