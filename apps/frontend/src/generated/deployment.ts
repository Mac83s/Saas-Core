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
    "shared.notifications",
    "shared.booking"
  ],
  "features": {
    "customDomains": true,
    "publicBooking": true
  },
  "profileHash": "sha256:6611c7f428e3bca295f027be688d8646c9d9656460b4d7e3185b6d553d759d11"
} as const
