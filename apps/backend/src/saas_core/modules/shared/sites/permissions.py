from typing import Final

SITE_CONTENT_EDIT: Final = "site.content.edit"
SITE_PUBLISH: Final = "site.publish"
SITES_ENABLED: Final = "sites.enabled"
SITES_MAX: Final = "sites.max"
#: Pages on one site (ADR-032); a plan without it has no page limit.
PAGES_MAX: Final = "pages.max"
#: The organization's own templates (F4-B, answer 4a); a plan without it has
#: no limit.
SITE_TEMPLATES_MAX: Final = "sites.templates.max"
CUSTOM_DOMAIN_ENABLED: Final = "custom_domain.enabled"
