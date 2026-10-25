import { useState } from "react";
import { type Proposal, type Review, api } from "../api";
import { dateTime, roundStageLabels } from "../format";
import { seniorOnly } from "../permissions";
import { useHandler } from "../session";
import { useAction } from "../useAction";
import { ConfirmDialog } from "./ConfirmDialog";
import { DiffView } from "./DiffView";

const CONFIRM: Record<Review, { title: string; label: string; body: string }> =
  {
    approve: {
      title: "Approve the proposal?",
      label: "Approve",
      body: "The improver goes on with it.",
    },
    reject: {
      title: "Reject the proposal?",
      label: "Reject",
      body: "Your reason goes back to the improver, which may propose again.",
    },
  };

function Change({ proposal }: Readonly<{ proposal: Proposal }>) {
  return (
    <table className="table before-after">
      <thead>
        <tr>
          <th />
          <th>Now</th>
          <th>Proposed</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <th scope="row">Model</th>
          <td className="mono">{proposal.model_before}</td>
          <td className="mono">{proposal.model}</td>
        </tr>
        <tr>
          <th scope="row">Reasoning effort</th>
          <td>{proposal.reasoning_effort_before}</td>
          <td>{proposal.reasoning_effort}</td>
        </tr>
      </tbody>
    </table>
  );
}

// The proposal a round waits on: what it changes, why, and, for a senior
// handler, approve or reject with a reason, each behind a confirmation.
export function ProposalReview({
  roundId,
  proposal,
  limit,
  onDecided,
}: Readonly<{
  roundId: string;
  proposal: Proposal;
  limit: number;
  onDecided: () => void;
}>) {
  const handler = useHandler();
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState<Review>();
  const { run, sending, error } = useAction();
  const change = proposal.kind === "change";
  const what = change ? "instructions" : "recipe";

  function decide(decision: Review) {
    setConfirming(undefined);
    run(() =>
      api
        .decideProposal(roundId, proposal.proposal_id, decision, reason)
        .then(onDecided),
    );
  }

  return (
    <section className="panel" aria-labelledby="proposal-title">
      <h2 id="proposal-title">
        {roundStageLabels[change ? "waiting_for_change" : "waiting_for_recipe"]}
      </h2>
      <p className="muted small">
        Proposed {dateTime(proposal.created_at)}, against{" "}
        {change ? "version" : "recipe"} {proposal.based_on}.
      </p>
      <h3 className="subheading">The improver's reason</h3>
      <p className="reason">{proposal.reason}</p>
      {change && <Change proposal={proposal} />}
      <h3 className="subheading">What changes in the {what}</h3>
      <DiffView lines={proposal.diff} label={`Changes to the ${what}`} />
      {handler.can_approve_over_limit ? (
        <div className="review">
          <label className="stacked-label">
            Reason, needed to reject
            <textarea
              value={reason}
              rows={2}
              onChange={(event) => {
                setReason(event.target.value);
              }}
            />
          </label>
          <div className="review-actions">
            <button
              type="button"
              className="button"
              aria-disabled={sending}
              onClick={() => {
                if (!sending) setConfirming("approve");
              }}
            >
              Approve
            </button>
            <button
              type="button"
              className="button danger"
              aria-disabled={sending || reason.trim() === ""}
              onClick={() => {
                if (!sending && reason.trim()) setConfirming("reject");
              }}
            >
              Reject
            </button>
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </div>
      ) : (
        <p className="notice" role="note">
          {seniorOnly(handler.name, limit, "approve or reject a proposal")}
        </p>
      )}
      {confirming && (
        <ConfirmDialog
          open
          title={CONFIRM[confirming].title}
          confirmLabel={CONFIRM[confirming].label}
          danger={confirming === "reject"}
          onConfirm={() => {
            decide(confirming);
          }}
          onCancel={() => {
            setConfirming(undefined);
          }}
        >
          <p>{CONFIRM[confirming].body}</p>
          {confirming === "reject" && <p className="reason">{reason}</p>}
        </ConfirmDialog>
      )}
    </section>
  );
}
