# Trazo — Claude Code entry point

Follow [AGENTS.md](AGENTS.md). It is the authoritative instruction file for
all AI coding agents in this repository; everything it references
(MASTER_PLAN.md, the area-owner docs, TASKS/, CODING_STANDARDS.md,
CONTRIBUTING.md) is binding.

Quick facts to avoid common mistakes:

- This is a docs-first repo in the design/scaffold stage: the handbook is
  the product until code phases open. Do not scaffold code outside a
  claimed `TRZ-Px-nn` task.
- Python packages use `uv` with split lockfiles (`sdk/`, `control-plane/`);
  never merge their dependencies.
- `schema/` is the root contract — changes there need lanes A+B review and
  a version note (see EVENTS.md for versioning rules).
- Run `make lint && make test` before proposing any PR; include the output
  in the PR description per AGENTS.md.
