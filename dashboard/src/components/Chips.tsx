import type {
  DecisionKind,
  Round,
  RunStatus,
  Status,
  VersionVerdict,
} from "../api";
import {
  decisionLabels,
  money,
  roundStageLabels,
  runLabels,
  statusLabels,
  verdictLabels,
} from "../format";

export function StatusChip({ status }: Readonly<{ status: Status }>) {
  return (
    <span className={`chip status-${status}`}>{statusLabels[status]}</span>
  );
}

export function DecisionChip({
  decision,
}: Readonly<{ decision: DecisionKind }>) {
  return (
    <span className={`chip decision-${decision}`}>
      {decisionLabels[decision]}
    </span>
  );
}

export function RunChip({ status }: Readonly<{ status: RunStatus }>) {
  return <span className={`chip run-${status}`}>{runLabels[status]}</span>;
}

// Whether the agent's decision and payout match the handler's.
export function RightChip({ right }: Readonly<{ right: boolean }>) {
  return right ? (
    <span className="chip score-right">Right</span>
  ) : (
    <span className="chip score-miss">Miss</span>
  );
}

export function DecisionPayout({
  decision,
  payout,
}: Readonly<{ decision: DecisionKind; payout: number }>) {
  return (
    <>
      <DecisionChip decision={decision} />{" "}
      <span className="mono">{money(payout)}</span>
    </>
  );
}

// Where a version stands: the current one, kept before, rolled back, or still
// being tried in a round.
export function VerdictChip({
  verdict,
  current,
}: Readonly<{ verdict: VersionVerdict | null; current: boolean }>) {
  if (current) return <span className="chip verdict-current">Current</span>;
  if (verdict === null)
    return <span className="chip verdict-trying">Being tried</span>;
  return (
    <span className={`chip verdict-${verdict}`}>{verdictLabels[verdict]}</span>
  );
}

// A round open, finished or stopped.
export function RoundChip({ round }: Readonly<{ round: Round }>) {
  if (round.stage === "finished" || round.stage === "stopped")
    return (
      <span className={`chip round-${round.stage}`}>
        {roundStageLabels[round.stage]}
      </span>
    );
  return <span className="chip round-open">Open</span>;
}

// A round's verdict on the version it tried.
export function RoundVerdictChip({
  verdict,
}: Readonly<{ verdict: VersionVerdict }>) {
  return (
    <span className={`chip verdict-${verdict}`}>{verdictLabels[verdict]}</span>
  );
}
