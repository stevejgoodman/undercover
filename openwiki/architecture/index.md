# Files

- [Agent Service Domain](agent-service-domain.md) - Runtime orchestration for the agent-side FastAPI service, including one-at-a-time gating, background dispatch and improvement work, restart handling, and the distinction between dispatcher runs and improver rounds.
- [Backend Domain](backend-domain.md) - FastAPI backend surface for claims, policies, documents, payouts, runs, and rounds, including the shared helpers that enforce 404 and 409 behavior and the startup seed path.
- [Dashboard Domain](dashboard-domain.md) - React dashboard routing, session gating, and Supabase-backed API access for queue, claims, scoreboard, evaluations, configuration, improvement, and settings workflows.
- [Architecture Overview](overview.md) - Small runtime map of the backend API, agent service, dashboard UI, persistent state, and external integrations, with the trust and process boundaries that matter for safe changes and debugging.
