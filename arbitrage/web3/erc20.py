from eth_utils import to_checksum_address

from web3 import Web3
from web3.contract import Contract

from .abi import DSHARE_ABI, ERC20_ABI, WRAPPED_DSHARE_ABI


def get_erc20_contract(provider: Web3, address: str) -> Contract:
    return provider.eth.contract(address=to_checksum_address(address), abi=ERC20_ABI)


def get_dshare_contract(provider: Web3, address: str) -> Contract:
    return provider.eth.contract(address=to_checksum_address(address), abi=DSHARE_ABI)


def get_wrapped_dshare_contract(provider: Web3, address: str) -> Contract:
    return provider.eth.contract(address=to_checksum_address(address), abi=WRAPPED_DSHARE_ABI)
