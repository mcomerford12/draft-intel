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

:func:`resolve_market_values` **layers** them: each player takes the value from the
highest-authority source that has one, and the fallbacks fill only the gaps. Twenty real
auction values for the twenty keepers are twenty real values, whatever the rest of the board
is priced from.

Nothing downstream is allowed to forget which it got. ``MarketValues.sources`` records the
provider per player, ``is_estimate_for`` answers it one player at a time, and the board-level
``is_estimate`` stays true unless every single value is real market data.

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
exactly the hazard the keeper manifest's position confirmation exists for. Sleeper's map holds
several thousand defensive and offensive-line players alongside the skill positions, and full
names collide across them: on the current slate two of this league's own keepers share a name
with a defender. Matching on name alone attaches a value to the wrong player silently, so a CSV
row resolves by name *and* position, and an ambiguous row is reported rather than guessed.
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

# Reported, not enforced. Below this share of the priced pool the board is mostly estimated and
# the notes say so -- but it no longer gates a provider out, because gating meant twenty real
# auction values for the twenty keepers counted for nothing. See `resolve_market_values`.
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
    sources: dict[str, str] = {}
    """``player_id -> provider name``. Empty for a single-provider result, where ``source``
    already answers it for every player. Populated by :func:`resolve_market_values`, which
    layers providers so one board can carry real dollars for some players and estimates for
    others -- and must therefore be able to say which is which, one player at a time."""

    unmatched: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def coverage(self) -> int:
        return len(self.values)

    @property
    def is_estimate(self) -> bool:
        """True unless *every* value here is real market dollars.

        Board-level and deliberately pessimistic: a board that is nine-tenths estimated is an
        estimated board. Use :meth:`is_estimate_for` for the per-player answer.
        """
        if self.sources:
            return any(source != CsvMarketValues.name for source in self.sources.values())
        return self.source != CsvMarketValues.name

    def is_estimate_for(self, player_id: str) -> bool:
        """Whether *this player's* number is an estimate rather than an observed market price."""
        return self.sources.get(player_id, self.source) != CsvMarketValues.name

    def source_for(self, player_id: str) -> str | None:
        """Which provider supplied this player's value, or ``None`` if nothing did."""
        if player_id not in self.values:
            return None
        return self.sources.get(player_id, self.source)

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


