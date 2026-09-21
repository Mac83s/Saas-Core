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
    "shared.notifications",
    "shared.sites",
    "shared.media",
    "shared.profiles",
    "shared.booking",
    "shared.seo",
    "shared.farms",
    "shared.inventory"
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
        "shared.notifications",
        "shared.sites",
        "shared.media",
        "shared.profiles",
        "shared.booking",
        "shared.seo",
        "shared.farms",
        "shared.inventory"
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
  "profileHash": "sha256:b6b1a224f3d94aaa816df116401379468b9e381c6099aede5a4975690177a914"
} as const
