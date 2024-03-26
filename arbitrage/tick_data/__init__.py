from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum, auto
from typing import Optional


class TickSource(StrEnum):
    CAMELOT = auto()
    POLYGON = auto()


class TickOrderSide(StrEnum):
    BUY = auto()
    SELL = auto()


@dataclass
class Tick:
    source: TickSource
    price_per_share: Decimal
    timestamp: datetime
    side: Optional[TickOrderSide]
