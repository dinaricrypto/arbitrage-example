from datetime import UTC, date, datetime
from decimal import Decimal
import logging
from queue import Queue
from threading import Event
from time import sleep

from polygon import RESTClient

from . import Tick, TickSource

logger = logging.getLogger(__name__)


def poll_polygon(
    queue: Queue[Tick], shutdown_event: Event, polling_interval: float, polygon_client: RESTClient, ticker: str
) -> None:
    logger.info("Looping polling Polygon")
    while not shutdown_event.is_set():
        try:
            today = date.today()
            market_price = polygon_client.get_aggs(ticker, 1, "minute", today, today, sort="desc", limit=1)
            if market_price and len(market_price) > 0:
                queue.put(
                    Tick(
                        source=TickSource.POLYGON,
                        price_per_share=Decimal(market_price[0].close),
                        timestamp=datetime.fromtimestamp(market_price[0].timestamp / 1000, tz=UTC),
                        side=None,
                    )
                )
        except:  # noqa: E722
            pass
        sleep(polling_interval)
    logger.info("Shutdown polling Polygon")
