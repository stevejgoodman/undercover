"""A stub model, so that tests never call a real model, replies to script it, and
the claim graph on it."""

import itertools
import threading
import time
from collections.abc import Iterator
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import PrivateAttr

from agent import api, harness


def setup(agents=3):
    """How the tests' runs are recorded: N claim agents of the first version, on
    the stub model."""
    return api.RunSetup(
        agents=agents, version=1, model="stub", reasoning_effort="default"
    )


# What OpenRouter reports for each reply.
USAGE = {"prompt_tokens": 1200, "completion_tokens": 300, "cost": 0.0042}


class StubModel(GenericFakeChatModel):
    """A chat model that gives scripted replies, with OpenRouter's token usage, or
    raises a scripted error, and keeps the prompts it was sent."""

    prompts: list[list[BaseMessage]] = []
    # What a run records of the model, as ChatOpenAI has them.
    model_name: str = "stub"
    reasoning_effort: str | None = None

    def bind_tools(self, tools, **kwargs):
        return self

    def next_reply(self, messages):
        return next(self.messages)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.prompts.append(messages)
        reply = self.next_reply(messages)
        if isinstance(reply, BaseException):
            raise reply
        message = AIMessage(content=reply) if isinstance(reply, str) else reply
        return ChatResult(
            generations=[ChatGeneration(message=message)],
            llm_output={"token_usage": USAGE},
        )


class SwarmModel(StubModel):
    """A stub model for claim agents working at once: each claim follows its own
    script, chosen by the claim named in its first message. It pauses a little in
    each reply, and counts the claims it is working on at once. With a fill, each
    reply first waits, for up to five seconds, until that many claims have been in
    at once, so the count doesn't depend on how quickly the threads start."""

    scripts: dict[str, Iterator[Any]]
    pause: float = 0.0
    fill: int = 0
    at_once: int = 0
    most_at_once: int = 0
    _lock: threading.Condition = PrivateAttr(default_factory=threading.Condition)

    def next_reply(self, messages):
        claim_id = messages[1].content.removeprefix("Claim ")
        with self._lock:
            self.at_once += 1
            self.most_at_once = max(self.most_at_once, self.at_once)
            self._lock.notify_all()
            self._lock.wait_for(lambda: self.most_at_once >= self.fill, timeout=5)
        time.sleep(self.pause)
        with self._lock:
            self.at_once -= 1
        return next(self.scripts[claim_id])


CALL_IDS = itertools.count()


def stub(*replies):
    return StubModel(messages=iter(replies))


def swarm(scripts, pause=0.0, fill=0):
    """A stub model with a script of replies for each claim."""
    each = {claim_id: iter(replies) for claim_id, replies in scripts.items()}
    return SwarmModel(messages=iter(()), scripts=each, pause=pause, fill=fill)


def call(name, text="", **args):
    """A reply that calls one tool, with an id of its own as a real model gives."""
    tool_call = {"name": name, "args": args, "id": f"call-{next(CALL_IDS)}"}
    return AIMessage(content=text, tool_calls=[tool_call])


def record(decision, payout):
    return call(
        "record_decision",
        decision=decision,
        payout=payout,
        section="Section 3, Trip Delay",
        reason="The delay was covered.",
    )


def decide(decision, payout):
    """The replies of a claim agent that reads its claim and decides it, which ends
    its work on the claim."""
    return [call("get_claim"), record(decision, payout)]


def graph_on(model, saver=None):
    """The claim graph of the first version on a stub model, saving its progress in
    memory."""
    instructions = api.get_agent_version(1)["instructions"]
    return harness.claim_graph(model, instructions, saver or InMemorySaver())
