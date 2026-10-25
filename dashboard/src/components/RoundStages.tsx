import { type Round, type RoundStage, roundStages } from "../api";
import { roundStageLabels } from "../format";

// An open round's stages in order, ending with its finish.
const STEPS: readonly RoundStage[] = roundStages.filter(
  (stage) => stage !== "stopped",
);

function stateOf(index: number, at: number): string {
  if (index < at) return "done";
  return index === at ? "current" : "to-come";
}

// Where an open round has got to, step by step, with how many of a stage's
// evaluations have started.
export function RoundStages({ round }: Readonly<{ round: Round }>) {
  const at = STEPS.indexOf(round.stage);
  return (
    <ol className="stages" aria-label={`Round ${String(round.number)} stages`}>
      {STEPS.map((step, index) => {
        const state = stateOf(index, at);
        return (
          <li
            key={step}
            className={`stage stage-${state}`}
            aria-current={state === "current" ? "step" : undefined}
          >
            <span className="stage-mark" aria-hidden="true">
              {index + 1}
            </span>
            <span>
              {roundStageLabels[step]}
              {state === "current" && round.progress && (
                <span className="muted small">
                  {" "}
                  {round.progress.done} of {round.progress.of}
                </span>
              )}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
