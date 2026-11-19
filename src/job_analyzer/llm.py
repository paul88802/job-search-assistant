"""One shared helper for every structured Claude call in the app.

Keeping the API call in one place means the reliability rules (stop_reason
checks, refusal fallback) are written once and apply everywhere.
"""

from typing import TypeVar

import anthropic
from pydantic import BaseModel

MODEL = "claude-opus-5-5"

T = TypeVar("T", bound=BaseModel)


class ExtractionError(Exception):
    """Raised when Claude did not return a usable result."""


def parse_structured(
    *,
    system: str,
    content: str | list,
    output_format: type[T],
    client: anthropic.Anthropic | None = None,
    max_tokens: int = 16000,
) -> T:
    """Send one user message and return Claude's answer as an `output_format` object."""
    client = client or anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
        # Structured outputs: the API guarantees the reply matches this schema.
        output_format=output_format,
        # If the model declines (stop_reason "refusal"), the API re-runs the
        # request on a suitable fallback model inside the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )

    # Always check WHY the model stopped before using the answer.
    if response.stop_reason == "refusal":
        raise ExtractionError("Claude declined to process this input.")
    if response.stop_reason == "max_tokens":
        raise ExtractionError("The answer was cut off (max_tokens reached).")
    if response.parsed_output is None:
        raise ExtractionError(f"No structured output (stop_reason={response.stop_reason}).")

    return response.parsed_output
