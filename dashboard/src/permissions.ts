import { money } from "./format";

// What a handler who can't sign off payouts over the limit is told they can't
// do, as the backend says it too.
export function cantSignOff(name: string, limit: number): string {
  return `${name} can't sign off payouts over ${money(limit)}`;
}

export function seniorOnly(name: string, limit: number, what: string): string {
  return `${cantSignOff(name, limit)}, so only a senior handler can ${what}.`;
}
