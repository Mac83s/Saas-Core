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
      "selfSignup": true,
      "roles": [],
      "serviceTemplates": []
    }
  ],
  "profileHash": "sha256:d1c21e12783bda7757c5eb6e741b26dfc3da88022654c9fff456d677169ea1f6"
} as const
