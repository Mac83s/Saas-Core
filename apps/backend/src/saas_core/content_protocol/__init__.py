"""The content translation protocol (ADR-069, ADR-070, docs/architecture/translation-sources.md).

Pure Python shared by every module that owns translatable content and by the
translation engine: the token grammar of a text unit, its provenance and hash,
and the facts a translation must keep. It imports nothing from
`saas_core.modules` (an import contract holds that), so core, shared and
vertical modules can all use it without bending the module layers, and a
profile without the engine still edits language versions by hand.
"""
