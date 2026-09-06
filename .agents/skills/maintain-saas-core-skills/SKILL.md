---
name: maintain-saas-core-skills
description: Repairing or extending the SaaS Core skill catalogue itself, after an ADR, an executable contract, a module descriptor, a quality command or a repeated agent failure changed the ground a skill stands on. Use when pnpm ai:validate fails, when a skill is stale, or when a new area of the repository needs one.
---

# Maintaining the catalogue

A skill is an instruction another agent will follow without a person checking
it, so a stale one is worse than a missing one: it is followed with confidence.
This is the procedure for changing them, and the point of it is that **the model
does not get to decide its own instructions are correct because the file
parses**.

Canonical skills live in `.agents/skills/<name>/SKILL.md`. Rules that apply to
every task stay in `AGENTS.md`.

## The cycle

1. **Detect.** Something changed under a skill: an ADR, a document in
   `docs/architecture/`, a module or deployment descriptor, the OpenAPI
   contract, a `pnpm` command, or an agent failed the same way twice.
2. **Locate.** Which skills name that source? Grep the catalogue for the path or
   the command. A skill that does not name its sources cannot be maintained —
   fix that first.
3. **Change only what the source changed.** A rewrite that also improves prose
   makes the diff unreviewable, and the diff is the review.
4. **Validate.** `pnpm ai:validate` checks frontmatter, unique names, name equal
   to directory, description length and uniqueness, every repository path and
   `pnpm` command a skill mentions, adapter frontmatter equal to canonical,
   adapters staying thin, mirrors staying identical, orphans, secrets, size,
   irreversible commands inside fenced blocks, and that every skill has a row in
   the routing map in `AGENTS.md`. Then `pnpm ai:eval` asks the question that
   comes after well-formedness: for the scenarios in
   `.agents/evals/routing.json`, does exactly one description stand out, and
   does every catalogued module have a procedure or a written reason for using a
   general one.
5. **Exercise.** Run the checks the changed skill itself promises. A skill that
   tells somebody to run `pnpm backend:test` is wrong if that command no longer
   exists — and right only if the command still does what the skill claims.
6. **Commit separately.** One commit for the catalogue change, revertable on its
   own, with the evidence in the message.

## Adding a skill

Only for an area that exists. A skill for an unwritten module describes an
intention, and the validator would call that intention current.

- a scenario in `.agents/evals/routing.json` whose terms the new description
  wins on. A skill nobody can route to is a file, not an instruction;
- one directory, one `SKILL.md`, `name` equal to the directory name;
- `description` says **when to use it**, not what it contains — that field is
  what routing reads, and two overlapping descriptions make the choice random.
  The validator refuses duplicates; near-duplicates are your judgement;
- a thin adapter at `.claude/skills/<name>/SKILL.md` repeating `name` and
  `description` **exactly** and pointing at the canonical file. Copying the body
  is how the two drift; a link alone without the frontmatter turns routing off
  silently, because clients route on the adapter's frontmatter;
- a row in the routing map in `AGENTS.md`, or nobody will find it;
- content that is operational: the order of work, the commands, and the traps
  that already cost somebody a day. A summary of an ADR is not a skill — the ADR
  is right there.

## What a skill may not do

- widen permissions, or authorize a production or irreversible action. The
  validator catches the checkable half — `git push`, `--force`, `--apply`,
  `rm -rf`, `DROP`/`TRUNCATE` inside a fenced command block. Prose *about* those
  commands is fine and often necessary; handing one over is not;
- replace an ADR. A skill explains how to work inside a decision; changing the
  decision needs a new ADR;
- contain a secret, a token or a customer's data;
- duplicate another skill's content. Application skills carry the differences
  and point at the Core and Shared skills for the rest.

## Traps

- **Editing the adapter instead of the canonical file.** The canonical file is
  in `.agents/skills/`; the adapter exists so clients that only scan
  `.claude/skills/` can route.
- **The memex skills are managed mirrors.** They are byte-identical copies by
  design and listed in the validator; do not thin them.
- **A path in backticks is checked.** If you mention
  `apps/backend/src/saas_core/config/urls.py`, it has to exist. That is
  deliberate: a moved file should break the instruction that points at it.

## Done means

```
pnpm ai:validate
pnpm ai:eval
```

green locally and in CI, the diff shown, and the reason for the change written
where the next person will see it — the commit message, and `HANDOFF` if the
change came from something bigger.
