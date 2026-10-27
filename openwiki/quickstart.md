---
type: navigation concept
title: Quickstart
description: Top-level map of the repository’s runtime domains, entrypoints, verification commands, and the safest order to inspect code when changing behavior.
tags: [navigation, quickstart, entrypoints, runtime-map, onboarding]
verified:
  - by: openwiki/0.7.2
    at: 2026-10-25T14:37:18.902Z
sources:
  - id: openwiki-source-2527b28a99919107a0d4b488
    resource: repo://agent/service.py
  - id: openwiki-source-fcffbe3e28749eaf9a39557c
    resource: repo://backend/main.py
  - id: openwiki-source-6d51e49e4521c1ae2c508a4c
    resource: repo://dashboard/src/App.tsx
  - id: openwiki-source-5b54a58d1b51cd490b0e7162
    resource: repo://package.json
  - id: openwiki-source-05ccef8d4cf1698187f20464
    resource: repo://pyproject.toml
  - id: openwiki-source-23775c3de52f3ab95a13cb8b
    resource: repo://README.md
generated: { by: "openwiki/0.7.2", at: "2026-10-25T14:37:18.902Z" }
---

# Quickstart

Use this page as the repository’s top-level navigation map. It points you to the runtime boundaries, the main entrypoints, and the documents that explain each domain in depth.

## What this repository runs

UnderCover has three main runtime pieces:

- the [backend domain](architecture/backend-domain.md), which owns the FastAPI API, database writes, payouts, runs, and rounds;
- the [agent service domain](architecture/agent-service-domain.md), which orchestrates dispatches, evaluations, claim resumes, and improvement rounds;
- and the [dashboard domain](architecture/dashboard-domain.md), which renders the authenticated React UI and drives backend actions from the browser.

The system overview in [Architecture Overview](architecture/overview.md) is the best place to start if you want the whole picture first.

## Repo entrypoints and the safest inspection order

When you are changing behavior, inspect code in this order:

1. `README.md` for the project’s intended runtime and workflow context.
2. `package.json` for the supported local commands and service entrypoints.
3. `pyproject.toml` for Python dependencies, test collection, and verification rules.
4. `backend/main.py` for backend routes, state transitions, and startup seeding.
5. `agent/service.py` for orchestration, concurrency gating, and resume behavior.
6. `dashboard/src/App.tsx` and the page modules it routes to for UI flow and session gating.

That order keeps you aligned with the repo’s own runtime boundaries before you dive into narrower helpers or tests.

## Main local commands

The root `package.json` defines the standard developer commands:

- `npm run dev` starts the backend, agent, and dashboard together.
- `npm run dev:backend` runs `backend.main:app` with reload support.
- `npm run dev:agent` runs `agent.service:app` on port `8002` with reload support.
- `npm run dev:dashboard` starts the Vite dashboard.
- `npm run seed` seeds the backend database.
- `npm run check:python` runs Python formatting, linting, type checking, and tests.
- `npm run check:ts` runs the dashboard and browser-side checks.
- `npm run e2e` runs the Playwright suite.
- `npm run check` runs the full verification stack.

For a fuller description of local workflows and environment expectations, see [Development and Verification](operations/development-and-verification.md).

## Domain navigation map

### Architecture

- [Architecture Overview](architecture/overview.md)
- [Backend Domain](architecture/backend-domain.md)
- [Agent Service Domain](architecture/agent-service-domain.md)
- [Dashboard Domain](architecture/dashboard-domain.md)

### Concepts

- [State and Data Model](concepts/state-and-data-model.md)

### Integrations

- [LangGraph and Checkpointing](integrations/langgraph-and-checkpoints.md)
- [Supabase and External Services](integrations/supabase-and-storage.md)

### Workflows

- [Request Lifecycle](workflows/request-lifecycle.md)
- [Agent Dispatch and Improvement Workflow](workflows/agent-dispatch-and-improvement.md)
- [User and Handler Flows](workflows/user-and-handler-flows.md)

### Operations

- [Development and Verification](operations/development-and-verification.md)
- [Runtime and Deployment](operations/runtime-and-deployment.md)

### Testing

- [Agent Tests](testing/agent-tests.md)
- [Backend Tests](testing/backend-tests.md)
- [Dashboard Tests](testing/dashboard-tests.md)

## How to choose the right page

- If you are tracing API behavior, start with [Backend Domain](architecture/backend-domain.md) and then follow the related workflow page.
- If you are changing dispatch, evaluation, or improvement orchestration, start with [Agent Service Domain](architecture/agent-service-domain.md) and then check the workflow and integration pages.
- If you are changing navigation, session gating, or authenticated browser flows, start with [Dashboard Domain](architecture/dashboard-domain.md) and then review the dashboard tests.
- If you are planning a cross-cutting change, read [Architecture Overview](architecture/overview.md) first, then the relevant domain page, then the matching workflow and test pages.

## Safe first-change paths

The safest first changes are usually narrow and local to the owning layer:

- backend validation, persistence, or API shape changes belong in the backend domain;
- dispatch, evaluation, resume, or round orchestration changes belong in the agent service domain;
- route composition, session gating, and API client behavior belong in the dashboard domain;
- environment, startup, and deployment questions belong in the operations pages;
- and behavior that spans multiple layers should be traced through the workflow pages before editing code.

If you are unsure where a behavior lives, start with [Architecture Overview](architecture/overview.md), then open the most specific domain page before making a change.
