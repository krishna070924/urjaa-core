# Git workflow — mandatory

This repo has two permanent branches: `main` (shipped) and `dev`
(integration branch for the next release — single-developer project, `dev`
doubles as staging).

- **Never commit directly to `main` or `dev`.** Cut a feature/bugfix branch
  from `dev` first (name it for what it does), push it to `origin` too.
- When done and verified, merge into `dev`. **Do not delete the branch after
  merging.**
- When `dev` is ready to ship, merge `dev` → `main`.
- Check `git branch --show-current` before changing anything — if it's
  `main` or `dev`, cut a branch first.

# Implementation workflow — mandatory

- Default to delegating real code implementation to subagents rather than
  editing directly. Direct edits are fine for trivial one-liners and
  orchestration/setup work only.
- Multiple independent fixes in flight → dispatch parallel subagents, one
  per branch/concern.
- Every agent working here (any session) applies the `ponytail` skill/mindset
  — see `~/Documents/urjaa-split/CLAUDE.md` if available, otherwise: lazy
  senior dev, shortest correct diff, no speculative abstractions, reuse
  what's already here before writing new code.
