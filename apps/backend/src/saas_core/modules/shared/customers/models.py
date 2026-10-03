"""The end customer of a company: the one record bookings, orders and the shop
point at (ADR-073 §2)."""

from __future__ import annotations

import uuid

from django.db import models

from saas_core.modules.core.organizations.tenancy import TenantScopedModel


class Customer(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    display_name = models.CharField(max_length=160)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    contact_hash = models.CharField(max_length=64)
    #: A content language from the company's list (ADR-071 pkt 21).
    locale = models.CharField(max_length=10, default="pl")
    anonymized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        # Only the model's state moved here from booking (ADR-073 §2): the
        # table, its RLS policy and its relation guard are the ones booking's
        # migrations made, under the names they gave them.
        db_table = "booking_customer"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(locale__regex=r"^[a-z]{2}$"),
                name="booking_customer_locale_format_ck",
            ),
        ]
        ordering = ("organization_id", "-created_at", "id")
        indexes = [
            models.Index(
                fields=["organization", "contact_hash"], name="booking_customer_contact_idx"
            )
        ]
