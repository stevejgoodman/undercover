import { useCallback, useState } from "react";
import { type Recipe, type Round, type Scores, api } from "../api";
import { RoundChip, RoundVerdictChip } from "../components/Chips";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { DiffView } from "../components/DiffView";
import { Message } from "../components/Message";
import { PageHeader } from "../components/PageHeader";
import { ProposalReview } from "../components/ProposalReview";
import { RoundStages } from "../components/RoundStages";
import { VersionChart } from "../components/VersionChart";
import {
  NONE_YET,
  dateTime,
  grade,
  modelCost,
  money,
  percent,
} from "../format";
import { seniorOnly } from "../permissions";
import { useHandler } from "../session";
import { useAction } from "../useAction";
import { REFRESH_MS, useLoad } from "../useLoad";

const CLOSED = new Set(["finished", "stopped"]);

function isOpen(round: Round): boolean {
  return !CLOSED.has(round.stage);
}

export function ImprovementPage() {
  const { data: rounds, error, reload } = useLoad(api.listRounds, REFRESH_MS);
  const { data: settings } = useLoad(api.getSettings);
  const open = rounds?.find(isOpen);
  const limit = settings?.current.payout_approval_limit;

  return (
    <>
      <PageHeader
        title="Improvement"
        lead="The improver reads how the claim agent is doing, proposes a better version for a senior handler to approve, and the rule keeps it or rolls it back on the held-out set. Each round ends by improving the improver's own recipe."
        action={
          rounds &&
          limit !== undefined && (
            // A new round remounts it, so it's ready again once that ends.
            <StartRound
              key={rounds.length}
              open={open}
              limit={limit}
              onStarted={reload}
            />
          )
        }
      />
      <div className="column">
        {!rounds && <Message error={error} />}
        {open && (
          <OpenRound
            key={open.round_id}
            roundId={open.round_id}
            onChanged={reload}
          />
        )}
        {rounds && <Rounds rounds={rounds} />}
        {rounds && settings && (
          <section className="panel" aria-labelledby="chart-title">
            <h2 id="chart-title">Versions on the held-out set</h2>
            <VersionChart
              rounds={rounds}
              floors={settings.current.objectives}
            />
          </section>
        )}
        <Recipes />
      </div>
    </>
  );
}

function StartRound({
  open,
  limit,
  onStarted,
}: Readonly<{ open?: Round; limit: number; onStarted: () => void }>) {
  const handler = useHandler();
  const [confirming, setConfirming] = useState(false);
  // A round is made in the background, so the button waits for it to appear.
  const [starting, setStarting] = useState(false);
  const { run, sending, error } = useAction();

  if (!handler.can_approve_over_limit)
    return (
      <p className="notice small" role="note">
        {seniorOnly(handler.name, limit, "start or stop a round")}
      </p>
    );
  const ready = !open && !sending && !starting;
  return (
    <div className="start-round">
      <button
        type="button"
        className="button"
        aria-disabled={!ready}
        onClick={() => {
          if (ready) setConfirming(true);
        }}
      >
        Start a round
      </button>
      {open && <p className="muted small">Round {open.number} is open.</p>}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <ConfirmDialog
        open={confirming}
        title="Start a round?"
        confirmLabel="Start a round"
        onConfirm={() => {
          setConfirming(false);
          setStarting(true);
          run(() =>
            api
              .startRound()
              .then(onStarted)
              .catch((reason: unknown) => {
                setStarting(false);
                throw reason;
              }),
          );
        }}
        onCancel={() => {
          setConfirming(false);
        }}
      >
        <p>
          The round works to the settings as they stand now. It may run the
          current version's evaluations first, then the improver proposes a
          change for you to approve.
        </p>
      </ConfirmDialog>
    </div>
  );
}

function OpenRound({
  roundId,
  onChanged,
}: Readonly<{ roundId: string; onChanged: () => void }>) {
  const handler = useHandler();
  const load = useCallback(() => api.getRound(roundId), [roundId]);
  const { data: round, error, reload } = useLoad(load, REFRESH_MS);
  const [confirming, setConfirming] = useState(false);
  const { run, sending, error: refused } = useAction();
  const changed = () => {
    reload();
    onChanged();
  };

  if (!round) return <Message error={error} />;
  const waiting = round.proposals.find((p) => p.status === "waiting");
  return (
    <>
      <section className="panel" aria-labelledby="open-round-title">
        <div className="panel-heading">
          <h2 id="open-round-title">Round {round.number}</h2>
          {handler.can_approve_over_limit && (
            <button
              type="button"
              className="button danger"
              aria-disabled={sending}
              onClick={() => {
                if (!sending) setConfirming(true);
              }}
            >
              Stop the round
            </button>
          )}
        </div>
        <p className="muted small">
          Started by {round.started_by}, {dateTime(round.started_at)}, on
          version {round.version_before} with recipe {round.recipe_version}.
          Spent <span className="mono">{modelCost(round.cost)}</span> of{" "}
          <span className="mono">{money(round.spending_limit)}</span>.
        </p>
        <RoundStages round={round} />
        {refused && (
          <p className="form-error" role="alert">
            {refused}
          </p>
        )}
        <ConfirmDialog
          open={confirming}
          title={`Stop round ${String(round.number)}?`}
          confirmLabel="Stop the round"
          danger
          onConfirm={() => {
            setConfirming(false);
            run(() => api.stopRound(round.round_id).then(changed));
          }}
          onCancel={() => {
            setConfirming(false);
          }}
        >
          <p>
            A round stopped before its verdict leaves the current version as it
            is. Work in hand finishes, and nothing more starts.
          </p>
        </ConfirmDialog>
      </section>
      {waiting && (
        <ProposalReview
          key={waiting.proposal_id}
          roundId={round.round_id}
          proposal={waiting}
          limit={round.settings.payout_approval_limit}
          onDecided={changed}
        />
      )}
    </>
  );
}

