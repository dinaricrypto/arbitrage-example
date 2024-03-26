from datetime import datetime, timedelta
from decimal import Decimal
from time import sleep
from typing import Optional

from eth_account.datastructures import SignedMessage
from eth_account.messages import encode_typed_data
from eth_account.signers.local import LocalAccount
from eth_utils.units import units

from arbitrage.web3 import Chain
from web3 import Web3
from web3.contract import Contract

CHAIN_ID_TO_BLOCKTIME_IN_S: dict[int, float] = {Chain.ARBITRUM: 0.25}
CHAIN_ID_TO_DEFAULT_CONFIRMATION_CYCLES_TO_WAIT: dict[int, int] = {Chain.ARBITRUM: 5}

# Update units to accommodate all decimal places
for i in range(1, 19):
    units[str(i)] = Decimal(f"1{'0' * i}")


def convert_amount_to_wei(amount: Decimal | float | int, unit: str = "ether") -> int:
    return Web3.to_wei(amount, unit)


def convert_wei_to_ether(amount: int, unit: str = "ether") -> Decimal:
    amount_in_ether = Web3.from_wei(amount, unit)

    if isinstance(amount_in_ether, Decimal):
        return amount_in_ether
    else:
        return Decimal(amount_in_ether)


def build_eip2612_permit_msg(
    token_contract: Contract, owner: LocalAccount, spender: str, value: int
) -> tuple[dict, SignedMessage]:
    try:
        if callable(getattr(token_contract.functions, "version", None)):
            version = token_contract.functions.version().call()
        else:
            version = "1"
    except:  # noqa: E722
        version = "1"

    permit_msg: dict = {
        "domain": {
            "name": token_contract.functions.name().call(),
            "version": version,
            "chainId": token_contract.w3.eth.chain_id,
            "verifyingContract": token_contract.address,
        },
        "message": {
            "owner": owner.address,
            "spender": spender,
            "value": value,
            "nonce": token_contract.functions.nonces(owner.address).call(),
            "deadline": int((datetime.now() + timedelta(minutes=20)).timestamp()),
        },
        "primaryType": "Permit",
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Permit": [
                {"name": "owner", "type": "address"},
                {"name": "spender", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "nonce", "type": "uint256"},
                {"name": "deadline", "type": "uint256"},
            ],
        },
    }
    signed_permit_msg = owner.sign_message(encode_typed_data(full_message=permit_msg))

    return permit_msg, signed_permit_msg


def sleep_for_confirmation(chain_id: int, confirmation: Optional[int] = None) -> None:
    if chain_id in CHAIN_ID_TO_BLOCKTIME_IN_S:
        if confirmation:
            sleep(CHAIN_ID_TO_BLOCKTIME_IN_S[chain_id] * confirmation)
        elif chain_id in CHAIN_ID_TO_DEFAULT_CONFIRMATION_CYCLES_TO_WAIT:
            sleep(CHAIN_ID_TO_BLOCKTIME_IN_S[chain_id] * CHAIN_ID_TO_DEFAULT_CONFIRMATION_CYCLES_TO_WAIT[chain_id])
