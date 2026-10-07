from typing import Any

from rest_framework import serializers

from saas_core.modules.core.organizations.serializers import PriceConversionSerializer

from .models import CatalogLayout, ProfileSubjectKind


class ProfileWriteSerializer(serializers.Serializer[dict[str, Any]]):
    display_name = serializers.CharField(max_length=160)
    headline = serializers.CharField(max_length=200, allow_blank=True, required=False)
    bio = serializers.CharField(max_length=4000, allow_blank=True, required=False)
    photo_id = serializers.UUIDField(required=False, allow_null=True)
    membership_id = serializers.UUIDField(required=False, allow_null=True)
    contact_email = serializers.EmailField(allow_blank=True, required=False)
    contact_phone = serializers.CharField(max_length=32, allow_blank=True, required=False)
    contact_address = serializers.CharField(max_length=240, allow_blank=True, required=False)
    links = serializers.ListField(child=serializers.DictField(), required=False)
    languages = serializers.ListField(child=serializers.CharField(), required=False)
    specializations = serializers.ListField(child=serializers.CharField(), required=False)
    # Still pl/en in the API: the profile endpoints move to content languages in
    # plan TL12, together with the OpenAPI floor they then have to meet. The
    # service already checks the language against the company's list.
    locale = serializers.ChoiceField(choices=[("pl", "Polski"), ("en", "English")], required=False)
    city_slug = serializers.CharField(max_length=80, allow_blank=True, required=False)
    category = serializers.CharField(max_length=64, allow_blank=True, required=False)
    layout = serializers.ChoiceField(choices=CatalogLayout.choices, required=False)


class ProfileCreateSerializer(ProfileWriteSerializer):
    subject_kind = serializers.ChoiceField(choices=ProfileSubjectKind.choices)


class ProfileUpdateSerializer(ProfileWriteSerializer):
    display_name = serializers.CharField(max_length=160, required=False)
    #: Optimistic lock. Two people editing the same profile is the ordinary
    #: case in a company, so the second one is told rather than overwritten.
    expected_version = serializers.IntegerField(min_value=1)


class ProfileTranslationSerializer(serializers.Serializer[dict[str, Any]]):
    expected_version = serializers.IntegerField(
        min_value=0,
        help_text="The language's version this change was made on; 0 for a language the "
        "card does not have yet. Another version answers 409.",
    )
    headline = serializers.CharField(max_length=200, allow_blank=True, required=False)
    bio = serializers.CharField(max_length=4000, allow_blank=True, required=False)
    link_labels = serializers.DictField(
        child=serializers.CharField(max_length=80, allow_blank=True),
        required=False,
        help_text="Link labels by the unit key of the link (`link/<12 hex>`, see `units`); "
        "an empty label removes the translation.",
    )
    allow_headline_fallback = serializers.BooleanField(required=False)
    allow_bio_fallback = serializers.BooleanField(required=False)


class ProfileTranslationUnitSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField(help_text="`headline`, `bio` or `link/<12 hex>`.")
    source_text = serializers.CharField(help_text="The text in the card's own language.")
    text = serializers.CharField(allow_blank=True, help_text="The translation; empty: none.")
    status = serializers.ChoiceField(
        choices=["fresh", "stale", "missing", "blocked", "copied", "unverified"],
        help_text="Against the current source text (translation-sources.md §4).",
    )
    origin = serializers.CharField(
        allow_blank=True, help_text="Who wrote it: human, ai, integration…; empty: nobody."
    )


class ProfileTranslationSummarySerializer(serializers.Serializer[dict[str, Any]]):
    locale = serializers.CharField()
    headline = serializers.CharField()
    bio = serializers.CharField()
    link_labels = serializers.DictField(child=serializers.CharField())
    allow_headline_fallback = serializers.BooleanField()
    allow_bio_fallback = serializers.BooleanField()
    version = serializers.IntegerField(help_text="0 for a language the card does not have yet.")
    units = ProfileTranslationUnitSerializer(many=True)


class ProfileTranslationListSerializer(serializers.Serializer[dict[str, Any]]):
    source_locale = serializers.CharField(help_text="The language the card is written in.")
    languages = ProfileTranslationSummarySerializer(
        many=True, help_text="Every other language of the company, translated or not."
    )


class ProfileSummarySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    subject_kind = serializers.CharField()
    display_name = serializers.CharField()
    headline = serializers.CharField()
    bio = serializers.CharField()
    photo_id = serializers.UUIDField(allow_null=True)
    membership_id = serializers.UUIDField(allow_null=True)
    contact_email = serializers.CharField()
    contact_phone = serializers.CharField()
    contact_address = serializers.CharField()
    links = serializers.ListField(child=serializers.DictField())
    languages = serializers.ListField(child=serializers.CharField())
    specializations = serializers.ListField(child=serializers.CharField())
    locale = serializers.CharField()
    city_slug = serializers.CharField()
    category = serializers.CharField()
    layout = serializers.CharField()
    version = serializers.IntegerField()


class CatalogStateSerializer(serializers.Serializer[dict[str, Any]]):
    """Whether this company is in the public catalogue, and under which address."""

    published = serializers.BooleanField()
    city_slug = serializers.CharField(allow_blank=True)
    slug = serializers.CharField(allow_blank=True)
    path = serializers.CharField(allow_blank=True)
    site_url = serializers.CharField(allow_blank=True, allow_null=True)
    published_at = serializers.DateTimeField(allow_null=True)
    suggested_category = serializers.CharField(
        allow_blank=True,
        help_text="While the card has no category: the one the company's own setup points at "
        "— the category of the preset its newest offer was made from. A key of the catalogue's "
        "dictionary for this type of company, or empty. Nothing is set by it: send it as "
        "`category` in the card's update to take it.",
    )


class OrganizationProfileSerializer(serializers.Serializer[dict[str, Any]]):
    profile = ProfileSummarySerializer()
    catalog = CatalogStateSerializer()


class CatalogItemSerializer(serializers.Serializer[dict[str, Any]]):
    """One row of the public listing (ADR-053 §5).

    `url` is always usable: the catalogue page when the company has no reachable
    site, that site's address when it has one. `is_external` says which, so the
    client can mark a link that leaves the platform without parsing the address.
    """

    slug = serializers.CharField()
    city_slug = serializers.CharField()
    city = serializers.CharField()
    category = serializers.CharField()
    display_name = serializers.CharField()
    headline = serializers.CharField(allow_blank=True)
    photo_id = serializers.CharField(allow_null=True)
    url = serializers.CharField()
    is_external = serializers.BooleanField()
    #: Kilometres from the searched point, town centre to town centre; null
    #: when the search had no point.
    distance_km = serializers.FloatField(allow_null=True)
    locale = serializers.CharField(
        help_text="The language of the card's texts in this answer: the asked one where the "
        "card is whole in it, the card's own otherwise."
    )
    source_locale = serializers.CharField(help_text="The language the card is written in.")
    translated_locales = serializers.ListField(
        child=serializers.CharField(),
        help_text="The company's languages the card has a complete translation in, in the "
        "company's order (TL20).",
    )
    badges = serializers.ListField(
        child=serializers.CharField(),
        help_text="What other modules say of the company, by key: `online_booking` — a "
        "visitor can book it online. The listing filters by one with `badge`.",
    )


class CatalogPageSerializer(serializers.Serializer[dict[str, Any]]):
    total = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    items = CatalogItemSerializer(many=True)
    #: Entries that fit the words by meaning without containing them (ADR-064):
    #: "Podobne" when `items` is empty, "Może też" below them otherwise.
    similar = CatalogItemSerializer(many=True)
    locale_has_entries = serializers.BooleanField(
        allow_null=True,
        help_text="With `locale`: whether any card of the catalogue is whole in that language. "
        "A listing in a language nobody speaks yet is not indexed. Null without `locale`.",
    )


class CatalogSitemapEntrySerializer(serializers.Serializer[dict[str, Any]]):
    city_slug = serializers.CharField()
    slug = serializers.CharField()
    source_locale = serializers.CharField(help_text="The language the card is written in.")
    translated_locales = serializers.ListField(
        child=serializers.CharField(),
        help_text="The languages the card has a complete translation in.",
    )
    updated_at = serializers.DateTimeField()


