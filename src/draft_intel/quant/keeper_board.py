"""DI-031 — the keeper surplus board and the structural keeper inflation figure.

Charter §4.5 draws a line this module exists to keep drawn:

    **keeper_inflation** is structural, fixed, and known before a single competitive bid is
    made. **market_inflation** is live, starts at exactly 1.00 and drifts with the room.

They are different quantities with different uses and they must never be conflated (ADR-0001).
This module owns only the first. DI-032 owns the second.

**What the surplus actually measures.** Each keeper was retained at some price. Our full-market
valuation says what that same player would have cost in a keeper-free $2,000 / 160-slot auction
-- their *book value*. The difference is surplus:

    surplus_i = book_value_i - price_paid_i

A positive league-wide surplus means the room collectively got its keepers below what they are
worth, so there is less money chasing what is left relative to its worth, and the remaining
board should clear **over** book. That is the 25% retention discount doing what it is meant to
do. A negative surplus means the keepers were retained at or above their open-market worth and
the remaining board should clear at a **discount**.

    keeper_inflation = total_live_money / available_book_value

Note what is *not* in that ratio. An earlier version computed ``discretionary_live /
discretionary`` and reported 0.71x. That is a ratio of money pools; it says nothing about what
a player costs, and it moves when the roster size changes even though no price does. The right
comparison is the money left in the room against the book value of what is still on the board.

**Two scenarios, always both.** The commissioner has confirmed that retention prices follow
``floor(0.75 * sleeper_auction_value)`` on draft day. But Sleeper publishes no auction value
(Finding 3), so the rule's inputs arrive from :mod:`draft_intel.quant.market`, and until they do
every rule-implied price is an estimate. Meanwhile the prices actually loaded into the draft
room are observed fact. Those two can disagree -- on the mock slate they disagree by $177 --
and which one is true changes what kind of auction this is:

===================  =============  =================  ==============================
scenario             ΣK             keeper_inflation   what the room feels like
===================  =============  =================  ==============================
prices as loaded     observed       computed from it   whatever was actually entered
prices under rule    Σ rule price   computed from it   what the league rule implies
===================  =============  =================  ==============================

Presenting one without the other is how a draft gets bid at the wrong level all night, so
:class:`KeeperBoard` carries both and :meth:`KeeperBoard.divergence` says how far apart they are.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from draft_intel.domain.keepers import retention_price
from draft_intel.quant.market import MarketValues
from draft_intel.quant.valuation import ValueBoard

# Charter §2: a loaded retention price this far from what the rule implies is worth surfacing.
# Not an error -- rounding, a stale auction value, or a hand-typed price all land here -- but a
# keeper mispriced by $20 moves that team's whole evening and must not pass unremarked.
PRICE_DIVERGENCE_DOLLARS = 3


class KeeperLine(BaseModel):
    """One keeper: what they are worth, what they cost, and what the rule says they cost."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    owner: str
    slot: int | None
    player_id: str
    name: str
    position: str

    book_value: float
    """Our full-market valuation: what this player would cost in a keeper-free auction."""

    market_value: float | None = None
    """The room's dollar opinion, when we have one. ``None`` until auction values arrive."""

    price_paid: int | None = None
    """The retention price actually loaded. Observed fact, or ``None`` if not yet known."""

    rule_price: int | None = None
    """``floor(0.75 * market_value)``, clamped to $1. An estimate while ``market_value`` is."""

    @property
    def surplus(self) -> float | None:
        """``book - paid``. Positive means this team got the player cheap."""
        if self.price_paid is None:
            return None
        return round(self.book_value - self.price_paid, 2)

    @property
    def rule_surplus(self) -> float | None:
        """``book - rule price``: the surplus the league's own rule implies."""
        if self.rule_price is None:
            return None
        return round(self.book_value - self.rule_price, 2)

    @property
    def price_divergence(self) -> int | None:
        """``paid - rule``. The §2 alert: a loaded price that is not what the rule produces."""
        if self.price_paid is None or self.rule_price is None:
            return None
        return self.price_paid - self.rule_price

    @property
    def diverged(self) -> bool:
        divergence = self.price_divergence
        return divergence is not None and abs(divergence) >= PRICE_DIVERGENCE_DOLLARS


