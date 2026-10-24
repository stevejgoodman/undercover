"""The improver, the agent's sixth part: a LangChain agent, as in the lab, that
follows a recipe to improve the claim agent. It reads the results, proposes a new
version, waits for a handler's approval, asks for the new version's evaluations
and proposes a better recipe. The backend keeps or rolls back each version by
UnderCover's rule, and the improver changes nothing a handler hasn't approved."""

import contextvars
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Annotated, Any, cast

from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    HumanInTheLoopMiddleware,
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelResponse,
    before_model,
    wrap_model_call,
    wrap_tool_call,
)
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langfuse.langchain import CallbackHandler
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from agent import harness, improver_api
from agent.client import Refused
from agent.dispatcher import work_run
from agent.models import model

log = logging.getLogger(__name__)

IMPROVER = {"model": "openai/gpt-6-luna", "reasoning_effort": "medium"}
# Writing a good change takes longer than deciding a claim, as in the lab.
IMPROVER_TIMEOUT = 300
# The improver's model calls in a round, across its stretches of work.
IMPROVER_MODEL_CALLS = 40
BEGIN = "Please carry out one round of your recipe."
PROPOSE_CHANGE = "propose_change"
PROPOSE_RECIPE = "propose_recipe"
# A new version's evaluations: once on the evaluation set, twice held out.
NEW_VERSION_EVALUATIONS: tuple[improver_api.EvaluationSet, ...] = (
    "evaluation",
    "held_out",
    "held_out",
)
CLOSED = ("finished", "stopped")
VERDICTS = {"kept": "Kept", "rolled_back": "Rolled back"}

Improver = CompiledStateGraph[Any, "ImproverContext", Any, Any]
# A handler's approval or rejection of a proposal, as the service passes it on.
Review = improver_api.Review
# Works one of a round's evaluations of a set on a version, and returns the run.
Evaluate = Callable[[improver_api.EvaluationSet, int], dict[str, Any]]


class RoundStopped(Exception):
    """The improver's round was stopped, so it makes no more model calls."""


@dataclass
class ImproverContext:
    """The round the improver works on, how to work one of its evaluations, and
    the proposal a handler approved, when it resumes after one."""

    round: dict[str, Any]
    evaluate: Evaluate
    proposal_id: int | None


@dataclass
class Improvement:
    """What a round needs from the agent's service: the improver's saver, and how
    to build a version's claim agents for its evaluations."""

    saver: BaseCheckpointSaver[Any]
    claim_agents: Callable[[int], harness.ClaimAgents]


def round_of(runtime: Runtime[ImproverContext] | ToolRuntime[ImproverContext]) -> str:
    return runtime.context.round["round_id"]


def allowed(context: ImproverContext, model: str, reasoning_effort: str) -> bool:
    """Say whether a model and a reasoning effort are among the models allowed."""
    return any(
        choice["model"] == model and reasoning_effort in choice["reasoning_efforts"]
        for choice in context.round["models_allowed"]
    )


# The tools, with the lab's names, since the recipe names them.


@tool
def read_results(runtime: ToolRuntime[ImproverContext]) -> str:
    """Read the current version of the claim agent's configuration, its scores, its
    mistakes and weakest explanations on the evaluation set, the earlier rounds,
    the objectives, what's left of the spending limit and the models allowed."""
    return json.dumps(improver_api.read_results(round_of(runtime)), indent=2)


@tool
def propose_change(
    instructions: Annotated[str, "The claim agent's complete instructions"],
    model: Annotated[str, "One of the models allowed"],
    reasoning_effort: Annotated[str, "A reasoning effort allowed for that model"],
    reason: Annotated[str, "Why this change should improve the scores"],
    runtime: ToolRuntime[ImproverContext],
) -> str:
    """Propose a new version of the claim agent's configuration. A handler reviews
    it before it's saved."""
    if not allowed(runtime.context, model, reasoning_effort):
        return (
            f"{model} at {reasoning_effort} isn't one of the models allowed. "
            "Choose from the models allowed."
        )
    tried = improver_api.get_round(round_of(runtime))["version_tried"]
    if tried is not None:
        return f"This round has already tried version {tried}, its one change."
    # It runs only once a handler has approved it, which the service passes on.
    proposal_id = cast(int, runtime.context.proposal_id)
    version = improver_api.create_version(round_of(runtime), proposal_id)
    return f"Saved as version {version['version']}. Run the evaluation next."


@tool
def run_evaluation(runtime: ToolRuntime[ImproverContext]) -> str:
    """Run the newest version once on the evaluation set and twice on the held-out
    set, then keep it or roll it back."""
    round_id = round_of(runtime)
    current = improver_api.get_round(round_id)
    version = current["version_tried"]
    if version is None:
        return "There's no new version to evaluate. Propose a change first."
    if current["verdict"] is not None:
        return (
            f"Version {version} already has its verdict: "
            f"{VERDICTS[current['verdict']]}, {current['why']}."
        )
    refused = ""
    for evaluation_set in NEW_VERSION_EVALUATIONS:
        try:
            runtime.context.evaluate(evaluation_set, version)
        except Refused as refusal:
            refused = f"Refused: {refusal.detail}. "
            break
    decided = improver_api.record_verdict(round_id)
    verdict = VERDICTS[decided["verdict"]]
    scores = {
        "held_out_before": decided["scores_before"],
        "held_out_after": decided["scores_after"],
    }
    return (
        f"{refused}{verdict} version {version}: {decided['why']}.\n"
        f"{json.dumps(scores, indent=2)}"
    )


