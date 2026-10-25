import type { Session } from "@supabase/supabase-js";
import { type ReactNode, useEffect, useState } from "react";
import { api } from "../api";
import { SignInPage } from "../pages/SignInPage";
import { SignedInHandler } from "../session";
import { onSessionChange, signOut } from "../supabase";
import { useLoad } from "../useLoad";
import { Message } from "./Message";

// Finds the handler signed in, or says why not, with a way to sign out.
function WithHandler({ children }: Readonly<{ children: ReactNode }>) {
  const { data: handler, error } = useLoad(api.getSignedInHandler);
  if (handler)
    return <SignedInHandler value={handler}>{children}</SignedInHandler>;
  return (
    <main className="sign-in">
      <div className="panel sign-in-panel">
        <Message error={error} />
        {error && (
          <button
            type="button"
            className="button secondary"
            onClick={() => {
              void signOut();
            }}
          >
            Sign out
          </button>
        )}
      </div>
    </main>
  );
}

// Shows its pages only to a signed-in handler, and the sign-in page to anyone
// else, on whatever page they asked for.
export function SessionGate({ children }: Readonly<{ children: ReactNode }>) {
  const [session, setSession] = useState<Session | null>();

  useEffect(() => onSessionChange(setSession), []);

  if (session === undefined) return <Message />;
  if (session === null) return <SignInPage />;
  return <WithHandler key={session.user.id}>{children}</WithHandler>;
}
