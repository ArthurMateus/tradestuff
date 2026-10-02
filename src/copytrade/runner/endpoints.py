"""The network endpoints the runner talks to. Build constants; there is no CLI flag or config key to change them
(a test injects loopback endpoints through ``RunnerDeps``)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Endpoints:
    """``info_url`` (HTTP POST, path exactly ``/info``), ``ws_url`` (``ws(s)://``), ``leaderboard_url`` (HTTP GET, the
    stats host: full leaderboard JSON) and ``telegram_base_url`` (Bot API base, no token in it)."""

    info_url: str
    ws_url: str
    leaderboard_url: str
    telegram_base_url: str


def mainnet_endpoints() -> Endpoints:
    """The real hosts: Hyperliquid mainnet info/ws (READ-ONLY use), its stats host and api.telegram.org."""
    return Endpoints(
        info_url="https://api.hyperliquid.xyz/info",
        ws_url="wss://api.hyperliquid.xyz/ws",
        leaderboard_url="https://stats-data.hyperliquid.xyz/Mainnet/leaderboard",
        telegram_base_url="https://api.telegram.org",
    )
