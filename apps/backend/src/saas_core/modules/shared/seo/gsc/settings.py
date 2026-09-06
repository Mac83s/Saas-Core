"""Operator-owned OAuth destination; callers cannot redirect authorization elsewhere."""

from urllib.parse import parse_qs, urlsplit

from django.conf import settings

from ..source import SeoUnavailable, SourceError


def redirect_uri() -> str:
    value = str(getattr(settings, "SEO_GSC_REDIRECT_URI", ""))
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"})
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path != "/api/v1/seo/gsc/callback/"
    ):
        raise SeoUnavailable(detail="Search Console OAuth redirect is not configured.")
    return value


def authorization_url(value: str, state: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise SourceError("gsc_authorization_malformed", retryable=False) from error
    query = parse_qs(parsed.query)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "accounts.google.com"
        or parsed.path not in {"/o/oauth2/auth", "/o/oauth2/v2/auth"}
        or parsed.fragment
        or query.get("state") != [state]
        or query.get("redirect_uri") != [redirect_uri()]
        or not 16 <= len(state) <= 512
    ):
        raise SourceError("gsc_authorization_mismatch", retryable=False)
    return value
