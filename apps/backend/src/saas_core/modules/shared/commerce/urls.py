from django.urls import path

from .views import (
    OptionsView,
    OrderDetailView,
    OrderListView,
    PaymentListView,
    PaymentPreviewView,
    PaymentVoidView,
)

urlpatterns = [
    path("options/", OptionsView.as_view(), name="commerce-options"),
    path("orders/", OrderListView.as_view(), name="commerce-orders"),
    path("orders/<uuid:order_id>/", OrderDetailView.as_view(), name="commerce-order"),
    path(
        "orders/<uuid:order_id>/payments/",
        PaymentListView.as_view(),
        name="commerce-order-payments",
    ),
    path(
        "orders/<uuid:order_id>/payments/preview/",
        PaymentPreviewView.as_view(),
        name="commerce-order-payment-preview",
    ),
    path(
        "orders/<uuid:order_id>/payments/<uuid:payment_id>/void/",
        PaymentVoidView.as_view(),
        name="commerce-order-payment-void",
    ),
]