@tool
def propose_recipe(
    recipe: Annotated[str, "The complete new recipe"],
    reason: Annotated[
        str, "What this round showed, and why the new recipe should do better"
    ],
    runtime: ToolRuntime[ImproverContext],
) -> str:
    """Propose a new version of your recipe for improving the claim agent. A
    handler reviews it before it's saved."""
    # It runs only once a handler has approved it, which the service passes on.
    proposal_id = cast(int, runtime.context.proposal_id)
    made = improver_api.create_recipe(round_of(runtime), proposal_id)
    return f"Saved as recipe version {made['version']}."


TOOLS = [read_results, propose_change, run_evaluation, propose_recipe]


# The middleware


def worth_a_handler(request: ToolCallRequest) -> bool:
    """Pause for a handler only on a change within the models allowed, in a round
    that hasn't tried a version yet; any other goes straight back to the improver,
    refused by the tool."""
    args = request.tool_call["args"]
    # The middleware runs with the improver's context.
    context = cast(ImproverContext, request.runtime.context)
    if not allowed(context, args["model"], args["reasoning_effort"]):
        return False
    round_id = context.round["round_id"]
    return improver_api.get_round(round_id)["version_tried"] is None


@before_model
def stop_with_the_round(
    state: AgentState[Any], runtime: Runtime[ImproverContext]
) -> None:
    """Make no more model calls once the round is stopped."""
    stage = improver_api.get_round(round_of(runtime))["stage"]
    if stage in CLOSED:
        raise RoundStopped(f"Round {runtime.context.round['number']} is {stage}")


@wrap_model_call
def record_cost(
    request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
) -> ModelResponse:
    """Record each model call's tokens and cost with the round, as OpenRouter
    reports them. The backend refuses it for a stopped round, which ends the
    improver."""
    response = handler(request)
    usage = response.result[-1].response_metadata["token_usage"]
    round_id = cast(ImproverContext, request.runtime.context).round["round_id"]
    improver_api.record_round_model_call(
        round_id,
        usage["prompt_tokens"],
        usage["completion_tokens"],
        usage["cost"],
    )
    return response


@wrap_tool_call
def refusals_as_answers(
    request: ToolCallRequest, handler: Callable[[ToolCallRequest], Any]
) -> Any:
    """Answer the improver with the backend's refusal of a tool, such as an
    evaluation the round can't afford, rather than ending its round. A stopped
    round ends before the improver's next model call."""
    try:
        return handler(request)
    except Refused as refusal:
        return ToolMessage(
            f"Refused: {refusal.detail}",
            tool_call_id=request.tool_call["id"],
            name=request.tool_call["name"],
            status="error",
        )


@wrap_model_call
def one_tool_call_at_a_time(
    request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
) -> ModelResponse:
    """Turn off parallel tool calls, so a reply never holds two proposals."""
    settings = {**request.model_settings, "parallel_tool_calls": False}
    return handler(request.override(model_settings=settings))


APPROVAL = HumanInTheLoopMiddleware(
    interrupt_on={
        PROPOSE_CHANGE: {
            "allowed_decisions": ["approve", "reject"],
            "when": worth_a_handler,
        },
        PROPOSE_RECIPE: {"allowed_decisions": ["approve", "reject"]},
    }
)


def middleware() -> list[AgentMiddleware[Any, Any, Any]]:
    """The improver's middleware: its cap on model calls in a round, a stop when
    the round stops, one tool call at a time, each call's cost, the backend's
    refusals sent back as answers, and the handler's approval of each
    proposal."""
    return [
        ModelCallLimitMiddleware(
            thread_limit=IMPROVER_MODEL_CALLS, exit_behavior="error"
        ),
        stop_with_the_round,
        one_tool_call_at_a_time,
        record_cost,
        refusals_as_answers,
        APPROVAL,
    ]


def improver_model() -> ChatOpenAI:
    """GPT-6 Luna at medium reasoning effort, or the model in MODEL_NAME."""
    return model(IMPROVER, timeout=IMPROVER_TIMEOUT)


def improver(saver: BaseCheckpointSaver[Any], instructions: str) -> Improver:
    """Build the improver with its recipe in its instructions, saving its progress
    after each step so a round waiting for a handler survives a restart."""
    return create_agent(
        model=improver_model(),
        tools=TOOLS,
        system_prompt=instructions,
        middleware=middleware(),
        context_schema=ImproverContext,
        checkpointer=saver,
    )


# A round's work


