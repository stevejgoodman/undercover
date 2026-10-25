# The claims pilot

From the head of claims operations at UnderCover Travel Insurance.

## How claims work today

UnderCover sells travel insurance on three plans: Economy, Premium and First. Our three claims handlers work through a queue of claims by hand. For each claim, a handler reads the customer's story and documents and checks them against the policy and our policy wording. Then they approve the claim with a payout, decline it or refer it. A claim is referred when it needs someone's judgment or more information, as the claims manual explains.

## The pilot

We want an AI agent, the UnderCover Agent, to work the queue the way a handler does. For each claim it should:

- read the claim, the customer's policy and claim history, and the sections of the policy wording and the claims manual it needs
- approve, decline or refer the claim
- work out the payout when it approves
- explain the decision in two or three sentences, along with the relevant section of the policy

Our goal is to handle claims straight through, as accurately as our handlers do.

## Working the queue on its own

The agent works the queue in dispatches, with many claims at once:

- A handler starts a dispatch on the queue page, choosing how many claim agents work at once, from 1 to 25. A dispatch works every claim left in progress and every waiting claim, oldest submitted first. Code chooses the claims and keeps track of the dispatch, with no model, and only one dispatch, evaluation or stretch of the improver's work runs at a time. The agent can also work one named claim.
- Each claim goes to a claim agent of its own that works that one claim from a clean start and reports back in a line: the decision and payout, or what went wrong. Every step on a claim is recorded on that claim.
- For each claim the agent looks up the sections of the policy wording and the claims manual it needs, the way a handler would, rather than being handed whole documents. It works out an approval's payout with UnderCover's payout rules, which are part of our systems.
- An approval over the sign-off limit pauses the agent's work on that claim, keeping everything it has worked out, until a handler signs off. As soon as a handler signs off, the agent picks the claim up from where it stopped and pays it, and between the sign-off and the payment the claim shows as in progress. If the agent isn't running at that moment, the next dispatch picks it up. The payment records who signed off and when. For now a handler can only sign off.
- Work survives a restart. If the agent is stopped partway through a claim, by a crash, a restart or Ctrl-C, the next dispatch carries on with that claim from where it got to, and that doesn't count as a new attempt. A dispatch that was stopped shows as stopped.
- Problems are put right automatically. A claim that hits a rate limit or a timeout waits and carries on from where it got to, as the same attempt, and one still hitting them after its waits stays in progress for the next dispatch. A claim that fails with any other error before it is decided goes back in the queue and the same dispatch tries it once more from the start, and a claim that fails twice is left for a handler. One bad claim never stops a dispatch, and no claim is ever decided or paid twice, even when a step runs again after a restart.
- When a dispatch finishes, its summary is built from our records, with no model writing it: how many claims were approved, declined and referred, each payout waiting for a sign-off, and each claim left for a handler or for the next dispatch.
- The tokens and cost of every model call, and the time the agent spends working on each claim, leaving out any wait for a sign-off, are recorded with the dispatch or evaluation they happened in.
- Evaluations check the agent's work against our handlers' decisions. An evaluation works copies of one of our two labeled sets of claims, whole or its five tiny claims, through the same dispatcher and claim agent. The copies never show in the queue, a dispatch never picks them up, nobody can sign them off, and an approval held for sign-off counts as finished. An evaluation stopped partway shows as stopped. Each evaluation is scored with our measures: how often the decision matches the handler's, how often the payout does too, the cost of the mistakes, the share of claims handled straight through, the model cost and time per claim, the time for the whole run, and a judge's grade of each explanation against the handler's reason, from F to A, with its own cost.
- Every dispatch and evaluation uses a version of the claim agent's configuration: its instructions, model and reasoning effort. A dispatch uses the current version, which changes only when a round of improvement keeps a new one.

## Improving the agent

- An improver, an AI agent of its own, works in rounds that a senior handler starts and can stop, one round open at a time. It follows a recipe: it reads how the current version is doing, proposes a new version with its reason, and after a handler approves it, has the new version evaluated once on the evaluation set and twice on the held-out set. Our rule then keeps it or rolls it back: a version is kept when it meets our objectives on the held-out set, at least one measure improves by more than its noise, and none gets worse by more than its tolerance. The round ends with the improver proposing a better recipe.
- Nothing the improver proposes takes effect until a handler approves it, and a rejection's reason goes back to the improver. It can't change the objectives, the noise and tolerance, the spending limit, the models allowed, the approval limit, the labeled sets or the judge.
- Each round has a spending limit that covers the improver's own model calls, its evaluations and the judge.

## Handlers sign in

- Handlers sign in to the dashboard with their email address and password. There's no sign-up, every page needs a signed-in handler, and the system checks the handler on every action they take. A sign-off records the handler signed in.
- Only a handler who can sign off payouts over the approval limit can start or stop a round, approve or reject the improver's proposals, or change a setting. Anyone else is told what they can't do and why, and the system refuses it too.

## What the team needs to see

- The queue, with where each claim stands: waiting, in progress, waiting for sign-off, decided or left for a handler.
- The latest dispatch, with each of its claims and where it stands, its model cost and time, and its summary when it finishes.
- A scoreboard of the evaluations, newest first, with their measures, each opening to its claims beside the handlers' decisions with the misses easy to spot.
- Each claim in full, with the agent's decision and its reasons.
- What the agent is doing on a claim while it works, step by step, including the sections it read and any attempt that failed.
- The claim agent's configuration: the current version, every version with its held-out scores, and what each changed.
- The improvement rounds as they happen: where a round has got to, a proposal waiting for approval with what it changes, the rounds so far with their scores before and after, verdict and cost, a chart of each version tried, and the recipe's versions.
- The settings: the approval limit, the objectives, the noise and tolerance, the spending limit and the claim agents at once in a round, with who changed each and when, and the models allowed. Each handler chooses light, dark or the computer's appearance.

## Rules

- A payout over the approval limit, $1,000 to start with and a setting since, needs a handler's sign-off. The agent can approve such a claim, but the payment waits until a handler signs off. The system must block the payment until then, even if the agent tries to pay.
- Decisions follow the policy wording and the claims manual. The wording comes first, and the manual says how to read it.
- Our handlers' own decisions on these claims are in `data/evals/`. We use them to check the agent's work. The claim agent must never see them. The improver reads our handlers' decisions and reasons on the evaluation set, never on the held-out set, of which it sees only the scores. The dashboard shows both sets' decisions.
- Amounts are in US dollars.

## Our records

Everything is in `data/`, described in `data/README.md`: the claims queue, the policies, the customers, the plans, the handlers, the policy wording and the claims manual. The held-out claims in `data/evals/` are for evaluations and stay out of the queue.

## Not for now

- No real payments.
- No messages to customers.