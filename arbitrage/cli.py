from decimal import Decimal
import logging
import os
from queue import Queue
import signal
from threading import Event, Thread
from typing import Any, Optional

import click
from dotenv import load_dotenv

from web3 import Web3
from web3.constants import MAX_INT

from .client import get_polygon_client_from_env, get_wallet_from_env, get_web3_provider_from_env
from .swap import Swap
from .swap.camelot import evaluate_camelot, swap_camelot_buy, swap_camelot_sell
from .tick_data import Tick, TickSource
from .tick_data.camelot import poll_camelot_pool
from .tick_data.polygon import poll_polygon
from .web3 import Chain
from .web3.address.camelot import CAMELOT_ADDRESSES, CamelotAddress
from .web3.address.dinari import DINARI_ADDRESSES, DinariAddress
from .web3.address.dshare import DSHARE_ADDRESSES, DShareAddress
from .web3.erc20 import get_dshare_contract

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s: %(levelname)s/%(processName)s/%(threadName)s] %(message)s",
)
logger = logging.getLogger(__name__)

load_dotenv()

SHUTDOWN_EVENT: Event = Event()


def shutdown_signal_handler(_sig: Any, _frame: Any) -> None:
    logger.info("Shutting down")
    SHUTDOWN_EVENT.set()


# Register signal handlers for shutdown
for s in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
    signal.signal(s, shutdown_signal_handler)


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.option("--polling_interval", type=float, default=1.0, help="How frequently to poll for tick data (in seconds)")
@click.option(
    "--max_allowable_tick_delta_in_s",
    type=int,
    default=60,
    help="Max delta allowed between ticks (in seconds) for evaluation",
)
@click.option(
    "--min_price_percentage_delta",
    type=float,
    default=1,
    help="Minimum delta between prices to trigger arbitrage; defined as whole number percentages (ex, 1 for 1%, 1.1 for 1.1%)",
)
@click.option(
    "--max_allowed_tokens", type=float, default=1, help="Max amount of tokens allowed to trade (in units of eth)"
)
@click.option(
    "--is-dry-run",
    is_flag=True,
    default=False,
    help="Turn on to not run any trades",
)
def camelot(
    polling_interval: float,
    max_allowable_tick_delta_in_s: int,
    min_price_percentage_delta: float,
    max_allowed_tokens: float,
    is_dry_run: bool,
) -> None:
    """
    Arbitrages between Camelot and Dinari
    """
    if is_dry_run:
        logger.warning("Dry run flag enabled. No trades will be executed!")

    # Instantiate clients
    provider = get_web3_provider_from_env()
    polygon_client = get_polygon_client_from_env()
    wallet = get_wallet_from_env(provider)

    # Validate addresses
    chain_id = Chain(provider.eth.chain_id)
    if chain_id not in CAMELOT_ADDRESSES:
        logger.error(f"{chain_id} is not supported")
        return
    camelot_address: CamelotAddress = CAMELOT_ADDRESSES[chain_id]

    if chain_id not in DINARI_ADDRESSES:
        logger.error(f"{chain_id} is not supported")
        return
    dinari_address: DinariAddress = DINARI_ADDRESSES[chain_id]

    # Get token addresses
    ticker_symbol = os.environ["ARB_DSHARE_TICKER_SYMBOL"]
    dshare_address: Optional[DShareAddress] = None
    for da in DSHARE_ADDRESSES[chain_id]:
        if da.ticker_symbol == ticker_symbol:
            dshare_address = da
            break
    if dshare_address is None or dshare_address.camelot_pool_address is None:
        logger.error(f"{ticker_symbol} is not supported")
        return

    # Instantiate threads
    tick_queue: Queue[Tick] = Queue(maxsize=20)
    buy_swap_queue: Queue[Swap] = Queue(maxsize=20)
    sell_swap_queue: Queue[Swap] = Queue(maxsize=20)

    # Start threads
    threads: list[Thread] = [
        Thread(
            target=swap_camelot_buy,
            args=(
                buy_swap_queue,
                SHUTDOWN_EVENT,
                provider,
                wallet,
                dshare_address.camelot_pool_address,
                camelot_address.router_address,
                dinari_address.order_processor_address,
                dshare_address.token_address,
                dshare_address.wrapped_address,
                is_dry_run,
            ),
        ),
        Thread(
            target=swap_camelot_sell,
            args=(
                sell_swap_queue,
                SHUTDOWN_EVENT,
                provider,
                wallet,
                dshare_address.camelot_pool_address,
                camelot_address.router_address,
                dinari_address.order_processor_address,
                dshare_address.token_address,
                dshare_address.wrapped_address,
                is_dry_run,
            ),
        ),
        Thread(
            target=evaluate_camelot,
            args=(
                tick_queue,
                buy_swap_queue,
                sell_swap_queue,
                SHUTDOWN_EVENT,
                TickSource.POLYGON,
                provider,
                dshare_address.camelot_pool_address,
                dshare_address.wrapped_address,
                max_allowable_tick_delta_in_s,
                Decimal(min_price_percentage_delta),
                Decimal(max_allowed_tokens),
            ),
        ),
        Thread(
            target=poll_camelot_pool,
            args=(
                tick_queue,
                SHUTDOWN_EVENT,
                polling_interval,
                provider,
                dshare_address.camelot_pool_address,
                camelot_address.quoter_address,
                dshare_address.wrapped_address,
                Decimal(max_allowed_tokens),
            ),
        ),
        Thread(
            target=poll_polygon,
            args=(tick_queue, SHUTDOWN_EVENT, polling_interval, polygon_client, ticker_symbol),
        ),
    ]

    for t in threads:
        t.start()


@cli.command()
def setup_approval_for_wrapping() -> None:
    """
    Sets up approval for quickly wrapping tokens
    """

    # Instantiate clients
    provider = get_web3_provider_from_env()
    wallet = get_wallet_from_env(provider)

    # Validate addresses
    chain_id = Chain(provider.eth.chain_id)

    # Get token address
    ticker_symbol = os.environ["ARB_DSHARE_TICKER_SYMBOL"]
    dshare_address: Optional[DShareAddress] = None
    for da in DSHARE_ADDRESSES[chain_id]:
        if da.ticker_symbol == ticker_symbol:
            dshare_address = da
            break
    if dshare_address is None or dshare_address.camelot_pool_address is None:
        logger.error(f"{ticker_symbol} is not supported")
        return

    dshare_contract = get_dshare_contract(provider, dshare_address.token_address)
    max_allowance = Web3.to_int(hexstr=MAX_INT)
    wrapped_allowance = dshare_contract.functions.allowance(wallet.address, dshare_address.wrapped_address).call()

    if wrapped_allowance != max_allowance:
        tx_hash = dshare_contract.functions.approve(dshare_address.wrapped_address, max_allowance).transact(
            transaction={
                "from": wallet.address,
            }
        )
        dshare_contract.w3.eth.wait_for_transaction_receipt(tx_hash)
        logger.info(f"Set up approval: {Web3.to_hex(tx_hash)}")


@cli.command()
def verify_setup() -> None:
    logger.info("======")
    logger.info("ENVIRONMENT VARIABLES")
    logger.info("")
    for k in os.environ:
        if k.startswith("ARB_"):
            logger.info(f"{k}: {os.environ[k]}")

    logger.info("======")
    logger.info("WEB3")
    logger.info("")
    provider = get_web3_provider_from_env()
    wallet = get_wallet_from_env(provider)
    logger.info(f"Chain Id: {provider.eth.chain_id}")
    logger.info(f"Wallet Address: {wallet.address}")


if __name__ == "__main__":
    cli()
