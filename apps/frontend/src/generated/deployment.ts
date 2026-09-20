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
  "profileHash": "sha256:984d8298dbfa11356d4e9c52e4e36325bb9821e5aa9f48deeafff0afacea13af"
} as const
