import type {
  DecisionKind,
  EvaluationSet,
  RoundStage,
  RunStatus,
  Status,
  VersionVerdict,
} from "./api";

const dollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

const day = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

const dayAndClock = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

const clock = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
});

// Model costs are often under a cent.
const modelDollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

export function money(amount: number): string {
  return dollars.format(amount);
}

// A share, such as 0.8, as a whole percentage: 80%.
export function percent(share: number): string {
  return `${String(Math.round(share * 100))}%`;
}

export const NOT_GRADED = "Not graded";

// The judge's grade, from 0 for F to 3 for A.
export function grade(score: number | null): string {
  return score === null ? NOT_GRADED : score.toFixed(2);
}

// One of the judge's checks, a probability, as yes when it's more likely than not.
export function check(probability: number): string {
  return probability > 0.5 ? "Yes" : "No";
}

export function modelCost(amount: number): string {
  return modelDollars.format(amount);
}

// A length of time, such as 41 s or 2 min 41 s.
export function duration(seconds: number): string {
  const whole = Math.round(seconds);
  const minutes = Math.floor(whole / 60);
  const rest = `${String(whole % 60)} s`;
  return minutes > 0 ? `${String(minutes)} min ${rest}` : rest;
}

export function date(isoDate: string): string {
  return day.format(new Date(`${isoDate}T00:00:00Z`));
}

export function time(isoTime: string): string {
  return clock.format(new Date(isoTime));
}

export function dateTime(isoTime: string): string {
  return dayAndClock.format(new Date(isoTime));
}

export function agentsAtOnce(agents: number): string {
  return `${String(agents)} claim ${agents === 1 ? "agent" : "agents"} at once`;
}

// A reason the backend gives in lower case, as a sentence on its own.
export function sentence(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function label(code: string): string {
  const words = code.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const statusLabels: Record<Status, string> = {
  waiting: "Waiting",
  in_progress: "In progress",
  waiting_for_sign_off: "Waiting for sign-off",
  decided: "Decided",
  left_for_handler: "Left for a handler",
};

export const runLabels: Record<RunStatus, string> = {
  running: "Running",
  finished: "Finished",
  stopped: "Stopped",
};

export const evaluationSetLabels: Record<EvaluationSet, string> = {
  evaluation: "Evaluation set",
  held_out: "Held-out set",
};

export function evaluationSetName(set: EvaluationSet, size: number): string {
  return `${evaluationSetLabels[set]}, ${String(size)} claims`;
}

export const roundStageLabels: Record<RoundStage, string> = {
  first_evaluations: "First evaluations",
  improving: "The improver is working",
  waiting_for_change: "A change is waiting for approval",
  evaluations: "Evaluations",
  verdict: "The verdict",
  waiting_for_recipe: "A recipe is waiting for approval",
  finished: "Finished",
  stopped: "Stopped",
};

export const verdictLabels: Record<VersionVerdict, string> = {
  kept: "Kept",
  rolled_back: "Rolled back",
};

// What a table shows for a measure there's nothing yet to work out from.
export const NONE_YET = "–";

export const decisionLabels: Record<DecisionKind, string> = {
  approve: "Approved",
  decline: "Declined",
  refer: "Referred",
};

const addOnNames: Record<string, string> = {
  adventure_sports: "Adventure Sports",
  pre_existing_waiver: "Pre-Existing Condition Waiver",
  electronics_plus: "Electronics Plus",
};

export function addOnName(code: string): string {
  return addOnNames[code] ?? label(code);
}