function BeforeAfter({
  before,
  after,
  show,
}: Readonly<{
  before: Scores | null;
  after: Scores | null;
  show: (scores: Scores) => string;
}>) {
  return (
    <span className="mono nowrap">
      {before ? show(before) : NONE_YET} → {after ? show(after) : NONE_YET}
    </span>
  );
}

function Rounds({ rounds }: Readonly<{ rounds: Round[] }>) {
  return (
    <section className="panel" aria-labelledby="rounds-title">
      <h2 id="rounds-title">Rounds</h2>
      {rounds.length === 0 ? (
        <p className="muted">
          No rounds yet. A senior handler starts one with Start a round.
        </p>
      ) : (
        <div className="table-scroll">
          <table className="table rounds">
            <thead>
              <tr>
                <th>Round</th>
                <th>Status</th>
                <th className="num">Recipe</th>
                <th className="num">Version tried</th>
                <th className="num">Held-out accuracy</th>
                <th className="num">Held-out grade</th>
                <th>Verdict</th>
                <th className="num">Cost</th>
              </tr>
            </thead>
            <tbody>
              {rounds.map((round) => (
                <tr key={round.round_id}>
                  <td>
                    Round {round.number}
                    <p className="muted small">
                      {round.started_by}, {dateTime(round.started_at)}
                    </p>
                  </td>
                  <td>
                    <RoundChip round={round} />
                  </td>
                  <td className="num mono">{round.recipe_version}</td>
                  <td className="num mono">
                    {round.version_tried ?? NONE_YET}
                  </td>
                  <td className="num">
                    <BeforeAfter
                      before={round.scores_before}
                      after={round.scores_after}
                      show={(s) => percent(s.accuracy)}
                    />
                  </td>
                  <td className="num">
                    <BeforeAfter
                      before={round.scores_before}
                      after={round.scores_after}
                      show={(s) => grade(s.grade)}
                    />
                  </td>
                  <td>
                    {round.verdict ? (
                      <>
                        <RoundVerdictChip verdict={round.verdict} />
                        <p className="muted small">{round.why}</p>
                      </>
                    ) : (
                      <span className="muted">
                        {round.why ??
                          (isOpen(round) ? "To come" : "No version tried")}
                      </span>
                    )}
                  </td>
                  <td className="num mono">{modelCost(round.cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Recipes() {
  const { data: recipes, error } = useLoad(api.listRecipes, REFRESH_MS);
  const [shown, setShown] = useState<number>();

  return (
    <section className="panel" aria-labelledby="recipes-title">
      <h2 id="recipes-title">The improver's recipe</h2>
      {!recipes && <Message error={error} />}
      {recipes?.map((recipe) => (
        <RecipeVersion
          key={recipe.version}
          recipe={recipe}
          open={shown === recipe.version}
          onToggle={() => {
            setShown(shown === recipe.version ? undefined : recipe.version);
          }}
        />
      ))}
    </section>
  );
}

function toggleLabel(recipe: Recipe, open: boolean): string {
  if (open) return "Hide";
  return recipe.version === 1 ? "Show" : "Show changes";
}

function RecipeVersion({
  recipe,
  open,
  onToggle,
}: Readonly<{ recipe: Recipe; open: boolean; onToggle: () => void }>) {
  return (
    <div className="recipe">
      <div className="recipe-line">
        <span>
          <strong>Recipe {recipe.version}</strong>{" "}
          <span className="muted small">
            {recipe.proposed_by}, approved by {recipe.approved_by},{" "}
            {dateTime(recipe.approved_at)}
          </span>
        </span>
        <button
          type="button"
          className="button secondary small-button"
          aria-expanded={open}
          onClick={onToggle}
        >
          {toggleLabel(recipe, open)}
        </button>
      </div>
      {open && (
        <>
          <p className="reason">{recipe.reason}</p>
          {recipe.version === 1 ? (
            <pre className="instructions">{recipe.recipe}</pre>
          ) : (
            <DiffView
              lines={recipe.diff}
              label={`Changes in recipe ${String(recipe.version)}`}
            />
          )}
        </>
      )}
    </div>
  );
}