class IncompleteScenario(Exception):
    """Raised when a figure is asked for that would be computed from a partial keeper spend."""


class Scenario(BaseModel):
    """One reading of the keeper slate: a keeper spend and everything it implies.

    **A partial keeper spend is not a small error, it is a wrong answer that looks right.**
    Missing one keeper's price understates ΣK, which overstates ``total_live_money``, which
    inflates every price on the board -- and nothing about the resulting number looks wrong. So
    the derived figures refuse rather than approximate: ``keeper_spend`` and ``missing`` are
    always readable, and everything computed *from* them raises while a price is unknown. This
    is the same posture ``value_board`` takes with its invariants, for the same reason.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    keeper_spend: int
    """Sum of the prices that are known. A partial sum when ``complete`` is False."""

    total_budget: int
    available_book_value: float
    keeper_book_value: float
    complete: bool
    missing: int = 0
    """Keepers with no price under this scenario. Non-zero makes the derived figures refuse."""

    def _require_complete(self, figure: str) -> None:
        if not self.complete:
            raise IncompleteScenario(
                f"{figure} is not computable for {self.label!r}: {self.missing} keeper(s) have "
                f"no price, so the ${self.keeper_spend} keeper spend is a partial sum and every "
                "figure derived from it would be wrong in the direction of looking fine"
            )

    @property
    def total_live_money(self) -> int:
        self._require_complete("total_live_money")
        return self.total_budget - self.keeper_spend

    @property
    def keeper_surplus(self) -> float:
        """``book - paid`` across every keeper. Positive means the room got them cheap."""
        self._require_complete("keeper_surplus")
        return round(self.keeper_book_value - self.keeper_spend, 2)

    @property
    def keeper_inflation(self) -> float:
        """Live money per dollar of book value still on the board.

        Above 1.0: the field should clear over book, which is what a retention discount
        produces. Below 1.0: the keepers were retained at or above their worth and the
        remaining board should clear at a discount.
        """
        self._require_complete("keeper_inflation")
        if self.available_book_value <= 0:
            return 1.0
        return round((self.total_budget - self.keeper_spend) / self.available_book_value, 4)


class KeeperBoard(BaseModel):
    """Every keeper, both scenarios, and the alerts between them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lines: tuple[KeeperLine, ...]
    as_loaded: Scenario
    under_rule: Scenario
    market_source: str
    market_is_estimate: bool

    @property
    def divergence(self) -> int | None:
        """``ΣK loaded - ΣK under the rule``. How far apart the two readings of the night are.

        ``None`` unless both scenarios are complete. Differencing two partial sums produces a
        number that is not the difference of anything, and it would read as a small
        disagreement precisely when the data is most incomplete.
        """
        if not (self.as_loaded.complete and self.under_rule.complete):
            return None
        return self.as_loaded.keeper_spend - self.under_rule.keeper_spend

    def alerts(self) -> list[str]:
        """Charter §2 reconciliation: the things worth saying out loud before the draft."""
        out: list[str] = []
        for line in sorted(self.lines, key=lambda line: -abs(line.price_divergence or 0)):
            if line.diverged:
                out.append(
                    f"{line.owner}: {line.name} loaded at ${line.price_paid}, rule implies "
                    f"${line.rule_price} ({line.price_divergence:+d})"
                )
        missing_price = [line.name for line in self.lines if line.price_paid is None]
        if missing_price:
            out.append(
                f"{len(missing_price)} keeper(s) have no loaded retention price yet: "
                f"{', '.join(sorted(missing_price))}"
            )
        missing_value = [line.name for line in self.lines if line.market_value is None]
        if missing_value:
            out.append(
                f"{len(missing_value)} keeper(s) have no auction value, so the 75% rule cannot "
                f"be checked for them: {', '.join(sorted(missing_value))}"
            )
        if self.market_is_estimate:
            out.append(
                f"auction values came from {self.market_source!r}, not from real market prices; "
                "every rule-implied figure on this board is an estimate"
            )
        divergence = self.divergence
        if divergence:
            out.append(
                f"loaded keeper spend is ${divergence:+d} against what the 75% rule implies "
                f"(${self.as_loaded.keeper_spend} vs ${self.under_rule.keeper_spend}), which "
                f"moves keeper inflation from {self.under_rule.keeper_inflation}x to "
                f"{self.as_loaded.keeper_inflation}x"
            )
        return out

    def by_team(self) -> dict[str, list[KeeperLine]]:
        out: dict[str, list[KeeperLine]] = {}
        for line in self.lines:
            out.setdefault(line.owner, []).append(line)
        return out


