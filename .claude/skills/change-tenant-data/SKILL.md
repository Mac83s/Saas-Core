---
name: change-tenant-data
description: Adding or changing a model, migration, manager, row-level-security policy or background task that touches tenant data in SaaS Core. Use when the work involves organization_id, TenantContext, SET LOCAL, RLS policies, a new table under core.organizations or shared.*, or a Celery task that reads tenant rows.
---

# change-tenant-data

The canonical text of this skill lives in `.agents/skills/change-tenant-data/SKILL.md`.
Read that file before working; this adapter exists only so a client that scans
`.claude/skills/` routes on the same `description` instead of a copy that can
drift.
