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
  "organizationTypes": [
    {
      "key": "business",
      "label": {
        "pl": "Firma",
        "en": "Business"
      },
      "description": null,
      "modules": [
        "shared.billing",
        "shared.sites",
        "shared.media",
        "shared.profiles",
        "shared.notifications",
        "shared.booking",
        "shared.seo"
      ],
      "planKeys": [
        "profile",
        "starter",
        "pro"
      ],
      "selfSignup": true
    }
  ],
  "profileHash": "sha256:747b11b729e8b5110dfcf3d7cf381dc81bc4d285ea50e270b2486d6ed9d16035"
} as const
