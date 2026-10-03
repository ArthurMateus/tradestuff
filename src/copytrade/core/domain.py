"""Shared domain types (F1). Later changes are CTO-serialized commits (§10 collision rule 2).

Interface stub written by the test designer. The developer owns the implementation.
"""

from __future__ import annotations

from enum import Enum


class ActionKind(Enum):
    """What an order intent does to our exposure. Opens and adds are entries; reduces and closes are exits."""

    OPEN = "open"
    ADD = "add"
    REDUCE = "reduce"
    CLOSE = "close"
