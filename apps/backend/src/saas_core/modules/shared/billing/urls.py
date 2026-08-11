from django.urls import path

from .views import (
    BillingCheckoutView,
    BillingEntitlementSupportView,
    BillingPortalView,
    StripeWebhookView,
)

urlpatterns = [
    path("checkout/", BillingCheckoutView.as_view(), name="billing-checkout"),
    path("portal/", BillingPortalView.as_view(), name="billing-portal"),
    path(
        "support/entitlements/",
        BillingEntitlementSupportView.as_view(),
        name="billing-entitlement-support",
    ),
    path("webhooks/stripe/", StripeWebhookView.as_view(), name="billing-stripe-webhook"),
]
