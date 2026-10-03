"""Support for the R3 candidate-screen tests (docs/sdlc/copytrade-v1/05-test-plan-R3.md).

Real components end to end (the F6 manager, ``PacedInputs``, the backfiller, F3's REST client and rate budget, F5's
scorer); the only doubles are the true boundaries: HTTP (the loopback ``FakeHl`` of ``r1_world``, which serves crafted
``userFillsByTime`` pages exactly like the exchange: earliest first, 2 000 rows a page, ``startTime`` inclusive), the
clock, the sleeper, the candle source, the leaderboard source, the open-share and state sources and the score store.

Nothing here decides an outcome of the code under test. Leaderboard rows are built from exact Decimal figures so a
threshold can be hit exactly; fills are built from real round trips (open, then close) in the recorded wire shape.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from copytrade.hl.budget import request_weight
from tests.hl.support import T0, Call, ok
from tests.selection.helpers import w
from tests.selection.r1_world import (
    DAY,
    PAGE,
    ManagerWorld,
    make_manager_world,
    r1_fixture,
)

HOUR = 3_600_000
MINUTE = 60_000
WINDOW_DAYS = 180  # scoring.window_days in the fixture config
K = 50  # scoring.candidates_k floor: tests pin it explicitly
SCREEN_EVENT = "candidate_screened"
PREFILTER_EVENT = "candidate_prefilter"
D = Decimal

_TEMPLATE = json.loads(
    (Path(__file__).resolve().parent.parent / "fixtures/exchange/hl/leaderboard.json").read_text()
)["leaderboardRows"][0]
_BASE_FILL = r1_fixture()[0]


# --- leaderboard rows ----------------------------------------------------------------------------------------------


def _s(value: Decimal | int | str) -> str:
    return format(value, "f") if isinstance(value, Decimal) else str(value)


def row(
    address: str,
    *,
    av: Decimal | int | str | None = 50_000,
    turn_m: Decimal | int = 8,
    vlm_month: Decimal | int | str | None = None,
    vlm_day: Decimal | int | str | None = None,
    vlm_week: Decimal | int | str = 200_000,
    vlm_prior: Decimal | int | str = 1_600_000,
    bps_m: Decimal | int | str = 50,
    bps_p: Decimal | int | str = 50,
    pnl_month: Decimal | int | str | None = None,
    pnl_prior: Decimal | int | str | None = None,
    pnl_day: Decimal | int | str = 100,
    pnl_week: Decimal | int | str = 1_000,
    drop: Sequence[str] = (),
    set_raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A leaderboard row of the recorded shape. Defaults pass every stage-1 rule (P1-P8) with K1 = 50.

    ``av`` x ``turn_m`` is the month volume unless ``vlm_month`` is given; month and prior P&L follow from ``bps_m`` and
    ``bps_p`` (basis points per traded dollar, exact in Decimal) unless ``pnl_month`` / ``pnl_prior`` are given.
    ``all-time`` figures are month + prior. ``drop`` removes fields: ``"av"`` or ``"<window>.<pnl|vlm|roi>"``.
    ``set_raw`` replaces whole raw values by the same names (a ``"window.field"`` or ``"av"`` key), for junk values.
    """
    av_d = None if av is None else D(_s(av))
    month_vlm = D(_s(vlm_month)) if vlm_month is not None else (av_d or D(50_000)) * D(_s(turn_m))
    day_vlm = D(_s(vlm_day)) if vlm_day is not None else D(1_000)
    prior_vlm = D(_s(vlm_prior))
    month_pnl = D(_s(pnl_month)) if pnl_month is not None else month_vlm * D(_s(bps_m)) / D(10_000)
    prior_pnl = D(_s(pnl_prior)) if pnl_prior is not None else prior_vlm * D(_s(bps_p)) / D(10_000)
    figures: dict[str, tuple[str, str]] = {
        "day": (_s(pnl_day), _s(day_vlm)),
        "week": (_s(pnl_week), _s(vlm_week)),
        "month": (_s(month_pnl), _s(month_vlm)),
        "allTime": (_s(month_pnl + prior_pnl), _s(month_vlm + prior_vlm)),
    }
    raw_over = set_raw or {}
    perf: list[list[Any]] = []
    for name, (pnl, vlm) in figures.items():
        cell: dict[str, str] = {"pnl": pnl, "roi": "0.1", "vlm": vlm}
        for field_name in ("pnl", "vlm", "roi"):
            if f"{name}.{field_name}" in drop:
                cell.pop(field_name)
            if f"{name}.{field_name}" in raw_over:
                cell[field_name] = raw_over[f"{name}.{field_name}"]
        perf.append([name, cell])
    out: dict[str, Any] = {**_TEMPLATE, "ethAddress": address, "windowPerformances": perf}
    if av_d is None or "av" in drop:
        out.pop("accountValue", None)
    else:
        out["accountValue"] = raw_over.get("av", _s(av_d))
    return out


