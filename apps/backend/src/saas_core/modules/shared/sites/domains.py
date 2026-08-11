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

    hostname = hostname.rstrip(".").casefold()
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
