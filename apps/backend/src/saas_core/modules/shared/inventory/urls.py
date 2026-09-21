from django.urls import path

from .views import (
    InventoryAdjustView,
    InventoryBalanceView,
    InventoryIssueView,
    InventoryItemDetailView,
    InventoryItemListView,
    InventoryMovementView,
    InventoryReceiptView,
    InventoryReturnView,
)

app_name = "inventory"

urlpatterns = [
    path("items/", InventoryItemListView.as_view(), name="item-list"),
    path("items/<uuid:item_id>/", InventoryItemDetailView.as_view(), name="item-detail"),
    path("balances/", InventoryBalanceView.as_view(), name="balances"),
    path("movements/", InventoryMovementView.as_view(), name="movements"),
    path("receipts/", InventoryReceiptView.as_view(), name="receipts"),
    path("issues/", InventoryIssueView.as_view(), name="issues"),
    path("returns/", InventoryReturnView.as_view(), name="returns"),
    path("adjustments/", InventoryAdjustView.as_view(), name="adjustments"),
]
