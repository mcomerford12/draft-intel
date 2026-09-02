"""DI-027 — where the market's dollar opinion comes from.

Sleeper publishes **no auction-value field** over REST (docs/api-findings.md, Finding 3). Every
ADP variant is there with full coverage; there is no ``auction``, ``auction_value``, ``dollar``
or ``price`` key anywhere in the projections payload. That single fact drives this module.

Two consequences follow, and they are the reason this exists:

1. **The league's keeper rule is not computable from the API.** ``floor(0.75 *
   sleeper_auction_value)`` references a number Sleeper will not give us. The commissioner has
   confirmed the rule *will* be applied on draft day, so the auction values have to arrive by
   some other route -- and that route is :class:`CsvMarketValues`.
2. **Our own ``market_value`` is a model opinion, not a market one.** It says what a player is
   worth under this league's scoring and replacement level. It does not say what the room will
   pay. Conflating the two makes every "edge" figure circular: you cannot measure your
   advantage over the field using a number derived entirely from your own model.

So there are three providers, in descending order of authority:

===========================  ===================================================================
provider                     what it actually knows
===========================  ===================================================================
:class:`CsvMarketValues`     Real dollar values the user supplies. The only true market source.
:class:`AdpMarketValues`     The market's *ordering*, from ADP. Borrows its price ladder.
:class:`InternalMarketValues`  Our own model. Not a market opinion at all; the honest floor.
===========================  ===================================================================

:func:`resolve_market_values` walks them in order and takes the first with adequate coverage,
recording in ``notes`` which one won and why the earlier ones did not. Nothing downstream is
allowed to forget which it got: ``MarketValues.source`` travels with the numbers, and a board
priced off ``InternalMarketValues`` must be badged as an estimate.

**These values do not replace the model's own ``market_value``.** That is the single most
tempting wrong move here and it breaks the charter's §4.3 invariants on contact: our
``market_value`` is constructed so that it sums to exactly the $2,000 in the room, while a CSV
of real auction values sums to whatever the field's willingness to pay happens to total. They
are different quantities. Market values feed exactly two things:

* **keeper retention prices** -- ``floor(0.75 * auction_value)``, which is the league's actual
  rule and is not computable without them;
* **edge** -- the gap between what our model says a player is worth and what the room will pay,
  which is the entire point of the exercise and is meaningless when both sides come from us.

Use :meth:`MarketValues.scaled_to` in the rare case a caller genuinely needs a market opinion
that also reconciles to the money in the room; it is a rescaling and it is lossy, and the
docstring says why.

**Names are input to resolution and nothing more.** The CSV is a name-keyed external file --
exactly the hazard the keeper manifest's position confirmation exists for. Sleeper's map carries
a guard named Josh Allen alongside the Buffalo quarterback and a cornerback named Lamar Jackson
alongside the Baltimore one, so a CSV row is resolved by name *and* position, and an ambiguous
row is reported rather than guessed.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from draft_intel.domain.keepers import AmbiguousPlayer, resolve_player_id
from draft_intel.quant.scoring import PlayerProjection

# ADP feeds use a sentinel rather than null for "not being drafted". Anything at or above this
# is absence of an opinion, not a very late pick, and must not be ranked as one.
ADP_SENTINEL = 900.0

# Below this share of the priced pool a provider is not a market opinion, it is a handful of
# anecdotes. Falling through to the next provider beats pricing 160 players off 12 data points.
MIN_COVERAGE_FRACTION = 0.5

_NAME_COLUMNS = ("name", "player", "player_name")
_POSITION_COLUMNS = ("pos", "position")
_VALUE_COLUMNS = ("value", "price", "auction", "auction_value", "cost", "dollars", "$")
_ID_COLUMNS = ("player_id", "id", "sleeper_id")


class MarketValues(BaseModel):
    """A market opinion in dollars, with its provenance attached and inseparable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    values: dict[str, float]
    unmatched: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def coverage(self) -> int:
        return len(self.values)

    @property
    def is_estimate(self) -> bool:
        """True when these are not real market dollars and must be badged as such."""
        return self.source != CsvMarketValues.name

    def get(self, player_id: str) -> float | None:
        return self.values.get(player_id)

    @property
    def total(self) -> float:
        return round(sum(self.values.values()), 2)

    def scaled_to(self, total: float) -> MarketValues:
        """Rescale so the values sum to ``total``. Lossy, and only occasionally correct.

        A market opinion has no reason to sum to the money in the room -- if the field
        collectively wants to spend $2,400 on a $2,000 board, that *is* the finding, and
        flattening it away destroys it. So this is never applied automatically.

        It is right in one situation: pricing a hypothetical where the room's total spend is
        fixed by construction and only the relative ordering is wanted from the market. The
        rescale factor is recorded in ``notes`` so a reader can always recover the original.

        Raises:
            ValueError: if the values sum to zero, where no scale factor exists.
        """
        current = sum(self.values.values())
        if current <= 0:
            raise ValueError(f"cannot rescale {self.source}: values sum to {current}")
        factor = total / current
        return self.model_copy(
            update={
                "values": {pid: round(v * factor, 2) for pid, v in self.values.items()},
                "notes": (*self.notes, f"rescaled by {factor:.4f} to total ${total:.2f}"),
            }
        )


