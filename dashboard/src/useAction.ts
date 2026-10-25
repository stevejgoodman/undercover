import { useCallback, useState } from "react";
import { REQUEST_FAILED } from "./api";

// Sends one request that does something, such as signing off a payout or saving
// the settings, at most one at a time, and keeps the reason if it's refused.
export function useAction() {
  const [error, setError] = useState<string>();
  const [sending, setSending] = useState(false);

  const run = useCallback(
    (action: () => Promise<unknown>) => {
      if (sending) return;
      setSending(true);
      setError(undefined);
      action()
        .catch((reason: unknown) => {
          setError(reason instanceof Error ? reason.message : REQUEST_FAILED);
        })
        .finally(() => {
          setSending(false);
        });
    },
    [sending],
  );
  return { run, sending, error };
}
