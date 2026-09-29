"""Suite-wide test harness (F1; shared, later changes are CTO-serialized).

1. Network guard (F1.AC3, and the "no live network in tests" rule). Every outbound connection or DNS
   lookup to a non-loopback host is blocked and recorded; any such attempt fails the test that made
   it, and the session. Loopback stays open for later features' local stubs. Because nothing can
   leave the machine, 0 requests reach the Hyperliquid ``/exchange`` endpoint in any test run.
2. Secret canaries (F1.AC5). Every secret environment variable is set to a canary value for the whole
   session, and every log record emitted anywhere in the suite is captured. At session end, any
   canary fragment in the captured logs fails the run. Later features add their own sinks (ledger,
   Telegram payloads, LLM prompts) to ``SECRET_SINKS``.
3. Hypothesis runs derandomized (seeded) so failures reproduce on every machine.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import pytest
from hypothesis import HealthCheck, settings

from tests.harness import CANARY_SECRETS, find_canary_leaks

settings.register_profile(
    "copytrade",
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("copytrade")


# --------------------------------------------------------------------------------------------------
# 1. Network guard
# --------------------------------------------------------------------------------------------------

class NetworkBlockedError(OSError):
    """Raised instead of opening a non-loopback connection during tests."""


def _host_of(address: object) -> str | None:
    if isinstance(address, tuple) and address:
        return str(address[0])
    return None  # AF_UNIX paths and other non-IP families


def _is_loopback_host(host: str | None) -> bool:
    if host is None:
        return True
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _is_numeric_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return True


@dataclass
class NetworkGuard:
    """Records every blocked network attempt. ``attempts`` holds (operation, target) pairs."""

    attempts: list[tuple[str, str]] = field(default_factory=list)
    all_connects: list[tuple[str, str]] = field(default_factory=list)  # loopback included

    def record_blocked(self, operation: str, target: str) -> None:
        self.attempts.append((operation, target))

    @contextmanager
    def expect_blocked(self) -> Iterator[list[tuple[str, str]]]:
        """Use in the guard's own self-test: attempts made inside are expected and not held against the test."""
        start = len(self.attempts)
        seen: list[tuple[str, str]] = []
        try:
            yield seen
        finally:
            seen.extend(self.attempts[start:])
            del self.attempts[start:]


_GUARD = NetworkGuard()


@pytest.fixture(scope="session", autouse=True)
def _network_guard_installed() -> Iterator[NetworkGuard]:
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self: socket.socket, address: object) -> None:
        host = _host_of(address)
        _GUARD.all_connects.append(("connect", repr(address)))
        if not _is_loopback_host(host):
            _GUARD.record_blocked("connect", repr(address))
            raise NetworkBlockedError(f"test network guard blocked a connection to {address!r}")
        return real_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: object) -> int:
        host = _host_of(address)
        _GUARD.all_connects.append(("connect_ex", repr(address)))
        if not _is_loopback_host(host):
            _GUARD.record_blocked("connect_ex", repr(address))
            raise NetworkBlockedError(f"test network guard blocked a connection to {address!r}")
        return real_connect_ex(self, address)

    def guarded_getaddrinfo(host: object, *args: object, **kwargs: object) -> list:  # type: ignore[type-arg]
        name = None if host is None else (host.decode() if isinstance(host, bytes) else str(host))
        if name is not None and not _is_loopback_host(name) and not _is_numeric_host(name):
            _GUARD.record_blocked("getaddrinfo", name)
            raise socket.gaierror(socket.EAI_NONAME, f"test network guard blocked a DNS lookup of {name!r}")
        return real_getaddrinfo(host, *args, **kwargs)  # type: ignore[arg-type]

    mp = pytest.MonkeyPatch()
    mp.setattr(socket.socket, "connect", guarded_connect)
    mp.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    mp.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    try:
        yield _GUARD
    finally:
        mp.undo()


@pytest.fixture(autouse=True)
def _fail_test_on_blocked_network(_network_guard_installed: NetworkGuard) -> Iterator[None]:
    start = len(_GUARD.attempts)
    yield
    blocked = _GUARD.attempts[start:]
    if blocked:
        pytest.fail(f"test attempted non-loopback network access (blocked): {blocked}", pytrace=False)


@pytest.fixture
def network_guard(_network_guard_installed: NetworkGuard) -> NetworkGuard:
    return _network_guard_installed


# --------------------------------------------------------------------------------------------------
# 2. Secret canaries
# --------------------------------------------------------------------------------------------------

class _CaptureAllHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.chunks: list[str] = []
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.chunks.append(self.format(record))
        except Exception:  # a record that cannot even be formatted is still captured raw
            self.chunks.append(repr(record.__dict__))


_LOG_CAPTURE = _CaptureAllHandler()

# Sinks later features register: callables returning all text they emitted during the session.
SECRET_SINKS: dict[str, Callable[[], str]] = {"logs": lambda: "\n".join(_LOG_CAPTURE.chunks)}


@pytest.fixture(scope="session", autouse=True)
def _canary_environment() -> Iterator[dict[str, str]]:
    mp = pytest.MonkeyPatch()
    for name, value in CANARY_SECRETS.items():
        mp.setenv(name, value)
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(_LOG_CAPTURE)
    root.setLevel(logging.DEBUG)
    try:
        yield dict(CANARY_SECRETS)
    finally:
        root.removeHandler(_LOG_CAPTURE)
        root.setLevel(old_level)
        mp.undo()


@pytest.fixture
def canary_secrets(_canary_environment: dict[str, str]) -> dict[str, str]:
    return dict(_canary_environment)


@pytest.fixture
def captured_log_text() -> Callable[[], str]:
    return lambda: "\n".join(_LOG_CAPTURE.chunks)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    problems: list[str] = []
    for sink, read in SECRET_SINKS.items():
        leaks = find_canary_leaks(read())
        if leaks:
            problems.append(f"F1.AC5: canary secrets {leaks} leaked into {sink}")
    if _GUARD.attempts:
        problems.append(f"F1.AC3: blocked network attempts during the session: {_GUARD.attempts}")
    if problems:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        for p in problems:
            if reporter is not None:
                reporter.write_line(p, red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