@runtime_checkable
class MarketValueProvider(Protocol):
    """A source of dollar opinions, keyed on ``player_id``."""

    name: str

    def market_values(self, players: Sequence[PlayerProjection]) -> MarketValues: ...


def parse_dollars(raw: str) -> float:
    """Parse a dollar cell tolerantly. ``$47``, ``47.0``, ``1,200`` and ``  47 `` all work.

    Raises:
        ValueError: on anything that is not a finite number. ``inf`` and ``nan`` are rejected
            explicitly -- ``float()`` accepts both, and either one silently poisons every sum
            downstream of it rather than failing where the bad data entered.
    """
    cleaned = raw.strip().lstrip("$").replace(",", "").replace("_", "")
    value = float(cleaned)
    if not math.isfinite(value):
        raise ValueError(f"{raw!r} is not a finite dollar amount")
    return value


def _column(fieldnames: Iterable[str], candidates: Sequence[str]) -> str | None:
    lookup = {name.strip().lower(): name for name in fieldnames if name}
    for candidate in candidates:
        if candidate in lookup:
            return lookup[candidate]
    return None


class CsvMarketValues:
    """Auction values supplied by the user, resolved to ``player_id`` by name and position.

    This is the path that makes the league's keeper rule computable. It is the only provider
    that carries real market dollars, so it outranks the others unconditionally.

    The file is read tolerantly because it will be assembled by hand, probably in a hurry, on
    the morning of the draft. Column names are matched case-insensitively across the obvious
    synonyms; ``$47``, ``47`` and ``1,200`` all parse. A ``player_id`` column, if present, wins
    over name resolution and is the escape hatch for a name collision the file cannot express.

    What it is *not* tolerant of is a row it cannot resolve. Those go to ``unmatched`` with the
    reason. Silently dropping a row would understate coverage and, worse, quietly omit a player
    from the keeper-price check -- the exact failure the keeper manifest's position confirmation
    was built to prevent.
    """

    name = "csv"

    def __init__(self, path: str | Path, players: Mapping[str, dict[str, Any]]) -> None:
        self.path = Path(path)
        self._players = dict(players)

    def market_values(self, players: Sequence[PlayerProjection]) -> MarketValues:
        del players  # resolution keys on the Sleeper map, not on who happens to be projected
        if not self.path.exists():
            return MarketValues(
                source=self.name,
                values={},
                notes=(f"no auction-value file at {self.path}",),
            )

        with self.path.open(newline="") as handle:
            # The shipped template documents itself in `#` comments, and a hand-built file will
            # pick up blank lines. Neither should arrive as forty unresolvable rows. Real file
            # line numbers are carried alongside, because "line 12" has to mean line 12 of the
            # user's file for the error to be worth printing.
            kept = [
                (number, line)
                for number, line in enumerate(handle, start=1)
                if line.strip() and not line.lstrip().startswith("#")
            ]
            reader = csv.DictReader([line for _number, line in kept])
            fields = reader.fieldnames or []
            name_col = _column(fields, _NAME_COLUMNS)
            pos_col = _column(fields, _POSITION_COLUMNS)
            value_col = _column(fields, _VALUE_COLUMNS)
            id_col = _column(fields, _ID_COLUMNS)
            if value_col is None:
                return MarketValues(
                    source=self.name,
                    values={},
                    notes=(
                        f"{self.path} has no value column; expected one of "
                        f"{', '.join(_VALUE_COLUMNS)} but found {', '.join(fields) or '(none)'}",
                    ),
                )
            if id_col is None and (name_col is None or pos_col is None):
                return MarketValues(
                    source=self.name,
                    values={},
                    notes=(
                        f"{self.path} needs either a player_id column or both a name and a "
                        f"position column; found {', '.join(fields)}",
                    ),
                )
            rows = list(zip([number for number, _line in kept[1:]], reader, strict=True))

        values: dict[str, float] = {}
        unmatched: list[str] = []
        duplicates: list[str] = []
        for line, row in rows:
            label = (row.get(name_col or "") or row.get(id_col or "") or "").strip()
            try:
                dollars = parse_dollars(row[value_col] or "")
            except (ValueError, TypeError):
                unmatched.append(f"line {line} {label!r}: unreadable value {row[value_col]!r}")
                continue
            if dollars < 0:
                unmatched.append(f"line {line} {label!r}: negative value {dollars}")
                continue

            player_id = (row.get(id_col) or "").strip() if id_col else ""
            if player_id and player_id not in self._players:
                unmatched.append(
                    f"line {line} {label!r}: player_id {player_id!r} is not in the map"
                )
                continue
            if not player_id:
                if name_col is None or pos_col is None:
                    unmatched.append(f"line {line} {label!r}: no player_id and no name/position")
                    continue
                try:
                    player_id = resolve_player_id(
                        (row.get(name_col) or "").strip(),
                        (row.get(pos_col) or "").strip().upper(),
                        self._players,
                    )
                except AmbiguousPlayer as exc:
                    unmatched.append(f"line {line}: {exc}")
                    continue

            if player_id in values:
                duplicates.append(f"{label!r} (player_id {player_id})")
            values[player_id] = dollars

        notes = [f"read {len(rows)} rows from {self.path}"]
        if duplicates:
            # Last row wins, which is what a hand-edited file appended to at the draft table
            # implies. Saying so beats leaving the user to discover the precedence by accident.
            notes.append(
                f"{len(duplicates)} duplicate player(s), last row wins: {', '.join(duplicates)}"
            )
        return MarketValues(
            source=self.name,
            values=values,
            unmatched=tuple(unmatched),
            notes=tuple(notes),
        )