def _read_records(
    handle: Iterable[str],
) -> tuple[list[str] | None, list[tuple[int, dict[str, str]]]]:
    """Parse a CSV into ``(header, [(file_line, row), ...])``, dropping comments and blanks.

    Comments and blank lines are dropped **after** csv has parsed the file, never before.
    Filtering physical lines first is wrong in a way that only shows up on real spreadsheet
    output: a quoted field may legally contain a newline, so one logical record can span
    several physical lines. A physical-line filter deletes blank lines from inside quoted
    fields, and pairing its output back against the record stream raises on any file
    containing one -- taking the whole pricing run down with an error naming neither the file
    nor a line, on input Excel and Google Sheets both emit.

    Parsing first also makes the comment test exact: a record is a comment when its *first
    field* starts with ``#``, so a ``#`` opening a continuation line inside a quoted value is
    content, which is what it is.

    ``csv.reader.line_num`` counts physical lines consumed, so it names the line the record
    *ends* on. For a single-line row that is the row's own line, which is what a user needs;
    for a multi-line row it points at the end of the record, which is still in the right place.
    """
    reader = csv.reader(handle)
    records: list[tuple[int, list[str]]] = []
    for row in reader:
        if not row or not any(cell.strip() for cell in row) or row[0].lstrip().startswith("#"):
            continue
        records.append((reader.line_num, row))

    if not records:
        return None, []
    _header_line, header = records[0]
    return header, [
        # `zip` without `strict`: a short row leaves later columns missing and a long one drops
        # the overflow, which is exactly what DictReader does and what a hand-edited file wants.
        # The value column simply comes back absent and the row is reported as unreadable.
        (line, dict(zip(header, row, strict=False)))
        for line, row in records[1:]
    ]


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
    synonyms; ``$47``, ``47`` and ``1,200`` all parse. Comment and blank rows are dropped after
    parsing, so a quoted field containing a newline -- which Excel and Google Sheets both emit
    -- survives intact. A ``player_id`` column, if present, wins over name resolution and is the
    escape hatch for a name collision the file cannot express.

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
            header, rows = _read_records(handle)

        fields = header or []
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

        values: dict[str, float] = {}
        unmatched: list[str] = []
        duplicates: list[str] = []
        for line, row in rows:
            label = (row.get(name_col or "") or row.get(id_col or "") or "").strip()
            try:
                dollars = parse_dollars(row.get(value_col) or "")
            except (ValueError, TypeError):
                unmatched.append(f"line {line} {label!r}: unreadable value {row.get(value_col)!r}")
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
    those same amounts to players in ADP order. Only the *ordering* comes from the market.

    **The ladder's total is preserved only when the ranked list is at least as long as the
    ladder**, and the earlier version of this docstring claimed otherwise. When fewer players
    carry a usable ADP than there are rungs, there is nobody to hand the surplus rungs to, and
    no rearrangement of the remaining players can make the total come out: the shortfall is
    real information about the ADP feed's coverage, not an arithmetic slip to be papered over
    by rescaling. It is reported in ``notes`` with the dollars involved, and
    :attr:`MarketValues.total` then genuinely is less than the ladder's. This matters live: the
    feed already reports nearly 200 projected players with no usable ``adp_2qb``.

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
        unranked = len(eligible) - len(ranked)
        if unranked > 0:
            # Counted against the players actually being priced, not against the payload. A
            # projected player with no record in the feed at all carries no ADP either, and an
            # earlier version missed exactly those, understating the gap it was reporting.
            notes.append(
                f"{unranked} of {len(eligible)} priced players carry no usable {self.adp_field}"
                + (f" ({missing} present in the feed but unusable)" if missing else "")
            )
        if len(ranked) < len(self.ladder):
            dropped = sum(self.ladder[len(ranked) :])
            notes.append(
                f"ladder has {len(self.ladder) - len(ranked)} more rungs than there are ranked "
                f"players, so ${dropped:.0f} of it goes unassigned and the total is short by "
                f"that much; the ADP feed does not cover the whole board"
            )
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
    """Layer the providers: every player takes the value from the highest-authority source
    that has one.

    Args:
        required: Size of the priced pool, used only to describe coverage in the notes.
        min_fraction: Retained for callers that want the old whole-board threshold reported.
            It no longer decides anything, because it should never have decided this.

    **This was winner-take-all and that was wrong.** A provider had to cover half the priced
    pool -- 80 of 160 -- or contribute nothing at all. The module's own stated primary purpose
    is to make ``floor(0.75 * auction_value)`` computable for the twenty keepers, and the
    template tells the user "the 20 keepers matter most". A user doing exactly that supplied
    twenty real dollar values, fell under the threshold, and had every one of them silently
    replaced by an ADP estimate. The feature did not do the job its own docstring said it
    existed for.

    Layering removes the cliff. Real auction values are used wherever they exist; the fallbacks
    fill the gaps and nothing else. Twenty real values are twenty real values.

    Provenance survives per player, because the alternative is a board where some prices are
    observed and some are guessed and nothing says which. ``sources`` maps every player to the
    provider that supplied their number, :meth:`MarketValues.is_estimate_for` answers the
    question one player at a time, and the board-level :attr:`MarketValues.is_estimate` stays
    true unless *every* value came from real market data.

    Every provider's ``unmatched`` rows are collected, prefixed with their source. Previously
    only the winner's survived, so a CSV that lost by five rows took the reasons for its
    forty-five failures with it -- leaving the user no way to learn which rows to fix, which is
    precisely the situation this function's docstring promised to prevent.
    """
    if not providers:
        raise ValueError("no market value providers supplied")

    values: dict[str, float] = {}
    sources: dict[str, str] = {}
    unmatched: list[str] = []
    notes: list[str] = []
    for provider in providers:
        result = provider.market_values(players)
        fresh = {pid: v for pid, v in result.values.items() if pid not in values}
        values.update(fresh)
        sources.update(dict.fromkeys(fresh, result.source))
        unmatched.extend(f"[{result.source}] {row}" for row in result.unmatched)
        notes.extend(f"{result.source}: {note}" for note in result.notes)
        notes.append(
            f"{result.source}: supplied {len(fresh)} value(s)"
            + (
                f", {result.coverage - len(fresh)} already covered"
                if result.coverage > len(fresh)
                else ""
            )
        )

    real = [pid for pid, source in sources.items() if source == CsvMarketValues.name]
    threshold = max(1, int(required * min_fraction))
    notes.insert(
        0,
        f"{len(values)} player(s) carry a market value against a priced pool of {required}; "
        f"{len(real)} of them are real auction dollars"
        + ("" if len(values) >= threshold else f" (below the {threshold} whole-board threshold)"),
    )
    return MarketValues(
        source=_layered_source(sources),
        values=values,
        sources=sources,
        unmatched=tuple(unmatched),
        notes=tuple(notes),
    )


def _layered_source(sources: Mapping[str, str]) -> str:
    """Name the layer honestly: one source if that is all there was, otherwise all of them."""
    distinct = sorted(set(sources.values()))
    if not distinct:
        return "none"
    if len(distinct) == 1:
        return distinct[0]
    return "+".join(distinct)
