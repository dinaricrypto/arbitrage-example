from dataclasses import dataclass

from .. import Chain


@dataclass
class DinariAddress:
    order_processor_address: str


DINARI_ADDRESSES: dict[Chain, DinariAddress] = {
    Chain.ARBITRUM: DinariAddress(order_processor_address="0x4c3bD1Ac4F62F25388c02caf8e3e0D32d09Ff8B3")
}
