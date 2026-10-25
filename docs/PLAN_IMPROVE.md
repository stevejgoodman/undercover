# Plan: an improver for the claim agent, and handlers who sign in

This plan builds what `docs/IMPROVE.md` asks for on top of the swarm, in six phases. Each phase leaves `npm run check` green and is committed before the next one starts.

SIDENOTE: For consistency with the course, please read `labs/week2day5.ipynb` and build the judge, the configuration's versions and the improver in the same style as the lab. Where the lab and this brief differ, follow the brief. Include this sidenote in your plan too.

When it's done, handlers sign in to the dashboard with Supabase Auth, and the backend checks the signed-in handler on every action. The claim agent's instructions, model and reasoning effort are one configuration, kept in versions, and every dispatch and evaluation records the version it used. Jev grades each explanation in an evaluation against the handler's reason. On a new Improvement page a senior handler starts a round: the improver, a LangChain agent following a recipe, reads the results, proposes a new version, waits for a handler's approval, asks for its evaluations, and the backend keeps it or rolls it back by UnderCover's rule, all within the round's spending limit. Then the improver proposes a better recipe. A Settings page holds the business's numbers, and every page of the dashboard is brought up to the standard of enterprise software.

## Design

### Modules

The backend gains five modules and two routers, each with one job:

- `auth.py` (new): the signed-in handler. It reads `VITE_SUPABASE_URL` once, checks the bearer token against the project's public keys at `/auth/v1/.well-known/jwks.json` with PyJWT's `PyJWKClient`, the audience `authenticated` and the issuer, requiring an expiry and an email, and finds the handler by the token's email. It offers the FastAPI dependency `SignedIn`: 401 with no valid sign-in, 403 for a sign-in that isn't a handler's, and 503 when Supabase's keys can't be fetched. Phase 2 adds `Senior`, a handler who can sign off payouts over the limit (403 otherwise, with one message for the backend and the dashboard).
- `judge.py` (new): Jev, `typesafe/jev-1.13`, through OpenRouter's Decisions endpoint with the `openrouter` package and the lab's three questions. It reads the endpoint's origin once from `OPENROUTER_URL` (default `https://openrouter.ai`) and passes it as `server_url` on each call, with `timeout_ms=10_000` and retries off. The call is written once, here. It grades a list of claims in parallel and returns each one's grade, or "not graded".
- `verdict.py` (new): UnderCover's rule as plain functions, like `scoring.py`: which measures got better by more than their noise, which got worse by more than their tolerance, and whether a version is kept. It uses `models.py` and nothing else.
- `diffs.py` (new): the lines that change between two texts, with Python's `difflib` as in the lab, as a list of added, removed and unchanged lines. Both the configuration and the recipe show their diffs through it.
- `new_runs.py` (new): recording a new run, a dispatch or an evaluation with its copies, which `runs.py` and `rounds.py` both do. It moves out of `runs.py`.
- `improver_view.py` (new): what the improver reads in a round, built for `read_results`.
- `spending.py` (new): what a round has spent (the improver's model calls, its evaluations' model calls and the judge's calls on them), what's left of its limit, and an evaluation's estimate. Three modules need it: the rounds router, `runs.py` (an evaluation cut short) and `main.py` (no new claim starts in a round that has spent its limit), so it has a module of its own.
- `configuration.py` (new `APIRouter`): the claim agent's versions: the current version, each version with its held-out scores and its diff from the one before, and the one operation the claim agent uses to fetch a version, which holds no scores.
- `rounds.py` (new `APIRouter`): rounds, proposals and the recipe's versions: starting, stopping, approving and rejecting for the dashboard; the improver's view, its proposals, its evaluations and the verdict for the agent's service, under `/api/runs/rounds`.
- `platform_settings.py` (new `APIRouter`): the settings and their changes, and the models allowed. Named so it doesn't clash with the `settings` table.

Changed: `database.py` gains the new tables and seeding (below); `models.py` the new shapes; `runs.py` records the version on a run, grades an evaluation as it finishes and adds the grade to the measures; `scoring.py` adds the average grade; `main.py` takes the approval limit from the current settings, signs off as the signed-in handler, refuses a copy's start once its round has spent its limit, and loses `get_instructions`; `agent_service.py` gains the calls to start a round and pass on a decision on a proposal. `backend/instructions/` gains `recipe.md`, the lab's first recipe, and `improver.md`, the improver's instructions, which wrap the recipe.

Inside the backend: `main`, `runs`, `configuration`, `rounds` and `platform_settings` each use `dependencies`, `auth`, `database` and `models` as they need; `runs` uses `judge`, `scoring` and `spending`; `rounds` uses `verdict`, `diffs`, `spending` and `agent_service`; `configuration` uses `diffs` and `scoring`. No router imports another router.

The agent gains a sixth part, the improver, and its own client:

- `improver.py` (new): the improver, a LangChain `create_agent` on GPT-6 Luna at medium reasoning effort, with the lab's four tools, `read_results`, `propose_change`, `run_evaluation` and `propose_recipe`, its middleware and its context. `work_round` runs a round's first evaluations and the improver up to its first pause; `carry_on_round` resumes it after a handler's decision. It uses `dispatcher.work_run` for evaluations and `improver_api` for the backend.
- `improver_api.py` (new): the improver's way to the backend, one function per operation it uses (its view, proposals, evaluations, the verdict, the round's stage and its model calls). The claim agent's `api.py` gains nothing that reaches the scores or the handlers' decisions, so `test_the_agent_cant_read_the_scoreboard` still holds.
- `client.py` (new): the one httpx client for the backend, with its address, and `Refused`, which both APIs send through. It moves out of `api.py`.
- `models.py` (new): the chat models the agent's parts run on through OpenRouter, the claim agent's from a version and the improver's, moved out of the harness so the improver doesn't borrow the harness's helper.
- `harness.py`: `claim_agents_of(version, pool)` builds the claim agents of a version: its model and reasoning effort, or `MODEL_NAME` at `default` when that is set, and its instructions from `api.get_agent_version`. `claim_config` tags a claim's trace with its run and, in a round, the round.
- `service.py`: the one-run rule now also covers a round's stretches of work, and a refusal names what is running. It gains `start_round` and `decide_proposal`, and on startup stops any round that was working, leaving one waiting for a handler.
- `api.py`: `get_instructions` gives way to `get_agent_version` and `get_current_version`; `create_dispatch` and `create_evaluation` take the version.

