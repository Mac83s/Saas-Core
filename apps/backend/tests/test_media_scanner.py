from __future__ import annotations

import struct
from typing import Self

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from saas_core.modules.shared.media.scanner import (
    ClamdMalwareScanner,
    MalwareScannerUnavailable,
    MalwareVerdict,
)


class FakeConnection:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.sent = bytearray()
        self.timeout: float | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def sendall(self, content: bytes) -> None:
        self.sent.extend(content)

    def recv(self, size: int) -> bytes:
        response, self.response = self.response[:size], self.response[size:]
        return response


@pytest.mark.parametrize(
    ("response", "verdict"),
    [
        (b"stream: OK\0", MalwareVerdict.CLEAN),
        (b"stream: Test-Signature FOUND\0", MalwareVerdict.INFECTED),
    ],
)
def test_clamd_scanner_uses_bounded_instream_protocol(
    monkeypatch: pytest.MonkeyPatch,
    response: bytes,
    verdict: MalwareVerdict,
) -> None:
    connection = FakeConnection(response)
    monkeypatch.setattr(
        "saas_core.modules.shared.media.scanner.socket.create_connection",
        lambda address, timeout: connection,
    )
    content = b"safe image bytes"

    result = ClamdMalwareScanner().scan(content)

    assert result == verdict
    assert connection.timeout == 30
    assert connection.sent.startswith(b"zINSTREAM\0")
    payload = connection.sent.removeprefix(b"zINSTREAM\0")
    length = struct.unpack("!I", payload[:4])[0]
    assert length == len(content)
    assert payload[4 : 4 + length] == content
    assert payload[4 + length :] == struct.pack("!I", 0)


@pytest.mark.parametrize("response", [b"stream: protocol error ERROR\0", b"x" * 4097])
def test_clamd_scanner_fails_closed_for_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    response: bytes,
) -> None:
    connection = FakeConnection(response)
    monkeypatch.setattr(
        "saas_core.modules.shared.media.scanner.socket.create_connection",
        lambda address, timeout: connection,
    )

    with pytest.raises(MalwareScannerUnavailable):
        ClamdMalwareScanner().scan(b"content")


class VerdictScanner:
    def __init__(self, verdict: MalwareVerdict) -> None:
        self.verdict = verdict

    def scan(self, content: bytes) -> MalwareVerdict:
        assert content == b"saas-core-malware-scanner-health-check"
        return self.verdict


def test_malware_scanner_management_check_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "saas_core.modules.shared.media.management.commands.check_malware_scanner.get_malware_scanner",
        lambda: VerdictScanner(MalwareVerdict.CLEAN),
    )
    call_command("check_malware_scanner")

    monkeypatch.setattr(
        "saas_core.modules.shared.media.management.commands.check_malware_scanner.get_malware_scanner",
        lambda: VerdictScanner(MalwareVerdict.INFECTED),
    )
    with pytest.raises(CommandError):
        call_command("check_malware_scanner")
