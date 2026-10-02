"""The translation engine (ADR-069): it translates what content modules register.

Segmentation, masks, the glossary, quality checks and the quote live here;
jobs, settlement, review and the API come with TL6. Content modules never
import this package — they meet it through `saas_core.content_protocol`.
"""