Inside the agent: `service` uses `improver`, `dispatcher`, `harness` and `api`; `improver` uses `dispatcher`, `harness`, `models` and `improver_api`; `harness` uses `models`, `tools` and `api`; `dispatcher` uses `harness` and `api`; `api` and `improver_api` use `client`. No cycles, and only `improver` uses `improver_api`: the service asks the improver to create a round, record a decision and stop working rounds. A round whose work fails is stopped with the error as its reason.

The dashboard gains `supabase.ts`, its only way to Supabase, with one function for each thing it does (sign in, sign out, follow the session, the access token); `session.ts`, the signed-in handler as a React context, and `components/SessionGate.tsx`, which shows the sign-in page to anyone not signed in; a sign-in page; the Configuration page in place of the Instructions page; the Improvement and Settings pages; and shared components for the page header, status badges, the diff, the confirmation dialog, tables, buttons and the loading, empty and error states. `api.ts` sends the session's access token with each request.

### How a round works

1. A senior handler presses Start a round on the Improvement page and confirms in the dashboard's dialog. The backend checks the handler and passes the start to the agent's service, with the handler, through `agent_service.py`.
2. The service refuses while a dispatch, an evaluation or another round's stretch of work is running, or while a round is open, saying which. Otherwise it answers 202 and, in the background, asks the backend to create the round. The backend snapshots the current settings, the models allowed and the newest recipe onto it, and gives it a number and a new thread id.
3. **First evaluations.** If the current version doesn't yet have one whole-set evaluation of the evaluation set and two of the held-out set from rounds, the service runs the ones missing, one at a time, through the dispatcher, with the round's agents at once. The stage reads "First evaluations, 1 of 3", and so on. The backend then records the version's held-out scores on the round as its scores before.
4. **The improver works.** The service invokes the improver on the round's thread. It calls `read_results` and proposes a change with `propose_change`. `HumanInTheLoopMiddleware` pauses before the tool runs; the service records the proposal with the backend, with the stage "A change is waiting for approval", and lets go of the one-run rule.
5. **A handler decides.** On the Improvement page the handler sees the diff of the instructions, the model and reasoning effort before and after, and the reason, and approves or rejects with a reason, confirming in the dialog. The backend checks the handler and the proposal and passes the decision to the service, which refuses it while something else runs. Otherwise the service records the decision and the handler with the backend, then resumes the improver. On approval `propose_change` runs and records the new version, untried. On rejection the improver reads the handler's reason and may propose again.
6. **Evaluations and the verdict.** The improver calls `run_evaluation`. The backend refuses any evaluation likely to cost more than what's left of the limit. The service runs the new version once on the evaluation set and twice on the held-out set, with the stage "Evaluations, 1 of 3" and so on, then asks the backend for the verdict. The backend averages the two held-out runs, applies the rule against the scores before, records the verdict and why, and makes a kept version current. The improver reads the verdict.
7. **The recipe.** The improver proposes a new recipe with `propose_recipe`, which pauses for a handler in the same way, shown as a diff. On approval it becomes the newest recipe, for the next round.
8. The improver ends its turn, and the service marks the round finished. A round in which the improver proposes nothing finishes with no version tried.

A handler can stop an open round at any point. The backend marks it stopped and then refuses anything the round records; the service starts no more claims or model calls for it, and lets go of the one-run rule when the work in hand ends. A round stopped before its verdict leaves the current version as it was, and the version it was trying is rolled back; one stopped after it keeps the verdict. A round whose first evaluations never all finish, for want of money or a stop, finishes with no version tried and says why. A restart stops a round that was working and keeps one waiting for a handler, whose improver resumes from its checkpoint.

### The configuration's versions

A version, in `agent_versions`:

| Field | Meaning |
| --- | --- |
| `version` | 1, 2, 3 and on |
| `instructions` | The claim agent's instructions, without the documents' contents, which are added when the claim agent fetches it |
| `model`, `reasoning_effort` | As the claim agent runs it |
| `based_on` | The version it was proposed against, which its diff is from; none for version 1 |
| `change` | What changed, in a line: "Instructions", "Model", "Reasoning effort" or a mix, worked out by the backend |
| `reason` | Why: "The claim agent as it was on Week 2 Day 4" for version 1, or the improver's reason |
| `proposed_by` | "UnderCover" for version 1, or the round, such as "The improver, round 2" |
| `approved_by`, `approved_at` | The handler who approved the proposal, and when; the seed for version 1 |
| `round_id` | The round that tried it, or none for version 1 |
| `verdict` | `kept` or `rolled_back`, or none while it is tried; version 1 is seeded `kept` |
| `created_at` | When it was recorded |

The current version is the newest kept one; nothing else can be, since a version is only kept against the version current when its round started. Seeding makes version 1 from `backend/instructions/claim.md`, with `openai/gpt-6-luna` at `low`.

A version's scores are the averages of the finished, whole-set evaluations that rounds ran on it, on each set. Evaluations started on the Scoreboard and tiny ones don't count. `runs` gains `version` and `round_id`.

- A dispatch and an evaluation started on the Scoreboard use the current version: the service asks for it with `get_current_version` and creates the run with it.
- An evaluation in a round uses the version under test, which `create_round_evaluation` records.
- The service builds each run's claim agents from its version: `model(version)` and the instructions from `get_agent_version`, which returns the instructions followed by the documents' contents, the model and the reasoning effort, and nothing else.
- With `MODEL_NAME` set, the claim agent and the improver use that model at reasoning effort `default`, which is then the only model allowed, at a price of 0. A reasoning effort that isn't set is recorded as `default`, never `none`, which Luna also has as a real level.

### The recipe's versions

`recipes`: `version`, `recipe`, `reason`, `proposed_by`, `approved_by`, `approved_at` and `round_id`. Seeding makes version 1 from `backend/instructions/recipe.md`, the lab's first recipe word for word. A round follows the newest recipe at its start. The recipe is data the improver follows, so it may be a list of steps; the instructions around it, `backend/instructions/improver.md`, are written as goals (rule 14).

### The judge

The lab's judge, moved into the backend because the backend holds the handlers' decisions:

