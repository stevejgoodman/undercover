import { api } from "../api";
import { useHandler } from "../session";
import { ActionForm } from "./ActionForm";

// Signs a held payout off as the handler signed in, or says why they can't.
export function SignOffForm({
  claimId,
  onSignedOff,
}: Readonly<{ claimId: string; onSignedOff: () => void }>) {
  const handler = useHandler();

  if (!handler.can_approve_over_limit)
    return (
      <p className="notice" role="note">
        {handler.name} can't sign off payouts over the approval limit. A senior
        handler can.
      </p>
    );
  return (
    <ActionForm
      label={`Sign off as ${handler.name}`}
      action={() => api.signOff(claimId).then(onSignedOff)}
    />
  );
}
