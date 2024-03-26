from datetime import datetime

import pytz


def is_date_in_trading_hours(_dt: datetime) -> bool:
    dt = datetime.fromtimestamp(_dt.timestamp(), tz=pytz.timezone("America/New_York"))
    if dt.hour < 9:
        return False
    elif dt.hour == 9 and dt.minute < 30:
        return False
    elif dt.hour > 16:
        return False
    elif dt.hour == 16 and dt.second >= 0:
        return False
    else:
        return True