def evaluate(
    round_id: str,
    claim_agents: Callable[[int], harness.ClaimAgents],
    evaluation_set: improver_api.EvaluationSet,
    version: int,
) -> dict[str, Any]:
    """Work one of a round's evaluations of a version through the dispatcher, with
    its claims tagged with the round in Langfuse. A fresh context keeps the
    dispatcher's graph from saving into the improver's thread."""
    agents = claim_agents(version)
    run = improver_api.create_round_evaluation(
        round_id, evaluation_set, version, agents.model, agents.reasoning_effort
    )
    work = partial(harness.work_in_run, new_graph=agents.new_graph, tags=(round_id,))
    contextvars.Context().run(work_run, run, work, set())
    return run


def round_config(round: dict[str, Any]) -> RunnableConfig:
    """Run on the round's thread, with all of its work in one Langfuse session."""
    return {
        "configurable": {"thread_id": round["thread_id"]},
        "callbacks": [CallbackHandler()],
        "run_name": f"Improver round {round['number']}",
        "metadata": {
            "langfuse_session_id": f"Round {round['number']}:{round['round_id']}"
        },
    }


def stretch(
    round: dict[str, Any],
    start: dict[str, Any] | Command,
    improvement: Improvement,
    proposal_id: int | None = None,
) -> dict[str, Any]:
    """Run the improver on its round until it pauses for a handler or ends."""
    instructions = improver_api.get_improver_instructions(round["round_id"])
    graph = improver(improvement.saver, instructions["instructions"])
    context = ImproverContext(
        round,
        partial(evaluate, round["round_id"], improvement.claim_agents),
        proposal_id,
    )
    return contextvars.Context().run(
        graph.invoke, start, round_config(round), context=context, durability="sync"
    )


def pause_or_finish(round_id: str, result: dict[str, Any]) -> None:
    """Record the proposal the improver is waiting on, or finish the round."""
    if "__interrupt__" not in result:
        log.info("Round %s ended: %s", round_id, result["messages"][-1].text)
        improver_api.finish_round(round_id)
        return
    request = result["__interrupt__"][0].value["action_requests"][0]
    args = request["args"]
    if request["name"] == PROPOSE_CHANGE:
        improver_api.record_change_proposal(
            round_id,
            args["instructions"],
            args["model"],
            args["reasoning_effort"],
            args["reason"],
        )
    else:
        improver_api.record_recipe_proposal(round_id, args["recipe"], args["reason"])


def first_evaluations(round: dict[str, Any], improvement: Improvement) -> bool:
    """Run the current version's evaluations it still needs, and hand the round to
    the improver, or say the round can't go on: it couldn't afford them, or was
    stopped."""
    for evaluation_set in round["first_evaluations_missing"]:
        try:
            evaluate(
                round["round_id"],
                improvement.claim_agents,
                evaluation_set,
                round["version_before"],
            )
        except Refused as refusal:
            log.warning("Round %s: %s", round["number"], refusal.detail)
            return False
    try:
        improver_api.start_improving(round["round_id"])
    except Refused as refusal:
        log.warning("Round %s: %s", round["number"], refusal.detail)
        return False
    return True


def work_round(round: dict[str, Any], improvement: Improvement) -> None:
    """Work a new round up to its first pause for a handler, or its end."""
    if not first_evaluations(round, improvement):
        if improver_api.get_round(round["round_id"])["stage"] not in CLOSED:
            improver_api.finish_round(round["round_id"])
        return
    result = stretch(round, {"messages": [HumanMessage(BEGIN)]}, improvement)
    pause_or_finish(round["round_id"], result)


def carry_on_round(
    round_id: str,
    proposal: dict[str, Any],
    decision: dict[str, Any],
    improvement: Improvement,
) -> None:
    """Resume a round's improver after a handler's decision, which the service has
    recorded, up to its next pause or its end. A rejection's reason goes back to
    the improver."""
    if decision["decision"] == "reject":
        resume = {"type": "reject", "message": decision["reason"]}
    else:
        resume = {"type": "approve"}
    round = improver_api.get_round(round_id)
    start = Command(resume={"decisions": [resume]})
    result = stretch(round, start, improvement, proposal["proposal_id"])
    pause_or_finish(round_id, result)


# What the agent's service asks of a round, through the improver


def new_round(handler: str) -> dict[str, Any]:
    """Record a new round for a handler, on the current version and recipe."""
    return improver_api.create_round(handler)


def round_number(round_id: str) -> int:
    return improver_api.get_round(round_id)["number"]


def record_decision(
    round_id: str, proposal_id: int, decision: dict[str, Any]
) -> dict[str, Any]:
    """Record a handler's decision on a proposal, before the improver resumes."""
    return improver_api.record_proposal_decision(
        round_id,
        proposal_id,
        decision["decision"],
        decision["reason"],
        decision["handler"],
    )


def stop_working_rounds(stopped_by: str) -> list[str]:
    """Stop the rounds that were working, keeping any waiting for a handler."""
    return improver_api.stop_working_rounds(stopped_by)
