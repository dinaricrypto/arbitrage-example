from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
import logging
from queue import Empty, Queue
import threading
from threading import Event
from time import sleep
from typing import Optional, cast

from eth_account.signers.local import LocalAccount
from hexbytes import HexBytes

from web3 import Web3
from web3.constants import ADDRESS_ZERO
from web3.contract.contract import ContractEvent
from web3.exceptions import Web3Exception
from web3.logs import DISCARD
from web3.types import EventData

from . import Exchange, Swap
from ..tick_data import Tick, TickOrderSide, TickSource
from ..util import is_date_in_trading_hours
from ..web3.camelot import get_pool_contract, get_router_contract
from ..web3.dinari import get_order_processor_contract
from ..web3.erc20 import get_dshare_contract, get_erc20_contract, get_wrapped_dshare_contract
from ..web3.util import build_eip2612_permit_msg, convert_amount_to_wei, convert_wei_to_ether, sleep_for_confirmation

logger = logging.getLogger(__name__)
# Uncomment below to get debug logs
# logger.setLevel(logging.DEBUG)

WALLET_LOCK = threading.Lock()
DINARI_ORDER_PRECISION = Decimal(".000001")


def evaluate_camelot(
    tick_queue: Queue[Tick],
    buy_swap_queue: Queue[Swap],
    sell_swap_queue: Queue[Swap],
    shutdown_event: Event,
    brokerage_source: TickSource,
    provider: Web3,
    pool_address: str,
    wrapped_dshare_address: str,
    max_allowable_tick_delta_in_s: int,
    min_price_percentage_delta: Decimal,
    max_wrapped_dshare_allowed_in_eth: Decimal,
    tick_queue_timeout: float = 0.1,
) -> None:
    # Instantiate contracts
    pool_contract = get_pool_contract(provider, pool_address)

    # Retrieve token information
    token_0 = pool_contract.functions.token0().call()
    token_1 = pool_contract.functions.token1().call()
    stable_coin_address = token_1 if token_0 == wrapped_dshare_address else token_0
    stable_coin_contract = get_erc20_contract(provider, stable_coin_address)
    stable_coin_decimals = str(stable_coin_contract.functions.decimals().call())

    logger.info("Looping evaluating ticks for swapping")
    latest_tick_by_source: dict[TickSource, Tick] = {}
    while not shutdown_event.is_set():
        try:
            tick = tick_queue.get(timeout=tick_queue_timeout)
            latest_tick_by_source[tick.source] = tick

            dt_now = datetime.now(UTC)
            if is_date_in_trading_hours(dt_now):
                # Get latest ticks
                brokerage_tick = latest_tick_by_source.get(brokerage_source)
                camelot_tick = latest_tick_by_source.get(TickSource.CAMELOT)

                # Skip if latest ticks aren't valid
                if not (brokerage_tick and camelot_tick and camelot_tick.side is not None):
                    continue
                logger.debug("===")
                logger.debug(f"Brokerage Price:\t{brokerage_tick.price_per_share}")
                logger.debug(f"Camelot Price:\t{camelot_tick.price_per_share}")
                logger.debug(f"Camelot Side:\t{camelot_tick.side}")

                # Evaluate ticks
                brokerage_dt = brokerage_tick.timestamp
                camelot_dt = camelot_tick.timestamp

                # Calculate time slippage
                now_brokerage_time_delta = abs((dt_now - brokerage_dt).total_seconds())
                now_camelot_time_delta = abs((dt_now - camelot_dt).total_seconds())
                brokerage_camelot_time_delta = abs((brokerage_dt - camelot_dt).total_seconds())
                logger.debug(f"Now <> Brokerage Delta:\t{now_brokerage_time_delta}")
                logger.debug(f"Now <> Camelot Delta:\t{now_camelot_time_delta}")
                logger.debug(f"Brokerage <> Camelot Delta:\t{brokerage_camelot_time_delta}")

                # Calculate price difference
                if brokerage_tick.price_per_share > camelot_tick.price_per_share:
                    price_delta_in_percentage = (
                        1 - (camelot_tick.price_per_share / brokerage_tick.price_per_share)
                    ) * 100
                else:
                    price_delta_in_percentage = (
                        1 - (brokerage_tick.price_per_share / camelot_tick.price_per_share)
                    ) * 100
                logger.debug(f"Price Delta:\t{price_delta_in_percentage}")

                is_within_time_slippage = (
                    now_brokerage_time_delta < max_allowable_tick_delta_in_s
                    and now_camelot_time_delta < max_allowable_tick_delta_in_s
                    and brokerage_camelot_time_delta < max_allowable_tick_delta_in_s
                )
                is_within_price_delta = price_delta_in_percentage > min_price_percentage_delta

                # Skip loop if ticks don't meet condition
                if not (is_within_time_slippage and is_within_price_delta):
                    continue

                # Create swap request
                swap: Optional[Swap] = None
                if (
                    brokerage_tick.price_per_share > camelot_tick.price_per_share
                    and camelot_tick.side == TickOrderSide.BUY
                ):
                    swap = Swap(
                        timestamp=dt_now,
                        buy_exchange=Exchange.CAMELOT,
                        sell_exchange=Exchange.DINARI,
                        stable_coin_amount_in_wei=convert_amount_to_wei(
                            max_wrapped_dshare_allowed_in_eth * camelot_tick.price_per_share, stable_coin_decimals
                        ),
                    )
                elif (
                    brokerage_tick.price_per_share < camelot_tick.price_per_share
                    and camelot_tick.side == TickOrderSide.SELL
                ):
                    swap = Swap(
                        timestamp=dt_now,
                        buy_exchange=Exchange.DINARI,
                        sell_exchange=Exchange.CAMELOT,
                        stable_coin_amount_in_wei=convert_amount_to_wei(
                            max_wrapped_dshare_allowed_in_eth * brokerage_tick.price_per_share, stable_coin_decimals
                        ),
                    )

                if swap:
                    # Queue swap if valid
                    swap_amount_in_eth = convert_wei_to_ether(swap.stable_coin_amount_in_wei, stable_coin_decimals)
                    if camelot_tick.side == TickOrderSide.BUY:
                        logger.debug(
                            f"TRIGGER {swap.buy_exchange} @ {camelot_tick.price_per_share} -> {swap.sell_exchange} @ {brokerage_tick.price_per_share} for {swap_amount_in_eth}"
                        )
                        buy_swap_queue.put(swap)
                    else:
                        logger.debug(
                            f"TRIGGER {swap.buy_exchange} @ {brokerage_tick.price_per_share} -> {swap.sell_exchange} @ {camelot_tick.price_per_share} for {swap_amount_in_eth}"
                        )
                        sell_swap_queue.put(swap)
        except Empty:
            pass
        except:  # noqa: E722
            logger.exception("There was an error")
    logger.info("Shutdown evaluating ticks for swapping")


