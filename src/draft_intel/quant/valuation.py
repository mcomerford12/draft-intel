"""DI-030 — dual valuation: full-market value and live auction value.

Charter §4.3 requires two distinct valuations and is explicit that they must not be conflated.

**(i) Full-market value** -- what a player would cost in a keeper-free $2,000 / 160-slot
auction. The reference used to price the keepers themselves and to compute keeper surplus::

    VORP_i           = max(0, proj_points_i - replacement_points_full_market(i))
    pool_full        = the 160 the replacement fixed point rosters, per position
    discretionary    = 2000 - 160 = 1840
    dollars_per_vorp = discretionary / sum(VORP over pool_full)
    market_value_i   = 1 + VORP_i * dollars_per_vorp

**(ii) Live auction value** -- what a player should cost in *this* auction, with the keepers
off the board and only ``2000 - sum(K_t)`` left in the room. **This is the number the user
bids against.**::

    VORP_live_i        = max(0, proj_points_i - replacement_points_post_keeper(i))
    pool_live          = the 140 available the live fixed point rosters, per position
    total_live_money   = 2000 - sum(K_t)
    discretionary_live = total_live_money - 140
    dpv_live           = discretionary_live / sum(VORP_live over pool_live)
    baseline_value_i   = 1 + VORP_live_i * dpv_live

Both display together, because **the gap between them is the keeper inflation made concrete
per player**. A player whose live value is $58 against a $47 full-market value tells the user
at a glance what the keeper discount is costing them tonight.

Three invariants gate the whole thing. Per §4.3: "If any fails, the model is broken and the
app must refuse to present prices." :func:`value_board` enforces that rather than warning.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from draft_intel.quant.replacement import Baselines
from draft_intel.quant.scoring import PlayerProjection

MIN_BID = 1
TOLERANCE = 1.0  # charter §4.3 states the sum invariants to within $1


class InvariantViolation(Exception):
    """Raised when a valuation invariant fails. Prices must not be shown."""


class PlayerValue(BaseModel):
    """One player's two valuations, kept as separate fields and never collapsed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    player_id: str
    name: str
    position: str
    team: str | None
    points: float

    vorp: float
    market_value: float
    """Full-market value: a keeper-free $2,000 / 160-slot auction."""

    vorp_live: float
    baseline_value: float
    """Live auction value. The number to bid against. Zero for a keeper (off the board)."""

    is_keeper: bool
    in_pool_full: bool
    in_pool_live: bool

    @property
    def keeper_premium(self) -> float:
        """``baseline_value - market_value``: this player's share of the keeper inflation."""
        return round(self.baseline_value - self.market_value, 2)


