---
type: testing overview
title: Dashboard Tests
description: Frontend unit and integration tests for the dashboard app. Covers route rendering, backend API assumptions, and signed-in behavior that protect safe UI changes.
tags: [testing, frontend, dashboard, vitest, react]
verified:
  - by: openwiki/0.7.2
    at: 2026-10-25T14:37:18.902Z
sources:
  - id: openwiki-source-04001153b9c1e10c7616815b
    resource: repo://dashboard/src/api.test.ts
  - id: openwiki-source-60759181198943ffd854ad5a
    resource: repo://dashboard/src/App.test.tsx
  - id: openwiki-source-ec2dec91f2a9e306e877ae5a
    resource: repo://dashboard/src/Session.test.tsx
  - id: openwiki-source-861eae0ed47c106314a6cad5
    resource: repo://dashboard/src/testing.tsx
generated: { by: "openwiki/0.7.2", at: "2026-10-25T14:37:18.902Z" }
---

# Dashboard Tests

The dashboard test suite is the main safety net for UI changes in `dashboard/src`. It uses Vitest, React Testing Library, and a fetch stub in `dashboard/src/testing.tsx` to render the app against a simulated backend and a simulated browser session. The tests are written to exercise the app the way a user experiences it: by visiting routes, loading data, signing in and out, and handling backend failures.

## What the suite protects

The tests are not a generic component inventory. They focus on behaviors that can break routing, backend integration, or signed-in UX:

- route selection and fallback pages
- API contracts that the frontend assumes from the backend
- session storage, Authorization headers, and sign-in/sign-out flow
- safe handling of empty states and backend refusals
- polling behavior so the app does not overfetch when a read is slow

That makes the suite useful for maintainers who want to refactor UI structure without changing visible behavior or request semantics.

## Test harness and shared fixtures

`dashboard/src/testing.tsx` provides the reusable test harness.

- `stubApi(routes)` replaces `fetch` with a route table keyed by `METHOD /path`.
- `Refusal` simulates non-2xx backend responses with a JSON body containing `detail`.
- `renderAt(path, signedIn = true)` mounts `App` under `MemoryRouter` and seeds or clears the Supabase session in `localStorage`.
- `storeSession()` writes a serialized session under `SESSION_KEY` with a test access token.
- `authorizations(fetchMock)` inspects the `Authorization` header used on backend requests.
- `sent(fetchMock, route)` captures JSON request bodies sent to a given route.

The harness encodes several API assumptions that matter when changing the frontend:

- the backend is addressed with literal route strings such as `GET /api/claims` and `GET /api/handlers/me`
- unsupported routes should behave like a 404 with `{ detail: "Not found" }`
- the signed-in handler endpoint defaults to Dana Whitfield unless a test overrides it
- authenticated requests carry `Authorization: Bearer <access token>`

Because the tests use a fetch stub rather than a browser mock server, they can assert the exact request path, method, headers, and JSON payloads the UI emits.

## Route behavior tests

`dashboard/src/App.test.tsx` verifies route-level rendering and fallback behavior.

### Queue page at `/`

The root route is tested as the claims queue. The suite checks that the page:

- renders a claim link to `/claims/CLM-1002`
- shows queue counts by status, including waiting, decided, in progress, and left for a handler
- renders status chips with the expected CSS class for `left_for_handler`
- displays decided-row content such as the approval label and payout amount
- formats repeated date and currency values consistently

This protects the table view from accidental regressions in counts, labels, row styling, and formatting.

### Claim detail page at `/claims/:claim_id`

The claim detail tests load a claim together with its policy and customer history. They verify that the page can compose data from multiple backend endpoints and show the combined result:

- claim story, summary heading, and line items
- total amount claimed
- attached document content
- policy plan and add-ons
- trip destination and travel dates
- earlier claims for the customer
- the claim status label

The suite also covers two important empty-state variants:

- a policy with no add-ons should show `None`
- a customer with no earlier claims should show `No earlier claims`

That protects the detail page from breaking when related data is sparse.

### Missing and failing routes

The app test file also checks fallback behavior:

- unknown paths render `Page not found`
- missing claims render `Claim not found`
- other claim-load failures surface the backend's alert text
- queue-load failures surface the backend's alert text

One test goes further and proves that a missing claim stops being re-requested after the error is shown. Another checks that a slow `/api/claims` read does not trigger a second refresh while the first read is still unresolved.

These tests matter because they guard the app's retry and polling behavior, which can otherwise cause duplicate load requests or noisy error loops during refactors.

## Client behavior and polling tests

The route tests also capture client-side refresh behavior that is easy to break during UI changes.

- the app should wait for an in-flight queue read before refreshing again
- a slow read should not cause overlapping `/api/claims` requests
- the error and not-found states should stop unnecessary repeated claim fetches

This is important for performance and for preventing request storms when the UI is mounted on routes that poll automatically.

## Session and sign-in tests

`dashboard/src/Session.test.tsx` covers the signed-in and signed-out user experience.

### Routes that require sign-in

The suite confirms that `/`, `/scoreboard`, `/claims/CLM-1002`, and `/nowhere` all redirect to or render the sign-in screen when there is no session. That means route protection is enforced consistently, not only on the main dashboard.

### Signing in

The sign-in flow is tested end to end:

- the form accepts email and password input
- the app posts to `POST ${import.meta.env.VITE_SUPABASE_URL}/auth/v1/token?grant_type=password`
- a successful response stores the session in `localStorage` under `SESSION_KEY`
- the signed-in shell then shows the handler's name and role

The suite also checks that the exact credentials entered in the form are sent to Supabase Auth.

### Sign-in failures and recovery

The tests distinguish between different kinds of failure:

- invalid credentials should show the app's `WRONG_SIGN_IN` message
- Supabase Auth transport or service failures should not be misreported as invalid credentials
- a rejected `GET /api/handlers/me` response should return the user to the sign-in screen
- a 403 from `handlers/me` should preserve the backend-provided reason, because it explains why the sign-in is not valid for this app

### Signed-in shell and sign-out

When a session exists, the app should display the current handler's identity and allow sign-out. The tests verify that clicking sign-out returns the user to the sign-in page and clears `SESSION_KEY` from `localStorage`.

They also confirm that authenticated backend requests include the bearer token on every request. This is a critical contract: if the app stops attaching the token, most backend reads will silently fail.

## API contract assumptions worth preserving

The tests encode several assumptions that are easy to miss during refactors:

1. **Backend data shape is stable enough for direct rendering.**
   The app expects claim, policy, history, and handler payloads to expose the fields used in the tests.

2. **Error responses expose `detail` JSON.**
   The frontend reads `detail` from refusal responses to show user-facing messages.

3. **Sessions are persisted in Supabase's storage format.**
   `SESSION_KEY` must remain compatible with the shape used in the harness.

4. **Authenticated requests must include `Authorization: Bearer <token>`.**
   Several pages depend on this to load data successfully after sign-in.

5. **The app must keep its refresh loop disciplined.**
   A new read should not begin while a previous queue read is still in flight.

## Why these tests matter for safe UI changes

These tests let maintainers change presentation without accidentally changing behavior:

- you can reorganize components, but route output must remain stable
- you can restyle queue rows, but status and count semantics must stay intact
- you can rewrite fetch code, but headers, route names, and error interpretation must not change
- you can adjust session handling, but sign-in persistence and sign-out recovery must keep working

If a UI change affects any of those contracts, the tests should fail before the change reaches users.
