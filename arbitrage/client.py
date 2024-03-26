import os
from urllib.parse import urlparse

from eth_account.signers.local import LocalAccount
from polygon import RESTClient

from web3 import Web3
from web3.middleware import construct_sign_and_send_raw_middleware


def get_web3_provider_from_env() -> Web3:
    uri = os.environ["ARB_PROVIDER_URI"]
    scheme = urlparse(uri).scheme

    match scheme:
        case "http" | "https":
            return Web3(Web3.HTTPProvider(uri))
        case "wss":
            return Web3(Web3.WebsocketProvider(uri))
        case _:
            raise NotImplementedError("Provided URI is not supported")


def get_polygon_client_from_env() -> RESTClient:
    polygon_api_key = os.environ["ARB_POLYGON_API_KEY"]
    return RESTClient(api_key=polygon_api_key)


def get_wallet_from_env(provider: Web3) -> LocalAccount:
    provider.eth.account.enable_unaudited_hdwallet_features()
    account = provider.eth.account.from_mnemonic(
        os.environ["ARB_WALLET_MNEMONIC"], account_path=os.environ["ARB_WALLET_PATH"]
    )
    provider.middleware_onion.add(construct_sign_and_send_raw_middleware(account))
    return account