class CatalogSitemapPageSerializer(serializers.Serializer[dict[str, Any]]):
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()
    items = CatalogSitemapEntrySerializer(many=True)


class CatalogPhotoSerializer(serializers.Serializer[dict[str, Any]]):
    """A unit's picture at the booking form's address: our copies, never the
    original."""

    id = serializers.UUIDField()
    thumbnail_url = serializers.CharField()
    preview_url = serializers.CharField()
    width = serializers.IntegerField(help_text="The stored picture's width; 0 while unknown.")
    height = serializers.IntegerField(help_text="Its height; 0 while unknown.")
    ai_generated = serializers.BooleanField(
        help_text="A model made the picture: the page marks it (ADR-059)."
    )


class CatalogTownSerializer(serializers.Serializer[dict[str, Any]]):
    slug = serializers.CharField()
    name = serializers.CharField()


class CatalogFromPriceSerializer(serializers.Serializer[dict[str, Any]]):
    """„od X zł/noc”: the lowest price of one night or day for one person in
    the year ahead — an announcement, not a quote."""

    gross_minor = serializers.IntegerField()
    currency = serializers.CharField()
    per = serializers.ChoiceField(
        choices=["night", "day", "stay"], help_text="`stay`: a price charged once."
    )


class CatalogBookableUnitSerializer(serializers.Serializer[dict[str, Any]]):
    """A unit the company shows on its form, as its card lists it."""

    slug = serializers.CharField(
        help_text="Its address under the card: `/katalog/{city}/{company}/{slug}`."
    )
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True, help_text="Its beginning.")
    capacity = serializers.IntegerField(allow_null=True, help_text="Null — nobody counts.")
    photo = CatalogPhotoSerializer(allow_null=True, help_text="The first picture it shows.")
    town = CatalogTownSerializer(allow_null=True)
    from_price = CatalogFromPriceSerializer(allow_null=True)
    range_unit = serializers.CharField(help_text="`night` or `day`: how it is booked.")


class CatalogBookingSerializer(serializers.Serializer[dict[str, Any]]):
    """What a visitor can book at the company from its card."""

    form_url = serializers.CharField(
        help_text="The company's booking form, in the page's language where the company has it."
    )
    origin = serializers.CharField(
        help_text="The token a link to the form carries as `origin`: the form sends it back "
        "with the booking, which then says it came from the catalogue. Signed, for this "
        "company only, good for 30 days."
    )
    units = CatalogBookableUnitSerializer(
        many=True,
        help_text="The units the form shows the content of; empty for a company "
        "that books visits only.",
    )
    conversion = PriceConversionSerializer(
        required=False,
        allow_null=True,
        help_text="Roughly what the prices are in the currency of whoever reads the page's "
        "language, for an indicative figure beside each; null — nothing to convert.",
    )


class CatalogProfileSerializer(CatalogItemSerializer):
    business_type = serializers.CharField(
        allow_blank=True,
        help_text="The schema.org subtype of LocalBusiness the company is: `LodgingBusiness` "
        "for one that lets units by the night, whatever its category; otherwise the subtype "
        "its category names, or empty.",
    )
    booking = CatalogBookingSerializer(
        allow_null=True, help_text="Null — nothing is booked online at this company now."
    )
    fallback = serializers.ListField(
        child=serializers.CharField(),
        help_text="Units shown in the card's own language. Empty since TL20: the card comes "
        "whole in the asked language or whole in its own.",
    )
    layout = serializers.CharField()
    voivodeship = serializers.CharField(allow_blank=True)
    bio = serializers.CharField(allow_blank=True)
    contact_email = serializers.CharField(allow_blank=True)
    contact_phone = serializers.CharField(allow_blank=True)
    contact_address = serializers.CharField(allow_blank=True)
    links = serializers.ListField(child=serializers.DictField())
    languages = serializers.ListField(child=serializers.CharField())
    specializations = serializers.ListField(child=serializers.CharField())