- The state is `{"handler": {decision, reason, reference}, "agent": {decision, reason, section}}`, and the questions are the lab's `grade` (a `score` over F, C, B and A with the lab's rubric), `same_grounds` and `same_section` (both `noul`), with the instructions naming the agent's `reason` and `section` in place of the lab's `rationale`.
- The score is Jev's `score`, from 0 to 3. The letter is the level with the highest probability, `GRADES[int(max(probabilities, key=probabilities.get))]`, never the score rounded. The two checks are kept as probabilities and shown as yes when above one half.
- `finish_run` on an evaluation grades its claims in parallel, in a thread pool, each call timing out after 10 seconds with the SDK's retries off (`RetryConfig("none", ...)`), so finishing stays well under the agent's 30 seconds. A copy the agent didn't decide gets an F with a score of 0 without asking the judge. A call that fails or times out leaves its claim not graded, out of the average.
- `grades`: one row per graded copy, with its score, letter, the two checks and the call's cost from the response's `usage.cost`. The judge's cost is recorded with the evaluation, apart from the claim agent's cost.
- Seeding stores each label's `reason` and `reference` in `handler_decisions`, from `data/evals/`.
- With `MODEL_NAME` set, the judge isn't called, and every claim shows as not graded.
- The judge is asked with no database connection held: `finish_run` reads the copies in one short transaction, grades them, then records the grades and finishes the run in a second, which refuses a run stopped meanwhile. An answer that isn't a grade leaves its claim ungraded, and the whole batch stops waiting after 15 seconds.
- An evaluation whose judge calls all fail still grades its undecided copies F, so its grade is 0 rather than none, and the rule reads it as missing the objectives. A version's grade averages its runs only when every one of them has a grade; otherwise it has none and is rolled back.
- The tests replace the judge's client with one on httpx's `MockTransport`, so they check the request the SDK sends and never reach OpenRouter. The end-to-end tests point `OPENROUTER_URL` at a stand-in.

`Measures` gains `grade` (the average score, or none when no claim was graded) and `judge_cost`. A scored claim gains its score, letter and two checks, or none when it wasn't graded.

### The improver

`agent/improver.py`, in the lab's style: `create_agent` with the four tools, `HumanInTheLoopMiddleware` and a checkpointer.

- **Model:** `ChatOpenAI` on `openai/gpt-6-luna` at `medium`, with a 300 second timeout and 5 retries as in the lab, and `parallel_tool_calls=False` in its model settings, so a reply never holds two proposals. With `MODEL_NAME`, that model at `default`.
- **Context:** `ImproverContext`, passed with `context=`: the round as the backend has it (its id, number, settings and models allowed), and how to work an evaluation, which the service binds to its pool.
- **Middleware**, in order:
  - `ModelCallLimitMiddleware(thread_limit=IMPROVER_MODEL_CALLS, exit_behavior="error")`, so a round's model calls are capped across its stretches, as the claim agent's are; each round has a thread of its own.
  - A `before_model` hook that stops the improver when the backend says its round is no longer open, so a stopped round makes no new model calls.
  - A `wrap_model_call` hook that records each model call's tokens and `usage.cost` with the round, once per call, through `improver_api.record_round_model_call`. The backend refuses it for a stopped round, which ends the improver.
  - A `wrap_tool_call` hook that answers the improver with the backend's refusal of a tool, such as an evaluation the round can't afford, rather than ending its round.
  - `HumanInTheLoopMiddleware` on `propose_change` and `propose_recipe`, allowing approve and reject. `propose_change` has a `when` that interrupts only a proposal within the models allowed in a round that hasn't tried a version, so any other runs at once and the tool answers the improver, without reaching a handler. The backend refuses such a version too. A second `run_evaluation` after the verdict is answered with the verdict.
- **Checkpointer:** a `PostgresSaver` of its own on the service's pool, saving with `durability="sync"`. Each round has a new thread id, so a reseed never meets an old round's checkpoints, and a round waiting for approval survives a restart. The tests use an `InMemorySaver`.
- **Tools**, with the lab's names, since the recipe names them:
  - `read_results`: the backend's view for the round, as JSON. It holds the current version and its scores on both sets; from the current version's latest round evaluation of the evaluation set, the wrong claims and the five right ones with the lowest grades, each with the claim's summary, the agent's decision, payout, reason and section, the handler's decision, payout, reason and reference, and the judge's score, letter and two checks; the earlier rounds; the objectives, the noise, the tolerance and the rule; what's left of the spending limit; and the models allowed with their reasoning efforts and prices. From the held-out set it holds the scores only.
  - `propose_change(instructions, model, reasoning_effort, reason)`: records the approved version, untried, and says to run the evaluation next.
  - `run_evaluation()`: asks the backend for each of the three evaluations in turn, works each through the dispatcher in a fresh `contextvars.Context`, as the harness runs each claim graph, since a graph compiled without a checkpointer otherwise saves into its caller's thread, then asks the backend for the verdict and returns it with the scores. A refused evaluation ends the tries, and the verdict rolls the version back.
  - `propose_recipe(recipe, reason)`: records the approved recipe.
- **Instructions:** `improver.md` gives the improver its goal (a better version: more accurate, closer to the handlers' reasoning, cheaper or faster, never below the objectives), what it has to work from (the claim agent works from its instructions with the contents of the policy wording and the claims manual, the claim, the policy and the customer's earlier claims, and its tools for searching and reading sections and working out a payout), that a change never names a claim, and what done looks like, with the recipe beneath to follow. The backend serves it with the round's recipe in place.
- **Langfuse:** the improver's work in a round goes in one session, `Round 2:<round_id>`, with a trace for each stretch, and each claim of the round's evaluations is tagged with its run and the round.

### Rounds and proposals

`rounds`:

| Field | Meaning |
| --- | --- |
| `round_id`, `number` | A UUID, and 1, 2, 3 and on |
| `thread_id` | The improver's thread, new for each round |
| `recipe_version` | The recipe it followed |
| `settings`, `models_allowed` | Snapshots of the settings and the models allowed at its start, which the round works to |
| `stage` | `first_evaluations`, `improving`, `waiting_for_change`, `evaluations`, `verdict`, `waiting_for_recipe`, `finished` or `stopped` |
| `version_before`, `version_tried` | The current version at its start, and the version it tried, if any |
| `reason` | The improver's reason for the version it tried |
| `scores_before`, `scores_after` | The held-out averages before and after |
| `verdict`, `why` | `kept` or `rolled_back`, and why, as the rule says it |
| `started_by`, `started_at`, `stopped_by`, `finished_at` | Who started it and when; who stopped it, or "A restart"; when it finished or stopped |

Its cost is worked out from the records, never stored. Its stage's "1, 2 or 3 of 3" counts the round's evaluations for that stage.

