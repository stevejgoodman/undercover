import { createContext, use } from "react";
import type { Handler } from "./api";

export const SignedInHandler = createContext<Handler | null>(null);

// The handler signed in, for any page inside SessionGate.
export function useHandler(): Handler {
  const handler = use(SignedInHandler);
  if (!handler) throw new Error("useHandler needs a SessionGate around it");
  return handler;
}
