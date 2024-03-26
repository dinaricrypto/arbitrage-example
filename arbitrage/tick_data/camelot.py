from datetime import UTC, datetime
from decimal import Decimal
import logging
from queue import Queue
from threading import Event
from time import sleep

from web3 import Web3

from . import Tick, TickOrderSide, TickSource
from ..web3.camelot import get_pool_contract, get_quoter_contract
from ..web3.erc20 import get_erc20_contract
from ..web3.util import convert_amount_to_wei, convert_wei_to_ether

logger = logging.getLogger(__name__)


def poll_camelot_pool(
    queue: Queue[Tick],
    shutdown_event: Event,
    polling_interval_in_s: float,
    provider: Web3,
    pool_address: str,
    quoter_address: str,
    wrapped_dshare_address: str,
    max_wrapped_dshare_allowed_in_eth: Decimal,
) -> None:
    # Instantiate contracts
    pool_contract = get_pool_contract(provider, pool_address)
    quoter_contract = get_quoter_contract(provider, quoter_address)

    # Retrieve token information
    token_0 = pool_contract.functions.token0().call()
    token_0_contract = get_erc20_contract(provider, token_0)
    token_0_decimals = token_0_contract.functions.decimals().call()
    token_1 = pool_contract.functions.token1().call()
    token_1_contract = get_erc20_contract(provider, token_1)
    token_1_decimals = token_1_contract.functions.decimals().call()

    # Start loop
    logger.info("Looping polling Camelot pool")
    while not shutdown_event.is_set():
        try:
            # Set an approximation for when Camelot was polled
            timestamp = datetime.now(UTC)

            # Get pool price
            pool_price, _, _, _, _, _, _, _ = tuple(pool_contract.functions.globalState().call())

            current_price = (pool_price / 2**96) ** 2
            price_of_t0_in_t1 = Decimal(current_price / (10**token_1_decimals / 10**token_0_decimals))
            price_of_t1_in_t0 = Decimal(1 / price_of_t0_in_t1)

            if token_0 == wrapped_dshare_address:
                queue.put(
                    Tick(
                        source=TickSource.CAMELOT,
                        price_per_share=price_of_t0_in_t1,
                        timestamp=timestamp,
                        side=None,
                    )
                )
            else:
                queue.put(
                    Tick(
                        source=TickSource.CAMELOT,
                        price_per_share=price_of_t1_in_t0,
                        timestamp=timestamp,
                        side=None,
                    )
                )

            # Get trading prices
            if token_0 == wrapped_dshare_address:
                t0_amount = convert_amount_to_wei(max_wrapped_dshare_allowed_in_eth, str(token_0_decimals))
                t1_amount = convert_amount_to_wei(
                    max_wrapped_dshare_allowed_in_eth * price_of_t0_in_t1, str(token_1_decimals)
                )
            else:
                t1_amount = convert_amount_to_wei(max_wrapped_dshare_allowed_in_eth, str(token_1_decimals))
                t0_amount = convert_amount_to_wei(
                    max_wrapped_dshare_allowed_in_eth * price_of_t1_in_t0, str(token_0_decimals)
                )

            # Poll for trading prices
            q0_timestamp = datetime.now(UTC)
            q0 = quoter_contract.functions.quoteExactInputSingle(token_0, token_1, t0_amount, 0).call()
            q0_t0_in_eth = convert_wei_to_ether(t0_amount, str(token_0_decimals))
            q0_t1_in_eth = convert_wei_to_ether(q0[0], str(token_1_decimals))

            q1_timestamp = datetime.now(UTC)
            q1 = quoter_contract.functions.quoteExactInputSingle(token_1, token_0, t1_amount, 0).call()
            q1_t0_in_eth = convert_wei_to_ether(q1[0], str(token_0_decimals))
            q1_t1_in_eth = convert_wei_to_ether(t1_amount, str(token_1_decimals))

            if token_0 == wrapped_dshare_address:
                queue.put(
                    Tick(
                        source=TickSource.CAMELOT,
                        price_per_share=q0_t1_in_eth / q0_t0_in_eth,
                        timestamp=q0_timestamp,
                        side=TickOrderSide.SELL,
                    )
                )
                queue.put(
                    Tick(
                        source=TickSource.CAMELOT,
                        price_per_share=1 / (q1_t0_in_eth / q1_t1_in_eth),
                        timestamp=q1_timestamp,
                        side=TickOrderSide.BUY,
                    )
                )
            else:
                queue.put(
                    Tick(
                        source=TickSource.CAMELOT,
                        price_per_share=1 / (q0_t1_in_eth / q0_t0_in_eth),
                        timestamp=q0_timestamp,
                        side=TickOrderSide.BUY,
                    )
                )
                queue.put(
                    Tick(
                        source=TickSource.CAMELOT,
                        price_per_share=q1_t0_in_eth / q1_t1_in_eth,
                        timestamp=q1_timestamp,
                        side=TickOrderSide.SELL,
                    )
                )
        except:  # noqa: E722
            pass

        # Sleep
        sleep(polling_interval_in_s)
    logger.info("Shutdown polling Camelot pool")
