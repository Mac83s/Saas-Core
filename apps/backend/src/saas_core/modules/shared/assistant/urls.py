from django.urls import path

from .views import (
    AssistantOfferView,
    ConversationDetailView,
    ConversationListView,
    TurnConsentView,
    TurnCreateView,
)

urlpatterns = [
    path("offer/", AssistantOfferView.as_view(), name="assistant-offer"),
    path("conversations/", ConversationListView.as_view(), name="assistant-conversations"),
    path(
        "conversations/<uuid:conversation_id>/",
        ConversationDetailView.as_view(),
        name="assistant-conversation",
    ),
    path(
        "conversations/<uuid:conversation_id>/turns/",
        TurnCreateView.as_view(),
        name="assistant-turns",
    ),
    path(
        "conversations/<uuid:conversation_id>/turns/<uuid:turn_id>/consents/",
        TurnConsentView.as_view(),
        name="assistant-turn-consents",
    ),
]