`proposals`: `proposal_id`, `round_id`, `kind` (`change` or `recipe`), what the improver proposed (instructions, model, reasoning effort and reason, or recipe and reason), the version or recipe it was proposed against, `status` (`waiting`, `approved` or `rejected`), `decided_by`, `decided_at` and the rejection's reason. A round has at most one waiting proposal, since each service write is taken only in the stage it belongs to: a change only while the improver works and before a version is tried, a version's evaluations only before its verdict and each set no more often than it needs, and the verdict once, with no evaluation running. An approved proposal makes one version or recipe, never two. Finishing or stopping a round rolls back a version it tried with no verdict, and rejects a proposal still waiting.

`round_model_calls`: the improver's tokens and cost for each model call, with its round.

### The rule

`verdict.py`, as the lab's `compare` and `keep_or_roll_back`, over `accuracy`, `grade`, `model_cost_per_claim` and `seconds_per_claim`:

- Accuracy and the grade are compared as differences; cost and time as fractions of the old value, so 0.15 is 15%.
- A version is kept when it meets the objectives (floors on held-out accuracy and the grade), at least one measure improves by more than its noise and none gets worse by more than its tolerance. The reason comes out as in the lab: "it missed the objectives on grade", "accuracy got worse", "no measure improved by more than the noise", "accuracy and grade improved".
- A run with no graded claims has no grade, and a version without a grade is rolled back ("it has no grade"). So is a version whose evaluations were stopped, or that the round couldn't afford to evaluate.

### Spending

- A round's spending covers the improver's model calls, every evaluation in the round, its first ones included, and the judge's calls on them.
- An evaluation's estimate is its claims times the highest cost per claim, model and judge together, seen so far for its model over finished evaluations. For a model with no runs yet, it is the current model's, scaled by the larger of the ratios of their input and output prices. With no runs on any model, the estimate is 0, so a round's first evaluation can start, and the claim check below holds it to the limit.
- `create_round_evaluation` refuses an evaluation whose estimate is more than what's left, with 402 and both amounts.
- Once a round has spent its limit, `start_claim` refuses a copy in its evaluations, so no new claim starts. `finish_run` marks an evaluation stopped when its round has spent its limit and a copy never started. A stopped evaluation's version is rolled back.
- The credit limit on the OpenRouter key, set at the end of the lab, covers everything as well.

### Settings

The settings are versioned rows in `settings`, the newest the current one, each with `changed_by` and `changed_at`:

- `payout_approval_limit`, seeded from `data/company.json`: $1,000
- `objectives`: `{"accuracy": 0.6, "grade": 1.0}`
- `noise`: `{"accuracy": 0.1, "grade": 0.15, "model_cost_per_claim": 0.15, "seconds_per_claim": 0.15}`
- `tolerance`: `{"accuracy": 0.1, "grade": 0.15, "model_cost_per_claim": 1.0, "seconds_per_claim": 0.25}`
- `spending_limit`: $0.50 a round
- `agents`: 25 claim agents at once in the improver's evaluations

All but the limit come from a new `data/improvement.json`. The plans move to a `plans` table of their own. `data/models.json` holds the models allowed, with their reasoning efforts and prices as numbers, in dollars per million input and output tokens: the lab's three, with Luna at `low` and `medium` only (`none` is left out, since the product records an unset effort as `default`). Every part of the product reads the settings from the database, a new approval limit applies to the decisions recorded after it, and a round keeps the settings it started with. The appearance is kept in the browser's `localStorage` alone.

### Sign-in

- The dashboard signs in with `@supabase/supabase-js` and `signInWithPassword`, reading `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`. There's no sign-up. Every page needs a signed-in handler; the sign-in page asks for an email address and password. The header shows the handler's name and role with Sign out.
- `api.ts` sends the session's access token as `Authorization: Bearer` on each request, and a 401 sends the handler back to sign in.
- `auth.py` checks the token as above. No Supabase secret is needed, since the project signs with asymmetric keys. Seeding stores each handler's email, and `data/handlers.json` sets `can_approve_over_limit` to `false` for Marcus Oyelaran and Priya Raman.
- `get_signed_in_handler` (`GET /api/handlers/me`) tells the dashboard who is signed in and what they can do. `list_handlers` goes: nothing uses it since the sign-off form lost its list, and it would show anyone the handlers' sign-in emails.
- `SignedIn` guards `start_dispatch`, `start_evaluation` and `sign_off_claim`; `Senior` guards `start_round`, `stop_round`, `decide_proposal` and `update_settings`, and `sign_off_claim` still refuses a handler who can't sign off over the limit. The service's own writes under `/api/runs` stay open until Week 3.
- A sign-off records the signed-in handler; `SignOffRequest` and the handler list in `SignOffForm.tsx` go.
- Vite reads `.env` from the repo root for `npm run dev` only: `vite.config.ts` sets `envDir` to the root in development mode, and the end-to-end dashboard runs in an `e2e` mode with its own values. Vitest and pytest set their own.

### API

New operations, each with an `operation_id`, a one-line docstring and no optional inputs:

