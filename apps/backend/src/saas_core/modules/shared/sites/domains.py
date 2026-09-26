from __future__ import annotations

import ipaddress
import re

import idna


class InvalidHostname(ValueError):
    pass


_FORBIDDEN_HOST_CHARACTERS = re.compile(r"[\x00-\x20/\\@?#]")


def normalize_hostname(value: str, *, allow_port: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise InvalidHostname("Hostname jest pusty albo zawiera białe znaki.")
    if _FORBIDDEN_HOST_CHARACTERS.search(value):
        raise InvalidHostname("Hostname zawiera niedozwolone znaki.")

    hostname = value
    if hostname.startswith("["):
        raise InvalidHostname("Adres IP nie może być domeną site.")
    if ":" in hostname:
        if not allow_port or hostname.count(":") != 1:
            raise InvalidHostname("Hostname zawiera niedozwolony port.")
        hostname, port_text = hostname.rsplit(":", 1)
        if not port_text.isascii() or not port_text.isdigit():
            raise InvalidHostname("Port hosta jest nieprawidłowy.")
        port = int(port_text)
        if not 1 <= port <= 65535:
            raise InvalidHostname("Port hosta jest poza zakresem.")

    # `lower`, not `casefold`: casefolding turns `ß` into `ss` and final `ς`
    # into `σ`, which IDNA2008 keeps as letters of their own, so `straße.de`
    # would compare equal to `strasse.de` although a browser opens another
    # domain. UTS46 below does the rest of the case mapping the browser does.
    hostname = hostname.rstrip(".").lower()
    if not hostname or hostname.startswith(".") or ".." in hostname:
        raise InvalidHostname("Hostname ma nieprawidłowe etykiety.")
    try:
        ascii_hostname = idna.encode(
            hostname,
            uts46=True,
            std3_rules=True,
        ).decode("ascii")
    except idna.IDNAError as error:
        raise InvalidHostname("Hostname nie jest prawidłową nazwą IDNA.") from error
    if len(ascii_hostname) > 253:
        raise InvalidHostname("Hostname jest za długi.")
    if any(not label or len(label) > 63 for label in ascii_hostname.split(".")):
        raise InvalidHostname("Etykieta hostname jest nieprawidłowa.")
    try:
        ipaddress.ip_address(ascii_hostname)
    except ValueError:
        return ascii_hostname
    raise InvalidHostname("Adres IP nie może być domeną site.")


def verification_record_name(hostname: str) -> str:
    return f"_saas-core.{normalize_hostname(hostname)}"


_TAB_OR_NEWLINE = re.compile(r"[\t\n\r]")
_C0_OR_SPACE = "".join(map(chr, range(0x21)))
_SCHEME = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*):")
_AUTHORITY_END = re.compile(r"[/?#]")


def link_host(href: str) -> str | None:
    """The host a link takes a visitor to, or `None` when it has none.

    Read the way a browser reads it (WHATWG URL), not the way `urlsplit` does,
    because the browser is what follows the link: tabs and newlines vanish, a
    backslash is a slash, any run of slashes after the scheme is skipped, and
    userinfo and port are not the host. So `//evil.test`, `/\\evil.test`,
    `https:///evil.test` and `https://allowed.test@evil.test` all answer
    `evil.test`.

    A path, query or in-page anchor stays on the site, and `mailto:`/`tel:` open
    the visitor's own mail or phone app rather than somebody's website; all of
    them answer `None`. Any other scheme answers with the whole link, which no
    host list names, so an unknown kind of link fails closed. A host that is
    not a valid name comes back as written, for the same reason.
    """
    value = _TAB_OR_NEWLINE.sub("", href).strip(_C0_OR_SPACE).replace("\\", "/")
    scheme = _SCHEME.match(value)
    if scheme is None:
        if not value.startswith("//"):
            return None
        rest = value
    else:
        name = scheme.group(1).casefold()
        if name in {"mailto", "tel"}:
            return None
        if name not in {"http", "https"}:
            return value
        rest = value[scheme.end():]
    authority = _AUTHORITY_END.split(rest.lstrip("/"), maxsplit=1)[0]
    host = authority.rpartition("@")[2]
    if not host.startswith("["):
        host = host.partition(":")[0]
    try:
        return normalize_hostname(host)
    except InvalidHostname:
        return host or value