def swap_camelot_buy(
    swap_queue: Queue[Swap],
    shutdown_event: Event,
    provider: Web3,
    account: LocalAccount,
    pool_address: str,
    router_address: str,
    order_processor_contract_address: str,
    dshare_address: str,
    wrapped_dshare_address: str,
    is_dry_run: bool,
    max_request_delta_in_s: int = 5,
    queue_poll_timeout: float = 0.1,
) -> None:
    # Get wallet address
    wallet_address = account.address
    chain_id = provider.eth.chain_id

    # Initialize contracts for Camelot
    pool_contract = get_pool_contract(provider, pool_address)
    router_contract = get_router_contract(provider, router_address)

    # Initialize contracts for Dinari
    order_processor_contract = get_order_processor_contract(provider, order_processor_contract_address)

    # Initialize contracts for tokens
    token_0 = pool_contract.functions.token0().call()
    token_1 = pool_contract.functions.token1().call()
    stable_coin_address = token_1 if token_0 == wrapped_dshare_address else token_0
    stable_coin_contract = get_erc20_contract(provider, stable_coin_address)
    stable_coin_decimals = str(stable_coin_contract.functions.decimals().call())
    dshare_contract = get_dshare_contract(provider, dshare_address)
    dshare_decimals = str(dshare_contract.functions.decimals().call())
    wrapped_dshare_contract = get_wrapped_dshare_contract(provider, wrapped_dshare_address)

    logger.info("Looping Camelot swap for buying")
    while not shutdown_event.is_set():
        # Acquire lock on wallet before processing
        WALLET_LOCK.acquire()
        try:
            swap = swap_queue.get(timeout=queue_poll_timeout)

            # Skip if swap request isn't within allotted time slippage
            dt_now = datetime.now(UTC)
            request_time_delta = abs((swap.timestamp - dt_now).total_seconds())

            if request_time_delta > max_request_delta_in_s:
                WALLET_LOCK.release()
                continue

            # Skip if swap is not between Camelot and Dinari
            if not (swap.buy_exchange == Exchange.CAMELOT and swap.sell_exchange == Exchange.DINARI):
                WALLET_LOCK.release()
                continue

            # Check balances before swapping
            current_stablecoin_balance = stable_coin_contract.functions.balanceOf(wallet_address).call()
            in_amount = min(
                swap.stable_coin_amount_in_wei,
                current_stablecoin_balance,
            )

            if in_amount > current_stablecoin_balance:
                WALLET_LOCK.release()
                continue

            # Skip as dry run
            if is_dry_run:
                logger.info("Dry run is active. Skipping swapping.")
                WALLET_LOCK.release()
                continue

            logger.info("=====")
            logger.info("Executing arbitrage...")

            logger.info(f"Sending {convert_wei_to_ether(in_amount, stable_coin_decimals)} to Camelot")
            # Buy on Camelot
            deadline = int((datetime.now() + timedelta(minutes=1)).timestamp())
            try:
                # Generate permit
                camelot_permit_msg, camelot_signed_permit_msg = build_eip2612_permit_msg(
                    stable_coin_contract, account, router_contract.address, in_amount
                )
                # Send a multicall to selfPermit then exactInputSingle
                camelot_tx_hash = router_contract.functions.multicall(
                    [
                        router_contract.encodeABI(
                            fn_name="selfPermit",
                            args=[
                                stable_coin_contract.address,
                                camelot_permit_msg["message"]["value"],
                                camelot_permit_msg["message"]["deadline"],
                                camelot_signed_permit_msg.v,
                                HexBytes(Web3.to_hex(camelot_signed_permit_msg.r)),
                                HexBytes(Web3.to_hex(camelot_signed_permit_msg.s)),
                            ],
                        ),
                        router_contract.encodeABI(
                            fn_name="exactInputSingle",
                            args=[
                                (
                                    stable_coin_address,
                                    wrapped_dshare_address,
                                    wallet_address,
                                    deadline,
                                    in_amount,
                                    0,
                                    0,
                                )
                            ],
                        ),
                    ]
                ).transact(
                    transaction={
                        "from": account.address,
                    }
                )
                camelot_tx_receipt = router_contract.w3.eth.wait_for_transaction_receipt(camelot_tx_hash)
                logger.info(f"Transaction Hash for buying on Camelot: {Web3.to_hex(camelot_tx_hash)}")

                if camelot_tx_receipt["status"] != 1:
                    logger.info("There was an issue buying on Camelot")
                    shutdown_event.set()
                    WALLET_LOCK.release()
                    continue
                else:
                    sleep_for_confirmation(chain_id)

                swap_events: list[EventData] = pool_contract.events.Swap().process_receipt(
                    camelot_tx_receipt, errors=DISCARD
                )
                if swap_events:
                    if token_0 == stable_coin_address:
                        wrapped_dshare_amount = abs(swap_events[0]["args"]["amount1"])
                    else:
                        wrapped_dshare_amount = abs(swap_events[0]["args"]["amount0"])
                else:
                    logger.info("There was an issue buying on Camelot")
                    shutdown_event.set()
                    WALLET_LOCK.release()
                    continue
            except Web3Exception:
                logger.exception("There was an issue buying on Camelot")
                shutdown_event.set()
                WALLET_LOCK.release()
                continue

            # Unwrap tokens
            try:
                dshare_amount = wrapped_dshare_contract.functions.previewRedeem(wrapped_dshare_amount).call()

                redeem_tx_hash = wrapped_dshare_contract.functions.redeem(
                    wrapped_dshare_amount, wallet_address, wallet_address
                ).transact(
                    transaction={
                        "from": account.address,
                    }
                )
                redeem_tx_receipt = router_contract.w3.eth.wait_for_transaction_receipt(redeem_tx_hash)
                logger.info(f"Transaction Hash for unwrapping dShare: {Web3.to_hex(redeem_tx_hash)}")

                if redeem_tx_receipt["status"] != 1:
                    logger.info("There was an issue unwrapping dShare")
                    shutdown_event.set()
                    WALLET_LOCK.release()
                    continue
                else:
                    sleep_for_confirmation(chain_id)
            except Web3Exception:
                logger.exception("There was an issue unwrapping dShare")
                shutdown_event.set()
                WALLET_LOCK.release()
                continue

            # Sell on Dinari
            try:
                # Round dshare to the correct precision
                dshare_amount = convert_amount_to_wei(
                    convert_wei_to_ether(dshare_amount, dshare_decimals).quantize(
                        DINARI_ORDER_PRECISION, rounding=ROUND_DOWN
                    ),
                    dshare_decimals,
                )
                # Generate permit
                dinari_permit_msg, dinari_signed_permit_msg = build_eip2612_permit_msg(
                    dshare_contract, account, order_processor_contract.address, dshare_amount
                )
                # Send a multicall to selfPermit then requestOrder
                dinari_tx_hash = order_processor_contract.functions.multicall(
                    [
                        order_processor_contract.encodeABI(
                            fn_name="selfPermit",
                            args=[
                                dshare_contract.address,
                                dinari_permit_msg["message"]["owner"],
                                dinari_permit_msg["message"]["value"],
                                dinari_permit_msg["message"]["deadline"],
                                dinari_signed_permit_msg.v,
                                HexBytes(Web3.to_hex(dinari_signed_permit_msg.r)),
                                HexBytes(Web3.to_hex(dinari_signed_permit_msg.s)),
                            ],
                        ),
                        order_processor_contract.encodeABI(
                            fn_name="requestOrder",
                            args=[
                                (
                                    account.address,
                                    dshare_contract.address,
                                    stable_coin_address,
                                    True,
                                    0,
                                    dshare_amount,
                                    0,
                                    0,
                                    1,
                                    ADDRESS_ZERO,
                                    0,
                                )
                            ],
                        ),
                    ]
                ).transact(
                    transaction={
                        "from": account.address,
                    }
                )
                dinari_tx_receipt = order_processor_contract.w3.eth.wait_for_transaction_receipt(dinari_tx_hash)
                logger.info(f"Transaction Hash for selling on Dinari: {Web3.to_hex(dinari_tx_hash)}")

                if dinari_tx_receipt["status"] != 1:
                    logger.exception("There was an issue selling on Dinari")
                    shutdown_event.set()
                    WALLET_LOCK.release()
                    continue
                else:
                    sleep_for_confirmation(chain_id)

                order_request_events: list[
                    EventData
                ] = order_processor_contract.events.OrderRequested().process_receipt(dinari_tx_receipt, errors=DISCARD)
                if order_request_events:
                    dinari_order_id = order_request_events[0]["args"]["id"]

                    dinari_order_fill_filter = cast(
                        ContractEvent, order_processor_contract.events.OrderFill
                    ).create_filter(
                        fromBlock=dinari_tx_receipt["blockNumber"], argument_filters={"id": dinari_order_id}
                    )

                    out_amount: Optional[int] = None
                    # Process existing entries
                    for ed in dinari_order_fill_filter.get_all_entries():
                        out_amount = ed["args"]["receivedAmount"]

                    while out_amount is None:
                        for ed in dinari_order_fill_filter.get_new_entries():
                            out_amount = ed["args"]["receivedAmount"]
                        sleep(1)

                    logger.info(f"Received {convert_wei_to_ether(out_amount, stable_coin_decimals)} from Dinari")
                    logger.info(
                        f"Arbitrage completed. Profited {convert_wei_to_ether(out_amount-in_amount, stable_coin_decimals)}"
                    )
            except Web3Exception:
                logger.exception("There was an issue selling on Dinari")
                shutdown_event.set()
                WALLET_LOCK.release()
                continue
        except Empty:
            pass
        except:  # noqa: E722
            logger.exception("There was an error")
            shutdown_event.set()
        # Release lock on wallet after processing
        WALLET_LOCK.release()
    logger.info("Shutdown Camelot swap for buying")


