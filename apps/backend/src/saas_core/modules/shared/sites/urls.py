from django.urls import path

from .views import PageDraftView, PageListCreateView, SiteListCreateView

app_name = "sites"

urlpatterns = [
    path("", SiteListCreateView.as_view(), name="list-create"),
    path("<uuid:site_id>/pages/", PageListCreateView.as_view(), name="page-list-create"),
    path("pages/<uuid:page_id>/draft/", PageDraftView.as_view(), name="page-draft"),
]