class CatalogCompanySerializer(CatalogItemSerializer):
    """The card a unit's page stands under: the company's identity, without
    what its card lists besides."""

    business_type = serializers.CharField(allow_blank=True)
    layout = serializers.CharField()
    voivodeship = serializers.CharField(allow_blank=True)
    bio = serializers.CharField(allow_blank=True)
    contact_email = serializers.CharField(allow_blank=True)
    contact_phone = serializers.CharField(allow_blank=True)
    contact_address = serializers.CharField(allow_blank=True)
    links = serializers.ListField(child=serializers.DictField())
    languages = serializers.ListField(child=serializers.CharField())
    specializations = serializers.ListField(child=serializers.CharField())
    fallback = serializers.ListField(child=serializers.CharField())


class CatalogAmenitySerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField()
    label = serializers.CharField(  # type: ignore[assignment]
        help_text="In the page's language."
    )


class CatalogUnitSerializer(serializers.Serializer[dict[str, Any]]):
    slug = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    capacity = serializers.IntegerField(allow_null=True, help_text="Null — nobody counts.")
    photos = CatalogPhotoSerializer(many=True)
    amenities = CatalogAmenitySerializer(many=True)
    town = CatalogTownSerializer(allow_null=True)
    from_price = CatalogFromPriceSerializer(allow_null=True)
    locale = serializers.CharField(
        help_text="The language of the name and description in this answer."
    )
    source_locale = serializers.CharField(help_text="The language the company writes in.")
    translated_locales = serializers.ListField(
        child=serializers.CharField(),
        help_text="The company's other languages the unit has a name of its own in: the "
        "page is worth indexing in those and in `source_locale`.",
    )


class CatalogUnitChoiceSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.ChoiceField(choices=["group", "unit"])
    id = serializers.UUIDField()


class CatalogUnitOfferSerializer(serializers.Serializer[dict[str, Any]]):
    """An offer the unit is booked through, with the one choice that books
    it: the unit itself, or the group of identical units it speaks for."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    range_unit = serializers.CharField(help_text="`night` or `day`.")
    choice = CatalogUnitChoiceSerializer()


class CatalogUnitFormSerializer(serializers.Serializer[dict[str, Any]]):
    form_url = serializers.CharField()
    form_slug = serializers.CharField(
        help_text="The form's address in the booking API: `/booking/public/{form_slug}/…`."
    )
    timezone = serializers.CharField(help_text="The company's: its today is the calendar's.")
    last_day = serializers.DateField(help_text="The last day an arrival is taken on.")
    paused = serializers.BooleanField(help_text="The company paused online booking.")
    origin = serializers.CharField(
        help_text="The token a link to the form carries as `origin` (see the card)."
    )
    conversion = PriceConversionSerializer(
        required=False,
        allow_null=True,
        help_text="Roughly what the unit's price is in the currency of whoever reads the "
        "page's language; null — nothing to convert.",
    )


class CatalogUnitPageSerializer(serializers.Serializer[dict[str, Any]]):
    company = CatalogCompanySerializer()
    booking = CatalogUnitFormSerializer()
    unit = CatalogUnitSerializer()
    offers = CatalogUnitOfferSerializer(many=True)
    thing = serializers.DictField(
        allow_null=True,
        help_text="What the unit is for a search engine — a schema.org node (`Accommodation`, "
        "or `Product` for a thing rented by the day); its `@id`, `url` and `image` are the "
        "page's to give. Null: nothing to state.",
    )


class CatalogCitySerializer(serializers.Serializer[dict[str, Any]]):
    slug = serializers.CharField()
    name = serializers.CharField()
    voivodeship = serializers.CharField()


class CatalogCategorySerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField()
    # `labels`, not `label`: DRF's Field already owns `label` as the human name
    # of a field, so a serializer attribute of that name collides with it.
    labels = serializers.DictField(child=serializers.CharField())


class CatalogDictionarySerializer(serializers.Serializer[dict[str, Any]]):
    cities = CatalogCitySerializer(many=True)
    categories = CatalogCategorySerializer(many=True)
    locales = serializers.ListField(
        child=serializers.CharField(),
        help_text="Languages at least one card is whole in (its own or a complete "
        "translation): a catalogue page in any other language is not indexed (TL20).",
    )
    badges = serializers.ListField(
        child=serializers.CharField(),
        help_text="The badges this product's catalogue filters by (`badge`): "
        "`online_booking` where the product takes bookings. Empty — no such filter.",
    )
