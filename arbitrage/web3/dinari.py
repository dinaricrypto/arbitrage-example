from eth_utils import to_checksum_address

from web3 import Web3
from web3.contract import Contract

from .abi import DINARI_ORDER_PROCESSOR_ABI


def get_order_processor_contract(provider: Web3, address: str) -> Contract:
    return provider.eth.contract(address=to_checksum_address(address), abi=DINARI_ORDER_PROCESSOR_ABI)
