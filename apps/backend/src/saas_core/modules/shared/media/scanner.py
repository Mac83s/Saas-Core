from __future__ import annotations

import socket
import struct
from enum import StrEnum
from functools import cache
from typing import Protocol

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class MalwareVerdict(StrEnum):
    CLEAN = "clean"
    INFECTED = "infected"


class MalwareScannerUnavailable(RuntimeError):
    pass


class MalwareScanner(Protocol):
    def scan(self, content: bytes) -> MalwareVerdict: ...


class ClamdMalwareScanner:
    chunk_size = 8192
    max_response_bytes = 4096

    def __init__(self) -> None:
        if not settings.CLAMAV_HOST:
            raise ImproperlyConfigured("Skaner ClamAV nie jest skonfigurowany")
        self.host = settings.CLAMAV_HOST
        self.port = settings.CLAMAV_PORT
        self.timeout = settings.CLAMAV_TIMEOUT_SECONDS

    def scan(self, content: bytes) -> MalwareVerdict:
        try:
            with socket.create_connection(
                (self.host, self.port),
                timeout=self.timeout,
            ) as connection:
                connection.settimeout(self.timeout)
                connection.sendall(b"zINSTREAM\0")
                for offset in range(0, len(content), self.chunk_size):
                    chunk = content[offset : offset + self.chunk_size]
                    connection.sendall(struct.pack("!I", len(chunk)))
                    connection.sendall(chunk)
                connection.sendall(struct.pack("!I", 0))
                response = self._receive_response(connection)
        except (OSError, TimeoutError, UnicodeDecodeError) as error:
            raise MalwareScannerUnavailable("Skaner plików jest niedostępny.") from error

        if response == "stream: OK":
            return MalwareVerdict.CLEAN
        if response.startswith("stream: ") and response.endswith(" FOUND"):
            return MalwareVerdict.INFECTED
        raise MalwareScannerUnavailable("Skaner plików zwrócił nieprawidłową odpowiedź.")

    def _receive_response(self, connection: socket.socket) -> str:
        response = bytearray()
        while len(response) <= self.max_response_bytes:
            chunk = connection.recv(min(1024, self.max_response_bytes + 1 - len(response)))
            if not chunk:
                break
            response.extend(chunk)
            if b"\0" in chunk or b"\n" in chunk:
                break
        if len(response) > self.max_response_bytes:
            raise MalwareScannerUnavailable("Odpowiedź skanera jest zbyt długa.")
        return bytes(response).rstrip(b"\0\r\n").decode("utf-8", errors="strict")


@cache
def get_malware_scanner() -> MalwareScanner:
    return ClamdMalwareScanner()
