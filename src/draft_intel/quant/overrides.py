"""DI-038 — value overrides. Charter §4.8's value half.

Budget and roster overrides are events in the ledger (Sprint 1, DI-020). *Value* overrides are
different in kind: they change what the model thinks a player is worth, not what the room has
actually done, so they belong to the valuation layer rather than the money ledger. They are
applied as a transformation of the priced board, never by mutating it.

Charter §4.8's precedence rule governs everything here::

    manual override  >  API-derived  >  model-computed

    The user always wins. **But the system must never silently hide a disagreement.** Whenever
    an override diverges from what the API or model says, display both values side by side with
    the delta. Never let the user forget they are looking at a number they typed rather than a
    number that was measured.

So :class:`OverriddenValue` carries the model's number alongside the user's, permanently.
Nothing downstream can obtain the overridden figure without also being handed what it replaced.

**Renormalisation is off by default and cannot happen implicitly.** §4.8:

    overriding one player's value must **not** silently redistribute value across the rest of
    the pool -- that would make a single edit ripple unpredictably through every other price
    mid-draft. Default to no renormalization, and display the resulting deviation of ``Σ values``
    from ``total_live_money`` as a visible number.

:attr:`OverrideResult.deviation` is that visible number. :func:`renormalise` exists as the
explicit opt-in, and returns a preview rather than applying anything.

Three override kinds, per §4.8:

* **per player** -- an outright replacement of ``baseline_value``, ``market_value`` or
  ``points``;
* **positional multiplier** -- "scale all TE values by 1.15", called out in the charter as *the
  highest-leverage knob in a live draft, because positional mispricing is usually recognized
  wholesale rather than one player at a time*;
* **blacklist** -- zero a player so the optimizer stops recommending them.

Order matters and is fixed: a multiplier scales the model's number, and an explicit per-player
override then replaces the result outright. Scaling a number the user typed would mean the user
did not actually win, which is precedence backwards.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from draft_intel.quant.valuation import PlayerValue


class PlayerOverride(BaseModel):
    """A user's replacement values for one player. Unset fields leave the model's number."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    baseline_value: float | None = None
    market_value: float | None = None
    points: float | None = None
    blacklisted: bool = False
    """Never bid. Injury news, a personal read -- a reason the model cannot see."""

    note: str = ""
    """Why. Optional, and worth having at 9pm when the reason has been forgotten."""


class OverriddenValue(BaseModel):
    """A player's value after overrides, with what it replaced kept alongside it.

    The model's original figures are not optional and not dropped. §4.8 requires both to be
    displayable side by side with the delta, and a type that can lose the original makes that
    a matter of discipline downstream rather than a property of the data.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    player: PlayerValue
    """The model's figures, untouched."""

    baseline_value: float
    market_value: float
    points: float
    blacklisted: bool
    sources: dict[str, str]
    """Field name -> ``model``, ``multiplier`` or ``manual``."""

    note: str = ""

    @property
    def player_id(self) -> str:
        return self.player.player_id

    @property
    def name(self) -> str:
        return self.player.name

    @property
    def position(self) -> str:
        return self.player.position

    @property
    def is_overridden(self) -> bool:
        return any(source != "model" for source in self.sources.values()) or self.blacklisted

    def deltas(self) -> dict[str, float]:
        """What each override changed, against the model's own number."""
        return {
            "baseline_value": round(self.baseline_value - self.player.baseline_value, 2),
            "market_value": round(self.market_value - self.player.market_value, 2),
            "points": round(self.points - self.player.points, 2),
        }

    def describe(self) -> str:
        if not self.is_overridden:
            return f"{self.name}: model"
        parts = [
            f"{field} {getattr(self.player, field)} -> {getattr(self, field)} ({source})"
            for field, source in sorted(self.sources.items())
            if source != "model"
        ]
        if self.blacklisted:
            parts.append("BLACKLISTED, never bid")
        detail = "; ".join(parts)
        return f"{self.name}: {detail}" + (f" [{self.note}]" if self.note else "")


class OverrideResult(BaseModel):
    """The overridden board, and the disagreement it creates with the money in the room."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    values: tuple[OverriddenValue, ...]
    total_live_money: int
    sum_baseline_before: float
    sum_baseline_after: float

    @property
    def deviation(self) -> float:
        """``Σ baseline_value - total_live_money`` after overrides. The §4.8 visible number.

        Non-zero is the expected state once anything has been overridden, and it is *not* an
        error. The charter is explicit that a single edit must not ripple through every other
        price, which means the sum stops reconciling and that fact gets shown rather than
        smoothed away.
        """
        return round(self.sum_baseline_after - self.total_live_money, 2)

    @property
    def moved(self) -> float:
        """How much the overrides changed the board's total, in dollars."""
        return round(self.sum_baseline_after - self.sum_baseline_before, 2)

    def overridden(self) -> tuple[OverriddenValue, ...]:
        return tuple(v for v in self.values if v.is_overridden)

    def banner(self) -> str | None:
        """The persistent reconciliation line, or ``None`` when nothing has been overridden."""
        changed = self.overridden()
        if not changed:
            return None
        return (
            f"{len(changed)} player value(s) overridden; the board now sums to "
            f"${self.sum_baseline_after:.0f} against ${self.total_live_money} of live money, a "
            f"deviation of ${self.deviation:+.0f}. Values are NOT renormalised, deliberately: "
            f"one edit must not move every other price."
        )