| Operation | Method and path | Who | What |
| --- | --- | --- | --- |
| `get_signed_in_handler` | GET `/api/handlers/me` | signed in | The handler and what they can do |
| `get_current_version` | GET `/api/configuration/current` | open | The current version, without scores |
| `get_agent_version` | GET `/api/configuration/versions/{version}/agent` | open | A version's instructions with the documents' contents, model and effort; no scores |
| `list_versions` | GET `/api/configuration/versions` | open | Every version, newest first, with its held-out and evaluation-set scores |
| `get_version` | GET `/api/configuration/versions/{version}` | open | A version with its scores and its diff from the one before |
| `get_settings` | GET `/api/settings` | open | The current settings, who changed them and when, and the changes so far |
| `update_settings` | PUT `/api/settings` | senior | A new version of the settings |
| `list_models` | GET `/api/models` | open | The models allowed, with their efforts and prices |
| `list_rounds` | GET `/api/rounds` | open | Every round, newest first, with its stage, scores, verdict and cost |
| `get_round` | GET `/api/rounds/{round_id}` | open | A round with its stage, its waiting proposal with its diffs, and its proposals so far |
| `start_round` | POST `/api/rounds` | senior | Ask the service to start a round; 202 |
| `stop_round` | POST `/api/rounds/{round_id}/stop` | senior | Mark an open round stopped |
| `decide_proposal` | POST `/api/rounds/{round_id}/proposals/{proposal_id}/decision` | senior | Pass an approval or a rejection with its reason to the service; 202 |
| `list_recipes` | GET `/api/recipes` | open | The recipe's versions with their diffs |
| `create_round` | POST `/api/runs/rounds` | service | Record a new round with its snapshots |
| `get_improver_instructions` | GET `/api/runs/rounds/{round_id}/instructions` | service | `improver.md` with the round's recipe |
| `read_results` | GET `/api/runs/rounds/{round_id}/results` | service | The improver's view |
| `start_improving` | POST `/api/runs/rounds/{round_id}/improving` | service | Hand the round to the improver once the current version has its first evaluations, recording its held-out scores before |
| `record_change_proposal` | POST `/api/runs/rounds/{round_id}/proposals/changes` | service | A change waiting for a handler, refused outside the models allowed |
| `record_recipe_proposal` | POST `/api/runs/rounds/{round_id}/proposals/recipes` | service | A recipe waiting for a handler |
| `record_proposal_decision` | POST `/api/runs/rounds/{round_id}/proposals/{proposal_id}/review` | service | The handler's decision |
| `create_version` | POST `/api/runs/rounds/{round_id}/versions` | service | The approved change as a version, untried, from the proposal's id |
| `create_recipe` | POST `/api/runs/rounds/{round_id}/recipes` | service | The approved recipe, from the proposal's id |
| `create_round_evaluation` | POST `/api/runs/rounds/{round_id}/evaluations` | service | An evaluation of a set on a version, refused over the limit |
| `record_verdict` | POST `/api/runs/rounds/{round_id}/verdict` | service | Keep or roll back by the rule |
| `record_round_model_call` | POST `/api/runs/rounds/{round_id}/model-calls` | service | One improver model call's tokens and cost |
| `finish_round` | POST `/api/runs/rounds/{round_id}/finish` | service | Mark a round finished |
| `stop_working_rounds` | POST `/api/runs/rounds/stop` | service | Stop the rounds that were working, as the service does when it starts |

Every service write under `/api/runs/rounds/{round_id}` is refused with 409 once the round is stopped. Changed: `create_dispatch` and `create_evaluation` take `version`; `finish_run` grades an evaluation, leaves a stopped run stopped, and stops an evaluation its round's limit cut short; `start_claim` refuses a copy in an evaluation that isn't running or whose round has spent its limit; `sign_off_claim` takes no body; `get_instructions` goes. The agent's service gains `start_round` (POST `/api/rounds`, body `{handler}`) and `decide_proposal` (POST `/api/rounds/{round_id}/proposals/{proposal_id}/decision`, body `{decision, reason, handler}`), both 202 or 409.

### One thing at a time

The `threading.Lock` stays in `agent/service.py`, with a description of what holds it, such as "Dispatch #4 is running", "Evaluation #5 is running" or "Round 2 is running", which every refusal gives. A round's stretch of work holds the lock from its start or its resume until its next pause or its end, and its evaluations run inside it, through the dispatcher in the same process, so they are never refused. While a round waits for a handler, dispatches and evaluations can run, but a new round can't start until it ends.

### Dashboard

Every page is built from the same parts, styled to `docs/BRAND.md` in light and dark mode:

- `PageHeader`: the title, a line on what the page is for, and the page's main action on the right.
- `StatusBadge`: a color and a word, for claims, runs, rounds, verdicts and proposals.
- `DiffView`: the lines added in Sea Green and removed in Raspberry, each with a plus or minus too, so color is never the only sign, in JetBrains Mono, with unchanged lines dimmed and long runs of them folded.
- `ConfirmDialog`: the dashboard's own dialog on the `<dialog>` element, before any action that changes the agent or a setting.
- `useAction`, the one way a page sends a request that does something and shows its refusal, which `ActionForm` uses too; and `permissions.ts`, the one owner of what a handler who can't sign off over the limit is told.
- `DataTable` styles: numbers right-aligned in JetBrains Mono with their units, fixed column widths so refreshes don't shift them.
- `LoadingState`, `EmptyState` and `ErrorState`, each saying what to do next. Panels keep their height while they refresh, and data stays on screen until the new data arrives.
- One button style in primary, secondary and danger forms.

Pages:

- **Sign in**: shown in place of whatever page was asked for, until a handler signs in: email and password, and a plain error.
- **Header:** the brand, the navigation (Queue, Scoreboard, Configuration, Improvement, Settings) with the current page marked, and who is signed in with Sign out.
- **Configuration** (`/configuration`), in place of Instructions: the current version (its model, effort, reason, who proposed and approved it, and its instructions), and every version with its held-out scores and verdict, each opening to its diff from the one before.
- **Improvement** (`/improvement`): Start a round and Stop the round; the open round's stage as a stepper (first evaluations 1 to 3 of 3, the improver working, a change waiting, evaluations 1 to 3 of 3, the verdict, a recipe waiting, finished or stopped); a waiting proposal with its diff, the model and effort before and after, the reason, and Approve and Reject with a reason; the rounds so far, newest first, with recipe, version tried, accuracy and grade before and after, verdict, why and cost; an SVG chart of the held-out accuracy and grade of each version tried, with no new library; and the recipe's versions with their diffs.
- **Settings** (`/settings`): the settings, editable by a senior handler with a confirmation, each with who last changed it and when; the models allowed, read only; and the appearance, light, dark or the same as the computer, remembered by the browser.
- Where a handler can't act, the page says what they can't do and why, such as "Marcus Oyelaran can't sign off payouts over $1,000.00. A senior handler can.", and the action's button is not offered.
- The Scoreboard adds the average grade; an evaluation's page shows each claim's letter, score and the two checks as yes or no, or "Not graded", and the judge's cost.
- The theme: `styles.css` gives each color for light and dark with `light-dark()`, and `data-theme` on the page sets `color-scheme` to light or dark, overriding the computer's choice.

### End-to-end tests

`playwright.config.ts` starts two more stand-ins beside the agent's: `e2e/auth_stand_in.ts`, which signs tokens with an ES256 key of its own, serves its public keys at `/auth/v1/.well-known/jwks.json`, answers `signInWithPassword` for the three handlers and the browser's cross-origin checks; and `e2e/judge_stand_in.ts`, which answers the Decisions endpoint with fixed grades. The backend gets `VITE_SUPABASE_URL` and `OPENROUTER_URL` pointing at them, and the dashboard runs in `e2e` mode with the stand-in's address. Every spec signs in first, through a shared helper in `e2e/`. The agent's stand-in also accepts round starts and decisions.

