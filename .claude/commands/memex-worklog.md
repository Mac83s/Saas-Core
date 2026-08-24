---
name: memex-worklog
description: Session checkpoint — record the worklog, merge today's changelog entry for this project, triage due follow-ups, commit, and report. Idempotent; run it several times a day.
argument-hint: "[short session title] — optional"
---

# memex-worklog

A checkpoint you run **during** the day, not only at the end of it. Running it
twice refines one day's entry rather than producing two — so run it whenever a
coherent piece of work is finished, and do not save it up.

It exists because `desk/worklog/` is written for agents and nobody reads forty
of those entries to learn what moved last week. The changelog is the half
written for the people who were not here.

## 0 — Which project is this?

Do not guess from the directory name. The repository carries a locator:

```bash
cat .memex/connection.json     # "project": "<name>"
```

If there is no locator, this repository is not connected to a vault. Say so and
stop — `memex connect` is the fix, and it is not this command's job.

## 1 — The deterministic half, free

```bash
memex checkpoint
```

It rebuilds the index and reports what is broken, what is due and what is
uncommitted. Read it before writing anything: it is the cheapest correction to
your own account of the session, and it costs no tokens. Do not re-derive any of
it by hand.

## 2 — Context, in priority order

1. **This session.** What was built, fixed or established here — including work
   that is not committed yet. This is the substance of both entries.
2. `git status --short` and `git diff --stat` in every repository you touched.
3. Today's commits, in case part of the session already landed:
   `git log --since="00:00" --format="%h %s" --no-merges`

`$ARGUMENTS` is a hint for the session title, not the whole title.

## 3 — The worklog: one record, not one per step

```
memex_work(action: "worklog", text: "<summary>", project: "<project>",
           changes: [...], evidence: [...], decisions: [...], next: [...])
```

Observable results in `changes`, commands and test output in `evidence`. Never
reasoning, never a narrative of what you tried. One call for the whole session.

## 4 — The changelog: merge into today's entry

```
memex_work(action: "changelog", text: "<title for today>", project: "<project>",
           highlights: [...], added: [...], improved: [...], fixed: [...])
```

`added`/`improved`/`fixed` accumulate and de-duplicate across runs, so pass only
what this session contributed. `highlights` replaces the day's list, so pass the
**whole** list each time, kept short as the day grows.

**Highlights are the point, and they are the part that gets done badly.** Three
to six sentences, each one plain enough for someone who has never opened this
repository: what was worked on, and what somebody gets out of it. No file names,
no class names, no table or endpoint names — those belong in the three change
lists below it. If a highlight cannot be understood by a reader who does not
know the codebase, it is a change bullet wearing the wrong hat.

Write both entries in the language the project's documents are written in.

## 5 — Follow-ups: close only what you can prove

```bash
memex follow list
```

The queue is **shared** across sessions, machines and plans. Most of what is due
is not yours: it belongs to someone else's work, or it cannot be verified from
this machine at all. Close a follow-up only when you can produce the result now
— its `--cmd` run, or an effect verified in this session:

```bash
memex follow done <id> --note "the actual result"
```

Leave everything else `pending`, with no comment. That is the correct outcome,
not neglect. **A `done` without evidence is a false confirmation that destroys
the only trace of unfinished work.** If many are stuck behind one blocker —
typically an undeployed change — say that in the report instead of pretending
the queue was worked through.

## 6 — Commit

Running this command **is** the request to commit. Nothing else is.

```bash
git status --short          # first, always: see the whole picture
git add <exact paths this session touched>
git commit -m "<type>(<scope>): <description>"
```

**Never `git add -A`, never a glob.** The working tree may be shared with
parallel sessions, and `-A` does not stage your work — it stages everyone's and
signs your name to it. If `git diff --cached --name-only` shows a path you did
not touch, unstage it rather than committing someone's half-finished change.

Commit the vault's own artefacts (worklog, changelog) separately from code —
they are different histories and get reverted for different reasons. Push only
when asked.

## 7 — Report

Short, in the language you are working in:

- worklog id, and whether the changelog entry was created or merged;
- how many follow-ups were due, how many were **closed with evidence**, and how
  many were left pending with the reason they could not be judged here;
- commit hashes, or "no changes";
- what is still open — one actionable line each — or a plain statement that the
  work is finished.