def apply_overrides(
    board: Sequence[PlayerValue],
    *,
    total_live_money: int,
    players: Mapping[str, PlayerOverride] | None = None,
    positional_multipliers: Mapping[str, float] | None = None,
    blacklist: frozenset[str] = frozenset(),
) -> OverrideResult:
    """Apply value overrides to a priced board without mutating it.

    Args:
        board: The model's priced board.
        total_live_money: What the board would sum to if untouched, for the deviation figure.
        players: Per-player replacements, keyed on ``player_id``.
        positional_multipliers: e.g. ``{"TE": 1.15}``. Applied to the model's figures.
        blacklist: Player ids to zero out so the optimizer stops recommending them.

    Order is fixed: multiplier first, then the explicit per-player value, then the blacklist.
    Scaling a number the user typed would mean the user did not win, which is §4.8's precedence
    backwards; and a blacklisted player is worth nothing whatever anybody typed, because the
    instruction is "never bid" rather than "bid this much".

    Raises:
        ValueError: on a non-positive multiplier. Zeroing a whole position is what the
            blacklist is for, and a negative multiplier makes every price at that position
            negative, which passes silently into the optimizer and inverts its preferences.
    """
    players = dict(players or {})
    multipliers = dict(positional_multipliers or {})
    for position, factor in multipliers.items():
        if factor <= 0:
            raise ValueError(
                f"positional multiplier for {position} is {factor}; use the blacklist to remove "
                "players rather than a zero or negative multiplier"
            )

    unknown = set(players) - {p.player_id for p in board}
    if unknown:
        raise KeyError(
            f"override(s) for {len(unknown)} player(s) not on the board: {sorted(unknown)}. "
            "A value override that names nobody is a typo, and silently dropping it leaves the "
            "user believing a correction was applied."
        )

    out: list[OverriddenValue] = []
    for player in board:
        override = players.get(player.player_id)
        factor = multipliers.get(player.position, 1.0)
        sources = {"baseline_value": "model", "market_value": "model", "points": "model"}

        baseline = player.baseline_value * factor
        market = player.market_value * factor
        points = player.points
        if factor != 1.0:
            sources["baseline_value"] = "multiplier"
            sources["market_value"] = "multiplier"

        if override is not None:
            if override.baseline_value is not None:
                baseline = override.baseline_value
                sources["baseline_value"] = "manual"
            if override.market_value is not None:
                market = override.market_value
                sources["market_value"] = "manual"
            if override.points is not None:
                points = override.points
                sources["points"] = "manual"

        blacklisted = player.player_id in blacklist or (
            override is not None and override.blacklisted
        )
        if blacklisted:
            baseline = 0.0
            market = 0.0

        out.append(
            OverriddenValue(
                player=player,
                baseline_value=round(baseline, 2),
                market_value=round(market, 2),
                points=round(points, 2),
                blacklisted=blacklisted,
                sources=sources,
                note=override.note if override else "",
            )
        )

    return OverrideResult(
        values=tuple(out),
        total_live_money=total_live_money,
        sum_baseline_before=round(sum(p.baseline_value for p in board if p.in_pool_live), 2),
        sum_baseline_after=round(sum(v.baseline_value for v in out if v.player.in_pool_live), 2),
    )


class RenormalisationPreview(BaseModel):
    """What renormalising *would* do. Never applied without being asked for."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    factor: float
    before: float
    after: float
    biggest_moves: tuple[tuple[str, float, float], ...]
    """``(name, from, to)`` for the players the rescale moves most, largest first."""

    def describe(self) -> str:
        return (
            f"Renormalising would scale every live value by {self.factor:.4f}, moving the "
            f"board total from ${self.before:.0f} to ${self.after:.0f}. The largest single "
            f"moves: "
            + ", ".join(f"{name} ${old:.0f}->${new:.0f}" for name, old, new in self.biggest_moves)
        )


def renormalise(result: OverrideResult, *, top: int = 5) -> RenormalisationPreview | None:
    """Preview scaling the live pool back to ``total_live_money``. Applies nothing.

    §4.8 requires renormalisation to be *"an explicit, opt-in action with a preview of what it
    would change"*. This is the preview. It returns ``None`` when there is nothing to
    renormalise -- the board already reconciles, or has no live value at all -- rather than a
    factor of 1.0, so a caller cannot render "renormalise (no change)" as an available action.
    """
    live = [v for v in result.values if v.player.in_pool_live and not v.blacklisted]
    total = sum(v.baseline_value for v in live)
    if total <= 0 or abs(result.deviation) < 0.01:
        return None

    factor = result.total_live_money / total
    moves = sorted(
        ((v.name, v.baseline_value, round(v.baseline_value * factor, 2)) for v in live),
        key=lambda row: -abs(row[2] - row[1]),
    )[:top]
    return RenormalisationPreview(
        factor=round(factor, 6),
        before=round(total, 2),
        after=round(total * factor, 2),
        biggest_moves=tuple(moves),
    )