class AdpMarketValues:
    """The market's *ordering*, taken from ADP, priced with a ladder borrowed from elsewhere.

    ADP is the one genuinely market-derived signal Sleeper does publish, with full coverage. It
    says who the field takes first. It does not say what the field pays, and no amount of
    arithmetic turns a rank into a dollar without an assumption about the shape of the curve.

    Rather than invent a shape, this does a rank transfer: it takes an existing price ladder --
    the sorted dollar amounts from some other valuation, normally our own board -- and reassigns
    those same amounts to players in ADP order. The ladder's shape and its total are preserved
    exactly, so the sum invariant holds by construction; only the *ordering* comes from the
    market.

    **Be clear about what that is and is not.** It is a faithful answer to "if the room spends
    the way my model says, but ranks players the way the field does, what does each player
    cost?" -- and the gap between that and our own board is a real, measurable disagreement
    about ordering, which is the input the edge calculation needs. It is **not** a measurement
    of how steeply the room actually bids. If a CSV of real auction values arrives, that is
    strictly better information and :func:`resolve_market_values` prefers it.
    """

    name = "adp_rank_transfer"

    def __init__(
        self,
        payload: Iterable[Mapping[str, Any]],
        ladder: Sequence[float],
        *,
        adp_field: str = "adp_2qb",
    ) -> None:
        self.payload = list(payload)
        self.ladder = sorted(ladder, reverse=True)
        self.adp_field = adp_field

    def market_values(self, players: Sequence[PlayerProjection]) -> MarketValues:
        eligible = {p.player_id for p in players}
        ranked: list[tuple[float, str]] = []
        missing = 0
        for record in self.payload:
            player_id = str(record.get("player_id") or "")
            adp = (record.get("stats") or {}).get(self.adp_field)
            if player_id not in eligible:
                continue
            if not isinstance(adp, int | float) or isinstance(adp, bool) or adp >= ADP_SENTINEL:
                missing += 1
                continue
            ranked.append((float(adp), player_id))

        ranked.sort()
        values = {
            player_id: self.ladder[i]
            for i, (_adp, player_id) in enumerate(ranked[: len(self.ladder)])
        }
        notes = [
            f"{self.adp_field}: {len(ranked)} players ranked, ladder of {len(self.ladder)} rungs",
        ]
        if missing:
            notes.append(f"{missing} projected players carry no usable {self.adp_field}")
        return MarketValues(source=self.name, values=values, notes=tuple(notes))