class ValueBoard(BaseModel):
    """The priced board, plus the figures needed to check it by hand."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    players: tuple[PlayerValue, ...]

    total_budget: int
    keeper_spend: int
    total_live_money: int
    discretionary: int
    discretionary_live: int
    dollars_per_vorp: float
    dollars_per_vorp_live: float

    pool_full_size: int
    pool_live_size: int
    sum_market_value: float
    sum_baseline_value: float

    keeper_book_value: float
    """Sum of ``market_value`` over the keepers: what they would cost at open auction."""

    available_book_value: float
    """Sum of ``market_value`` over the non-keeper pool: the book value still on the board."""

    @property
    def keeper_surplus(self) -> float:
        """``book - paid`` across all keepers. Positive means the room got them cheap."""
        return round(self.keeper_book_value - self.keeper_spend, 2)

    @property
    def keeper_inflation(self) -> float:
        """Structural, fixed, known before the draft: live money per dollar of book value.

        Charter §4.5 defines this as "live value / full-market value". It is **not** a ratio of
        discretionary totals -- an earlier version computed ``discretionary_live /
        discretionary`` and reported 0.71x, which is the ratio of money pools and says nothing
        about what a player costs. The right comparison is the money left in the room against
        the book value of what is still on the board.

        Above 1.0 means the field should clear over book, which is what the 25% retention
        discount is supposed to produce. Below 1.0 means the keepers were retained at or above
        their open-market worth, and the remaining board should clear at a discount.

        ADR-0001 keeps this permanently distinct from ``market_inflation``, which is live,
        starts at exactly 1.00 and drifts with the room.
        """
        if self.available_book_value <= 0:
            return 1.0
        return round(self.total_live_money / self.available_book_value, 4)

    def by_position(self, position: str) -> list[PlayerValue]:
        return [p for p in self.players if p.position == position]

    def available(self) -> list[PlayerValue]:
        return [p for p in self.players if not p.is_keeper]


def _pool_for(
    players: Sequence[PlayerProjection],
    vorp: Mapping[str, float],
    rostered: Mapping[str, int],
) -> set[str]:
    """The priced pool implied by a baseline's own per-position roster.

    ``rostered`` is what :func:`~draft_intel.quant.replacement.last_drafted_baseline` converged
    on: how many players at each position the league actually buys. Taking the best ``n`` at
    each position by VORP reproduces exactly that roster, so the pool and the replacement level
    that prices it are the same set by construction rather than by coincidence.
    """
    by_position: dict[str, list[PlayerProjection]] = {}
    for player in players:
        by_position.setdefault(player.position, []).append(player)
    chosen: set[str] = set()
    for position, group in by_position.items():
        group.sort(key=lambda p: vorp[p.player_id], reverse=True)
        chosen.update(p.player_id for p in group[: rostered.get(position, 0)])
    return chosen


def value_board(
    players: Sequence[PlayerProjection],
    *,
    baselines: Baselines,
    keeper_ids: frozenset[str],
    keeper_spend: int,
    total_budget: int,
    roster_spots_full: int,
    roster_spots_live: int,
) -> ValueBoard:
    """Price every player both ways, and refuse to return if an invariant fails.

    Raises:
        InvariantViolation: if any of the three §4.3 invariants does not hold. The charter is
            unambiguous that a broken model must not present prices, so this raises rather
            than returning a board with a warning attached.
    """
    if not players:
        raise InvariantViolation("no projections supplied; cannot price an empty board")

    # The charter's three sum invariants are all self-consistent under nonsense input: a
    # keeper spend larger than the budget gives negative live money, a negative dollars-per-
    # VORP, negative prices, and sums that still reconcile exactly. Arithmetic consistency is
    # not the same as sanity, so the inputs are checked before the sums are.
    if keeper_spend < 0:
        raise InvariantViolation(f"keeper spend ${keeper_spend} is negative")
    if keeper_spend > total_budget:
        raise InvariantViolation(
            f"keeper spend ${keeper_spend} exceeds the ${total_budget} total budget; "
            "there is no money left to price the board with"
        )
    if roster_spots_live > total_budget - keeper_spend:
        raise InvariantViolation(
            f"${total_budget - keeper_spend} of live money cannot fill {roster_spots_live} "
            "roster spots at the $1 minimum bid"
        )

    full_vorp = {p.player_id: baselines.full_last_drafted.vorp(p) for p in players}
    live_vorp = {
        p.player_id: (0.0 if p.player_id in keeper_ids else baselines.live_last_drafted.vorp(p))
        for p in players
    }

    # **The pool is the one the replacement level was solved for, position by position.**
    #
    # A flat "top 160 by VORP" is the obvious reading of §4.3 and it disagrees with the fixed
    # point that produced the replacement levels it ranks by. `last_drafted_baseline` iterates
    # to a per-position roster -- with K *pinned*, because a league that starts a kicker must
    # buy ten of them whatever the value curve says -- and settles on 25 QB / 10 K. Ranking the
    # same players flat by VORP gives 31 QB / 6 K, because kickers have almost no VORP and lose
    # every tiebreak.
    #
    # So four kickers the league is obliged to buy fell outside the priced pool and rendered as
    # `--`, while the `dollars_per_vorp` denominator summed VORP over a pool that was not the
    # pool the replacement levels assumed. The money involved is small -- every affected player
    # sits at VORP 0, about $6 of $2,000 -- but two halves of one valuation disagreeing about
    # who is in the auction is not a rounding difference, and it stops being small the moment a
    # roster setting changes.
    available = [p for p in players if p.player_id not in keeper_ids]
    pool_full = _pool_for(players, full_vorp, baselines.full_last_drafted.rostered)
    pool_live = _pool_for(available, live_vorp, baselines.live_last_drafted.rostered)

    # Having just made the pool follow the baseline's own roster, refuse to price a board where
    # the two still disagree. `compute_baselines` guarantees the sum because `last_drafted_
    # baseline` fills exactly `roster_spots`, but nothing in the type system does, and a silent
    # divergence here is precisely the defect this construction removes.
    for label, pool, expected in (
        ("full", pool_full, roster_spots_full),
        ("live", pool_live, roster_spots_live),
    ):
        if len(pool) != expected:
            raise InvariantViolation(
                f"the {label} priced pool holds {len(pool)} players but {expected} roster spots "
                "are being priced; the baseline's rostered counts and the roster spots passed "
                "in describe different auctions"
            )

    total_live_money = total_budget - keeper_spend
    discretionary = total_budget - roster_spots_full
    discretionary_live = total_live_money - roster_spots_live

    sum_vorp_full = sum(full_vorp[pid] for pid in pool_full)
    sum_vorp_live = sum(live_vorp[pid] for pid in pool_live)
    dpv = discretionary / sum_vorp_full if sum_vorp_full > 0 else 0.0
    dpv_live = discretionary_live / sum_vorp_live if sum_vorp_live > 0 else 0.0

    priced: list[PlayerValue] = []
    for player in players:
        pid = player.player_id
        in_full, in_live = pid in pool_full, pid in pool_live
        priced.append(
            PlayerValue(
                player_id=pid,
                name=player.name,
                position=player.position,
                team=player.team,
                points=player.points,
                vorp=round(full_vorp[pid], 2),
                market_value=round(MIN_BID + full_vorp[pid] * dpv, 2) if in_full else 0.0,
                vorp_live=round(live_vorp[pid], 2),
                baseline_value=round(MIN_BID + live_vorp[pid] * dpv_live, 2) if in_live else 0.0,
                is_keeper=pid in keeper_ids,
                in_pool_full=in_full,
                in_pool_live=in_live,
            )
        )
    priced.sort(key=lambda p: (p.baseline_value, p.market_value), reverse=True)

    sum_market = round(sum(p.market_value for p in priced if p.in_pool_full), 2)
    sum_baseline = round(sum(p.baseline_value for p in priced if p.in_pool_live), 2)

    # Charter §4.3: property-test all three. A failure here means the app refuses to price.
    if abs(sum_market - total_budget) > TOLERANCE:
        raise InvariantViolation(
            f"sum of market_value over pool_full is ${sum_market}, expected ${total_budget} "
            f"+/- ${TOLERANCE}"
        )
    if abs(sum_baseline - total_live_money) > TOLERANCE:
        raise InvariantViolation(
            f"sum of baseline_value over pool_live is ${sum_baseline}, expected "
            f"${total_live_money} +/- ${TOLERANCE}"
        )
    if keeper_spend + total_live_money != total_budget:
        raise InvariantViolation(
            f"keeper spend ${keeper_spend} + live money ${total_live_money} != "
            f"${total_budget} exactly"
        )

    return ValueBoard(
        players=tuple(priced),
        keeper_book_value=round(sum(p.market_value for p in priced if p.is_keeper), 2),
        available_book_value=round(
            sum(p.market_value for p in priced if not p.is_keeper and p.in_pool_full), 2
        ),
        total_budget=total_budget,
        keeper_spend=keeper_spend,
        total_live_money=total_live_money,
        discretionary=discretionary,
        discretionary_live=discretionary_live,
        dollars_per_vorp=round(dpv, 4),
        dollars_per_vorp_live=round(dpv_live, 4),
        pool_full_size=len(pool_full),
        pool_live_size=len(pool_live),
        sum_market_value=sum_market,
        sum_baseline_value=sum_baseline,
    )