### Following the lab

As in the lab: the judge's state, its three questions and rubric, the score as the grade and the most likely level as its letter; a configuration of instructions, model and reasoning effort, with version 1 as the agent before; the lab's objectives, noise, tolerance and budget, and its models allowed; `compare` and `keep_or_roll_back`, with cost and time as fractions and accuracy and the grade as differences; the improver as `create_agent` with the four tools by the lab's names, `HumanInTheLoopMiddleware` on the two propose tools with approve and reject, and Luna at medium; the first recipe word for word; one evaluation-set run and two held-out runs for a new version, averaged; the improver seeing the held-out scores only; the diff with `difflib`; one Langfuse session per round; and resuming with `Command(resume={"decisions": [...]})`.

Where the brief differs, we follow the brief:

- The judge runs in the backend, each call capped at 10 seconds with no retries, and an undecided claim gets an F without a call.
- Versions, recipes, rounds and the scoreboard live in the database, not in lists in memory, and the backend applies the rule.
- The current version needs one evaluation-set run and two held-out runs from rounds before a round compares against it, and the round runs them first.
- The improver's checkpointer is a `PostgresSaver`, not an `InMemorySaver`, so a round waiting for approval survives a restart; and a handler's approval comes through the dashboard, not a notebook cell.
- A proposal outside the models allowed goes straight back to the improver, without a handler.
- The budget is a spending limit for each round, covering the improver's own calls too, and is a setting.
- The claim agent is the product's, with its tools for the manual, the history and the payout, so the improver's instructions say so; the lab's agent saw only the wording.
- The improver has `parallel_tool_calls=False` and a cap on its model calls.

### What goes

`get_instructions`, the Instructions page and `InstructionsPage.tsx`, `list_handlers`, `SignOffRequest` and the handler list in `SignOffForm.tsx`, the approval limit and plans in the single-row `settings` table, and `ALREADY_RUNNING`'s single message.

### Checked against the code standards

- Rule 7: the improver reaches the backend only through `agent/improver_api.py`, the dashboard reaches Supabase only through `dashboard/src/supabase.ts` and the backend only through `api.ts`, the backend reaches the service only through `agent_service.py`, and the judge's call and its address are written once, in `backend/judge.py`. Supabase's address is read once, in `backend/auth.py`. Rules 7 and 13 are updated for the improver, its client and the dashboard's Supabase client.
- Rule 8: the diff, the spending and the rule are modules of their own because more than one module needs them; no router imports another, and shared test helpers (a signed-in client, a stub judge, a round played out) live in their own modules.
- Rule 9: stages, verdicts, proposal kinds and decisions are `StrEnum`s in `models.py`; the refusal messages are named once.
- Rule 10: FastAPI dependencies for the signed-in handler, `create_agent` with `HumanInTheLoopMiddleware`, `ModelCallLimitMiddleware` and middleware hooks for the improver, LangGraph's checkpointer and `Command(resume=...)`, `PyJWKClient`, `difflib`, `supabase-js`, and the native `<dialog>`.
- Rule 11: `work_round` splits the first evaluations, the improver's stretch and recording the pause into functions of their own; `finish_run` calls the grading as one step.
- Rule 13: six parts, with the improver beside the claim agent and the dispatcher, reaching evaluations only through `dispatcher.work_run`. The backend enforces the spending limit, the models allowed, who may approve and the rule, whatever the improver does.
- Rule 14: the improver's instructions give its goal, what it has, and what done looks like; the recipe beneath is data.

### How the criteria are checked

"pytest" and "vitest" criteria are tests in `npm run check`, on a stub model, a stub judge and signed tokens from a test key. "Browser" criteria are checked through the Playwright MCP server with `npm run dev` running, signed in with `HANDLER_PASSWORD`. "Supabase MCP" criteria are read-only queries. In this build the Playwright MCP server isn't connected and the Supabase MCP server isn't authorized, so the browser checks run as Playwright scripts against `npm run dev`, with their screenshots read back, and the database checks as read-only SQL over `DATABASE_URL`. The live runs in Phase 6 use the real model, after one `npm run seed`.

## Phase 1: Handlers sign in

Sign-in first, so every later page is built signed in.

- [x] `uv add "pyjwt[crypto]"` puts PyJWT in the project's dependencies, and `npm install @supabase/supabase-js` in the dashboard's
- [x] `data/handlers.json` has `can_approve_over_limit: false` for Marcus Oyelaran and Priya Raman, and seeding stores each handler's email
- [x] pytest: a token signed with the test key, for Dana Whitfield's email and the audience `authenticated`, lets `start_dispatch`, `start_evaluation` and `sign_off_claim` through
- [x] pytest: each of those returns 401 with no token, a garbled, expired, unsigned or HS256 token, a token for another audience, signed with another key, or with no email, expiry or issuer, and 403 for a token for an email no handler has, and the agent's service is never asked. Supabase's keys out of reach give 503
- [x] pytest: `sign_off_claim` by Marcus Oyelaran returns 403 with "Marcus Oyelaran can't sign off payouts over $1,000.00", and by Dana Whitfield records her name and the time
- [x] pytest: `get_signed_in_handler` returns the handler and whether they can sign off over the limit
- [x] pytest: the service's writes under `/api/runs` still need no sign-in
- [x] `grep -rn "VITE_SUPABASE_URL\|jwks" backend --include=*.py` finds them only in `backend/auth.py`, and `grep -rn "supabase-js\|createClient" dashboard/src` only in `dashboard/src/supabase.ts`
- [x] vitest: with no session, every route shows the sign-in page; a session shows the page with the handler's name in the header; Sign out returns to sign-in; a 401 from the backend returns to sign-in
- [x] vitest: the sign-off form has no handler list and signs off as the signed-in handler; for a handler who can't sign off over the limit it says so and offers no button
- [x] vitest: every request from `api.ts` carries the session's token
- [x] e2e: the Auth stand-in serves its keys, signs in each handler and answers a preflight; every spec signs in through the shared helper; a sign-off as Dana Whitfield on the dashboard is recorded with her name
- [x] `npm run check` passes with `.env` moved out of the way, and `npm run dev`'s dashboard reads `VITE_SUPABASE_URL` from the root `.env`
- [x] Browser: signed in as Dana Whitfield with `HANDLER_PASSWORD`, the header shows her name and role; a wrong password shows a plain error; Sign out returns to sign-in
- [x] `npm run seed`, then a read-only query: `handlers` has an `email` column with the three addresses, and only Dana Whitfield can sign off over the limit
- [x] `npm run check` passes

