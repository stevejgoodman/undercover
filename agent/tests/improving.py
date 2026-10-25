"""Rounds of improvement the agent's tests work: an improver on a stub model with
the replies a test scripts, and claim agents that refer every claim."""

from typing import Any

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent import harness, improver, improver_api
from agent.tests.stubs import StubModel, call, graph_on, record

CHANGE = {
    "instructions": "# UnderCover Agent\n\nRefer a claim that is missing a document.",
    "model": "openai/gpt-6-luna",
    "reasoning_effort": "low",
    "reason": "Fewer wrongful approvals",
}
RECIPE = {
    "recipe": "1. Read the results.\n2. Add rules for kinds of mistakes.",
    "reason": "One rule per kind of mistake generalizes better",
}


class Referrer(StubModel):
    """A claim agent that reads its claim and refers it, whichever claim it is, so
    any number of copies can be worked at once."""

    def next_reply(self, messages):
        return call("get_claim") if len(messages) == 2 else record("refer", 0)


def improvement(saver=None) -> improver.Improvement:
    """A round's needs on stub models: claim agents that refer every claim, with
    their progress in memory, and the improver's own saver."""
    claim_saver = InMemorySaver()
    referrer = Referrer(messages=iter(()))

    def claim_agents(version: int) -> harness.ClaimAgents:
        return harness.ClaimAgents(
            version, "stub", "default", lambda: graph_on(referrer, claim_saver)
        )

    return improver.Improvement(saver or InMemorySaver(), claim_agents)


def script(monkeypatch, *replies: Any) -> StubModel:
    """Give the improver a stub model with these replies, across its stretches."""
    model = StubModel(messages=iter(replies))
    monkeypatch.setattr(improver, "improver_model", lambda: model)
    return model


def reads_and_proposes(**changes: Any) -> list[AIMessage]:
    return [call("read_results"), call("propose_change", **CHANGE | changes)]


def new_round() -> dict[str, Any]:
    return improver_api.get_round(
        improver_api.create_round("Dana Whitfield")["round_id"]
    )
