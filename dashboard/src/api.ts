import { accessToken, signOut } from "./supabase";

export const statuses = [
  "waiting",
  "in_progress",
  "waiting_for_sign_off",
  "decided",
  "left_for_handler",
] as const;
export type Status = (typeof statuses)[number];
export type DecisionKind = "approve" | "decline" | "refer";
export type StepKind =
  "tool_call" | "tool_result" | "message" | "reading" | "error";

export interface ClaimSummary {
  claim_id: string;
  customer_name: string;
  claim_type: string;
  summary: string;
  amount_claimed: number;
  submitted_on: string;
  status: Status;
  decision: DecisionKind | null;
  payout: number | null;
}

export interface Item {
  description: string;
  category: string;
  amount: number;
}

export interface ClaimDocument {
  name: string;
  type: string;
  content: string;
}

export interface Decision {
  decision: DecisionKind;
  payout: number;
  section: string;
  reason: string;
  decided_at: string;
  signed_off_by: string | null;
  signed_off_at: string | null;
}

export interface Payment {
  amount: number;
  paid_at: string;
  signed_off_by: string | null;
  signed_off_at: string | null;
}

export interface Claim {
  claim_id: string;
  policy_id: string;
  customer_id: string;
  customer_name: string;
  claim_type: string;
  submitted_on: string;
  incident_date: string;
  incident_location: string;
  summary: string;
  story: string;
  items: Item[];
  amount_claimed: number;
  documents: ClaimDocument[];
  status: Status;
  thread_id: string | null;
  attempts: number;
  // Set on an evaluation's copy of a claim.
  evaluation_id: string | null;
  copy_of: string | null;
  decision: Decision | null;
  payment: Payment | null;
}

export interface Policy {
  policy_id: string;
  customer_id: string;
  plan: string;
  add_ons: string[];
  purchased_on: string;
  sold_through: string;
  trip: {
    destination: string;
    departs_on: string;
    returns_on: string;
    trip_cost: number;
  };
  travelers: string[];
  status: string;
}

export interface PreviousClaim {
  claim_id: string;
  filed_on: string;
  incident_date: string;
  claim_type: string;
  summary: string;
  outcome: string;
  amount_paid: number;
}

export interface Handler {
  handler_id: string;
  name: string;
  role: string;
  email: string;
  can_approve_over_limit: boolean;
}

export interface Step {
  step_id: number;
  thread_id: string;
  kind: StepKind;
  content: string;
  created_at: string;
}

export type RunStatus = "running" | "finished" | "stopped";
export type RunKind = "dispatch" | "evaluation";
export const evaluationSets = ["evaluation", "held_out"] as const;
export type EvaluationSet = (typeof evaluationSets)[number];

export interface HeldPayout {
  claim_id: string;
  payout: number;
}

export interface DispatchSummary {
  approved: number;
  declined: number;
  referred: number;
  waiting_for_sign_off: HeldPayout[];
  left_for_handler: string[];
  // In progress or back in the queue, for the next dispatch.
  unfinished: string[];
}

// A claim's line in the queue, with its cost and time in a run.
export interface RunClaim extends ClaimSummary {
  started_at: string | null;
  seconds: number;
  model_cost: number;
}

export interface RunDetails {
  run_id: string;
  number: number;
  kind: RunKind;
  agents: number;
  version: number;
  round_id: string | null;
  model: string;
  reasoning_effort: string;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
  seconds: number | null;
  model_cost: number;
}

export interface Run extends RunDetails {
  evaluation_set: EvaluationSet | null;
  tiny: boolean | null;
  summary: DispatchSummary | null;
  claims: RunClaim[];
}

export interface Measures {
  decision_accuracy: number;
  accuracy: number;
  cost_of_mistakes: number;
  straight_through: number;
  model_cost_per_claim: number;
  seconds_per_claim: number;
  run_seconds: number | null;
}

// An evaluation's copy of a claim beside the handler's decision on it.
export interface ScoredClaim extends RunClaim {
  copy_of: string;
  reason: string | null;
  handler_decision: DecisionKind;
  handler_payout: number;
  right: boolean;
  mistake_cost: number;
}

export interface Evaluation extends RunDetails {
  evaluation_set: EvaluationSet;
  tiny: boolean;
  size: number;
  measures: Measures;
}

export interface ScoredEvaluation extends Evaluation {
  claims: ScoredClaim[];
}

export interface Accepted {
  status: "accepted";
}

export type LineChange = "added" | "removed" | "unchanged";

