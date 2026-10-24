"""The shapes of the backend's requests and responses."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator


class Status(StrEnum):
    """Where a claim stands."""

    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_SIGN_OFF = "waiting_for_sign_off"
    DECIDED = "decided"
    LEFT_FOR_HANDLER = "left_for_handler"


class DecisionKind(StrEnum):
    APPROVE = "approve"
    DECLINE = "decline"
    REFER = "refer"


class RunKind(StrEnum):
    DISPATCH = "dispatch"
    EVALUATION = "evaluation"


class RunStatus(StrEnum):
    RUNNING = "running"
    FINISHED = "finished"
    STOPPED = "stopped"


class LineChange(StrEnum):
    """How a line of a text changed from one version to the next."""

    ADDED = "added"
    REMOVED = "removed"
    UNCHANGED = "unchanged"


class VersionVerdict(StrEnum):
    """Whether a round kept the version of the claim agent it tried."""

    KEPT = "kept"
    ROLLED_BACK = "rolled_back"


class EvaluationSet(StrEnum):
    """The labeled sets of claims an evaluation can work."""

    EVALUATION = "evaluation"
    HELD_OUT = "held_out"


StepKind = Literal["tool_call", "tool_result", "message", "reading", "error"]
MOST_AGENTS = 25
Agents = Annotated[
    int, Field(ge=1, le=MOST_AGENTS, description="How many claim agents work at once")
]
DocumentName = Literal["policy_wording", "claims_manual"]
Benefit = Literal[
    "trip_cancellation",
    "trip_interruption",
    "trip_delay",
    "baggage_delay",
    "baggage",
    "passport",
    "emergency_medical",
]
LineKind = Literal[
    "item", "electronics", "cash", "expense", "hotel", "meals_without_receipts"
]


class Item(BaseModel):
    description: str
    category: str
    amount: float


class Document(BaseModel):
    name: str
    type: str
    content: str


class Decision(BaseModel):
    decision: DecisionKind
    payout: float
    section: str
    reason: str
    decided_at: str
    signed_off_by: str | None
    signed_off_at: str | None


class Payment(BaseModel):
    amount: float
    paid_at: str
    signed_off_by: str | None
    signed_off_at: str | None


class ClaimSummary(BaseModel):
    claim_id: str
    customer_name: str
    claim_type: str
    summary: str
    amount_claimed: float
    submitted_on: str
    status: Status
    decision: DecisionKind | None
    payout: float | None


class Claim(BaseModel):
    claim_id: str
    policy_id: str
    customer_id: str
    customer_name: str
    claim_type: str
    submitted_on: str
    incident_date: str
    incident_location: str
    summary: str
    story: str
    items: list[Item]
    amount_claimed: float
    documents: list[Document]
    status: Status
    thread_id: str | None
    attempts: int
    evaluation_id: str | None
    copy_of: str | None
    decision: Decision | None
    payment: Payment | None


class Trip(BaseModel):
    destination: str
    departs_on: str
    returns_on: str
    trip_cost: float


class Policy(BaseModel):
    policy_id: str
    customer_id: str
    plan: str
    add_ons: list[str]
    purchased_on: str
    sold_through: str
    trip: Trip
    travelers: list[str]
    status: str


class PreviousClaim(BaseModel):
    claim_id: str
    filed_on: str
    incident_date: str
    claim_type: str
    summary: str
    outcome: str
    amount_paid: float


class Handler(BaseModel):
    handler_id: str
    name: str
    role: str
    email: str
    can_approve_over_limit: bool


class Step(BaseModel):
    step_id: int
    thread_id: str
    kind: StepKind
    content: str
    created_at: str


class Section(BaseModel):
    document: DocumentName
    document_title: str
    number: int
    title: str
    text: str


class SectionMatch(BaseModel):
    document: DocumentName
    number: int
    title: str
    excerpts: list[str]


class StartRequest(BaseModel):
    thread_id: str = Field(min_length=1)


class StepRequest(BaseModel):
    kind: StepKind
    content: str = Field(min_length=1)


class DecisionRequest(BaseModel):
    decision: DecisionKind
    payout: float = Field(
        ge=0, description="In US dollars, 0 for a decline or referral"
    )
    section: str = Field(
        min_length=1, description="The sections of the wording and the manual relied on"
    )
    reason: str = Field(
        min_length=1, description="Two or three sentences explaining the decision"
    )

    @model_validator(mode="after")
    def check_payout(self) -> Self:
        """An approval pays something, and a decline or referral pays nothing."""
        if self.decision == DecisionKind.APPROVE and self.payout == 0:
            raise ValueError("An approval needs a payout above zero")
        if self.decision != DecisionKind.APPROVE and self.payout != 0:
            raise ValueError("A decline or a referral has a payout of zero")
        return self


class PaymentRequest(BaseModel):
    amount: float = Field(gt=0, description="The approved payout in US dollars")


class Plan(BaseModel):
    plan: str
    name: str
    trip_cancellation_max: float
    trip_delay_waiting_hours: int
    trip_delay_max: float
    baggage_delay_waiting_hours: int
    baggage_delay_max: float
    baggage_max: float
    per_item_limit: float
    passport_max: float
    emergency_medical_max: float
    deductible: float


class AddOn(BaseModel):
    add_on: str
    name: str
    effect: str
    electronics_per_item_limit: float | None = None


class Plans(BaseModel):
    plans: list[Plan]
    deductible_applies_to: list[Benefit]
    add_ons: list[AddOn]


class Line(BaseModel):
    description: str = Field(min_length=1)
    amount: float = Field(ge=0, description="The total claimed, before limits")
    quantity: int = Field(ge=1, description="How many separate items")
    kind: LineKind
    nights: int = Field(ge=0, description="For a hotel, and 0 otherwise")
    hours: float = Field(
        ge=0, description="For meals without receipts, and 0 otherwise"
    )


class PayoutRequest(BaseModel):
    benefit: Benefit
    lines: list[Line] = Field(
        description="The covered lines, with any excluded left out"
    )
    paid_by_others: float = Field(ge=0, description="Paid or refunded by others")


class CalculationStep(BaseModel):
    step: str
    amount: float


class Payout(BaseModel):
    calculation: list[CalculationStep]
    payout: float
    needs_sign_off: bool


class FailureRequest(BaseModel):
    reason: str = Field(min_length=1, description="What went wrong")


class ModelCallRequest(BaseModel):
    run_id: str | None = Field(description="The run the call was made in, or null")
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost: float = Field(ge=0, description="In US dollars, as OpenRouter reports it")


class ModelCall(BaseModel):
    claim_id: str
    thread_id: str
    run_id: str | None
    input_tokens: int
    output_tokens: int
    cost: float
    created_at: str


class WorkTimeRequest(BaseModel):
    run_id: str | None = Field(description="The run the work was done in, or null")
    seconds: float = Field(ge=0, description="How long the agent worked on the claim")


class WorkTime(BaseModel):
    claim_id: str
    thread_id: str
    run_id: str | None
    started_at: str
    seconds: float


class StartDispatchRequest(BaseModel):
    agents: Agents


class CreateDispatchRequest(StartDispatchRequest):
    version: int = Field(ge=1, description="The claim agent's version")
    model: str = Field(min_length=1)
    reasoning_effort: str = Field(min_length=1, description="Or default")


class RunClaimsRequest(BaseModel):
    claim_ids: list[str] = Field(description="The claims a dispatch works, in order")


class HeldPayout(BaseModel):
    claim_id: str
    payout: float


class DispatchSummary(BaseModel):
    approved: int
    declined: int
    referred: int
    waiting_for_sign_off: list[HeldPayout]
    left_for_handler: list[str]
    unfinished: list[str]


class RunClaim(ClaimSummary):
    started_at: str | None
    seconds: float
    model_cost: float


class RunDetails(BaseModel):
    run_id: str
    number: int
    kind: RunKind
    agents: int
    version: int
    round_id: str | None
    model: str
    reasoning_effort: str
    status: RunStatus
    started_at: str
    finished_at: str | None
    seconds: float | None
    model_cost: float


class Run(RunDetails):
    evaluation_set: EvaluationSet | None
    tiny: bool | None
    summary: DispatchSummary | None
    claims: list[RunClaim]


class StartEvaluationRequest(StartDispatchRequest):
    evaluation_set: EvaluationSet
    tiny: bool = Field(description="Only the set's five tiny claims")


class CreateEvaluationRequest(StartEvaluationRequest, CreateDispatchRequest):
    pass


class Measures(BaseModel):
    decision_accuracy: float
    accuracy: float
    cost_of_mistakes: float
    straight_through: float
    model_cost_per_claim: float
    seconds_per_claim: float
    run_seconds: float | None


class ScoredClaim(RunClaim):
    copy_of: str
    reason: str | None
    handler_decision: DecisionKind
    handler_payout: float
    right: bool
    mistake_cost: float


class Evaluation(RunDetails):
    evaluation_set: EvaluationSet
    tiny: bool
    size: int
    measures: Measures


class ScoredEvaluation(Evaluation):
    claims: list[ScoredClaim]


class Accepted(BaseModel):
    status: Literal["accepted"] = "accepted"


class DiffLine(BaseModel):
    change: LineChange
    text: str


class Objectives(BaseModel):
    """The floors a new version must reach on the held-out set."""

    accuracy: float = Field(ge=0, le=1)
    grade: float = Field(ge=0, le=3)


class Limits(BaseModel):
    """How far each measure must move to count: a difference for accuracy and the
    grade, and a fraction of the old value for cost and time."""

    accuracy: float = Field(ge=0, le=1)
    grade: float = Field(ge=0, le=3)
    model_cost_per_claim: float = Field(ge=0)
    seconds_per_claim: float = Field(ge=0)


class SettingsRequest(BaseModel):
    payout_approval_limit: float = Field(gt=0, description="In US dollars")
    objectives: Objectives
    noise: Limits
    tolerance: Limits
    spending_limit: float = Field(gt=0, description="For each round, in US dollars")
    agents: Agents


class Settings(SettingsRequest):
    changed_by: str
    changed_at: str


class SettingsHistory(BaseModel):
    current: Settings
    changes: list[Settings] = Field(description="Every version, newest first")


class AllowedModel(BaseModel):
    model: str
    reasoning_efforts: list[str]
    input_price: float = Field(description="US dollars per million input tokens")
    output_price: float = Field(description="US dollars per million output tokens")


class Scores(BaseModel):
    """A version's measures, averaged over the whole-set evaluations rounds ran on
    it on one set."""

    runs: int
    decision_accuracy: float
    accuracy: float
    cost_of_mistakes: float
    straight_through: float
    model_cost_per_claim: float
    seconds_per_claim: float
    grade: float | None


class VersionScores(BaseModel):
    evaluation: Scores | None
    held_out: Scores | None


class AgentConfiguration(BaseModel):
    """What the claim agent works from: its instructions, ending with the
    documents' contents, its model and its reasoning effort. No scores."""

    version: int
    instructions: str
    model: str
    reasoning_effort: str


class AgentVersion(BaseModel):
    version: int
    instructions: str
    model: str
    reasoning_effort: str
    based_on: int | None = Field(description="The version it was proposed against")
    change: str
    reason: str
    proposed_by: str
    approved_by: str
    approved_at: str
    round_id: str | None
    verdict: VersionVerdict | None
    created_at: str


class VersionSummary(AgentVersion):
    current: bool
    scores: VersionScores


class VersionDetails(VersionSummary):
    diff: list[DiffLine] = Field(description="From the version before, if any")
