from django.urls import path

from .views import OptionsView, OrderDetailView, OrderListView

urlpatterns = [
    path("options/", OptionsView.as_view(), name="commerce-options"),
    path("orders/", OrderListView.as_view(), name="commerce-orders"),
    path("orders/<uuid:order_id>/", OrderDetailView.as_view(), name="commerce-order"),
]
