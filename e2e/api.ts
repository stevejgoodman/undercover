import { type APIRequestContext, expect } from "@playwright/test";
import type { DecisionKind, EvaluationSet, Run } from "../dashboard/src/api";

// Stands in for the agent's service and its claim agents, with one function for
// each backend operation the tests use, sent through the dashboard's proxy.
type Request = APIRequestContext;

const MODEL = {
  version: 1,
  model: "openai/gpt-6-luna",
  reasoning_effort: "low",
};
const claimPath = (claimId: string) =>
  `/api/claims/${encodeURIComponent(claimId)}`;
const runPath = (runId: string) => `/api/runs/${runId}`;

async function send(
  request: Request,
  method: "POST" | "PUT",
  path: string,
  data: object = {},
) {
  const response = await request.fetch(path, { method, data });
  await expect(response).toBeOK();
  return response;
}

export const startClaim = (request: Request, claimId: string, thread: string) =>
  send(request, "POST", `${claimPath(claimId)}/start`, { thread_id: thread });

export const recordStep = (
  request: Request,
  claimId: string,
  kind: "tool_call" | "tool_result" | "message" | "reading",
  content: string,
) => send(request, "POST", `${claimPath(claimId)}/steps`, { kind, content });

export const recordDecision = (
  request: Request,
  claimId: string,
  decision: {
    decision: DecisionKind;
    payout: number;
    section: string;
    reason: string;
  },
) => send(request, "POST", `${claimPath(claimId)}/decision`, decision);

// Asks to pay a claim and returns the backend's answer, which may be a refusal.
export const askToPay = (request: Request, claimId: string, amount: number) =>
  request.post(`${claimPath(claimId)}/payment`, { data: { amount } });

export async function payClaim(
  request: Request,
  claimId: string,
  amount: number,
) {
  await expect(await askToPay(request, claimId, amount)).toBeOK();
}

export const failClaim = (request: Request, claimId: string, reason: string) =>
  send(request, "POST", `${claimPath(claimId)}/failure`, { reason });

export const recordModelCall = (
  request: Request,
  claimId: string,
  runId: string,
  cost: number,
) =>
  send(request, "POST", `${claimPath(claimId)}/model-calls`, {
    run_id: runId,
    input_tokens: 1200,
    output_tokens: 300,
    cost,
  });

export const recordWorkTime = (
  request: Request,
  claimId: string,
  runId: string,
  seconds: number,
) =>
  send(request, "POST", `${claimPath(claimId)}/work-times`, {
    run_id: runId,
    seconds,
  });

export async function createDispatch(
  request: Request,
  agents: number,
): Promise<Run> {
  const response = await send(request, "POST", "/api/runs/dispatches", {
    agents,
    ...MODEL,
  });
  return (await response.json()) as Run;
}

export async function createEvaluation(
  request: Request,
  evaluationSet: EvaluationSet,
  tiny: boolean,
  agents: number,
): Promise<Run> {
  const response = await send(request, "POST", "/api/runs/evaluations", {
    evaluation_set: evaluationSet,
    tiny,
    agents,
    ...MODEL,
  });
  return (await response.json()) as Run;
}

const roundPath = (roundId: string, ...parts: string[]) =>
  ["/api/runs/rounds", roundId, ...parts].join("/");

// Works an evaluation's copies, referring every one, and finishes it.
async function referAll(request: Request, run: Run) {
  for (const { claim_id } of run.claims) {
    await startClaim(request, claim_id, `e2e-${claim_id}`);
    await recordDecision(request, claim_id, {
      decision: "refer",
      payout: 0,
      section: "Claims manual, section 2",
      reason: "A colleague should look at it.",
    });
  }
  await finishRun(request, run.run_id);
}

// Plays a round out as the agent's service would, up to a change waiting for a
// handler: the current version's first evaluations, then the improver's
// proposal. Returns the round's id and the proposal's.
export async function roundWaitingOnAChange(request: Request) {
  const created = await send(request, "POST", "/api/runs/rounds", {
    started_by: "Dana Whitfield",
  });
  const { round_id: roundId } = (await created.json()) as { round_id: string };
  for (const evaluationSet of ["evaluation", "held_out", "held_out"]) {
    const response = await send(
      request,
      "POST",
      roundPath(roundId, "evaluations"),
      {
        evaluation_set: evaluationSet,
        ...MODEL,
      },
    );
    await referAll(request, (await response.json()) as Run);
  }
  await send(request, "POST", roundPath(roundId, "improving"));
  const proposed = await send(
    request,
    "POST",
    roundPath(roundId, "proposals", "changes"),
    {
      instructions: "# UnderCover Agent\n\nRefer a claim missing a document.",
      model: MODEL.model,
      reasoning_effort: "medium",
      reason: "Fewer wrongful approvals",
    },
  );
  const { proposal_id: proposalId } = (await proposed.json()) as {
    proposal_id: number;
  };
  return { roundId, proposalId };
}

export const recordRunClaims = (
  request: Request,
  runId: string,
  claimIds: string[],
) => send(request, "PUT", `${runPath(runId)}/claims`, { claim_ids: claimIds });

export const finishRun = (request: Request, runId: string) =>
  send(request, "POST", `${runPath(runId)}/finish`);

// The stand-in for the agent's service, which Playwright starts on its own port.
export const AGENT_STAND_IN = "http://127.0.0.1:8003";
export const AUTH_STAND_IN = "http://127.0.0.1:8004";
export const JUDGE_STAND_IN = "http://127.0.0.1:8005";
// The handlers' password in the end-to-end tests, which the Auth stand-in checks.
export const HANDLER_PASSWORD = "e2e-password";
export const DANA = "dana.whitfield@undercover.example";
export const MARCUS = "marcus.oyelaran@undercover.example";

export async function resumed(request: Request): Promise<string[]> {
  const response = await request.get(`${AGENT_STAND_IN}/api/resumed`);
  await expect(response).toBeOK();
  return (await response.json()) as string[];
}

export interface Started {
  path: string;
  body: unknown;
}

export async function started(request: Request): Promise<Started[]> {
  const response = await request.get(`${AGENT_STAND_IN}/api/started`);
  await expect(response).toBeOK();
  return (await response.json()) as Started[];
}
