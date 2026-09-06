// Wygenerowano przez pnpm deployment:render. Nie edytuj ręcznie.
export const deployment = {
  "schemaVersion": 1,
  "id": "business",
  "product": {
    "name": "SaaS Core Business",
    "defaultLocale": "pl",
    "supportedLocales": [
      "pl",
      "en"
    ],
    "platformDomain": "business.localhost"
  },
  "modules": [
    "core.health",
    "core.identity",
    "core.organizations",
    "shared.billing",
    "shared.sites",
    "shared.media",
    "shared.profiles",
    "shared.notifications",
    "shared.booking",
    "shared.seo"
  ],
  "features": {
    "customDomains": true,
    "publicBooking": true
  },
  "profileHash": "sha256:4ff69cf4be23258e8ed2637416f2ccf803f780d689b920b32a711024e45b093f"
} as const
