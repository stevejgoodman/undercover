# Code standards

## General

1. Keep it simple, do not overcomplicate.
2. Comments only when necessary.
3. Be concise: a short README and no emojis.
4. IMPORTANT: avoid overly defensive code. Handle exceptions only when necessary.
5. Use uv: ALWAYS `uv run`, NEVER `python3`.
6. TypeScript: strict mode, never `any`.

## Structure

7. One way to do each thing. The claim agent and the dispatcher reach the backend only through `agent/api.py`, the improver and its rounds only through `agent/improver_api.py`, and the dashboard only through `dashboard/src/api.ts`, each with one function per backend operation, named after it; the agent's two send their requests through `agent/client.py`, which holds the base URL. The dashboard reaches Supabase Auth only through `dashboard/src/supabase.ts`. The backend reaches the agent's service only through `backend/agent_service.py`, Supabase Auth's keys only through `backend/auth.py` and the judge only through `backend/judge.py`. The base URL and each path are written once, there, and no other module builds a URL or sends a request.
8. Each module has one job, and its name says what it is. A module uses another through what that module is for, and never borrows its helpers. A helper two modules need goes in a module of its own. No circular imports. Tests follow the same rule: shared test helpers live in their own module, never in another test file.
9. Write a literal once. A URL, a path, a status or a message used in more than one place is named once, in the module that owns it.
10. Use the framework's own way before writing your own: FastAPI dependencies and models, LangChain's `context_schema` with `ToolRuntime` for what a tool needs to know, LangGraph's `StateGraph`, `ToolNode`, `interrupt()` and checkpointer for the claim agent, LangGraph's `Send`, `max_concurrency` and `RetryPolicy` for the dispatcher, SQLAlchemy Core for the database, React hooks and shared components. Check the documentation for the installed version.
11. A function does one job. Split one that mixes levels of detail, such as setting up a run, driving the agent and recording the result.
12. When you extend code, bring it up to these standards first. Never copy a pattern they rule out.

## The agent

13. The agent has six parts, kept apart. `api.py` is the backend's API for the claim agent, with nothing that reads the scores or the handlers' decisions. `tools.py` holds every tool and the context and state the tools read. `harness.py` builds and runs the claim agent, and the claim graph's nodes do what middleware would. `dispatcher.py` works a dispatch or an evaluation with no model, and reaches the claim agent only through the harness's one function, `work_in_run`. `improver.py` is the improver, a LangChain agent with its tools and middleware, which reaches the backend through `improver_api.py` and works its evaluations only through the dispatcher. `service.py` is the agent's service: it receives the backend's calls and hands them to the dispatcher, the harness or the improver. Rules about claims, payments, rounds, spending and keeping a version are enforced by the backend, whatever the agent does.
14. Instructions give an agent its goal, what it has to work from and what done looks like. They don't script its steps: it plans those itself. Anything that must always happen, or happen in a fixed order, is done by the code.