## Phase 2: The configuration's versions and the Settings page

- [x] Seeding makes version 1 from `backend/instructions/claim.md` with `openai/gpt-6-luna` at `low`, kept, and the settings from `data/company.json` and `data/improvement.json`, with the lab's values and 25 agents at once
- [x] pytest: `create_dispatch` and `create_evaluation` record their version, and the dispatch and the evaluation in responses show it
- [x] Stub model test: the service starts a dispatch and an evaluation on the current version, and the claim agent's system prompt is that version's instructions followed by the documents' contents
- [x] Stub model test: with `MODEL_NAME` set, the claim agent's model is that model with no reasoning effort sent, and the run records `default`
- [x] pytest: `get_agent_version` and `get_current_version` hold no scores, and `test_the_agent_cant_read_the_scoreboard` still passes with `list_versions` and `get_version` added to its names
- [x] pytest: a version's scores count only finished whole-set evaluations that rounds ran on it: a Scoreboard evaluation, a tiny one and a stopped one on the same version leave them as they were
- [x] pytest: `get_version` returns its diff from the one before, from `difflib`, as added, removed and unchanged lines
- [x] pytest: `update_settings` by Dana Whitfield records a new version of the settings with her name and the time; by Marcus Oyelaran it returns 403 and records nothing; with no token 401; a negative limit or noise returns 422
- [x] pytest: after the approval limit changes to $2,000, a $1,350 approval recorded next is paid without a sign-off, and one recorded before the change stays held
- [x] pytest: `list_models` returns the three models with their efforts and prices as numbers; with `MODEL_NAME=openrouter/free` it returns that model alone at `default` with prices of 0
- [x] `curl -s localhost:8000/api/instructions` returns 404
- [x] vitest: the Configuration page shows the current version and each version with its held-out scores, and opens a version's diff from the version it was based on; the Settings page shows each setting with who changed it and when, saves a change after the confirmation dialog, refuses to save a value out of its range or not a number, says why Marcus Oyelaran can't change them and offers him no fields, and lists the models allowed read only
- [x] vitest: the appearance switch sets `data-theme` on the page and keeps the choice in `localStorage`; "Same as the computer" removes it
- [x] e2e: signed in as Dana Whitfield, a change to a setting is saved after the confirmation and shows with her name; switching to dark sets the page dark and stays so after a reload, and light stays light on a computer set to dark. The test changes the claim agents at once in a round rather than the approval limit, since the specs share one database and others depend on the $1,000.00 limit
- [x] Browser: the Configuration page shows version 1; the Settings page in light and dark mode
- [x] `npm run seed`, then a read-only query: `agent_versions` has version 1, `settings` one row, and `runs` has `version` and `round_id`
- [x] `npm run check` passes

## Phase 3: The judge

- [x] Seeding stores each label's `reason` and `reference` in `handler_decisions`
- [x] pytest, with the stub judge: finishing an evaluation sends one request per decided copy with the handler's decision, reason and reference beside the agent's decision, reason and section, the lab's three questions, the `server_url` from `OPENROUTER_URL` and a 10 second timeout, and records each grade
- [x] pytest: with probabilities `{"0": 0.1, "1": 0.2, "2": 0.45, "3": 0.25}` and a score of 1.85, the letter is B and the score 1.85; with the most probable level 1 and a score of 1.6, the letter is C, not the rounded B
- [x] pytest: an undecided copy is graded F with a score of 0 and no call; a call that fails or times out leaves its claim not graded and out of the average; an evaluation with no graded claim has no grade
- [x] pytest: the judge's cost is recorded with the evaluation and is apart from its model cost
- [x] pytest: grading 25 claims, with the stub judge taking a second each, finishes in under 5 seconds, so the calls run in parallel
- [x] pytest: with `MODEL_NAME` set, no call is made and every claim is not graded
- [x] pytest: `get_claim` on a copy, and every response the claim agent's `api.py` reads, still hold nothing from `handler_decisions`
- [x] `grep -rn "jev-1.13\|decisions.create\|OPENROUTER_URL" backend --include=*.py` finds them only in `backend/judge.py`
- [x] vitest: the Scoreboard shows the average grade beside the other measures, or "Not graded"; an evaluation's page shows each claim's letter and score and the two checks as Yes or No, or "Not graded", and the judge's cost
- [x] e2e: an evaluation played out through the API, with the judge stand-in, shows its grades on the Scoreboard and its page
- [x] `npm run check` passes

## Phase 4: The improver's records in the backend

The rounds, proposals, recipes, spending and the rule, with the service's operations, before the improver itself.

- [x] Seeding makes recipe version 1 from `backend/instructions/recipe.md`, word for word the lab's, and empties the rounds; `npm run seed` takes the configuration and the recipe back to version 1
- [x] pytest, `verdict.py`, with measures worked out by hand against the lab's settings: before `{accuracy 0.72, grade 1.80, cost 0.0010, seconds 20}`, after `{0.84, 1.85, 0.0018, 22}` is kept ("accuracy improved"); after `{0.84, 1.60, 0.0010, 20}` is rolled back ("grade got worse"); after `{0.74, 1.90, 0.0010, 20}` is rolled back ("no measure improved by more than the noise"); after `{0.58, 2.2, 0.0005, 10}` is rolled back ("it missed the objectives on accuracy"); after `{0.72, 1.80, 0.00084, 20}` is kept ("model_cost_per_claim improved", as a fraction); after `{0.72, 1.80, 0.0010, 25.5}` is rolled back ("seconds_per_claim got worse", as a fraction); and a version with no grade is rolled back ("it has no grade")
- [x] pytest: `read_results` holds the current version, its scores on both sets, the wrong claims and the five right ones with the lowest grades from its latest round evaluation of the evaluation set with the handlers' reasons, the earlier rounds, the round's objectives, noise, tolerance and rule, what's left of the limit and the models allowed; and nothing from the held-out set but its scores: no held-out claim id, reason, reference or decision appears anywhere in it
- [x] pytest: a round keeps its settings when they change: after `update_settings` raises the limit and the floors, the round's view and its verdict still use the ones it started with
- [x] pytest: `create_version` refuses a model or an effort outside the round's models allowed with 422; a version is untried and the current version is unchanged until its verdict keeps it
- [x] pytest: `create_round_evaluation` is refused with 402 when its estimate is more than what's left, naming both amounts; the estimate is the claims times the highest cost per claim seen for the model, or the current model's scaled by the larger price ratio for a model with no runs
- [x] pytest: once a round's spending reaches its limit, `start_claim` on a copy in its evaluation is refused, and `finish_run` marks that evaluation stopped; its version is rolled back by the verdict
- [x] pytest: `stop_round` by Dana Whitfield marks the round stopped and its running evaluation stopped, and every service write for that round is then refused with 409; by Marcus Oyelaran it returns 403; a stopped round before its verdict leaves the current version as it was, and one after its verdict keeps it
- [x] pytest: `decide_proposal` by Dana Whitfield passes the decision, its reason and her name to the agent's service and records nothing itself; a service 409 comes back with its detail; Marcus Oyelaran gets 403 and the service isn't asked; a proposal that isn't waiting returns 409
- [x] pytest: `start_round` by Dana Whitfield asks the service with her name; `stop_working_rounds` stops the rounds in a working stage and leaves one waiting for approval
- [x] pytest: a round's cost is the sum of its improver calls, its evaluations' model calls and the judge's calls on them
- [x] The shared OpenAPI test passes, with every new operation
- [x] `npm run check` passes

