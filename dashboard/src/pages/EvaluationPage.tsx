import { useCallback } from "react";
import { useParams } from "react-router";
import {
  type Grade,
  type ScoredClaim,
  type ScoredEvaluation,
  api,
} from "../api";
import { DecisionPayout, RightChip, RunChip } from "../components/Chips";
import { Breadcrumb } from "../components/Breadcrumb";
import { ClaimLink } from "../components/ClaimLink";
import { Message } from "../components/Message";
import { ModelName } from "../components/ModelName";
import { PageHeader } from "../components/PageHeader";
import {
  NOT_GRADED,
  agentsAtOnce,
  check,
  dateTime,
  duration,
  evaluationSetName,
  grade as gradeScore,
  modelCost,
  money,
} from "../format";
import { MEASURES } from "../measures";
import { SCOREBOARD } from "../paths";
import { REFRESH_MS, useLoad } from "../useLoad";

export function EvaluationPage() {
  const { runId = "" } = useParams();
  const load = useCallback(() => api.getEvaluation(runId), [runId]);
  const { data: evaluation, error } = useLoad(load, REFRESH_MS);

  if (!evaluation)
    return <Message error={error} notFound="Evaluation not found" />;

  return (
    <>
      <Breadcrumb
        crumbs={[
          { label: "Scoreboard", to: SCOREBOARD },
          { label: `Evaluation #${String(evaluation.number)}` },
        ]}
      />
      <PageHeader
        title={`Evaluation #${String(evaluation.number)}`}
        lead={
          <>
            <RunChip status={evaluation.status} /> Each copy beside the
            handler's decision on its original, with the judge's grade of the
            agent's reason.
          </>
        }
      />
      <div className="column">
        <MeasuresPanel evaluation={evaluation} />
        <ScoredClaims claims={evaluation.claims} />
      </div>
    </>
  );
}

function MeasuresPanel({
  evaluation,
}: Readonly<{ evaluation: ScoredEvaluation }>) {
  return (
    <section className="panel" aria-labelledby="measures-title">
      <h2 id="measures-title">Measures</h2>
      <p className="muted small">
        {evaluationSetName(evaluation.evaluation_set, evaluation.size)}, with{" "}
        {agentsAtOnce(evaluation.agents)} on <ModelName run={evaluation} />.
        Started {dateTime(evaluation.started_at)}.
      </p>
      <dl className="facts measures">
        {MEASURES.map(({ label, show }) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd className="mono">{show(evaluation.measures)}</dd>
          </div>
        ))}
        <div>
          <dt>Judge's cost</dt>
          <dd className="mono">{modelCost(evaluation.measures.judge_cost)}</dd>
        </div>
      </dl>
      <p className="muted small">
        Jev grades each of the agent's reasons against the handler's, from F to
        A, and checks whether it gives the same grounds and the same section.
        Its cost is apart from the claim agent's model cost.
      </p>
    </section>
  );
}

function CheckChip({ probability }: Readonly<{ probability: number }>) {
  const answer = check(probability);
  return <span className={`chip check-${answer.toLowerCase()}`}>{answer}</span>;
}

// A claim's grade, its letter and score, and the two checks, or not graded.
function GradeCells({ grade }: Readonly<{ grade: Grade | null }>) {
  if (!grade)
    return (
      <td className="muted" colSpan={3}>
        {NOT_GRADED}
      </td>
    );
  return (
    <>
      <td className="nowrap">
        <span className={`chip letter letter-${grade.letter}`}>
          {grade.letter}
        </span>{" "}
        <span className="mono small">{gradeScore(grade.score)}</span>
      </td>
      <td>
        <CheckChip probability={grade.same_grounds} />
      </td>
      <td>
        <CheckChip probability={grade.same_section} />
      </td>
    </>
  );
}

// The claims table's columns, which each claim's reason spans beneath it.
const COLUMNS = 11;

function ScoredClaims({ claims }: Readonly<{ claims: ScoredClaim[] }>) {
  return (
    <section className="panel" aria-labelledby="claims-title">
      <h2 id="claims-title">Claims</h2>
      <p className="muted small">
        A claim the agent didn't decide counts as a referral.
      </p>
      <div className="table-scroll">
        <table className="table scored">
          <thead>
            <tr>
              <th>Copy</th>
              <th>Of</th>
              <th>Handler</th>
              <th>Agent</th>
              <th>Score</th>
              <th>Grade</th>
              <th>Same grounds</th>
              <th>Same section</th>
              <th className="num">Mistake cost</th>
              <th className="num">Model cost</th>
              <th className="num">Time</th>
            </tr>
          </thead>
          {claims.map((claim) => (
            <tbody key={claim.claim_id}>
              <tr>
                <td className="nowrap">
                  <ClaimLink claimId={claim.claim_id} />
                </td>
                <td className="mono nowrap">{claim.copy_of}</td>
                <td className="nowrap">
                  <DecisionPayout
                    decision={claim.handler_decision}
                    payout={claim.handler_payout}
                  />
                </td>
                <td className="nowrap">
                  {claim.decision && claim.payout !== null ? (
                    <DecisionPayout
                      decision={claim.decision}
                      payout={claim.payout}
                    />
                  ) : (
                    <span className="muted">No decision</span>
                  )}
                </td>
                <td>
                  <RightChip right={claim.right} />
                </td>
                <GradeCells grade={claim.grade} />
                <td className="num mono">{money(claim.mistake_cost)}</td>
                <td className="num mono">{modelCost(claim.model_cost)}</td>
                <td className="num mono">{duration(claim.seconds)}</td>
              </tr>
              {claim.reason && (
                <tr className="reason-row">
                  <td colSpan={COLUMNS} className="small">
                    <span className="muted">The agent's reason: </span>
                    {claim.reason}
                  </td>
                </tr>
              )}
            </tbody>
          ))}
        </table>
      </div>
    </section>
  );
}
