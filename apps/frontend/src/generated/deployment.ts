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
  "profileHash": "sha256:edbf207a4aba67229d67be329f5e673204088bb2a86990e14533d61c1a35a84d"
} as const
