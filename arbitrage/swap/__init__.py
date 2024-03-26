from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, auto


class Exchange(StrEnum):
    DINARI = auto()
    CAMELOT = auto()


@dataclass
class Swap:
    timestamp: datetime
    buy_exchange: Exchange
    sell_exchange: Exchange
    stable_coin_amount_in_wei: int
