"""The document a content import reads: `content-import.v1` (ADR-079 pkt 34).

The schema lives here, in code — the command that reads a document runs in
the backend's image, where a file of the repository's contract directory is
not — and `docs/architecture/content-import.v1.schema.json` is its published
copy, held to it by a test. `python manage.py sites_import_content --schema`
prints it.
"""

from __future__ import annotations

from typing import Any, Final

SCHEMA_NAME: Final = "content-import.v1"

_SLUG: Final = {
    "type": "string",
    "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
    "maxLength": 120,
    "description": "Lower-case Latin letters, digits and single hyphens.",
}
_LOCALE: Final = {"type": "string", "pattern": "^[a-z]{2}$"}
_ID: Final = {
    "type": "string",
    "minLength": 1,
    "maxLength": 200,
    "description": "The object's id where it comes from; unique in its list, stable between runs.",
}
_SHA: Final = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_NAMES: Final = {
    "type": "object",
    "minProperties": 1,
    "propertyNames": _LOCALE,
    "additionalProperties": {"type": "string", "minLength": 1, "maxLength": 120},
    "description": "The name per language code; the site's own language is required. A name "
    "is kept as a person's text: the translation engine never overwrites it.",
}
_SLUGS: Final = {
    "type": "object",
    "propertyNames": _LOCALE,
    "additionalProperties": {**_SLUG, "maxLength": 80},
    "description": "The archive's address per language. A language left out gets its address "
    "from the name in that language (or follows the site's language where it has no name).",
}
_FORMER: Final = {
    "type": "array",
    "items": _SLUG,
    "maxItems": 50,
    "description": "Slugs this object answered under before — the last part of an old "
    "address, never a whole path. Each answers one 308 to today's address.",
}
_PICTURE: Final = {
    "type": "object",
    "additionalProperties": False,
    "required": ["file"],
    "properties": {
        "file": {
            "type": "string",
            "minLength": 1,
            "description": "Path of a JPEG, PNG or WebP file, relative to the document's "
            "directory. No absolute path and nothing outside that directory.",
        },
        "alt": {"type": "string", "maxLength": 300, "description": "What the picture shows."},
    },
}
_FIELD: Final = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "origin": {
            "enum": ["human", "ai", "import"],
            "description": "Who wrote this field: a person, a model, or nobody vouches "
            "(`import`). Left out: the version's `origin`.",
        },
        "model": {"type": "string", "maxLength": 120, "description": "The model, for `ai`."},
        "sha256": {
            **_SHA,
            "description": "This text's own fingerprint, as whoever prepared the document "
            "computed it. On a source version it is what translations' `source_sha256` are "
            "compared with; left out, the import computes SHA-256 of the field's UTF-8 text "
            "exactly as the document holds it (`body`: the `html` string, or the blocks as "
            "JSON with sorted keys and no spaces).",
        },
        "source_sha256": {
            **_SHA,
            "description": "For a translated field: the fingerprint of the source text it "
            "was made from. Kept as given. When it differs from the source version's "
            "fingerprint the translation is reported as stale.",
        },
    },
}

