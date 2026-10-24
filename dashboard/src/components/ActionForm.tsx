import type { ReactNode, SyntheticEvent } from "react";
import { useAction } from "../useAction";

// A form that asks the backend to do one thing, such as signing off a payout
// or starting a dispatch, and shows the backend's reason if it refuses. The
// button stays focusable while the request is sent, so a keyboard user can
// try again after a refusal.
export function ActionForm({
  label,
  className = "action-form",
  ready = true,
  action,
  children,
}: Readonly<{
  label: string;
  className?: string;
  ready?: boolean;
  action: () => Promise<unknown>;
  children?: ReactNode;
}>) {
  const { run, sending, error } = useAction();
  const disabled = !ready || sending;

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!disabled) run(action);
  }

  return (
    <form className={className} onSubmit={submit}>
      {children}
      <button type="submit" className="button" aria-disabled={disabled}>
        {label}
      </button>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
