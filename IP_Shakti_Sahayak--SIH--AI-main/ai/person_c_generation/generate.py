"""
person_c_generation/generate.py

Answer-generation module for the legal RAG pipeline.

Takes a Shape-3 `retrieval_result` (produced by Person B), formats it into
the system prompt in prompts/system_prompt.txt, calls the LLM, and parses
the response into the Shape-4 `final_answer` schema.

Today this is wired to fixtures/fake_retrieval_result.json. Swapping in
Person B's real retrieval function later means only changing where
`retrieval_result` comes from (see `main()` at the bottom) — the
`generate_answer()` signature does not change.

Usage:
    python generate.py                     # runs the fixture, calls the real LLM API
    python generate.py --mock              # runs the fixture with a canned response (no API key needed)
    python generate.py --abstain           # runs the abstain fixture
    python generate.py --query "..." --mock

Environment:
    GROQ_API_KEY        required unless --mock is used
    LLM_MODEL           optional, defaults to a Groq-hosted model — set to
                         whatever model string your Groq account has access to
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# Make `shared/schema.py` importable regardless of cwd.
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.schema import (  # noqa: E402
    Citation,
    FinalAnswer,
    MatchedChunk,
    RetrievalResult,
)

DEFAULT_MODEL = os.environ.get(
    "LLM_MODEL",
    "openai/gpt-oss-120b",
)
SYSTEM_PROMPT_PATH = _THIS_DIR / "prompts" / "system_prompt.txt"


# ---------------------------------------------------------------------------
# Prompt formatting
# ---------------------------------------------------------------------------

def load_prompt_template(path: Path = SYSTEM_PROMPT_PATH) -> str:
    return path.read_text(encoding="utf-8")


def format_sources(matched_chunks: list[MatchedChunk]) -> str:
    """Render matched chunks as a numbered block the LLM can cite from."""
    if not matched_chunks:
        return "(no sources retrieved)"

    blocks = []
    for i, c in enumerate(matched_chunks, start=1):
        blocks.append(
            f"[{i}] act_name: {c.act_name}\n"
            f"    section: {c.section}\n"
            f"    jurisdiction: {c.jurisdiction}\n"
            f"    similarity_score: {c.similarity_score}\n"
            f"    text: {c.text}"
        )
    return "\n\n".join(blocks)


def jurisdiction_rule(label: str | None) -> str:
    """The instruction that keeps one jurisdiction's answer inside it.

    Retrieval has already been filtered, so the other jurisdiction's text is
    not in the prompt at all. This closes the remaining hole: the model's own
    training knowledge, which will happily supply a TRIPS article the sources
    never mentioned. Empty when no jurisdiction was requested, in which case
    the template's own general rule about not mixing jurisdictions applies.
    """
    if not label:
        return ""
    return (
        f"JURISDICTION: you are answering under {label} law only. Use ONLY the "
        f"{label} sources provided. Do not reference, compare with, or infer "
        f"rules from any other jurisdiction, and do not supply a provision "
        f"from memory that is not in the sources above — if the {label} "
        f"sources do not cover it, say so."
    )


def build_prompt(
    template: str,
    retrieval_result: RetrievalResult,
    jurisdiction_label: str | None = None,
) -> str:
    """
    Fill {chunks}, {query} and {jurisdiction_rule} in the system prompt
    template.

    NOTE: the template also contains a literal JSON example with `{` `}`
    braces (the "Respond in this exact JSON shape" line), so we can't use
    str.format() naively — it would choke on those braces. We do a plain
    substring replace instead.
    """
    sources_block = format_sources(retrieval_result.matched_chunks)
    prompt = template.replace("{chunks}", sources_block)
    prompt = prompt.replace("{query}", retrieval_result.query)
    prompt = prompt.replace("{jurisdiction_rule}", jurisdiction_rule(jurisdiction_label))
    return prompt


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

class MockLLM:
    """
    Deterministic stand-in for the real API, used for offline development
    and for the eval runner so tests don't require network access or an
    API key. Mimics the abstain / cite-first-two-chunks behavior a
    well-behaved model should exhibit given this system prompt.
    """

    def complete(self, prompt: str, retrieval_result: RetrievalResult) -> str:
        if retrieval_result.should_abstain or not retrieval_result.matched_chunks:
            payload = {
                "answer_text": (
                    "The provided sources do not clearly answer this question, "
                    "so I can't provide a reliable answer here."
                ),
                "citations": [],
                "abstained": True,
            }
            return json.dumps(payload)

        top = retrieval_result.matched_chunks[0]
        payload = {
            "answer_text": (
                f"Based on {top.act_name} ({top.jurisdiction} jurisdiction), "
                f"the sources address this. See {top.section} for the operative rule. "
                'This is informational, not legal advice.'
            ),
            "citations": [
                {"act_name": c.act_name, "section": c.section}
                for c in retrieval_result.matched_chunks[:2]
            ],
            "abstained": False,
        }
        return json.dumps(payload)


def call_llm(
    prompt: str,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
) -> str:
    """
    Call Groq's OpenAI-compatible chat completion API.

    The rest of the RAG pipeline remains provider-independent:
    retrieval -> prompt -> LLM -> JSON parsing -> FinalAnswer.
    """

    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError(
            "The 'openai' package is required for Groq API calls. "
            "Install it with: pip install openai"
        ) from e

    api_key = api_key or os.environ.get("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. "
            "Add it to your .env file or pass api_key explicitly."
        )

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        max_tokens=1024,
        temperature=0,
    )

    if not response.choices:
        raise RuntimeError("Groq returned an empty response.")

    content = response.choices[0].message.content

    if not content:
        raise RuntimeError("Groq returned an empty message.")

    return content


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def parse_llm_response(raw_text: str) -> dict:
    """
    Strip markdown code fences if present and parse the JSON payload the
    model was instructed to return.
    """
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Fall back to grabbing the first {...} block in case the model
        # added stray preamble text despite instructions.
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"Could not parse LLM response as JSON: {raw_text!r}") from e


# ---------------------------------------------------------------------------
# Main entry point used by both the app and the eval runner
# ---------------------------------------------------------------------------

def generate_answer(
    retrieval_result: RetrievalResult,
    model: str = DEFAULT_MODEL,
    mock: bool = False,
    prompt_template_path: Path = SYSTEM_PROMPT_PATH,
    api_key: str | None = None,
    jurisdiction_label: str | None = None,
) -> FinalAnswer:
    """
    Core function: retrieval_result -> final_answer.

    This is the function Person B's real retrieval output gets plugged into
    later — the signature stays the same whether `retrieval_result` came
    from the fixture file or from a live ChromaDB/SQLite-backed call.

    `api_key` is forwarded to call_llm() as-is (None falls back to the
    GROQ_API_KEY environment variable there) — see its docstring.

    `jurisdiction_label` ("India" / "International") constrains the answer to
    one legal system. Retrieval is already filtered to it by the caller; this
    stops the model topping the answer up from its own training knowledge.
    None leaves the prompt's general no-mixing rule to do the work, which is
    the behaviour every caller had before the jurisdiction scope existed.
    """
    template = load_prompt_template(prompt_template_path)
    prompt = build_prompt(template, retrieval_result, jurisdiction_label)

    if mock:
        raw = MockLLM().complete(prompt, retrieval_result)
    else:
        raw = call_llm(prompt, model=model, api_key=api_key)

    parsed = parse_llm_response(raw)

    citations = [
        Citation(act_name=c["act_name"], section=c["section"])
        for c in parsed.get("citations", [])
    ]

    return FinalAnswer(
        answer_text=parsed.get("answer_text", ""),
        citations=citations,
        confidence=retrieval_result.confidence,
        abstained=parsed.get("abstained", retrieval_result.should_abstain),
        disclaimer="This is informational, not legal advice.",
    )


def load_retrieval_result_from_fixture(abstain: bool = False) -> RetrievalResult:
    fixture_name = (
        "fake_retrieval_result_abstain.json" if abstain else "fake_retrieval_result.json"
    )
    path = _THIS_DIR / "fixtures" / fixture_name
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return RetrievalResult.from_dict(data)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Run Person C's answer-generation module.")
    parser.add_argument("--mock", action="store_true", help="Use MockLLM instead of a real API call.")
    parser.add_argument("--abstain", action="store_true", help="Use the abstain-case fixture.")
    parser.add_argument("--query", type=str, default=None, help="Override the fixture's query text.")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Model string for the real API call.")
    args = parser.parse_args(argv)

    retrieval_result = load_retrieval_result_from_fixture(abstain=args.abstain)
    if args.query:
        retrieval_result.query = args.query

    answer = generate_answer(retrieval_result, model=args.model, mock=args.mock)
    print(json.dumps(answer.to_dict(), indent=2))


if __name__ == "__main__":
    main()