def board(rows: Sequence[dict[str, Any]], *, total: int = 1000) -> bytes:
    """A leaderboard body: ``rows`` in the order given, then filler wallets that FAIL stage 1 (month volume 0.8 x account
    value, below P4) up to ``total`` rows (the manager treats fewer than 1 000 rows as an outage)."""
    out = list(rows)
    i = 0
    while len(out) < total:
        out.append({**_TEMPLATE, "ethAddress": w(1_000_000 + i), "accountValue": "50000.0"})
        i += 1
    return json.dumps({"leaderboardRows": out}).encode()


# --- fills ---------------------------------------------------------------------------------------------------------


class Tids:
    """Unique ids for one wallet's fills."""

    def __init__(self, start: int = 1) -> None:
        self._next = start

    def take(self) -> int:
        self._next += 1
        return self._next - 1


def fill(
    coin: str,
    side: str,
    sz: str,
    px: str,
    time_ms: int,
    start: str,
    tids: Tids,
    *,
    crossed: bool = True,
    direction: str = "Open Long",
    closed_pnl: str = "0.0",
) -> dict[str, Any]:
    tid = tids.take()
    out = dict(_BASE_FILL)
    out.update(
        coin=coin, side=side, sz=sz, px=px, time=time_ms, startPosition=start, crossed=crossed, dir=direction,
        closedPnl=closed_pnl, tid=tid, oid=10_000_000 + tid, hash="0x" + f"{tid:064x}",
    )
    return out


def trip(
    tids: Tids,
    open_ms: int,
    close_ms: int | None,
    *,
    coin: str = "BTC",
    sz: str = "1",
    px: str = "2000",
    open_crossed: bool = True,
    close_crossed: bool = True,
) -> list[dict[str, Any]]:
    """One long round trip: an open fill and (unless ``close_ms`` is None, an OPEN trip) a closing fill. Each fill has
    notional ``sz`` x ``px``: the default 2 000 USD."""
    rows = [fill(coin, "B", sz, px, open_ms, "0.0", tids, crossed=open_crossed)]
    if close_ms is not None:
        rows.append(
            fill(coin, "A", sz, px, close_ms, sz, tids, crossed=close_crossed, direction="Close Long", closed_pnl="1.0")
        )
    return rows


def good_trips(
    t: int,
    n: int = 160,
    *,
    first_ago: int = 100 * DAY,
    last_ago: int = 2 * DAY,
    hold_ms: int = HOUR,
    tids: Tids | None = None,
    open_px: Callable[[int], str] | None = None,
    open_crossed: Callable[[int], bool] | None = None,
    close_crossed: Callable[[int], bool] | None = None,
    coin: str = "BTC",
) -> list[dict[str, Any]]:
    """``n`` closed trips of ``coin`` spread evenly from ``t - first_ago`` (the first open is exactly there) to
    ``t - last_ago``, each held ``hold_ms``, 2 000 USD per fill unless ``open_px`` says otherwise. All taker by default."""
    tids = tids or Tids()
    step = (first_ago - last_ago) // max(n - 1, 1)
    rows: list[dict[str, Any]] = []
    for k in range(n):
        at = t - first_ago + k * step
        rows += trip(
            tids, at, at + hold_ms, coin=coin, px=open_px(k) if open_px else "2000",
            open_crossed=open_crossed(k) if open_crossed else True,
            close_crossed=close_crossed(k) if close_crossed else True,
        )
    return rows


def non_core(tids: Tids, time_ms: int, notional: Decimal | int, *, coin: str = "@107", crossed: bool = True) -> dict[str, Any]:
    """One fill outside the v1 universe (spot index, ``A/B`` spot pair or ``dex:COIN`` HIP-3 name) of the given USD
    notional: size ``notional / 2000`` at price 2000."""
    sz = D(notional) / D(2000)
    return fill(coin, "B", format(sz, "f"), "2000", time_ms, "0.0", tids, crossed=crossed, direction="Buy")


