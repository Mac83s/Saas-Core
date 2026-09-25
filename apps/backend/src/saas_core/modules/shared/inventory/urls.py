from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("categories/", views.InventoryCategoryListView.as_view(), name="category-list"),
    path(
        "categories/<uuid:category_id>/",
        views.InventoryCategoryDetailView.as_view(),
        name="category-detail",
    ),
    path("locations/", views.StockLocationListView.as_view(), name="location-list"),
    path(
        "locations/<uuid:location_id>/",
        views.StockLocationDetailView.as_view(),
        name="location-detail",
    ),
    path("suppliers/", views.SupplierListView.as_view(), name="supplier-list"),
    path(
        "suppliers/<uuid:supplier_id>/",
        views.SupplierDetailView.as_view(),
        name="supplier-detail",
    ),
    path("items/", views.InventoryItemListView.as_view(), name="item-list"),
    path("items/<uuid:item_id>/", views.InventoryItemDetailView.as_view(), name="item-detail"),
    path("balances/", views.InventoryBalanceView.as_view(), name="balances"),
    path("movements/", views.InventoryMovementView.as_view(), name="movements"),
    path("lots/", views.InventoryLotView.as_view(), name="lots"),
    path("documents/", views.StockDocumentListView.as_view(), name="document-list"),
    path(
        "documents/<uuid:document_id>/",
        views.StockDocumentDetailView.as_view(),
        name="document-detail",
    ),
    path(
        "documents/<uuid:document_id>/post/",
        views.StockDocumentPostView.as_view(),
        name="document-post",
    ),
    path(
        "documents/<uuid:document_id>/correct/",
        views.StockDocumentCorrectView.as_view(),
        name="document-correct",
    ),
    path("receipts/", views.InventoryReceiptView.as_view(), name="receipts"),
    path("issues/", views.InventoryIssueView.as_view(), name="issues"),
    path("returns/", views.InventoryReturnView.as_view(), name="returns"),
    path("adjustments/", views.InventoryAdjustView.as_view(), name="adjustments"),
]
