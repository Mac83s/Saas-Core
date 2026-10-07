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
    "shared.model-port",
    "shared.billing",
    "shared.media",
    "shared.notifications",
    "shared.sites",
    "shared.image-generation",
    "shared.profiles",
    "shared.translation",
    "shared.assistant",
    "shared.customers",
    "shared.commerce",
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
        "shared.model-port",
        "shared.billing",
        "shared.media",
        "shared.notifications",
        "shared.sites",
        "shared.image-generation",
        "shared.profiles",
        "shared.translation",
        "shared.assistant",
        "shared.customers",
        "shared.commerce",
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
  "profileHash": "sha256:6e8ed5e25303eb0be48b7c90beebc0709ba7b3cb5d36e6621be25ec20c26ae45"
} as const
