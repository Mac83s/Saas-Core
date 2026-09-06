---
name: maintain-saas-core-skills
description: Repairing or extending the SaaS Core skill catalogue itself, after an ADR, an executable contract, a module descriptor, a quality command or a repeated agent failure changed the ground a skill stands on. Use when pnpm ai:validate fails, when a skill is stale, or when a new area of the repository needs one.
---

# maintain-saas-core-skills

The canonical text of this skill lives in `.agents/skills/maintain-saas-core-skills/SKILL.md`.
Read that file before working; this adapter exists only so a client that scans
`.claude/skills/` routes on the same `description` instead of a copy that can
drift.