def keeper_board(
    board: ValueBoard,
    *,
    keeper_owners: Mapping[str, str],
    slots: Mapping[str, int] | None = None,
    prices: Mapping[str, int | None] | None = None,
    market: MarketValues,
    minimum_retention_price: int = 1,
) -> KeeperBoard:
    """Build the keeper surplus board from a priced :class:`ValueBoard`.

    Args:
        board: The priced board. Supplies each keeper's ``market_value`` (their book value) and
            the ``available_book_value`` that the inflation ratio divides into.
        keeper_owners: ``player_id -> owner``. Every id here must be a keeper on ``board``;
            one that is not is a resolution bug upstream and raises rather than being skipped.
        slots: ``player_id -> draft_slot``, when identity has resolved. Display only.
        prices: ``player_id -> loaded retention price``. ``None`` for a keeper whose price is
            not yet known, which is the normal state until draft morning.
        market: The room's dollar opinions, from :mod:`draft_intel.quant.market`. Drives the
            rule-implied prices, and carries the provenance that decides whether this board is
            badged as an estimate.
        minimum_retention_price: Clamp for ``floor(0.75 * value)``. ``floor(0.75 * 1) == 0``,
            and a $0 keeper breaks both money conservation and the max-bid reserve.

    Raises:
        KeyError: if a ``keeper_owners`` id is not a keeper on ``board``. Silently dropping it
            would understate the keeper spend, which scales every price in the model.
    """
    prices = dict(prices or {})
    slots = dict(slots or {})
    priced = {p.player_id: p for p in board.players}

    lines: list[KeeperLine] = []
    for player_id, owner in keeper_owners.items():
        player = priced.get(player_id)
        if player is None:
            raise KeyError(f"keeper {player_id!r} ({owner}) is not on the priced board")
        if not player.is_keeper:
            raise KeyError(f"{player.name} ({owner}) is priced as available, not as a keeper")
        value = market.get(player_id)
        lines.append(
            KeeperLine(
                owner=owner,
                slot=slots.get(player_id),
                player_id=player_id,
                name=player.name,
                position=player.position,
                book_value=player.market_value,
                market_value=value,
                price_paid=prices.get(player_id),
                rule_price=(
                    retention_price(int(value), minimum=minimum_retention_price)
                    if value is not None
                    else None
                ),
            )
        )
    lines.sort(key=lambda line: (line.owner, -line.book_value))

    def scenario(label: str, amounts: Sequence[int | None]) -> Scenario:
        known = [amount for amount in amounts if amount is not None]
        return Scenario(
            label=label,
            keeper_spend=sum(known),
            total_budget=board.total_budget,
            available_book_value=board.available_book_value,
            keeper_book_value=board.keeper_book_value,
            complete=len(known) == len(amounts),
            missing=len(amounts) - len(known),
        )

    return KeeperBoard(
        lines=tuple(lines),
        as_loaded=scenario("prices as loaded", [line.price_paid for line in lines]),
        under_rule=scenario("prices under the 75% rule", [line.rule_price for line in lines]),
        market_source=market.source,
        market_is_estimate=market.is_estimate,
    )