## Phase 5: The improver and the Improvement page

- [x] `agent/improver.py` builds the improver with `create_agent`, the four tools named as in the lab, `HumanInTheLoopMiddleware` on `propose_change` and `propose_recipe`, `ModelCallLimitMiddleware` and `parallel_tool_calls=False`; a pytest test checks each, and that its model is `openai/gpt-6-luna` at `medium`
- [x] `grep -rn "improver_api" agent` finds it only in `agent/improver.py` and the tests, and `agent/api.py` has no function for rounds, versions' scores or results
- [x] Stub model test, a whole round: with no evaluations yet, the round runs the first three evaluations (stage `first_evaluations`, 1 to 3 of 3), the improver calls `read_results` and `propose_change`, and the round waits with the proposal recorded and the one-run rule free
- [x] Stub model test: a proposal changes nothing until it is approved: while it waits, the current version and `agent_versions` are as they were
- [x] Stub model test: a rejection's reason reaches the improver as the tool's answer, and its next proposal is recorded as a new waiting proposal
- [x] Stub model test: a proposal outside the models allowed never reaches a handler: no proposal is recorded, and the improver's next message holds the refusal
- [x] Stub model test: after approval the service records the decision and the handler first, then the improver runs the three evaluations (1 to 3 of 3), the verdict, and pauses for the recipe; after the recipe's approval the round finishes, with recipe version 2 recorded
- [x] Stub model test: an approval while a dispatch runs is refused with "Dispatch #N is running", and nothing is recorded; a dispatch or an evaluation started while a round waits is accepted
- [x] Stub model test: an evaluation refused for the limit ends `run_evaluation` with the version rolled back and the reason
- [x] Stub model test: stopping a round while its evaluation runs starts no more claims and no more model calls, the current version stays, and the next start is accepted once the work in hand ends
- [x] Stub model test: a round whose improver ends without a proposal finishes with no version tried
- [x] Stub model test: a round waiting for approval survives a restart of the service (a new service on the same saver resumes it); a round that was working is stopped by the restart
- [x] Stub model test: the improver's model calls are recorded with the round; its traces carry the round's Langfuse session; each claim of its evaluations is tagged with its run and the round; `run_evaluation` runs the dispatcher in a fresh `contextvars.Context`, so no claim checkpoint lands on the improver's thread
- [x] Stub model test: the improver's model calls stop at the cap
- [x] vitest: the Improvement page shows each stage as it happens, from a stubbed `get_round`; a waiting proposal with its diff in color, the model and effort before and after, and Approve and Reject, each behind the confirmation dialog, with Reject needing a reason; the rounds newest first with scores before and after, verdict and cost; the chart with one point per version tried; the recipe's versions with their diffs; and for Marcus Oyelaran, why he can't start, stop or decide, with no buttons
- [x] e2e: signed in as Dana Whitfield, a round and a proposal played out through the API show on the Improvement page; approving it after the confirmation reaches the agent's stand-in with the decision and her name
- [x] Browser: the Improvement page with no rounds says how to start one, in light and dark mode
- [x] `npm run check` passes

## Phase 6: The look of the whole dashboard, the documents and the live runs

- [x] Every page uses `PageHeader`, the same spacing and the same buttons; the navigation marks the current page; tables right-align numbers with their units; statuses are badges with a color and a word; nothing on the existing pages changes how it works, and the existing vitest and e2e tests pass unchanged in what they check
- [x] vitest: each page's loading, empty and error states say what to do next, and a refresh keeps the data on screen with no change of layout
- [x] `docs/SPEC.md` (the approval limit as a setting, the sign-in, the improver, what the improver reads of the handlers' decisions, and what the team needs to see), `docs/TECH_STACK.md`, `docs/PROCESS.md`, `docs/CODE_STANDARDS.md` (rules 7 and 13), `docs/STATUS.md` and `data/README.md` describe the product as it now is
- [x] After one `npm run seed`, with `npm run dev` running and the default model, checked in the browser with Playwright scripts (the Playwright MCP server wasn't connected), signed in as Dana Whitfield:
  - [x] Two rounds from the Improvement page: reject the first proposal with a reason, then approve the next one, and approve the rest. Each round shows on the page as it happens, and afterwards the rounds show the scores before and after, the verdict and the cost
  - [x] The Configuration page shows the versions and their diffs
  - [x] Through Langfuse's API, each round's improver traces are found in one session
  - [x] Report how far version 1's two held-out runs differed on each measure, beside the noise and tolerance
  - [x] A dispatch at N=25 on the current version, which the run records
  - [x] Signed in as Marcus Oyelaran, a payout waiting for sign-off can't be signed off and the settings can't be changed, and each page says why. Signed in as Dana Whitfield, the same payout is signed off and paid
  - [x] Screenshots of every page in light and dark mode. A fresh subagent reviews them once, as a senior product designer would, against `docs/BRAND.md` and point 8 of the brief, and what it finds is fixed
  - [x] Report what the live checks spent; on GPT-6 Luna they should come to under $1
- [ ] Review of the whole branch against `main` by a fresh subagent, and its findings fixed
- [ ] `npm run check` passes with `.env` moved out of the way
