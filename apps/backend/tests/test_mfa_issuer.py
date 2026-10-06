"""The name an authenticator app shows beside the code is the product's own.

A product never set `MFA_ISSUER_NAME`, so a person of HoofCare or MedPlano
scanned the code and got an entry called „SaaS Core”.
"""

from __future__ import annotations

import json
import os
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from django.conf import settings

from saas_core.modules.core.identity.mfa import begin_totp_enrollment
from saas_core.modules.core.identity.models import User, UserStatus

pytestmark = pytest.mark.django_db


def test_the_authenticator_entry_carries_the_profiles_product_name() -> None:
    profile = json.loads(settings.DEPLOYMENT_PROFILE_PATH.read_text(encoding="utf-8"))
    expected = os.environ.get("MFA_ISSUER_NAME") or profile["product"]["name"]
    assert expected == settings.MFA_ISSUER_NAME

    user = User.objects.create_user(email="issuer@example.com", password="Bezpieczne-Haslo-2026!")
    user.status = UserStatus.ACTIVE
    user.save()
    uri = urlsplit(begin_totp_enrollment(user=user).provisioning_uri)

    assert unquote(uri.path) == f"/{expected}:issuer@example.com"
    assert parse_qs(uri.query)["issuer"] == [expected]
