import { api } from "../api";
import { cantSignOff } from "../permissions";
import { useHandler } from "../session";
import { useLoad } from "../useLoad";
import { ActionForm } from "./ActionForm";

// Why a handler who can't sign off over the limit can't, with the limit.
function CantSignOff({ name }: Readonly<{ name: string }>) {
  const { data: settings } = useLoad(api.getSettings);
  if (!settings) return null;
  return (
    <p className="notice" role="note">
      {cantSignOff(name, settings.current.payout_approval_limit)}. A senior
      handler can.
    </p>
  );
}

// Signs a held payout off as the handler signed in, or says why they can't.
export function SignOffForm({
  claimId,
  onSignedOff,
}: Readonly<{ claimId: string; onSignedOff: () => void }>) {
  const handler = useHandler();

  if (!handler.can_approve_over_limit)
    return <CantSignOff name={handler.name} />;
  return (
    <ActionForm
      label={`Sign off as ${handler.name}`}
      action={() => api.signOff(claimId).then(onSignedOff)}
    />
  );
}
