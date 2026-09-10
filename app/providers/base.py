"""Source-tagged values.

The master methodology forbids unsourced numbers and requires facts, estimates
and assumptions to be distinguishable. Every figure that enters the terminal is
therefore wrapped so the report can print where it came from and when.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
from enum import Enum
from typing import Any


class Basis(str, Enum):
    CONSOLIDATED = "consolidated"
    STANDALONE = "standalone"
    UNKNOWN = "unknown"


class Kind(str, Enum):
    """The evidence hierarchy from the master methodology."""

    FACT = "fact"
    ESTIMATE = "estimate"
    CONSENSUS = "consensus"
    GUIDANCE = "management guidance"
    ASSUMPTION = "model assumption"
    DERIVED = "derived"


@dataclass(frozen=True)
class Sourced:
    """A single value with its provenance."""

    value: Any
    source: str
    as_of: date | None = None
    kind: Kind = Kind.FACT
    basis: Basis = Basis.UNKNOWN
    note: str | None = None

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["as_of"] = self.as_of.isoformat() if self.as_of else None
        d["kind"] = self.kind.value
        d["basis"] = self.basis.value
        return d

    def __float__(self) -> float:
        return float(self.value)


class MissingData(Exception):
    """Raised when a required figure is unavailable.

    The terminal reports missing data rather than substituting a guess.
    """

    def __init__(self, what: str, tried: str) -> None:
        super().__init__(f"{what} unavailable (tried {tried}).")
        self.what = what
        self.tried = tried
