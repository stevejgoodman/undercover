import {
  type Session,
  createClient,
  isAuthApiError,
} from "@supabase/supabase-js";

// The dashboard's only way to Supabase: signing handlers in and out with Supabase
// Auth. The address and the publishable key are meant to be public.
export const SESSION_KEY = "undercover-session";
export const WRONG_SIGN_IN = "That email address and password don't match.";
const REFUSED = 400;

const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY,
  { auth: { storageKey: SESSION_KEY } },
);

// Signs a handler in, or says why not: a wrong email address or password, or
// Supabase's own error, such as when it can't be reached.
export async function signIn(email: string, password: string): Promise<void> {
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (isAuthApiError(error) && error.status === REFUSED)
    throw new Error(WRONG_SIGN_IN);
  if (error) throw error;
}

export async function signOut(): Promise<void> {
  await supabase.auth.signOut({ scope: "local" });
}

// Calls back with the session at once, and again whenever it changes, until the
// returned function is called.
export function onSessionChange(
  callback: (session: Session | null) => void,
): () => void {
  const { data } = supabase.auth.onAuthStateChange((_event, session) => {
    callback(session);
  });
  return () => {
    data.subscription.unsubscribe();
  };
}

// The signed-in handler's access token, sent with each request to the backend.
export async function accessToken(): Promise<string | undefined> {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token;
}
