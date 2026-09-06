from django.urls import path

from . import views

urlpatterns = [
    path("connection/", views.ConnectionView.as_view()),
    path("prepare/", views.PrepareView.as_view()),
    path("properties/", views.PropertiesView.as_view()),
    path("authorize/", views.AuthorizeView.as_view()),
    path("callback/", views.CallbackView.as_view()),
    path("grants/", views.GrantListView.as_view()),
    path("grants/<uuid:grant_id>/", views.GrantView.as_view()),
    path("grants/<uuid:grant_id>/sync/", views.SyncView.as_view()),
    path("grants/<uuid:grant_id>/metrics/", views.MetricsView.as_view()),
    path("grants/<uuid:grant_id>/revoke/", views.RevokeView.as_view()),
    path("disconnect/", views.DisconnectView.as_view()),
]