class InternalMarketValues:
    """Our own model's ``market_value``, wrapped as a provider. The honest floor.

    This is **not a market opinion**. Using it wherever a market opinion is called for makes
    every edge figure circular -- the edge becomes the difference between our model and itself,
    which is zero by construction. It exists so the tool has a defined answer before any auction
    values arrive, and so that answer is *labelled*: ``MarketValues.is_estimate`` is true for it,
    and the board it prices must be badged accordingly.
    """

    name = "internal_model"

    def __init__(self, values: Mapping[str, float]) -> None:
        self._values = dict(values)

    def market_values(self, players: Sequence[PlayerProjection]) -> MarketValues:
        eligible = {p.player_id for p in players}
        return MarketValues(
            source=self.name,
            values={pid: v for pid, v in self._values.items() if pid in eligible},
            notes=(
                "model estimate, not a market observation -- everything downstream is estimated",
            ),
        )


def resolve_market_values(
    providers: Sequence[MarketValueProvider],
    players: Sequence[PlayerProjection],
    *,
    required: int,
    min_fraction: float = MIN_COVERAGE_FRACTION,
) -> MarketValues:
    """Take the first provider with adequate coverage, recording why the others lost.

    Args:
        required: Size of the priced pool. Coverage is judged against this, not against the
            number of players projected -- pricing 160 auction spots off 12 rows is not a
            market opinion however complete those 12 rows are.
        min_fraction: Share of ``required`` a provider must cover to be used.

    The rejected providers' reasons are carried into the winner's ``notes``. A provider that
    fell through because a file was missing and one that fell through because half its rows
    failed to resolve are very different situations on draft morning, and the difference has to
    reach the user.
    """
    if not providers:
        raise ValueError("no market value providers supplied")

    threshold = max(1, int(required * min_fraction))
    rejected: list[str] = []
    for provider in providers:
        result = provider.market_values(players)
        if result.coverage >= threshold:
            return result.model_copy(
                update={
                    "notes": (*rejected, *result.notes),
                }
            )
        detail = "; ".join(result.notes) or "no reason given"
        rejected.append(
            f"skipped {result.source}: covered {result.coverage} of {required} "
            f"(needs {threshold}) -- {detail}"
        )

    # Every provider fell short. Returning the last one's values silently would price the board
    # off whatever scraps the weakest source had; returning empty makes the caller decide.
    return MarketValues(
        source="none",
        values={},
        notes=(*rejected, f"no provider covered {threshold} of {required} players"),
    )
