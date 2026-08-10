from __future__ import annotations

from django.db import models

from .context import require_tenant_context


class TenantScopedQuerySet(models.QuerySet["TenantScopedModel"]):
    def for_tenant(self) -> TenantScopedQuerySet:
        context = require_tenant_context()
        return self.filter(organization_id=context.organization_id)


class TenantScopedManager(models.Manager["TenantScopedModel"]):
    def get_queryset(self) -> TenantScopedQuerySet:
        queryset = TenantScopedQuerySet(self.model, using=self._db)
        return queryset.for_tenant()

    def for_tenant(self) -> TenantScopedQuerySet:
        return self.get_queryset()


class TenantScopedModel(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="+",
    )

    objects = TenantScopedManager()

    class Meta:
        abstract = True
