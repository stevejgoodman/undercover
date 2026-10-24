import { type ReactNode, type SyntheticEvent, useState } from "react";
import { REQUEST_FAILED } from "../api";

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
  const [error, setError] = useState<string>();
  const [sending, setSending] = useState(false);
  const disabled = !ready || sending;

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (disabled) return;
    setSending(true);
    setError(undefined);
    action()
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : REQUEST_FAILED);
      })
      .finally(() => {
        setSending(false);
      });
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
