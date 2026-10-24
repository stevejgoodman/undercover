"""The harness: it builds the claim agent's graph and works a claim with it."""

import contextvars
import json
import logging
import os
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from typing import Any, NamedTuple, cast

from langchain.tools import ToolException
from langchain_core.exceptions import ModelRateLimitError, ModelTimeoutError
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import Runnable, RunnableConfig
from langfuse.langchain import CallbackHandler
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from psycopg import Connection, sql
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from agent import api
from agent.client import Refused
from agent.console import describe
from agent.models import DEFAULT_EFFORT, model
from agent.tools import CLAIM_TOOLS, ClaimContext, ClaimState

log = logging.getLogger(__name__)

ClaimGraph = CompiledStateGraph[ClaimState, ClaimContext, Any, Any]
NewGraph = Callable[[], ClaimGraph]
Pool = ConnectionPool[Connection[DictRow]]
Messages = dict[str, list[BaseMessage]]
Start = Messages | Command | None
# Langfuse tags beyond a claim's run, such as the round its evaluation is in.
Tags = tuple[str, ...]


class Trace(NamedTuple):
    """How a claim's work is traced: the run it's in, if any, and other tags."""

    run_id: str | None
    tags: Tags


# The model's errors that pass with time: a claim that hits one is left in progress,
# with its progress saved, to carry on later.
TRANSIENT = (ModelRateLimitError, ModelTimeoutError)

SCHEMA = "undercover"
CONNECTIONS = 4
CONNECTION_WAIT = 120
CLAIM_MODEL_CALLS = 30
NO_DECISION = "The agent finished without recording a decision"
WORK_CLAIM = "Work claim"
CARRY_ON = "Carry on"
AGENT = "agent"
TOOLS = "tools"
PAUSE = "wait_for_sign_off"
PAY = "pay"


class TooManyModelCalls(Exception):
    """The claim agent made as many model calls as it may without finishing."""


@contextmanager
def checkpoint_pool() -> Iterator[Pool]:
    """Open the process's pool of at most CONNECTIONS connections to DATABASE_URL,
    where claim graphs save their progress in our own schema, set up once. A claim
    agent waits up to CONNECTION_WAIT seconds for a connection."""
    settings = {
        "autocommit": True,
        "prepare_threshold": 0,
        "row_factory": dict_row,
        "options": f"-c search_path={SCHEMA}",
    }
    with ConnectionPool[Connection[DictRow]](
        os.environ["DATABASE_URL"],
        min_size=1,
        max_size=CONNECTIONS,
        timeout=CONNECTION_WAIT,
        kwargs=settings,
    ) as pool:
        with pool.connection() as connection:
            create = sql.SQL("CREATE SCHEMA IF NOT EXISTS {}")
            connection.execute(create.format(sql.Identifier(SCHEMA)))
        PostgresSaver(pool).setup()
        yield pool


def refusal(error: Exception) -> str:
    """Show the model why a tool was refused, and let any other error stop the agent."""
    if isinstance(error, Refused):
        return f"Refused with status {error}"
    if isinstance(error, ToolException):
        return f"Refused: {error}"
    raise error


def record_reply(claim_id: str, reply: BaseMessage) -> None:
    """Record the model's reply on the claim: its text, then each tool it calls."""
    if reply.text:
        api.record_step(claim_id, "message", reply.text)
    if isinstance(reply, AIMessage):
        for call in reply.tool_calls:
            args = ", ".join(f"{k}={json.dumps(v)}" for k, v in call["args"].items())
            api.record_step(claim_id, "tool_call", f"{call['name']}({args})")


