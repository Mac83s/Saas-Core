// Wygenerowano przez pnpm deployment:render. Nie edytuj ręcznie.
export const deployment = {
  "schemaVersion": 1,
  "id": "agro",
  "product": {
    "name": "SaaS Core Agro (profil wzorcowy)",
    "defaultLocale": "pl",
    "supportedLocales": [
      "pl",
      "en"
    ],
    "platformDomain": "agro.localhost"
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
    "shared.seo",
    "shared.farms"
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
        "shared.seo",
        "shared.farms"
      ],
      "planKeys": [
        "profile",
        "starter",
        "pro"
      ],
      "selfSignup": true,
      "roles": [],
      "serviceTemplates": []
    }
  ],
  "profileHash": "sha256:51febbe0d0e8044341effa865c5ea94f896e582a953b7a6658102b8f94653f40"
} as const
