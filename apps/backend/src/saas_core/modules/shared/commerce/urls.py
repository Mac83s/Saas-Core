from django.urls import path

from .views import (
    OptionsView,
    OrderDetailView,
    OrderListView,
    PaymentListView,
    PaymentPreviewView,
    PaymentVoidView,
    RefundListView,
    RefundPreviewView,
    RefundVoidView,
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
    path(
        "orders/<uuid:order_id>/refunds/",
        RefundListView.as_view(),
        name="commerce-order-refunds",
    ),
    path(
        "orders/<uuid:order_id>/refunds/preview/",
        RefundPreviewView.as_view(),
        name="commerce-order-refund-preview",
    ),
    path(
        "orders/<uuid:order_id>/refunds/<uuid:refund_id>/void/",
        RefundVoidView.as_view(),
        name="commerce-order-refund-void",
    ),
]
