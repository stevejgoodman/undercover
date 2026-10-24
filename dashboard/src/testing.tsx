import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import { App } from "./App";
import type {
  Claim,
  ClaimSummary,
  Handler,
  Policy,
  PreviousClaim,
} from "./api";
import { SESSION_KEY } from "./supabase";

// Stands in for the backend: answers "METHOD /path" with the JSON given, or
// with the status and detail given as an error, and a 404 for anything else.
// The signed-in handler is Dana Whitfield unless the routes say otherwise.
export type Routes = Record<string, unknown>;

export const dana: Handler = {
  handler_id: "HND-01",
  name: "Dana Whitfield",
  role: "Senior Claims Handler",
  email: "dana.whitfield@undercover.example",
  can_approve_over_limit: true,
};

export const marcus: Handler = {
  handler_id: "HND-02",
  name: "Marcus Oyelaran",
  role: "Claims Handler",
  email: "marcus.oyelaran@undercover.example",
  can_approve_over_limit: false,
};

export const SIGNED_IN = "GET /api/handlers/me";
export const ACCESS_TOKEN = "a-test-access-token";

export class Refusal {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {}
}

export function stubApi(routes: Routes) {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    const route = `${init?.method ?? "GET"} ${path}`;
    const answer =
      route === SIGNED_IN ? (routes[route] ?? dana) : routes[route];
    if (answer === undefined)
      return Promise.resolve(
        Response.json({ detail: "Not found" }, { status: 404 }),
      );
    if (answer instanceof Refusal)
      return Promise.resolve(
        Response.json({ detail: answer.detail }, { status: answer.status }),
      );
    return Promise.resolve(Response.json(answer));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

// The Authorization header of each request sent to the backend, in order.
export function authorizations(fetchMock: ReturnType<typeof stubApi>) {
  return fetchMock.mock.calls
    .filter(([path]) => path.startsWith("/api/"))
    .map(([, init]) => new Headers(init?.headers).get("Authorization"));
}

// The bodies of the requests sent to "METHOD /path", in order.
export function sent(fetchMock: ReturnType<typeof stubApi>, route: string) {
  return fetchMock.mock.calls
    .filter(([path, init]) => `${init?.method ?? "GET"} ${path}` === route)
    .map(([, init]) =>
      typeof init?.body === "string"
        ? (JSON.parse(init.body) as unknown)
        : undefined,
    );
}

// Keeps a session in the browser's storage, as Supabase Auth does after a
// sign-in, with an access token that lasts the test out.
export function storeSession() {
  localStorage.setItem(
    SESSION_KEY,
    JSON.stringify({
      access_token: ACCESS_TOKEN,
      refresh_token: "a-test-refresh-token",
      token_type: "bearer",
      expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600,
      user: {
        id: "user-1",
        aud: "authenticated",
        email: dana.email,
        app_metadata: {},
        user_metadata: {},
        created_at: "2026-10-01T00:00:00Z",
      },
    }),
  );
}

export function renderAt(path: string, signedIn = true) {
  if (signedIn) storeSession();
  else localStorage.removeItem(SESSION_KEY);
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

// Finds the panel headed by the given heading, to look inside it.
export async function panel(heading: string) {
  return within(await screen.findByRole("region", { name: heading }));
}

export const claim: Claim = {
  claim_id: "CLM-1002",
  policy_id: "POL-2002",
  customer_id: "CUS-3002",
  customer_name: "Tom Becker",
  claim_type: "baggage",
  submitted_on: "2026-07-20",
  incident_date: "2026-06-21",
  incident_location: "Frankfurt, Germany",
  summary: "Suitcase lost on a connecting flight",
  story: "My suitcase never arrived in Prague.",
  items: [
    { description: "Hard-shell suitcase", category: "luggage", amount: 280 },
    { description: "Wool suit", category: "clothing", amount: 870 },
  ],
  amount_claimed: 1150,
  documents: [
    {
      name: "Lost baggage report",
      type: "carrier_report",
      content: "One checked bag not delivered.",
    },
  ],
  status: "waiting",
  thread_id: null,
  attempts: 0,
  evaluation_id: null,
  copy_of: null,
  decision: null,
  payment: null,
};

export const summary: ClaimSummary = {
  claim_id: "CLM-1002",
  customer_name: "Tom Becker",
  claim_type: "baggage",
  summary: "Suitcase lost on a connecting flight",
  amount_claimed: 1150,
  submitted_on: "2026-07-20",
  status: "waiting",
  decision: null,
  payout: null,
};

export const policy: Policy = {
  policy_id: "POL-2002",
  customer_id: "CUS-3002",
  plan: "premium",
  add_ons: ["electronics_plus"],
  purchased_on: "2026-05-02",
  sold_through: "UnderCover website",
  trip: {
    destination: "Prague, Czech Republic",
    departs_on: "2026-06-20",
    returns_on: "2026-06-30",
    trip_cost: 2400,
  },
  travelers: ["Tom Becker"],
  status: "active",
};

export const history: PreviousClaim[] = [
  {
    claim_id: "CLM-0412",
    filed_on: "2024-08-19",
    incident_date: "2024-08-09",
    claim_type: "baggage_delay",
    summary: "Checked bag arrived 30 hours late in Lisbon",
    outcome: "approved",
    amount_paid: 140,
  },
];