def swap_camelot_sell(
    swap_queue: Queue[Swap],
    shutdown_event: Event,
    provider: Web3,
    account: LocalAccount,
    pool_address: str,
    router_address: str,
    order_processor_contract_address: str,
    dshare_address: str,
    wrapped_dshare_address: str,
    is_dry_run: bool,
    max_request_delta_in_s: int = 5,
    queue_poll_timeout: float = 0.1,
) -> None:
    # Get wallet address
    wallet_address = account.address
    chain_id = provider.eth.chain_id

    # Initialize contracts for Camelot
    pool_contract = get_pool_contract(provider, pool_address)
    router_contract = get_router_contract(provider, router_address)

    # Initialize contracts for Dinari
    order_processor_contract = get_order_processor_contract(provider, order_processor_contract_address)

    # Initialize contracts for tokens
    token_0 = pool_contract.functions.token0().call()
    token_1 = pool_contract.functions.token1().call()
    stable_coin_address = token_1 if token_0 == wrapped_dshare_address else token_0
    stable_coin_contract = get_erc20_contract(provider, stable_coin_address)
    stable_coin_decimals = str(stable_coin_contract.functions.decimals().call())
    dshare_contract = get_dshare_contract(provider, dshare_address)
    wrapped_dshare_contract = get_wrapped_dshare_contract(provider, wrapped_dshare_address)

    logger.info("Looping Camelot swap for selling")
    while not shutdown_event.is_set():
        # Acquire lock on wallet before processing
        WALLET_LOCK.acquire()
        try:
            swap = swap_queue.get(timeout=queue_poll_timeout)

            # Skip if swap request isn't within allotted time slippage
            dt_now = datetime.now(UTC)
            request_time_delta = abs((swap.timestamp - dt_now).total_seconds())

            if request_time_delta > max_request_delta_in_s:
                WALLET_LOCK.release()
                continue

            # Skip if swap is not between Camelot and Dinari
            if not (swap.buy_exchange == Exchange.DINARI and swap.sell_exchange == Exchange.CAMELOT):
                WALLET_LOCK.release()
                continue

            # Check balances before swapping
            current_stablecoin_balance = stable_coin_contract.functions.balanceOf(wallet_address).call()
            in_amount = min(
                swap.stable_coin_amount_in_wei,
                current_stablecoin_balance,
            )

            if in_amount > current_stablecoin_balance:
                WALLET_LOCK.release()
                continue

            # Skip as dry run
            if is_dry_run:
                logger.info("Dry run is active. Skipping swapping.")
                WALLET_LOCK.release()
                continue

            logger.info("=====")
            logger.info("Executing arbitrage...")

            logger.info(f"Sending {convert_wei_to_ether(in_amount, stable_coin_decimals)} to Dinari")
            # Buy on Dinari
            try:
                # Generate permit
                dinari_permit_msg, dinari_signed_permit_msg = build_eip2612_permit_msg(
                    stable_coin_contract, account, order_processor_contract.address, in_amount
                )
                # Send a multicall to selfPermit then requestOrder
                dinari_tx_hash = order_processor_contract.functions.multicall(
                    [
                        order_processor_contract.encodeABI(
                            fn_name="selfPermit",
                            args=[
                                stable_coin_contract.address,
                                dinari_permit_msg["message"]["owner"],
                                dinari_permit_msg["message"]["value"],
                                dinari_permit_msg["message"]["deadline"],
                                dinari_signed_permit_msg.v,
                                HexBytes(Web3.to_hex(dinari_signed_permit_msg.r)),
                                HexBytes(Web3.to_hex(dinari_signed_permit_msg.s)),
                            ],
                        ),
                        order_processor_contract.encodeABI(
                            fn_name="requestOrder",
                            args=[
                                (
                                    account.address,
                                    dshare_contract.address,
                                    stable_coin_address,
                                    False,
                                    0,
                                    0,
                                    in_amount,
                                    0,
                                    1,
                                    ADDRESS_ZERO,
                                    0,
                                )
                            ],
                        ),
                    ]
                ).transact(
                    transaction={
                        "from": account.address,
                    }
                )
                dinari_tx_receipt = order_processor_contract.w3.eth.wait_for_transaction_receipt(dinari_tx_hash)
                logger.info(f"Transaction Hash for buying on Dinari: {Web3.to_hex(dinari_tx_hash)}")

                if dinari_tx_receipt["status"] != 1:
                    logger.exception("There was an issue buying on Dinari")
                    shutdown_event.set()
                    WALLET_LOCK.release()
                    continue
                else:
                    sleep_for_confirmation(chain_id)

                order_request_events: list[
                    EventData
                ] = order_processor_contract.events.OrderRequested().process_receipt(dinari_tx_receipt, errors=DISCARD)
                if order_request_events:
                    dinari_order_id = order_request_events[0]["args"]["id"]

                    dinari_order_fill_filter = cast(
                        ContractEvent, order_processor_contract.events.OrderFill
                    ).create_filter(
                        fromBlock=dinari_tx_receipt["blockNumber"], argument_filters={"id": dinari_order_id}
                    )

                    dshare_amount: Optional[int] = None
                    # Process existing entries
                    for ed in dinari_order_fill_filter.get_all_entries():
                        dshare_amount = ed["args"]["receivedAmount"]

                    while dshare_amount is None:
                        for ed in dinari_order_fill_filter.get_new_entries():
                            dshare_amount = ed["args"]["receivedAmount"]
                        sleep(1)
            except Web3Exception:
                logger.exception("There was an issue buying on Dinari")
                shutdown_event.set()
                WALLET_LOCK.release()
                continue

            # Wrap tokens
            try:
                wrapped_dshare_amount = wrapped_dshare_contract.functions.previewDeposit(dshare_amount).call()

                deposit_tx_hash = wrapped_dshare_contract.functions.deposit(dshare_amount, wallet_address).transact(
                    transaction={
                        "from": account.address,
                    }
                )
                deposit_tx_receipt = router_contract.w3.eth.wait_for_transaction_receipt(deposit_tx_hash)
                logger.info(f"Transaction Hash for wrapping dShare: {Web3.to_hex(deposit_tx_hash)}")

                if deposit_tx_receipt["status"] != 1:
                    logger.info("There was an issue wrapping dShare")
                    shutdown_event.set()
                    WALLET_LOCK.release()
                    continue
                else:
                    sleep_for_confirmation(chain_id)
            except Web3Exception:
                logger.exception("There was an issue wrapping dShare")
                shutdown_event.set()
                WALLET_LOCK.release()
                continue

            # Sell on Camelot
            deadline = int((datetime.now() + timedelta(minutes=1)).timestamp())
            try:
                # Generate permit
                camelot_permit_msg, camelot_signed_permit_msg = build_eip2612_permit_msg(
                    wrapped_dshare_contract, account, router_contract.address, wrapped_dshare_amount
                )
                # Send a multicall to selfPermit then exactInputSingle
                camelot_tx_hash = router_contract.functions.multicall(
                    [
                        router_contract.encodeABI(
                            fn_name="selfPermit",
                            args=[
                                wrapped_dshare_contract.address,
                                camelot_permit_msg["message"]["value"],
                                camelot_permit_msg["message"]["deadline"],
                                camelot_signed_permit_msg.v,
                                HexBytes(Web3.to_hex(camelot_signed_permit_msg.r)),
                                HexBytes(Web3.to_hex(camelot_signed_permit_msg.s)),
                            ],
                        ),
                        router_contract.encodeABI(
                            fn_name="exactInputSingle",
                            args=[
                                (
                                    wrapped_dshare_address,
                                    stable_coin_address,
                                    wallet_address,
                                    deadline,
                                    wrapped_dshare_amount,
                                    0,
                                    0,
                                )
                            ],
                        ),
                    ]
                ).transact(
                    transaction={
                        "from": account.address,
                    }
                )
                camelot_tx_receipt = router_contract.w3.eth.wait_for_transaction_receipt(camelot_tx_hash)
                logger.info(f"Transaction Hash for selling on Camelot: {Web3.to_hex(camelot_tx_hash)}")

                if camelot_tx_receipt["status"] != 1:
                    logger.info("There was an issue selling on Camelot")
                    shutdown_event.set()
                    WALLET_LOCK.release()
                    continue
                else:
                    sleep_for_confirmation(chain_id)

                swap_events: list[EventData] = pool_contract.events.Swap().process_receipt(
                    camelot_tx_receipt, errors=DISCARD
                )
                if swap_events:
                    if token_0 == stable_coin_address:
                        out_amount = abs(swap_events[0]["args"]["amount0"])
                    else:
                        out_amount = abs(swap_events[0]["args"]["amount1"])
                    logger.info(f"Received {convert_wei_to_ether(out_amount, stable_coin_decimals)} from Camelot")
                    logger.info(
                        f"Arbitrage completed. Profited {convert_wei_to_ether(out_amount-in_amount, stable_coin_decimals)}"
                    )
                else:
                    logger.info("There was an issue selling on Camelot")
                    shutdown_event.set()
                    WALLET_LOCK.release()
                    continue
            except Web3Exception:
                logger.exception("There was an issue selling on Camelot")
                shutdown_event.set()
                WALLET_LOCK.release()
                continue
        except Empty:
            pass
        except:  # noqa: E722
            logger.exception("There was an error")
            shutdown_event.set()
        # Release lock on wallet after processing
        WALLET_LOCK.release()
    logger.info("Shutdown Camelot swap for selling")
