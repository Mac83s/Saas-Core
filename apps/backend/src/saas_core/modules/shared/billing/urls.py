from django.urls import path

from .views import (
    BillingCheckoutView,
    BillingDetailsView,
    BillingEntitlementSupportView,
    BillingOverviewView,
    BillingPortalView,
    BillingTrialActivationView,
    StripeWebhookView,
)

urlpatterns = [
    path("overview/", BillingOverviewView.as_view(), name="billing-overview"),
    path("details/", BillingDetailsView.as_view(), name="billing-details"),
    path(
        "trial-activation/",
        BillingTrialActivationView.as_view(),
        name="billing-trial-activation",
    ),
    path("checkout/", BillingCheckoutView.as_view(), name="billing-checkout"),
    path("portal/", BillingPortalView.as_view(), name="billing-portal"),
    path(
        "support/entitlements/",
        BillingEntitlementSupportView.as_view(),
        name="billing-entitlement-support",
    ),
    path("webhooks/stripe/", StripeWebhookView.as_view(), name="billing-stripe-webhook"),
]
