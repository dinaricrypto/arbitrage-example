from eth_utils import to_checksum_address

from web3 import Web3
from web3.contract import Contract

from .abi import CAMELOT_POOL_ABI, CAMELOT_QUOTER_ABI, CAMELOT_ROUTER_ABI


def get_pool_contract(provider: Web3, address: str) -> Contract:
    return provider.eth.contract(address=to_checksum_address(address), abi=CAMELOT_POOL_ABI)


def get_quoter_contract(provider: Web3, address: str) -> Contract:
    return provider.eth.contract(address=to_checksum_address(address), abi=CAMELOT_QUOTER_ABI)


def get_router_contract(provider: Web3, address: str) -> Contract:
    return provider.eth.contract(address=to_checksum_address(address), abi=CAMELOT_ROUTER_ABI)