def pad_to_full(rows: list[dict[str, Any]], tids: Tids, first_ms: int, last_ms: int) -> list[dict[str, Any]]:
    """Add tiny non-core fills (USD 0.002 each: the core share stays ~1) to reach a FULL page of exactly 2 000 rows. The
    first and last padding fills sit at ``first_ms`` and ``last_ms``, the rest in between; all times unique."""
    need = PAGE - len(rows)
    assert need >= 2, "too many rows for a full page"
    pads = []
    for k in range(need):
        at = first_ms + (last_ms - first_ms) * k // (need - 1)
        pads.append(fill("@107", "B", "0.000001", "2000", at, "0.0", tids, direction="Buy"))
    out = [*rows, *pads]
    assert len(out) == PAGE
    return out


def full_short_page(first_ms: int, span_ms: int, *, coin: str = "BTC") -> list[dict[str, Any]]:
    """2 000 core fills (one per slot) spanning exactly ``span_ms`` from ``first_ms``: a too-active wallet."""
    tids = Tids()
    return [
        fill(coin, "B", "0.01", "2000", first_ms + span_ms * k // (PAGE - 1), "0.0", tids) for k in range(PAGE)
    ]


# --- the world -----------------------------------------------------------------------------------------------------


@dataclass
class R3:
    mw: ManagerWorld
    served: list[tuple[int, str, int]] = field(default_factory=list)  # (t_ms, wallet, rows served) per fills call
    refusals: list[tuple[int, float]] = field(default_factory=list)  # (t_ms, wait seconds) per budget refusal

    @property
    def world(self) -> Any:
        return self.mw.world

    @property
    def clock(self) -> Any:
        return self.mw.world.clock

    def serve_at(self, wallet: str, build: Callable[[int], list[dict[str, Any]]]) -> None:
        """Serve ``build(call time)`` as the wallet's whole history (so a fact like 'the first fill is exactly 60 days
        before the screen' holds whatever the clock says), sliced like the exchange: ``startTime`` inclusive,
        ``endTime`` inclusive when given, earliest first, 2 000 rows."""

        def rule(call: Call) -> Any:
            rows = sorted(build(call.t_ms), key=lambda r: (r["time"], r["tid"]))
            lo, hi = call.body["startTime"], call.body.get("endTime")
            chosen = [r for r in rows if r["time"] >= lo and (hi is None or r["time"] <= hi)][:PAGE]
            self.served.append((call.t_ms, wallet, len(chosen)))
            return ok(chosen)

        self.world.hl.rules[(wallet, "userFillsByTime")] = rule

    def serve(self, wallet: str, rows: list[dict[str, Any]]) -> None:
        self.serve_at(wallet, lambda _t: rows)

    def set_board(self, rows: Sequence[dict[str, Any]], *, total: int = 1000) -> None:
        self.mw.board.outcome = board(rows, total=total)

    def cycle(self, ticks: int = 0) -> Any:
        report = self.mw.manager.run_cycle(p95_latency_s=None)
        self.drive(ticks)
        return report

    def drive(self, ticks: int, tick_s: int = 10) -> None:
        """What the runner does: one paced slice every ``tick_s`` seconds of fake time."""
        for _ in range(ticks):
            self.mw.inputs.work()
            self.world.tick(tick_s)

    def drive_until_complete(self, max_ticks: int = 600, tick_s: int = 10) -> int:
        for n in range(1, max_ticks + 1):
            self.mw.inputs.work()
            if self.mw.inputs.complete:
                return n
            self.world.tick(tick_s)
        raise AssertionError(f"the pass did not complete in {max_ticks} slices")

    def advance_h(self, hours: float) -> None:
        self.clock.advance(int(hours * HOUR))

    # --- observations over the HTTP boundary ---
    def fills_calls(self, wallet: str | None = None) -> list[Call]:
        return self.world.fills_calls(wallet)

    def screen_calls(self, wallet: str | None = None) -> list[Call]:
        """Fills requests that start at the scoring window start: a screen or a backfill page 1 (never an incremental
        page, which starts at a fill time)."""
        return [
            c for c in self.fills_calls(wallet)
            if abs(c.body["startTime"] - (c.t_ms - WINDOW_DAYS * DAY)) <= 5 * MINUTE
        ]

    def screened_order(self) -> list[str]:
        """Wallets in the order of their FIRST window-start fills request."""
        seen: list[str] = []
        for c in self.screen_calls():
            if c.body["user"] not in seen:
                seen.append(c.body["user"])
        return seen

    def calls_of(self, rtype: str, wallet: str | None = None) -> list[Call]:
        return [
            c for c in self.world.http.calls
            if c.body["type"] == rtype and (wallet is None or c.body.get("user") == wallet)
        ]

    def backfilled(self) -> set[str]:
        """Wallets that received any non-fills per-wallet request (portfolio, clearinghouseState, userRole)."""
        return {
            c.body["user"] for c in self.world.http.calls
            if c.body["type"] in ("portfolio", "clearinghouseState", "userRole") and "user" in c.body
        }

    def weight_of(self, call: Call, rows: int) -> int:
        return request_weight(call.body["type"], rows, self.world.cfg)

    def install_refusal_log(self) -> None:
        sleeper = self.world.sleeper
        original = sleeper.sleep

        def sleep(seconds: float) -> None:
            self.refusals.append((self.clock.now_ms(), seconds))
            original(seconds)

        sleeper.sleep = sleep


def make_r3(tmp_path: Path, *, fail_fast: bool = True, k: int = K, **overrides: Any) -> R3:
    """The PO's wiring (fail-fast scoring client) with ``scoring.candidates_k`` = ``k``."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    mw = make_manager_world(tmp_path, fail_fast=fail_fast, scoring__candidates_k=k, **overrides)
    r3 = R3(mw)
    if fail_fast:
        r3.install_refusal_log()
    return r3


# --- log helpers ---------------------------------------------------------------------------------------------------

_TOKEN = re.compile(r"(\w+)=(\S+)")


def tokens(record: logging.LogRecord) -> dict[str, str]:
    """``key=value`` tokens of the MESSAGE text (what the PO reads on the console)."""
    return dict(_TOKEN.findall(record.getMessage()))


def records(caplog: pytest.LogCaptureFixture, event: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "event", None) == event]


def screen_lines(caplog: pytest.LogCaptureFixture, wallet: str | None = None) -> list[dict[str, str]]:
    out = []
    for rec in records(caplog, SCREEN_EVENT):
        assert rec.levelno >= logging.INFO  # readable on the INFO console
        toks = tokens(rec)
        if wallet is None or toks.get("wallet") == wallet:
            out.append(toks)
    return out


def id_set(text: str | None) -> set[str]:
    """``"S3,S4"`` -> {"S3", "S4"}; ``"none"`` / missing -> empty."""
    if text is None or text == "none":
        return set()
    return set(text.split(","))


def verdict(caplog: pytest.LogCaptureFixture, wallet: str) -> dict[str, Any]:
    """The one screen line of ``wallet`` as {outcome, failed, not_evaluable}."""
    lines = screen_lines(caplog, wallet)
    assert len(lines) == 1, f"expected exactly one '{SCREEN_EVENT}' line for {wallet}, got {len(lines)}"
    (line,) = lines
    return {
        "outcome": line.get("outcome"),
        "failed": id_set(line.get("failed")),
        "not_evaluable": id_set(line.get("not_evaluable")),
    }


def ranked_wallets(n: int, *, first: int = 1) -> list[str]:
    return [w(i) for i in range(first, first + n)]


def ok_page(t: int = T0, **kw: Any) -> list[dict[str, Any]]:
    """A page that passes S1-S9 for a wallet with the default row (AV 50 000): 160 closed taker trips of 2 000 USD
    per fill, held 1 h, first core fill 100 days before ``t``, 320 rows."""
    return good_trips(t, **kw)


# --- crafted pages: each fails exactly one screen rule (AV 50 000 row, screen at ``t``) ---------------------------


def full_page(
    t: int,
    core_rows: list[dict[str, Any]],
    tids: Tids,
    *,
    first_ago: int = 100 * DAY,
    span_ms: int = 50 * DAY,
) -> list[dict[str, Any]]:
    """A FULL page (2 000 rows): ``core_rows`` plus tiny non-core padding so that the earliest row is at
    ``t - first_ago`` and the latest exactly ``span_ms`` after it. ``core_rows`` must start at ``t - first_ago``."""
    first = t - first_ago
    assert min(r["time"] for r in core_rows) == first
    assert max(r["time"] for r in core_rows) < first + span_ms
    return pad_to_full(core_rows, tids, first + 1, first + span_ms)


def trips_in(
    t: int, n: int, *, first_ago: int, span_ms: int, hold_ms: int = HOUR, tids: Tids, coin: str = "BTC"
) -> list[dict[str, Any]]:
    """``n`` closed 2 000 USD trips from ``t - first_ago`` to two days before ``first + span``."""
    return good_trips(
        t, n, first_ago=first_ago, last_ago=first_ago - span_ms + 2 * DAY, hold_ms=hold_ms, tids=tids, coin=coin
    )


def page_ok_full(t: int, *, n_trips: int = 40, span_ms: int = 50 * DAY, hold_ms: int = HOUR) -> list[dict[str, Any]]:
    """A full page that passes S1-S8 (S9 is not evaluable on a full page): rate 40 fills a day over 180 d < 10 000."""
    tids = Tids()
    core = trips_in(t, n_trips, first_ago=100 * DAY, span_ms=span_ms, hold_ms=hold_ms, tids=tids)
    return full_page(t, core, tids, span_ms=span_ms)


def page_s1(t: int) -> list[dict[str, Any]]:
    return []


def page_s2(t: int, span_ms: int = DAY - 1) -> list[dict[str, Any]]:
    return full_short_page(t - 10 * DAY, span_ms)


def page_s3(t: int, extra_usd: int = 642_000) -> list[dict[str, Any]]:
    """Core notional 640 000 (160 trips x 2 fills x 2 000); the non-core fills add ``extra_usd`` (core share 0.4992)."""
    tids = Tids()
    rows = good_trips(t, tids=tids)
    rows.append(non_core(tids, t - 50 * DAY, extra_usd))
    return rows


def page_s4(t: int, makers: int = 225) -> list[dict[str, Any]]:
    """``makers`` of the 320 core fills are maker fills of 2 000 USD: 224 = exactly 0.70, 225 = 0.703."""
    n_close = makers - 160
    return good_trips(t, open_crossed=lambda k: False, close_crossed=lambda k: k >= n_close)


def page_s5(t: int, first_ago: int = 59 * DAY) -> list[dict[str, Any]]:
    return good_trips(t, first_ago=first_ago)


def page_s6(t: int, span_ms: int = 30 * DAY) -> list[dict[str, Any]]:
    """Full page over ``span_ms``: 2 000 / span x 180 d = 12 000 fills a window at 30 days (>= 10 000)."""
    return page_ok_full(t, span_ms=span_ms)


def page_s7(t: int, hold_ms: int = 899_999) -> list[dict[str, Any]]:
    return good_trips(t, hold_ms=hold_ms)


def page_s8(t: int, exec_trips: int = 79) -> list[dict[str, Any]]:
    """160 trips, ``exec_trips`` of them 2 000 USD (>= the 1 667 USD an executable open needs at AV 50 000) and the rest
    100 USD: 79 / 160 = 0.494 fails, 80 / 160 = 0.5 passes."""
    return good_trips(t, open_px=lambda k: "2000" if k < exec_trips else "100")


def page_s9(t: int, n: int = 149) -> list[dict[str, Any]]:
    return good_trips(t, n)


FAILING_PAGES: dict[str, Callable[[int], list[dict[str, Any]]]] = {
    "S3": page_s3, "S4": page_s4, "S5": page_s5, "S6": page_s6, "S7": page_s7, "S8": page_s8, "S9": page_s9,
}


def ranked_rows(n: int, *, first: int = 1, bps: int = 50) -> list[dict[str, Any]]:
    """``n`` rows with the same K1 and a higher all-time pnl for a higher number: rank order is last, ..., first."""
    return [
        row(w(i), bps_m=bps, bps_p=bps, vlm_prior=1_600_000 + i * 1_000) for i in range(first, first + n)
    ]


# --- log capture stamped with the fake clock -----------------------------------------------------------------------


class Stamped(logging.Handler):
    """Collects (fake clock ms at emit time, record) of every INFO+ record: how often a line is logged is observable."""

    def __init__(self, clock: Any) -> None:
        super().__init__(logging.INFO)
        self.clock = clock
        self.items: list[tuple[int, logging.LogRecord]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.items.append((self.clock.now_ms(), record))

    def lines(self, pattern: str) -> list[tuple[int, str]]:
        rx = re.compile(pattern)
        return [(t, rec.getMessage()) for t, rec in self.items if rx.search(rec.getMessage())]


@contextmanager
def stamped(r3: R3) -> Iterator[Stamped]:
    handler = Stamped(r3.clock)
    root = logging.getLogger()
    previous = root.level
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)