DOCUMENT_SCHEMA: Final[dict[str, Any]] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://saas-core.local/contracts/content-import.v1.schema.json",
    "title": "Content import document",
    "description": "A body of existing content for one site: content types, categories, tags "
    "and entries with their language versions. Read by `manage.py sites_import_content`.",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema", "source", "organization", "default_locale", "entries"],
    "properties": {
        "schema": {"const": SCHEMA_NAME},
        "source": {
            "type": "string",
            "pattern": "^[a-z0-9][a-z0-9._-]{0,79}$",
            "description": "A name for where the content comes from. Ids are unique within "
            "it, and a later document with the same `source` updates what this one brought.",
        },
        "organization": {
            "type": "string",
            "minLength": 1,
            "description": "The slug of the organization the document is for. The command "
            "refuses a document for another organization than the one its operator named.",
        },
        "default_locale": {
            **_LOCALE,
            "description": "The site's own language; must equal the site's.",
        },
        "types": {
            "type": "array",
            "description": "Content types the entries go into. An existing type is found by "
            "`key` and left as it is; a missing one is made (the deployment's offer and the "
            "plan's limit apply) and needs `name` and `base_path`.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["key"],
                "properties": {
                    "key": {**_SLUG, "maxLength": 60, "description": "The type's stable key."},
                    "name": {"type": "string", "minLength": 1, "maxLength": 120},
                    "base_path": {
                        **_SLUG,
                        "maxLength": 80,
                        "description": "The type's name in addresses of the site's language.",
                    },
                    "locale_paths": {
                        "type": "object",
                        "propertyNames": _LOCALE,
                        "additionalProperties": {**_SLUG, "maxLength": 80},
                        "description": "Its name in addresses of other languages.",
                    },
                    "kind": {"enum": ["blog", "news", "guide"], "default": "blog"},
                    "schema_type": {
                        "enum": ["BlogPosting", "NewsArticle", "Article", "WebPage"],
                        "description": "What an entry is to search engines.",
                    },
                },
            },
        },
        "categories": {
            "type": "array",
            "description": "Categories of a type, a parent before what is under it (three "
            "levels at most).",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "type", "names"],
                "properties": {
                    "id": _ID,
                    "type": {"type": "string", "description": "The key of its content type."},
                    "parent": {
                        "type": ["string", "null"],
                        "description": "The `id` of the category above it; null at the top.",
                    },
                    "names": _NAMES,
                    "slugs": _SLUGS,
                    "former_slugs": _FORMER,
                },
            },
        },
        "tags": {
            "type": "array",
            "description": "Tags of the site, shared by its content types.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "names"],
                "properties": {
                    "id": _ID,
                    "names": _NAMES,
                    "slugs": _SLUGS,
                    "former_slugs": _FORMER,
                },
            },
        },
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "type", "versions"],
                "properties": {
                    "id": _ID,
                    "type": {"type": "string", "description": "The key of its content type."},
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 10,
                        "description": "Ids of categories of its type; every language version "
                        "is filed under them.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 10,
                        "description": "Ids of tags; every language version carries them.",
                    },
                    "author_name": {"type": "string", "maxLength": 120},
                    "source_locale": {
                        **_LOCALE,
                        "description": "The language the others were translated from; left "
                        "out, the site's own.",
                    },
                    "versions": {
                        "type": "array",
                        "minItems": 1,
                        "description": "The entry in each language it has: one translation "
                        "group. A language is given once.",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["locale", "title", "body", "status"],
                            "properties": {
                                "locale": _LOCALE,
                                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                                "excerpt": {"type": "string", "maxLength": 400},
                                "slug": {
                                    **_SLUG,
                                    "description": "The last part of the entry's address. Left "
                                    "out: made from the title (a Cyrillic title is written in "
                                    "Latin letters), unique in the type and language.",
                                },
                                "former_slugs": _FORMER,
                                "body": {
                                    "oneOf": [
                                        {
                                            "type": "object",
                                            "additionalProperties": False,
                                            "required": ["html"],
                                            "properties": {
                                                "html": {
                                                    "type": "string",
                                                    "description": "HTML, turned into blocks "
                                                    "by the core's converter. Every loss is "
                                                    "reported.",
                                                }
                                            },
                                        },
                                        {
                                            "type": "object",
                                            "additionalProperties": False,
                                            "required": ["blocks"],
                                            "properties": {
                                                "blocks": {
                                                    "type": "array",
                                                    "minItems": 1,
                                                    "items": {"type": "object"},
                                                    "description": "Core blocks "
                                                    "(`block_type`, `schema_version`, `data`). "
                                                    "A picture is named by "
                                                    '`"asset_id": "file:<path>"`.',
                                                }
                                            },
                                        },
                                    ]
                                },
                                "cover": {
                                    **_PICTURE,
                                    "description": "A picture shown first in the body (HTML "
                                    "bodies): what lists and shared links show of the entry.",
                                },
                                "images": {
                                    "type": "object",
                                    "additionalProperties": _PICTURE,
                                    "description": "For an HTML body: the file for each "
                                    "`<img src>` of the HTML, by that `src` exactly. An image "
                                    "without one is reported as lost.",
                                },
                                "status": {
                                    "enum": ["published", "draft"],
                                    "description": "The import publishes what says "
                                    "`published` and nothing else; it never withdraws.",
                                },
                                "published_at": {
                                    "type": "string",
                                    "format": "date-time",
                                    "description": "The date readers, feeds and structured "
                                    "data show as the publication date (with a zone). "
                                    "Required for `published`; never in the future.",
                                },
                                "changed_at": {
                                    "type": "string",
                                    "format": "date-time",
                                    "description": "When this text last changed where it "
                                    "comes from: the page's „updated”, the sitemap's "
                                    "`lastmod`, `dateModified`. Left out: `published_at`.",
                                },
                                "noindex": {"type": "boolean", "default": False},
                                "origin": {
                                    "enum": ["human", "ai", "import"],
                                    "default": "import",
                                    "description": "Who wrote this version's texts, unless a "
                                    "field says otherwise. A version with any `ai` field is "
                                    "marked as machine text to search engines.",
                                },
                                "model": {"type": "string", "maxLength": 120},
                                "fields": {
                                    "type": "object",
                                    "propertyNames": {"pattern": "^[a-z][a-z0-9_]{0,39}$"},
                                    "additionalProperties": _FIELD,
                                    "description": "Per field — `title`, `excerpt`, `body`, "
                                    "or any other name the source has — its origin and "
                                    "fingerprints. Fields the core does not hold are kept "
                                    "for the record.",
                                },
                                "accept_losses": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Kinds of content the HTML converter may "
                                    "lose in this version without holding it back from "
                                    "publication (the kinds are named in the report).",
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}
