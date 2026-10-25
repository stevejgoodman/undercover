"""A stand-in for Jev on OpenRouter's Decisions endpoint, so no test calls the
judge: it answers each request the SDK sends with the answer it is given."""

import json
from dataclasses import dataclass, field
from typing import Any, cast

import httpx

COST = 0.00002


def answer(score=2.0, probabilities=None, same_grounds=0.9, same_section=0.7):
    """A Decisions response with the lab's three answers."""
    return {
        "answers": {
            "grade": {
                "type": "score",
                "score": score,
                "probabilities": {"0": 0.05, "1": 0.15, "2": 0.6, "3": 0.2}
                if probabilities is None
                else probabilities,
            },
            "same_grounds": {"type": "noul", "noul": same_grounds},
            "same_section": {"type": "noul", "noul": same_section},
        },
        "model": "typesafe/jev-1.13",
        "usage": {"input_tokens": 300, "output_tokens": 4, "cost": COST},
        "id": "decision-1",
        "provider": "typesafe",
    }


@dataclass
class StandInJudge:
    """Answers every request with `reply`, which a test may change to an answer, a
    status code, an exception to raise or a function of the request, and keeps
    each request it was sent."""

    reply: Any = field(default_factory=answer)
    requests: list[httpx.Request] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.reply, Exception):
            raise self.reply
        if callable(self.reply):
            return cast(httpx.Response, self.reply(request))
        if isinstance(self.reply, int):
            return httpx.Response(self.reply, json={"error": {"message": "No"}})
        return httpx.Response(200, json=self.reply)

    def states(self) -> list[dict[str, Any]]:
        """The state of each request, as the judge was asked to grade it."""
        return [json.loads(request.content)["state"] for request in self.requests]
