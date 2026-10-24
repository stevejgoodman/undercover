import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SESSION_KEY, WRONG_SIGN_IN } from "./supabase";
import {
  ACCESS_TOKEN,
  Refusal,
  SIGNED_IN,
  dana,
  marcus,
  authorizations,
  renderAt,
  sent,
  stubApi,
} from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

const SIGN_IN = `POST ${import.meta.env.VITE_SUPABASE_URL}/auth/v1/token?grant_type=password`;

function signInWith(email: string, password: string) {
  fireEvent.change(screen.getByLabelText("Email address"), {
    target: { value: email },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: password },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

it.each(["/", "/scoreboard", "/claims/CLM-1002", "/nowhere"])(
  "asks for a sign-in on %s",
  async (path) => {
    stubApi({});
    renderAt(path, false);
    expect(
      await screen.findByRole("heading", { name: "Sign in", level: 1 }),
    ).toBeDefined();
    expect(screen.queryByRole("navigation")).toBeNull();
  },
);

it("signs a handler in with their email and password", async () => {
  const fetchMock = stubApi({
    [SIGN_IN]: {
      access_token: ACCESS_TOKEN,
      refresh_token: "refresh",
      token_type: "bearer",
      expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600,
      user: { id: "user-1", aud: "authenticated", email: dana.email },
    },
    "GET /api/claims": [],
    "GET /api/dispatches/latest": null,
  });
  renderAt("/", false);
  await screen.findByRole("heading", { name: "Sign in" });
  signInWith(dana.email, "the password");
  expect(await screen.findByText("Dana Whitfield")).toBeDefined();
  expect(screen.getByText("Senior Claims Handler")).toBeDefined();
  expect(sent(fetchMock, SIGN_IN)[0]).toMatchObject({
    email: dana.email,
    password: "the password",
  });
  expect(localStorage.getItem(SESSION_KEY)).toContain(ACCESS_TOKEN);
});

it("says when the email and password don't match", async () => {
  stubApi({
    [SIGN_IN]: new Refusal(400, "Invalid login credentials"),
  });
  renderAt("/", false);
  await screen.findByRole("heading", { name: "Sign in" });
  signInWith(dana.email, "wrong");
  expect((await screen.findByRole("alert")).textContent).toBe(WRONG_SIGN_IN);
});

it("shows who is signed in, and signs them out", async () => {
  stubApi({
    [SIGNED_IN]: marcus,
    "GET /api/claims": [],
    "GET /api/dispatches/latest": null,
  });
  renderAt("/");
  expect(await screen.findByText("Marcus Oyelaran")).toBeDefined();
  expect(screen.getByText("Claims Handler")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeDefined();
  expect(localStorage.getItem(SESSION_KEY)).toBeNull();
});

it("goes back to the sign-in page when the backend refuses the sign-in", async () => {
  stubApi({
    [SIGNED_IN]: new Refusal(401, "Please sign in"),
  });
  renderAt("/");
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeDefined();
});

it("sends the access token with every request", async () => {
  const fetchMock = stubApi({
    "GET /api/claims": [],
    "GET /api/dispatches/latest": null,
  });
  renderAt("/");
  await screen.findByText("Dana Whitfield");
  const sent = authorizations(fetchMock);
  expect(sent.length).toBeGreaterThan(1);
  expect(new Set(sent)).toEqual(new Set([`Bearer ${ACCESS_TOKEN}`]));
});

it("says when Supabase Auth can't be reached", async () => {
  stubApi({ [SIGN_IN]: new Refusal(503, "Service unavailable") });
  renderAt("/", false);
  await screen.findByRole("heading", { name: "Sign in" });
  signInWith(dana.email, "the password");
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).not.toBe(WRONG_SIGN_IN);
});

it("says why a sign-in isn't a handler's, with a way to sign out", async () => {
  stubApi({
    [SIGNED_IN]: new Refusal(
      403,
      "No handler signs in as someone@else.example",
    ),
  });
  renderAt("/");
  expect((await screen.findByRole("alert")).textContent).toBe(
    "No handler signs in as someone@else.example",
  );
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeDefined();
});
