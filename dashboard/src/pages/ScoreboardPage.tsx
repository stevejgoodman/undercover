import { useState } from "react";
import { Link } from "react-router";
import {
  api,
  type Evaluation,
  type EvaluationSet,
  evaluationSets,
} from "../api";
import { ActionForm } from "../components/ActionForm";
import { AgentsChoice, FIRST_CHOICE } from "../components/AgentsChoice";
import { RunChip } from "../components/Chips";
import { Message } from "../components/Message";
import { ModelName } from "../components/ModelName";
import { PageHeader } from "../components/PageHeader";
import {
  agentsAtOnce,
  dateTime,
  evaluationSetLabels,
  evaluationSetName,
} from "../format";
import { MEASURES } from "../measures";
import { evaluationPage } from "../paths";
import { REFRESH_MS, useLoad } from "../useLoad";

export function ScoreboardPage() {
  return (
    <>
      <PageHeader
        title="Scoreboard"
        lead="Each evaluation works copies of a labeled set's claims, which never show in the queue, and scores the agent's decisions against our handlers', with a judge's grade of each explanation."
      />
      <div className="column">
        <StartEvaluation />
        <Evaluations />
      </div>
    </>
  );
}

function StartEvaluation() {
  const [evaluationSet, setEvaluationSet] = useState<EvaluationSet>(
    evaluationSets[0],
  );
  const [tiny, setTiny] = useState(false);
  const [agents, setAgents] = useState(FIRST_CHOICE);

  return (
    <section className="panel" aria-labelledby="start-title">
      <h2 id="start-title">Start an evaluation</h2>
      <ActionForm
        label="Start an evaluation"
        action={() => api.startEvaluation(evaluationSet, tiny, agents)}
      >
        <label>
          Set
          <select
            value={evaluationSet}
            onChange={(event) => {
              const chosen = evaluationSets.find(
                (set) => set === event.target.value,
              );
              if (chosen) setEvaluationSet(chosen);
            }}
          >
            {evaluationSets.map((set) => (
              <option key={set} value={set}>
                {evaluationSetLabels[set]}
              </option>
            ))}
          </select>
        </label>
        <label>
          Claims
          <select
            value={tiny ? "tiny" : "all"}
            onChange={(event) => {
              setTiny(event.target.value === "tiny");
            }}
          >
            <option value="all">All 25</option>
            <option value="tiny">The five tiny claims</option>
          </select>
        </label>
        <AgentsChoice agents={agents} onChange={setAgents} />
      </ActionForm>
    </section>
  );
}

function Evaluations() {
  const { data: evaluations, error } = useLoad(api.listEvaluations, REFRESH_MS);

  return (
    <section className="panel" aria-labelledby="evaluations-title">
      <h2 id="evaluations-title">Evaluations</h2>
      {!evaluations && <Message error={error} />}
      {evaluations?.length === 0 && (
        <p className="muted">No evaluations yet.</p>
      )}
      {evaluations && evaluations.length > 0 && (
        <div className="table-scroll">
          <table className="table scoreboard">
            <thead>
              <tr>
                <th>Evaluation</th>
                <th>Status</th>
                {MEASURES.map(({ label }) => (
                  <th className="num" key={label}>
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {evaluations.map((evaluation) => (
                <EvaluationRow
                  key={evaluation.run_id}
                  evaluation={evaluation}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function EvaluationRow({ evaluation }: Readonly<{ evaluation: Evaluation }>) {
  return (
    <tr>
      <td>
        <Link to={evaluationPage(evaluation.run_id)}>
          Evaluation #{evaluation.number}
        </Link>
        <p>{evaluationSetName(evaluation.evaluation_set, evaluation.size)}</p>
        <p className="muted small">
          {dateTime(evaluation.started_at)}, {agentsAtOnce(evaluation.agents)},{" "}
          <ModelName run={evaluation} />
        </p>
      </td>
      <td>
        <RunChip status={evaluation.status} />
      </td>
      {MEASURES.map(({ label, show }) => (
        <td className="num mono" key={label}>
          {show(evaluation.measures)}
        </td>
      ))}
    </tr>
  );
}