export interface DiffLine {
  change: LineChange;
  text: string;
}

// A version's measures, averaged over the whole-set evaluations rounds ran on it.
export interface Scores {
  runs: number;
  decision_accuracy: number;
  accuracy: number;
  cost_of_mistakes: number;
  straight_through: number;
  model_cost_per_claim: number;
  seconds_per_claim: number;
  grade: number | null;
}

export type VersionVerdict = "kept" | "rolled_back";

export interface AgentVersion {
  version: number;
  instructions: string;
  model: string;
  reasoning_effort: string;
  change: string;
  reason: string;
  proposed_by: string;
  approved_by: string;
  approved_at: string;
  round_id: string | null;
  verdict: VersionVerdict | null;
  created_at: string;
}

export interface VersionSummary extends AgentVersion {
  current: boolean;
  scores: { evaluation: Scores | null; held_out: Scores | null };
}

export interface VersionDetails extends VersionSummary {
  diff: DiffLine[];
}

export interface Objectives {
  accuracy: number;
  grade: number;
}

// How far each measure must move to count: a difference for accuracy and the
// grade, a fraction of the old value for cost and time.
export interface Limits {
  accuracy: number;
  grade: number;
  model_cost_per_claim: number;
  seconds_per_claim: number;
}

export interface SettingsRequest {
  payout_approval_limit: number;
  objectives: Objectives;
  noise: Limits;
  tolerance: Limits;
  spending_limit: number;
  agents: number;
}

export interface Settings extends SettingsRequest {
  changed_by: string;
  changed_at: string;
}

export interface SettingsHistory {
  current: Settings;
  changes: Settings[];
}

export interface AllowedModel {
  model: string;
  reasoning_efforts: string[];
  input_price: number;
  output_price: number;
}

export const REQUEST_FAILED = "The request failed";
const NOT_SIGNED_IN = 401;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

// Sends the signed-in handler's token with every request. A refusal for want of
// a sign-in signs the handler out, which takes them back to the sign-in page.
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await accessToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { ...init, headers });
  if (response.status === NOT_SIGNED_IN) await signOut();
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    const detail =
      typeof body.detail === "string" ? body.detail : REQUEST_FAILED;
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

function send<T>(method: "POST" | "PUT", path: string, body?: object) {
  return request<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body && JSON.stringify(body),
  });
}

const post = <T>(path: string, body?: object) => send<T>("POST", path, body);

const claimPath = (claimId: string) =>
  `/api/claims/${encodeURIComponent(claimId)}`;
const DISPATCHES = "/api/dispatches";
const VERSIONS = "/api/configuration/versions";
const SETTINGS = "/api/settings";
const EVALUATIONS = "/api/evaluations";

export const api = {
  listClaims: () => request<ClaimSummary[]>("/api/claims"),
  getClaim: (claimId: string) => request<Claim>(claimPath(claimId)),
  listSteps: (claimId: string) =>
    request<Step[]>(`${claimPath(claimId)}/steps`),
  getPolicy: (policyId: string) =>
    request<Policy>(`/api/policies/${encodeURIComponent(policyId)}`),
  getClaimHistory: (customerId: string) =>
    request<PreviousClaim[]>(
      `/api/customers/${encodeURIComponent(customerId)}/claims`,
    ),
  listVersions: () => request<VersionSummary[]>(VERSIONS),
  getVersion: (version: number) =>
    request<VersionDetails>(`${VERSIONS}/${String(version)}`),
  getSettings: () => request<SettingsHistory>(SETTINGS),
  updateSettings: (settings: SettingsRequest) =>
    send<Settings>("PUT", SETTINGS, settings),
  listModels: () => request<AllowedModel[]>("/api/models"),
  getSignedInHandler: () => request<Handler>("/api/handlers/me"),
  getLatestDispatch: () => request<Run | null>(`${DISPATCHES}/latest`),
  startDispatch: (agents: number) => post<Accepted>(DISPATCHES, { agents }),
  listEvaluations: () => request<Evaluation[]>(EVALUATIONS),
  getEvaluation: (runId: string) =>
    request<ScoredEvaluation>(`${EVALUATIONS}/${encodeURIComponent(runId)}`),
  startEvaluation: (
    evaluationSet: EvaluationSet,
    tiny: boolean,
    agents: number,
  ) =>
    post<Accepted>(EVALUATIONS, {
      evaluation_set: evaluationSet,
      tiny,
      agents,
    }),
  signOff: (claimId: string) => post<Claim>(`${claimPath(claimId)}/sign-off`),
};
