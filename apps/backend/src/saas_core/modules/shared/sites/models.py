from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from saas_core.modules.core.organizations.tenancy import TenantScopedModel


def canonical_json_hash(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(serialized).hexdigest()


class SitePurpose(models.TextChoices):
    """Whose site this is, and what it is for.

    Read by inventory and by SeoContentRank. Deliberately not read by the
    renderer or the publication path — those treat every site identically, and
    a label that changed how something renders would make the platform's own
    pages a second, less-tested code path.
    """

    CUSTOMER = "customer", "Strona klienta"
    PLATFORM_MARKETING = "platform_marketing", "Strona marketingowa platformy"
    PLATFORM_BLOG = "platform_blog", "Blog platformy"


class PageType(models.TextChoices):
    """What kind of page this is, in the vocabulary SEO tooling uses.

    An optimiser needs to know that a page is the contact page before it starts
    rewriting it like a landing page. The list is the one W9.6.2 fixes; it is
    metadata about intent, and nothing in the rendering path branches on it.
    """

    HOMEPAGE = "homepage", "Strona główna"
    LANDING = "landing", "Landing"
    SERVICE = "service", "Usługa"
    ABOUT = "about", "O nas"
    CONTACT = "contact", "Kontakt"
    LEGAL = "legal", "Dokument prawny"
    ARTICLE_INDEX = "article_index", "Indeks artykułów"
    ARTICLE = "article", "Artykuł"


class Site(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=80)
    default_locale = models.CharField(
        max_length=10,
        choices=[("pl", "Polski"), ("en", "English")],
        default="pl",
    )
    purpose = models.CharField(
        max_length=32,
        choices=SitePurpose.choices,
        default=SitePurpose.CUSTOMER,
    )
    current_publication = models.ForeignKey(
        "Publication",
        on_delete=models.PROTECT,
        related_name="current_for_sites",
        null=True,
        blank=True,
    )
    # Navigation is edited as a whole — reordering one item moves others — so it
    # carries its own optimistic lock rather than borrowing any page's version.
    navigation_version = models.PositiveBigIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_sites",
    )
    idempotency_key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "slug", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "slug"],
                name="sites_site_org_slug_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "created_by", "idempotency_key"],
                name="sites_site_org_actor_idem_uq",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "id"], name="sites_site_org_id_idx"),
            models.Index(
                fields=["organization", "current_publication"],
                name="sites_site_org_pub_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.organization_id}:{self.slug}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.slug = self.slug.strip().lower()
        super().save(*args, **kwargs)


class DomainKind(models.TextChoices):
    PLATFORM = "platform", "Subdomena platformy"
    CUSTOM = "custom", "Domena własna"


class DomainStatus(models.TextChoices):
    PENDING = "pending", "Oczekuje"
    VERIFIED = "verified", "Zweryfikowana"
    FAILED = "failed", "Weryfikacja nieudana"
    DISABLED = "disabled", "Wyłączona"
    RELEASED = "released", "Zwolniona"


class DomainTlsStatus(models.TextChoices):
    PENDING = "pending", "Oczekuje"
    ELIGIBLE = "eligible", "Kwalifikuje się"
    REQUESTED = "requested", "Zażądano certyfikatu"
    DISABLED = "disabled", "Wyłączony"
    FAILED = "failed", "Błąd"


class PageAutomationPolicy(models.TextChoices):
    """Who may write this page's content.

    `MANUAL` is the default: a page becomes writable by the automation only when
    a human says so, never by an integration granting itself access.

    `PROPOSED` is the middle setting a cautious client needs: the automation may
    write a draft, but only a person turns that draft into what visitors see.
    The draft slot is the proposal — there is no second review object yet, so an
    automated proposal replaces the previous draft rather than queueing behind
    it (ADR-035 §5 keeps the fuller `ContentChangeSet` contract open).
    """

    MANUAL = "manual", "Tylko ludzie"
    PROPOSED = "proposed", "Propozycje do akceptacji"
    AUTOMATED = "automated", "Automatyzacja treści"


class SiteOnboardingStep(models.TextChoices):
    ADDRESS = "address", "Adres"
    DETAILS = "details", "Podstawowe dane"
    REVIEW = "review", "Podsumowanie"
    COMPLETED = "completed", "Zakończony"


class Domain(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="domains")
    hostname = models.CharField(max_length=253)
    kind = models.CharField(max_length=16, choices=DomainKind)
    status = models.CharField(
        max_length=16,
        choices=DomainStatus,
        default=DomainStatus.PENDING,
    )
    verification_name = models.CharField(max_length=253)
    verification_token = models.CharField(max_length=320)
    tls_status = models.CharField(
        max_length=16,
        choices=DomainTlsStatus,
        default=DomainTlsStatus.PENDING,
    )
    is_canonical = models.BooleanField(default=False)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    next_check_at = models.DateTimeField(null=True, blank=True)
    dns_error_code = models.CharField(max_length=40, blank=True)
    consecutive_transient_errors = models.PositiveIntegerField(default=0)
    tls_last_requested_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    quarantine_until = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_site_domains",
    )
    idempotency_key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "site_id", "hostname", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["hostname"],
                condition=~models.Q(status=DomainStatus.RELEASED),
                name="sites_domain_active_hostname_uq",
            ),
            models.UniqueConstraint(
                fields=["site"],
                condition=(
                    models.Q(is_canonical=True)
                    & ~models.Q(status=DomainStatus.RELEASED)
                ),
                name="sites_domain_active_canonical_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "created_by", "idempotency_key"],
                name="sites_domain_org_actor_idem_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status=DomainStatus.RELEASED,
                        released_at__isnull=False,
                        quarantine_until__isnull=False,
                        is_canonical=False,
                    )
                    | (
                        ~models.Q(status=DomainStatus.RELEASED)
                        & models.Q(released_at__isnull=True, quarantine_until__isnull=True)
                    )
                ),
                name="sites_domain_release_state_ck",
            ),
        ]
        indexes = [
            models.Index(fields=["hostname", "status"], name="sites_domain_host_status_idx"),
            models.Index(
                fields=["status", "next_check_at"],
                name="sites_domain_reverify_idx",
            ),
            models.Index(
                fields=["organization", "site", "id"],
                name="sites_domain_org_site_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.hostname

    def clean(self) -> None:
        super().clean()
        if self.site_id and self.site.organization_id != self.organization_id:
            raise ValidationError({"site": "Domena należy do site innej organizacji."})


class DomainMutation(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    domain = models.ForeignKey(Domain, on_delete=models.PROTECT, related_name="mutations")
    action = models.CharField(max_length=32)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_domain_mutations",
    )
    idempotency_key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "domain_id", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "domain", "created_by", "action", "idempotency_key"],
                name="sites_domainmutation_idem_uq",
            )
        ]
        indexes = [
            models.Index(
                fields=["organization", "domain", "created_at"],
                name="sites_domainmutation_org_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.domain_id and self.domain.organization_id != self.organization_id:
            raise ValidationError({"domain": "Mutacja należy do domeny innej organizacji."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError("Mutacja domeny jest niemutowalna.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValidationError("Mutacja domeny jest niemutowalna.")


class SiteOnboardingDraft(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    step = models.CharField(
        max_length=16,
        choices=SiteOnboardingStep,
        default=SiteOnboardingStep.ADDRESS,
    )
    name = models.CharField(max_length=160, blank=True)
    subdomain_label = models.CharField(max_length=63, blank=True)
    default_locale = models.CharField(
        max_length=10,
        choices=[("pl", "Polski"), ("en", "English")],
        default="pl",
    )
    site = models.OneToOneField(
        Site,
        on_delete=models.PROTECT,
        related_name="onboarding_draft",
        null=True,
        blank=True,
    )
    version = models.PositiveBigIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_site_onboarding_drafts",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_site_onboarding_drafts",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization"],
                name="sites_onboarding_org_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(step=SiteOnboardingStep.COMPLETED, site__isnull=False)
                    | (
                        ~models.Q(step=SiteOnboardingStep.COMPLETED)
                        & models.Q(site__isnull=True)
                    )
                ),
                name="sites_onboarding_completion_ck",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        site = self.site
        if (
            self.site_id
            and site is not None
            and site.organization_id != self.organization_id
        ):
            raise ValidationError({"site": "Onboarding wskazuje site innej organizacji."})


class SiteOnboardingMutation(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    draft = models.ForeignKey(
        SiteOnboardingDraft,
        on_delete=models.PROTECT,
        related_name="mutations",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="site_onboarding_mutations",
    )
    idempotency_key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    resulting_version = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "actor", "idempotency_key"],
                name="sites_onboarding_mutation_idem_uq",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.draft_id and self.draft.organization_id != self.organization_id:
            raise ValidationError({"draft": "Mutacja wskazuje onboarding innej organizacji."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError("Mutacja onboardingu jest niemutowalna.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValidationError("Mutacja onboardingu jest niemutowalna.")


class Page(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="pages")
    name = models.CharField(max_length=160)
    key = models.SlugField(max_length=80)
    page_type = models.CharField(
        max_length=32,
        choices=PageType.choices,
        default=PageType.LANDING,
    )
    version = models.PositiveBigIntegerField(default=0)
    automation_policy = models.CharField(
        max_length=16,
        choices=PageAutomationPolicy.choices,
        default=PageAutomationPolicy.MANUAL,
    )
    # Set while a person has the editor open, refreshed as they work. The
    # automation is refused until it lapses, so a human mid-sentence is never
    # overwritten; the automation can simply come back later.
    editing_locked_until = models.DateTimeField(null=True, blank=True)
    editing_locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="locked_site_pages",
        null=True,
        blank=True,
    )
    current_draft = models.ForeignKey(
        "PageVersion",
        on_delete=models.PROTECT,
        related_name="current_for_pages",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_site_pages",
    )
    idempotency_key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "site_id", "key", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "site", "key"],
                name="sites_page_org_site_key_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "site", "created_by", "idempotency_key"],
                name="sites_page_org_site_actor_idem_uq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "site", "id"],
                name="sites_page_org_site_idx",
            ),
            models.Index(
                fields=["organization", "current_draft"],
                name="sites_page_org_draft_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.site_id}:{self.key}"

    def clean(self) -> None:
        super().clean()
        if self.site_id and self.site.organization_id != self.organization_id:
            raise ValidationError({"site": "Strona należy do innej organizacji."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.key = self.key.strip().lower()
        super().save(*args, **kwargs)


class PageTranslation(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    site = models.ForeignKey(
        Site,
        on_delete=models.PROTECT,
        related_name="page_translations",
    )
    page = models.ForeignKey(
        Page,
        on_delete=models.PROTECT,
        related_name="translations",
    )
    locale = models.CharField(
        max_length=10,
        choices=[("pl", "Polski"), ("en", "English")],
    )
    slug = models.SlugField(max_length=80)
    title = models.CharField(max_length=160, blank=True)
    description = models.CharField(max_length=320, blank=True)
    social_title = models.CharField(max_length=160, blank=True)
    social_description = models.CharField(max_length=320, blank=True)
    allow_title_fallback = models.BooleanField(default=False)
    allow_description_fallback = models.BooleanField(default=False)
    allow_social_title_fallback = models.BooleanField(default=False)
    allow_social_description_fallback = models.BooleanField(default=False)
    version = models.PositiveBigIntegerField(default=1)
    slug_locked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "site_id", "page_id", "locale")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "page", "locale"],
                name="sites_translation_org_page_locale_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "site", "locale", "slug"],
                name="sites_translation_org_site_locale_slug_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="sites_translation_version_positive_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(locale__in=["pl", "en"]),
                name="sites_translation_locale_supported_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "site", "locale", "slug"],
                name="sites_translation_route_idx",
            ),
            models.Index(
                fields=["organization", "page", "locale"],
                name="sites_translation_page_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.page_id}:{self.locale}:{self.slug}"

    def clean(self) -> None:
        super().clean()
        if self.page_id and self.page.organization_id != self.organization_id:
            raise ValidationError({"page": "Tłumaczenie należy do innej organizacji."})
        if self.site_id and self.site.organization_id != self.organization_id:
            raise ValidationError({"site": "Tłumaczenie należy do innej organizacji."})
        if self.page_id and self.site_id and self.page.site_id != self.site_id:
            raise ValidationError({"site": "Tłumaczenie należy do innego site."})
        if (
            self.site_id
            and self.locale == self.site.default_locale
            and any(
                (
                    self.allow_title_fallback,
                    self.allow_description_fallback,
                    self.allow_social_title_fallback,
                    self.allow_social_description_fallback,
                )
            )
        ):
            raise ValidationError(
                {"locale": "Locale bazowe nie może korzystać z fallbacku."}
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.slug = self.slug.strip().lower()
        super().save(*args, **kwargs)


class PageTranslationMutation(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    translation = models.ForeignKey(
        PageTranslation,
        on_delete=models.PROTECT,
        related_name="mutations",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_page_translation_mutations",
    )
    idempotency_key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    resulting_version = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "translation_id", "resulting_version")
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "organization",
                    "translation",
                    "created_by",
                    "idempotency_key",
                ],
                name="sites_trmutation_org_actor_idem_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "translation", "resulting_version"],
                name="sites_trmutation_org_version_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(resulting_version__gte=1),
                name="sites_trmutation_version_positive_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "translation", "created_at"],
                name="sites_trmutation_org_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.translation_id}:v{self.resulting_version}"

    def clean(self) -> None:
        super().clean()
        if (
            self.translation_id
            and self.translation.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"translation": "Mutacja tłumaczenia należy do innej organizacji."}
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError("Zapis mutacji tłumaczenia jest niemutowalny.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValidationError("Zapis mutacji tłumaczenia jest niemutowalny.")


class SiteRedirect(TenantScopedModel):
    """One address that now answers somewhere else.

    Kept per site and per locale because the same slug means different pages in
    different languages. `page` is nullable: a redirect outlives the page that
    caused it, and a page deleted later must not take its incoming links with
    it.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="redirects")
    page = models.ForeignKey(
        "Page",
        on_delete=models.SET_NULL,
        related_name="redirects",
        null=True,
        blank=True,
    )
    locale = models.CharField(max_length=10)
    from_path = models.CharField(max_length=300)
    to_path = models.CharField(max_length=300)
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_site_redirects",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "site_id", "from_path")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "site", "from_path"],
                name="sites_redirect_org_site_from_uq",
            ),
            models.CheckConstraint(
                condition=~models.Q(from_path=models.F("to_path")),
                name="sites_redirect_not_self_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "site", "to_path"],
                name="sites_redirect_target_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.from_path} -> {self.to_path}"

    def clean(self) -> None:
        super().clean()
        if self.site_id and self.site.organization_id != self.organization_id:
            raise ValidationError({"site": "Przekierowanie należy do innej organizacji."})


class PageVersion(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    page = models.ForeignKey(Page, on_delete=models.PROTECT, related_name="versions")
    number = models.PositiveBigIntegerField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_page_versions",
    )
    idempotency_key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64)
    # `created_by` is the person a credential was issued by, so it cannot answer
    # "was this written by a human". A plain id, not a foreign key: the API key
    # lives in another module and this column only has to distinguish, not join.
    created_by_credential = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "page_id", "number")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "page", "number"],
                name="sites_version_org_page_number_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "page", "created_by", "idempotency_key"],
                name="sites_version_org_page_actor_idem_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(number__gte=1),
                name="sites_version_number_positive_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "page", "created_at"],
                name="sites_version_org_page_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.page_id}:v{self.number}"

    def clean(self) -> None:
        super().clean()
        if self.page_id and self.page.organization_id != self.organization_id:
            raise ValidationError({"page": "Wersja należy do strony innej organizacji."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError("Wersja strony jest niemutowalna.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValidationError("Wersja strony jest niemutowalna.")


class PageBlock(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    page_version = models.ForeignKey(
        PageVersion,
        on_delete=models.PROTECT,
        related_name="blocks",
    )
    position = models.PositiveIntegerField()
    block_type = models.CharField(max_length=120)
    schema_version = models.PositiveIntegerField()
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "page_version_id", "position")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "page_version", "position"],
                name="sites_block_org_version_position_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(schema_version__gte=1),
                name="sites_block_schema_positive_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    block_type__regex=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$"
                ),
                name="sites_block_type_format_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "page_version", "position"],
                name="sites_block_org_version_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.page_version_id}:{self.position}:{self.block_type}"

    def clean(self) -> None:
        super().clean()
        if (
            self.page_version_id
            and self.page_version.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"page_version": "Blok należy do wersji innej organizacji."}
            )
        if not isinstance(self.data, dict):
            raise ValidationError({"data": "Dane bloku muszą być obiektem JSON."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError("Blok wersji strony jest niemutowalny.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValidationError("Blok wersji strony jest niemutowalny.")


class Publication(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="publications")
    sequence = models.PositiveBigIntegerField()
    snapshot_schema_version = models.PositiveIntegerField(default=1)
    snapshot = models.JSONField(default=dict)
    snapshot_hash = models.CharField(max_length=64)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_site_publications",
    )
    source_publication = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="rollbacks",
        null=True,
        blank=True,
    )
    idempotency_key = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "site_id", "sequence")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "site", "sequence"],
                name="sites_publication_org_site_seq_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "site", "created_by", "idempotency_key"],
                name="sites_publication_org_site_actor_idem_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gte=1),
                name="sites_publication_sequence_positive_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(snapshot_schema_version__gte=1),
                name="sites_publication_schema_positive_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "site", "created_at"],
                name="sites_publication_org_site_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.site_id}:p{self.sequence}"

    def clean(self) -> None:
        super().clean()
        if self.site_id and self.site.organization_id != self.organization_id:
            raise ValidationError({"site": "Publikacja należy do innej organizacji."})
        if not isinstance(self.snapshot, dict):
            raise ValidationError({"snapshot": "Snapshot musi być obiektem JSON."})
        expected_hash = canonical_json_hash(self.snapshot)
        if self.snapshot_hash and self.snapshot_hash != expected_hash:
            raise ValidationError({"snapshot_hash": "Hash nie odpowiada snapshotowi."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError("Publikacja jest niemutowalna.")
        self.snapshot_hash = canonical_json_hash(self.snapshot)
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValidationError("Publikacja jest niemutowalna.")


class NavigationItem(TenantScopedModel):
    """One entry in a site's menu.

    Deliberately has no label of its own: the visible text is the page's
    translated title, so a menu is multilingual for free and cannot drift from
    the page it points at. An entry that needs different wording than its page
    is a later change, and a real one — it would need its own translations.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    site = models.ForeignKey(
        Site, on_delete=models.PROTECT, related_name="navigation_items"
    )
    page = models.ForeignKey(
        Page, on_delete=models.CASCADE, related_name="navigation_items"
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="children",
        null=True,
        blank=True,
    )
    position = models.PositiveIntegerField()
    # Hidden entries stay in the tree and keep their place, so hiding a page for
    # a while is not the same as losing where it belonged.
    visible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "site_id", "position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "site", "page"],
                name="sites_navitem_org_site_page_uq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "site", "position"],
                name="sites_navitem_org_site_pos_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.site_id}:{self.page_id}"

    def clean(self) -> None:
        super().clean()
        if self.site_id and self.site.organization_id != self.organization_id:
            raise ValidationError({"site": "Nawigacja należy do innej organizacji."})
        if self.page_id and self.page.site_id != self.site_id:
            raise ValidationError({"page": "Podstrona należy do innego serwisu."})
        if self.parent_id:
            if self.parent_id == self.id:
                raise ValidationError({"parent": "Pozycja nie może być swoim rodzicem."})
            parent = self.parent
            if parent is not None and parent.site_id != self.site_id:
                raise ValidationError({"parent": "Rodzic należy do innego serwisu."})


class ContentCollectionKind(models.TextChoices):
    BLOG = "blog", "Blog"
    NEWS = "news", "Aktualności"
    GUIDE = "guide", "Poradniki"


class ContentEntryState(models.TextChoices):
    DRAFT = "draft", "Szkic"
    PUBLISHED = "published", "Opublikowany"
    WITHDRAWN = "withdrawn", "Wycofany"


class ContentCollection(TenantScopedModel):
    """A repeatable surface — a blog, news, guides.

    Separate from `Page` because entries publish one at a time (ADR-035 §1).
    Folding them into the site's atomic snapshot would make publishing the
    three-hundredth article rewrite the previous two hundred and ninety-nine.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    site = models.ForeignKey(
        Site, on_delete=models.PROTECT, related_name="content_collections"
    )
    key = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    kind = models.CharField(
        max_length=16,
        choices=ContentCollectionKind.choices,
        default=ContentCollectionKind.BLOG,
    )
    # The path the index lives at: "blog" gives /blog/ and /blog/<entry>/.
    base_path = models.SlugField(max_length=80)
    # Appended to the end of the published menu when set. See the module note
    # on why this is a flag rather than a navigation item.
    show_in_navigation = models.BooleanField(default=False)
    automation_policy = models.CharField(
        max_length=16,
        choices=PageAutomationPolicy.choices,
        default=PageAutomationPolicy.MANUAL,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_content_collections",
    )
    idempotency_key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "site_id", "key", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "site", "key"],
                name="sites_collection_org_site_key_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "site", "base_path"],
                name="sites_collection_org_site_path_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "site", "created_by", "idempotency_key"],
                name="sites_collection_org_actor_idem_uq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "site", "id"],
                name="sites_collection_org_site_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.site_id}:{self.key}"

    def clean(self) -> None:
        super().clean()
        if self.site_id and self.site.organization_id != self.organization_id:
            raise ValidationError({"site": "Kolekcja należy do innej organizacji."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.key = self.key.strip().lower()
        self.base_path = self.base_path.strip().lower()
        super().save(*args, **kwargs)


class ContentEntry(TenantScopedModel):
    """One article, with its own draft pointer, version and publication, so it
    moves through the lifecycle independently of its neighbours."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    collection = models.ForeignKey(
        ContentCollection, on_delete=models.PROTECT, related_name="entries"
    )
    site = models.ForeignKey(
        Site, on_delete=models.PROTECT, related_name="content_entries"
    )
    slug = models.SlugField(max_length=140)
    locale = models.CharField(
        max_length=10,
        choices=[("pl", "Polski"), ("en", "English")],
    )
    # Entries sharing this are the same article in different languages. A new
    # entry starts as its own group of one, so an article that never gets
    # translated needs no special case anywhere.
    translation_group = models.UUIDField(default=uuid.uuid7, editable=False)
    title = models.CharField(max_length=200)
    excerpt = models.CharField(max_length=400, blank=True)
    author_name = models.CharField(max_length=120, blank=True)
    state = models.CharField(
        max_length=16,
        choices=ContentEntryState.choices,
        default=ContentEntryState.DRAFT,
    )
    version = models.PositiveBigIntegerField(default=0)
    current_draft = models.ForeignKey(
        "ContentEntryVersion",
        on_delete=models.PROTECT,
        related_name="current_for_entries",
        null=True,
        blank=True,
    )
    current_publication = models.ForeignKey(
        "ContentEntryPublication",
        on_delete=models.PROTECT,
        related_name="current_for_entries",
        null=True,
        blank=True,
    )
    # Distinct from the publication timestamp: an article can be backdated, and
    # the index orders by this rather than by when the button was pressed.
    published_at = models.DateTimeField(null=True, blank=True)
    noindex = models.BooleanField(default=False)
    editing_locked_until = models.DateTimeField(null=True, blank=True)
    editing_locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="locked_content_entries",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_content_entries",
    )
    idempotency_key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "collection_id", "-published_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "collection", "locale", "slug"],
                name="sites_entry_org_coll_locale_slug_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "collection", "created_by", "idempotency_key"],
                name="sites_entry_org_coll_actor_idem_uq",
            ),
            # One article per language: a second Polish version of the same
            # article would leave hreflang pointing at two addresses for one
            # language, which search engines read as a mistake.
            models.UniqueConstraint(
                fields=["organization", "translation_group", "locale"],
                name="sites_entry_org_group_locale_uq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "collection", "state", "-published_at"],
                name="sites_entry_index_idx",
            ),
            models.Index(
                fields=["organization", "translation_group"],
                name="sites_entry_group_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.collection_id}:{self.slug}"

    def clean(self) -> None:
        super().clean()
        if (
            self.collection_id
            and self.collection.organization_id != self.organization_id
        ):
            raise ValidationError({"collection": "Wpis należy do innej organizacji."})
        if self.collection_id and self.collection.site_id != self.site_id:
            raise ValidationError({"collection": "Wpis należy do innego serwisu."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.slug = self.slug.strip().lower()
        super().save(*args, **kwargs)


class ContentEntryVersion(TenantScopedModel):
    """Immutable draft content, exactly as `PageVersion` is for pages."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    entry = models.ForeignKey(
        ContentEntry, on_delete=models.PROTECT, related_name="versions"
    )
    number = models.PositiveBigIntegerField()
    blocks = models.JSONField(default=list)
    content_hash = models.CharField(max_length=64)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_content_entry_versions",
    )
    idempotency_key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    # See `PageVersion.created_by_credential`.
    created_by_credential = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "entry_id", "number")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "entry", "number"],
                name="sites_entryversion_org_entry_number_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "entry", "created_by", "idempotency_key"],
                name="sites_entryversion_org_actor_idem_uq",
            ),
        ]


class ContentEntryPublication(TenantScopedModel):
    """Append-only, one entry at a time.

    The snapshot holds only this article, which is the whole point: its size
    does not grow with the archive, so publishing costs the same whether the
    blog has ten entries or ten thousand.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    entry = models.ForeignKey(
        ContentEntry, on_delete=models.PROTECT, related_name="publications"
    )
    sequence = models.PositiveBigIntegerField()
    snapshot = models.JSONField(default=dict)
    snapshot_hash = models.CharField(max_length=64)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_content_entry_publications",
    )
    idempotency_key = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "entry_id", "sequence")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "entry", "sequence"],
                name="sites_entrypub_org_entry_seq_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "entry", "created_by", "idempotency_key"],
                name="sites_entrypub_org_actor_idem_uq",
            ),
        ]


class AutomationGrantMode(models.TextChoices):
    SUGGEST_ONLY = "suggest_only", "Tylko propozycje"
    DRAFT_WRITE = "draft_write", "Zapis draftu"
    PUBLISH_WITH_APPROVAL = "publish_with_approval", "Publikacja po akceptacji"
    AUTONOMOUS = "autonomous", "Autonomiczna publikacja"


class ContentAutomationGrant(TenantScopedModel):
    """What one credential may touch, and until when (ADR-035 §4).

    Without this a key reaches every collection in its organization. That is
    tolerable while the platform operator is the only holder, and not tolerable
    the moment a key is issued against a customer site — the agreement with the
    customer is usually "the blog", not "the website".

    A grant names either a whole site or a single collection. Leaving both unset
    is not allowed: an unbounded grant is the thing this model exists to prevent.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    # Not a foreign key: the credential lives in shared.notifications, and a
    # cross-module foreign key would tie the two tables' lifecycles together.
    credential_id = models.UUIDField()
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="automation_grants",
        null=True,
        blank=True,
    )
    collection = models.ForeignKey(
        ContentCollection,
        on_delete=models.CASCADE,
        related_name="automation_grants",
        null=True,
        blank=True,
    )
    mode = models.CharField(
        max_length=32,
        choices=AutomationGrantMode.choices,
        default=AutomationGrantMode.SUGGEST_ONLY,
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    # Emergency revoke: set once and the grant is dead, without deleting the
    # row, so the audit trail survives the incident that caused it.
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_automation_grants",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "credential_id", "id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(site__isnull=False, collection__isnull=True)
                    | models.Q(site__isnull=True, collection__isnull=False)
                ),
                name="sites_grant_exactly_one_target_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "credential_id"],
                name="sites_grant_org_credential_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.credential_id}:{self.mode}"

    def clean(self) -> None:
        super().clean()
        site = self.site if self.site_id else None
        if site is not None and site.organization_id != self.organization_id:
            raise ValidationError({"site": "Grant należy do innej organizacji."})
        collection = self.collection if self.collection_id else None
        if (
            collection is not None
            and collection.organization_id != self.organization_id
        ):
            raise ValidationError({"collection": "Grant należy do innej organizacji."})

    @property
    def active(self) -> bool:
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > timezone.now()


class SiteOutboxEvent(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    publication = models.OneToOneField(
        Publication,
        on_delete=models.PROTECT,
        related_name="outbox_event",
    )
    event_type = models.CharField(max_length=120)
    version = models.PositiveIntegerField(default=1)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_site_outbox_events",
    )
    correlation_id = models.UUIDField()
    causation_id = models.CharField(max_length=160)
    payload = models.JSONField(default=dict)
    occurred_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "occurred_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="sites_outbox_version_positive_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "published_at", "occurred_at"],
                name="sites_outbox_pending_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event_type}.v{self.version}:{self.id}"

    def clean(self) -> None:
        super().clean()
        if self.publication_id and self.publication.organization_id != self.organization_id:
            raise ValidationError({
                "publication": "Zdarzenie wskazuje publikację innej organizacji."
            })
        if not isinstance(self.payload, dict):
            raise ValidationError({"payload": "Payload zdarzenia musi być obiektem JSON."})
