---
name: memex-tidy
description: Survey and clean up a repository's stray files — documents left outside the project's own conventions, leftovers, duplicates, and files nothing references. Use when connecting memex to an existing project for the first time, when the repo has visibly accumulated clutter, or when asked to tidy up.
---

# memex-tidy

`memex tidy <project>` reports what a repository actually contains: where its
documents live, which ones sit outside every convention the repo follows, what
looks like a leftover, what is duplicated, what is too large to read cheaply,
and — the number that matters — **how many other files reference each one**.

It changes nothing. You do the changing, and only after checking.

## Why it does not move anything itself

In the repository this was built against, a file that looked like obvious
clutter — a 67 KB log at the repo root, outside every convention — turned out
to be referenced from eighteen other files. Anything that moved files on its
own judgement would have broken all eighteen in one pass, and the breakage
would not have shown up until someone followed a link.

So the tool establishes facts and stops. The judgement is yours.

## Read the report in this order

1. **`PINNED`** — a vault page's `derived_from` cites this exact path. Moving
   it breaks the knowledge base. Either leave it, or move it *and* update the
   citing page in the same change. Never move it silently.
2. **The reference count.** `0 refs` means nothing was found pointing at it.
   `18 ref(s)` means eighteen files would need rewriting. This is the cost of
   moving, stated up front.
3. **The confidence.** `high` appears only for markdown, where links are parsed
   and resolved. Everything else is `low` — and low means *the tool could be
   wrong*, not *probably unused*.

## What "low confidence" actually means

For anything that is not markdown, the tool searched for the filename, the path,
and the module-path forms an import would use. That misses real references:

- a script invoked from CI, a systemd unit, a cron entry, or a container
  `ENTRYPOINT` that is not in this repo
- a file loaded by glob or by a name built at runtime
- something a person runs by hand once a quarter
- a module imported through a re-export or a path alias

**Never delete a `low` confidence file on the report alone.** Check with
`git log` who last touched it and why, grep for fragments of its name, and if
it is still unclear, ask. An unused file costs disk; a deleted deploy script
costs an outage.

## Moving a document safely

In this order, or you will break links:

1. `git mv <old> <new>` — never `rm` plus create. History follows the file,
   and history is how the next person understands why it exists.
2. Rewrite every inbound reference. The report says how many there are; find
   them by grepping the old path *and* the bare filename.
3. If the file was `PINNED`, update the `derived_from` path in the citing vault
   page — and its `sha256` if the content changed too.
4. Re-run `memex tidy <project>`. The file should no longer be homeless and its
   reference count should be unchanged. A count that dropped means you broke
   something.
5. Run `memex doctor`. `source-missing` or `not-in-index` appearing where it did
   not before means a vault page now points at nothing.

## Where a homeless document belongs

The report lists the repo's **inferred homes** — the directories it already
keeps documents in, read from the repo itself rather than imposed. Put the file
in the one that matches what it is. If nothing matches, that is a finding worth
raising rather than a reason to invent a new folder: repos accumulate layout
conventions for reasons, and a fifth documentation directory usually makes
things worse.

Two exceptions that are not clutter: a `README.md` beside the thing it
describes, and files in tool-required locations such as `.github/`.

## At first connection

The first run on an existing project is a survey, not a cleanup. Most of what
it reports has been there for years and works. Use it to answer:

- **What documentation does this project already have?** The homes list is the
  answer, and it is the fastest way to learn a repo's shape.
- **What is worth bringing into the vault?** Documents that record decisions,
  architecture, or hard-won constraints are worth `memex_remember` or
  `memex_propose` — the knowledge outlives the file.
- **What is genuinely abandoned?** Unreferenced, not touched in a long time,
  and superseded by something newer. Propose removing it; do not just remove it.

Do not attempt to fix everything on day one. Report what you found, propose an
order, and let the owner choose.

## Cost gate

Do not run this for a single file, on every session, or as a reflex before
unrelated work. It reads the whole repository. Once at connection, and then
only when there is reason to think the repo has drifted.
