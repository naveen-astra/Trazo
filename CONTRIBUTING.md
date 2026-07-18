# Contributing to Trazo — Humans and AI Agents

This process is written to be executable by an AI coding agent with no
additional context. Deviating from it is how parallel contributors corrupt
each other's work; don't.

## 1. Before writing any code

1. Read [MASTER_PLAN.md](MASTER_PLAN.md) fully.
2. Read the docs owning your area (map in MASTER_PLAN §1).
3. Find your task in [TASKS/](TASKS/). If it doesn't exist, open an issue
   proposing it — do not invent unplanned work.
4. Check the task's `Deps:` are all closed; check no open PR claims it.

## 2. Claiming and executing a task

- Claim by opening a draft PR titled `TRZ-Px-nn: <slug>` from branch
  `lane/TRZ-Px-nn-slug` immediately — the draft PR *is* the lock.
- Stay inside your lane's write scope (IMPLEMENTATION_PLAN §3). Needing to
  edit another lane's files = stop, comment on the task issue, get an ack.
- Contract changes (`schema/`, API_SPEC, EVENTS, DATABASE) require the doc
  and code in the same PR + review from lanes A and B.

## 3. PR requirements (all must hold to merge)

- [ ] One task ID; DoD checklist from the TASKS file copied into the PR
      description with every box checked
- [ ] CI green (lint, types, unit, contract, integration)
- [ ] New behavior has tests; bug fixes have regression tests
- [ ] Docs updated in-PR if any contract or behavior described in the
      handbook changed
- [ ] No `DEBT(` without linked issue; no new type-ignores without issue
- [ ] Squash-merge; PR title becomes the commit (conventional-commit form)

## 4. Rules specific to AI agents

- Never rewrite files outside the task's stated file list; if the list is
  wrong, say so in the PR instead of expanding silently.
- Never "improve" adjacent code opportunistically — file an issue.
- Never regenerate lockfiles, schema files, or golden fixtures unless the
  task says to.
- If the task description conflicts with a handbook doc, the handbook
  wins; flag the conflict in the PR description.
- Include in the PR description: what you read (docs consulted), what you
  verified (commands run + results). Unverifiable claims are review
  rejects.

## 5. Design contributions

Schema, replay semantics, and taxonomy changes are the highest-leverage
and highest-risk contributions: open an issue using the ADR template
(`DECISIONS/ADR-000-template.md`) *before* implementation. Silence is not
consent; an ADR needs explicit approval from the maintainer.

## 6. Issue labels

`lane:A|B|C|D`, `phase:P0..P7`, `kind:bug|task|adr|debt`,
`good-first-task` (S-sized, no cross-lane deps).
