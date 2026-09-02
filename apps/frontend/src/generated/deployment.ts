// Wygenerowano przez pnpm deployment:render. Nie edytuj ręcznie.
export const deployment = {
  "schemaVersion": 1,
  "id": "core-only",
  "product": {
    "name": "SaaS Core",
    "defaultLocale": "pl",
    "supportedLocales": [
      "pl",
      "en"
    ],
    "platformDomain": "core.localhost"
  },
  "modules": [
    "core.health",
    "core.identity",
    "core.organizations"
  ],
  "features": {
    "customDomains": false,
    "publicBooking": false
  }
} as const