def record_result(
    request: ToolCallRequest,
    execute: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    """Run a tool and record its result on the claim, then any step it gives as its
    artifact, such as a section it read."""
    result = execute(request)
    if isinstance(result, ToolMessage):
        message = result
    else:
        message = cast(dict[str, Any], result.update)["messages"][0]
    claim_id = cast(ClaimContext, request.runtime.context).claim_id
    api.record_step(claim_id, "tool_result", f"{message.name}: {message.text}")
    if message.artifact:
        api.record_step(claim_id, *message.artifact)
    return result


def record_call(context: ClaimContext, reply: BaseMessage) -> None:
    """Record the tokens and the cost of one model call, as OpenRouter reports them."""
    usage = reply.response_metadata["token_usage"]
    api.record_model_call(
        context.claim_id,
        context.run_id,
        usage["prompt_tokens"],
        usage["completion_tokens"],
        usage["cost"],
    )


def call_model(
    state: ClaimState,
    runtime: Runtime[ClaimContext],
    llm: Runnable[LanguageModelInput, BaseMessage],
    instructions: SystemMessage,
) -> dict[str, Any]:
    """Ask the model for its next step, up to CLAIM_MODEL_CALLS times in all, and
    record its cost and its reply on the claim."""
    calls = state["model_calls"]
    if calls >= CLAIM_MODEL_CALLS:
        message = f"The claim agent made {calls} model calls without finishing"
        raise TooManyModelCalls(message)
    reply = llm.invoke([instructions, *state["messages"]])
    record_call(runtime.context, reply)
    record_reply(runtime.context.claim_id, reply)
    return {"messages": [reply], "model_calls": 1}


def wait_for_sign_off(state: ClaimState, runtime: Runtime[ClaimContext]) -> None:
    """Pause until a handler signs off the payout, which the backend records. On
    resume this runs again from the top, so nothing comes before the interrupt."""
    interrupt({"claim_id": runtime.context.claim_id})


def pay(state: ClaimState, runtime: Runtime[ClaimContext]) -> dict[str, Any]:
    """Pay the approved payout, which the backend refuses unless it may be paid."""
    claim = api.pay_claim(runtime.context.claim_id, state["decision"]["payout"])
    return {"status": claim["status"]}


def after_agent(state: ClaimState) -> str:
    """Run the tools the model asked for, or stop: it finished without a decision."""
    reply = state["messages"][-1]
    return TOOLS if isinstance(reply, AIMessage) and reply.tool_calls else END


def after_tools(state: ClaimState) -> str:
    """Go back to the model until a decision is recorded, then pay an approval, after
    a sign-off if the backend holds it, or stop."""
    decision, status = state["decision"], state["status"]
    if not decision:
        return AGENT
    if status == api.Status.WAITING_FOR_SIGN_OFF:
        return PAUSE
    if decision["decision"] == api.APPROVE and status == api.Status.IN_PROGRESS:
        return PAY
    return END


def claim_graph(
    llm: BaseChatModel, instructions: str, saver: BaseCheckpointSaver[Any]
) -> ClaimGraph:
    """Build the claim agent's graph, which saves its progress after every step."""
    builder = StateGraph(ClaimState, context_schema=ClaimContext)
    builder.add_node(
        AGENT,
        partial(
            call_model,
            llm=llm.bind_tools(CLAIM_TOOLS),
            instructions=SystemMessage(instructions),
        ),
    )
    builder.add_node(
        TOOLS,
        ToolNode(CLAIM_TOOLS, handle_tool_errors=refusal, wrap_tool_call=record_result),
    )
    builder.add_node(PAUSE, wait_for_sign_off)
    builder.add_node(PAY, pay)
    builder.add_edge(START, AGENT)
    builder.add_conditional_edges(AGENT, after_agent, [TOOLS, END])
    builder.add_conditional_edges(TOOLS, after_tools, [AGENT, PAUSE, PAY, END])
    builder.add_edge(PAUSE, PAY)
    builder.add_edge(PAY, END)
    return builder.compile(checkpointer=saver)


def claim_graphs(llm: BaseChatModel, instructions: str, pool: Pool) -> NewGraph:
    """Return how to build a claim graph with a saver of its own on the pool, since
    a saver lets one claim at a time read or write."""

    def new_graph() -> ClaimGraph:
        return claim_graph(llm, instructions, PostgresSaver(pool))

    return new_graph


@dataclass
class ClaimAgents:
    """The claim agents of one version: its number, the model and reasoning effort
    a run records, and how to build a claim graph with a saver of its own."""

    version: int
    model: str
    reasoning_effort: str
    new_graph: NewGraph

    def setup(self, agents: int) -> api.RunSetup:
        """How a run with N of these claim agents at once is recorded."""
        return api.RunSetup(
            agents=agents,
            version=self.version,
            model=self.model,
            reasoning_effort=self.reasoning_effort,
        )


def claim_agents_of(version: int, pool: Pool) -> ClaimAgents:
    """Build the claim agents of a version, from what the backend says it works
    from, on the process's pool."""
    configuration = api.get_agent_version(version)
    llm = model(configuration)
    return ClaimAgents(
        version,
        llm.model_name,
        llm.reasoning_effort or DEFAULT_EFFORT,
        claim_graphs(llm, configuration["instructions"], pool),
    )


def thread_of(claim: dict[str, Any]) -> RunnableConfig:
    """Address the claim's thread, where the claim graph saves its progress."""
    return {"configurable": {"thread_id": claim["thread_id"]}}


def claim_config(claim: dict[str, Any], name: str, trace: Trace) -> RunnableConfig:
    """Run on the claim's thread, traced in Langfuse in the session of that thread
    and tagged with the run, if any, and any other tags, such as a round."""
    session = f"{claim['claim_id']}:{claim['thread_id']}"
    metadata: dict[str, Any] = {
        "langfuse_session_id": session,
        "langfuse_trace_name": name,
    }
    if trace.run_id is not None:
        metadata["langfuse_tags"] = [trace.run_id, *trace.tags]
    return thread_of(claim) | {
        "callbacks": [CallbackHandler()],
        "metadata": metadata,
        # One tool call at a time, so two decisions in one reply can't race.
        "max_concurrency": 1,
    }


def begin(claim_id: str) -> Messages:
    """Give a claim agent its first message, naming the claim it works on."""
    return {"messages": [HumanMessage(f"Claim {claim_id}")]}


def report(claim: dict[str, Any], reason: str) -> str:
    """Say in one line how a claim ended: its decision and payout, or why it failed."""
    claim_id, status, decision = claim["claim_id"], claim["status"], claim["decision"]
    if status == api.Status.WAITING:
        return f"{claim_id}  failed: {reason}, back in the queue"
    if status == api.Status.LEFT_FOR_HANDLER:
        return f"{claim_id}  failed: {reason}, left for a handler"
    line = f"{claim_id}  {decision['decision']}  ${decision['payout']:,.2f}"
    if status == api.Status.WAITING_FOR_SIGN_OFF:
        return f"{line}, waiting for sign-off"
    if decision["decision"] == api.APPROVE and claim["payment"] is None:
        return f"{line}, not paid yet"
    return line


def run_claim_graph(
    graph: ClaimGraph,
    start: Start,
    claim: dict[str, Any],
    name: str,
    trace: Trace,
) -> str | None:
    """Run the claim graph on the claim's thread, saving each step, and say what went
    wrong, if anything. A rate limit or a timeout is raised again, leaving the claim
    in progress with its progress saved, to carry on later."""
    try:
        # A fresh context makes this a root run even inside the dispatcher, which
        # Langfuse needs to put it in the claim's session.
        contextvars.Context().run(
            graph.invoke,
            start,
            claim_config(claim, name, trace),
            context=ClaimContext(claim["claim_id"], trace.run_id),
            durability="sync",
        )
    except TRANSIENT:
        raise
    except Exception as error:  # a claim that fails must not stop the run
        return describe(error)
    return None


@contextmanager
def spell(claim_id: str, run_id: str | None) -> Iterator[None]:
    """Time one spell of work on a claim, and record it however it ends."""
    started = time.monotonic()
    try:
        yield
    finally:
        api.record_work_time(claim_id, run_id, time.monotonic() - started)


def settle(claim_id: str, error: str | None) -> str:
    """Fail a claim the agent left undecided, and report how the claim ended. An
    error after the decision is logged, and the claim keeps its decision."""
    claim = api.get_claim(claim_id)
    reason = error or NO_DECISION
    if claim["status"] == api.Status.IN_PROGRESS and claim["decision"] is None:
        claim = api.fail_claim(claim_id, reason)
    elif error:
        log.warning("%s  %s", claim_id, error)
    line = report(claim, reason)
    log.info(line)
    return line


def work_claim(
    claim_id: str, run_id: str | None, graph: ClaimGraph, tags: Tags = ()
) -> str:
    """Work one claim from a clean start, as a new attempt, in the run given if any,
    and report how it ended."""
    claim = api.start_claim(claim_id, str(uuid.uuid4()))
    with spell(claim_id, run_id):
        trace = Trace(run_id, tags)
        error = run_claim_graph(graph, begin(claim_id), claim, WORK_CLAIM, trace)
        return settle(claim_id, error)


def carry_on(
    claim_id: str, run_id: str | None, graph: ClaimGraph, tags: Tags = ()
) -> str:
    """Carry a claim in progress on from its saved progress, as the same attempt, and
    report how it ended. A claim at the pause has been signed off, so it resumes past
    it. One with nothing saved, stopped before its first step, starts on its own
    thread; any other carries on, finishing a step whose writes were saved."""
    claim = api.get_claim(claim_id)
    saved = graph.get_state(thread_of(claim))
    start: Start = None
    if saved.next == (PAUSE,):
        start = Command(resume=True)
    elif saved.created_at is None and claim["decision"] is None:
        start = begin(claim_id)
    with spell(claim_id, run_id):
        error = run_claim_graph(graph, start, claim, CARRY_ON, Trace(run_id, tags))
        return settle(claim_id, error)


def work_in_run(
    claim_id: str, run_id: str, new_graph: NewGraph, tags: Tags = ()
) -> str:
    """Work one claim in a run on a claim graph of its own, carrying it on if it is
    in progress or starting it if it is waiting, and report how it ended. A copy in
    an evaluation held for sign-off is finished. Its trace is tagged with the run
    and any other tags given, such as a round's."""
    graph = new_graph()
    if api.get_claim(claim_id)["status"] == api.Status.IN_PROGRESS:
        line = carry_on(claim_id, run_id, graph, tags)
    else:
        line = work_claim(claim_id, run_id, graph, tags)
    finish_held_copy(claim_id, graph)
    return line


def finish_held_copy(claim_id: str, graph: ClaimGraph) -> None:
    """Clear the saved progress of an evaluation's copy held for sign-off: nobody
    can sign a copy off, so its work is finished."""
    claim = api.get_claim(claim_id)
    held = claim["status"] == api.Status.WAITING_FOR_SIGN_OFF
    if claim["evaluation_id"] and held:
        # claim_graph always compiles the graph with a saver.
        saver = cast(BaseCheckpointSaver[Any], graph.checkpointer)
        saver.delete_thread(claim["thread_id"])


def current_claim_agents(pool: Pool) -> ClaimAgents:
    """Build the claim agents of the version every dispatch uses."""
    return claim_agents_of(api.get_current_version()["version"], pool)
