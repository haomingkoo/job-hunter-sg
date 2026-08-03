"""Evidence-bounded AI coaching for one negotiation rehearsal turn."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, ValidationError, field_validator

from ai_service import call_sealion_json
from config import SEALION_FAST_MODEL
from prompt_safety import UNTRUSTED_DATA_RULE, xml_data_block


NEGOTIATION_COACH_MAX_TOKENS = 1200
NEGOTIATION_COACH_VALIDATION_RETRIES = 1
NEGOTIATION_COACH_MAX_CONTEXT_CHARS = 12_000
NUMBER_WORDS = frozenset(
    {
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "first",
        "second",
        "third",
        "fourth",
        "fifth",
        "sixth",
        "seventh",
        "eighth",
        "ninth",
        "tenth",
    }
)


class NegotiationCoachUnavailable(RuntimeError):
    """The configured model did not return a safe, valid coaching turn."""


class NegotiationCoaching(BaseModel):
    opening: str = Field(..., min_length=1, max_length=1200)
    questions: list[str] = Field(..., min_length=1, max_length=5)
    priority_order: list[str] = Field(..., min_length=1, max_length=5)

    @field_validator("opening", mode="before")
    @classmethod
    def join_opening_lines(cls, value):
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return " ".join(item.strip() for item in value if item.strip())
        return value


def _number_tokens(value: object) -> set[str]:
    text = str(value or "")
    numeric = re.findall(r"(?<![A-Za-z])(?:S\$|\$)?\d[\d,.%]*", text)
    normalized = {token.removeprefix("S$").removeprefix("$").replace(",", "") for token in numeric}
    return normalized | (set(re.findall(r"[a-z]+", text.casefold())) & NUMBER_WORDS)


def coach_negotiation(context: dict) -> dict:
    """Return one scenario-responsive coaching turn or fail explicitly."""
    system = f"""You are a Singapore job-offer negotiation coach.
Respond to the candidate's actual scenario, using only the supplied role, priorities,
and cited compensation observations. Do not invent a salary, time period, package
component, walk-away point, employer policy, candidate preference, or candidate fact.
Keep incompatible compensation definitions separate. Return only one JSON object with
exactly these keys: opening, questions, priority_order. Opening must be one string.
Questions must contain 1 to 5 concise strings. Priority_order must contain 1 to 5 exact
strings copied from the supplied priorities, ordered by what the candidate should protect
first. Do not propose concessions, new terms, or a walk-away recommendation.

SECURITY: {UNTRUSTED_DATA_RULE}"""
    content = call_sealion_json(
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": xml_data_block(
                    "negotiation_context_data",
                    json.dumps(context, ensure_ascii=False),
                    NEGOTIATION_COACH_MAX_CONTEXT_CHARS,
                ),
            },
        ],
        max_tokens=NEGOTIATION_COACH_MAX_TOKENS,
        model=SEALION_FAST_MODEL,
        max_retries=NEGOTIATION_COACH_VALIDATION_RETRIES,
    )
    if not content:
        raise NegotiationCoachUnavailable("The negotiation coach is unavailable; no rehearsal was saved.")
    try:
        coaching = NegotiationCoaching.model_validate(json.loads(content))
    except (json.JSONDecodeError, ValidationError, TypeError) as error:
        raise NegotiationCoachUnavailable(
            "The negotiation coach returned an invalid response; no rehearsal was saved."
        ) from error
    unsupported_numbers = _number_tokens(coaching.model_dump_json()) - _number_tokens(context)
    if unsupported_numbers:
        raise NegotiationCoachUnavailable(
            "The negotiation coach introduced unsupported figures; no rehearsal was saved."
        )
    supplied_priorities = {
        str(priority).strip().casefold(): str(priority).strip()
        for priority in context.get("priorities", [])
        if str(priority).strip()
    }
    try:
        ordered_priorities = [supplied_priorities[item.strip().casefold()] for item in coaching.priority_order]
    except KeyError as error:
        raise NegotiationCoachUnavailable(
            "The negotiation coach introduced an unsupported priority; no rehearsal was saved."
        ) from error
    if len(set(item.casefold() for item in ordered_priorities)) != len(ordered_priorities):
        raise NegotiationCoachUnavailable("The negotiation coach repeated a priority; no rehearsal was saved.")
    return {
        "opening": coaching.opening,
        "questions": coaching.questions,
        "trade_offs": [f"Protect {priority} before trading another term." for priority in ordered_priorities],
        "concessions": [
            f"If you move on {priority}, ask the employer to confirm what it can move in return."
            for priority in reversed(ordered_priorities)
        ],
    }
