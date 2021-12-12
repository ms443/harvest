# Builtin Imports
import re
import sys
import time
import random
import logging
import datetime as dt
from datetime import datetime, timezone as tz
from enum import IntEnum, auto
from zoneinfo import ZoneInfo

# External Imports
import pandas as pd

# Configure a logger used by all of Harvest.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s : %(name)s : %(levelname)s : %(message)s",
    datefmt="%m/%d/%Y %I:%M:%S %p",
    handlers=[logging.FileHandler("harvest.log"), logging.StreamHandler(sys.stdout)],
)
debugger = logging.getLogger("harvest")


class Interval(IntEnum):
    SEC_15 = auto()
    MIN_1 = auto()
    MIN_5 = auto()
    MIN_15 = auto()
    MIN_30 = auto()
    HR_1 = auto()
    DAY_1 = auto()


def interval_string_to_enum(str_interval: str):
    if str_interval == "15SEC":
        return Interval.SEC_15
    elif str_interval == "1MIN":
        return Interval.MIN_1
    elif str_interval == "5MIN":
        return Interval.MIN_5
    elif str_interval == "15MIN":
        return Interval.MIN_15
    elif str_interval == "30MIN":
        return Interval.MIN_30
    elif str_interval == "1HR":
        return Interval.HR_1
    elif str_interval == "1DAY":
        return Interval.DAY_1
    else:
        raise ValueError(f"Invalid interval string {str_interval}")


class Stats:
    def __init__(self, timestamp=None, timezone=None, watchlist_cfg=None):
        self._timestamp = timestamp
        self._timezone = timezone
        self._watchlist_cfg = watchlist_cfg

    @property
    def timestamp(self):
        return self._timestamp

    @timestamp.setter
    def timestamp(self, value):
        self._timestamp = value

    @property
    def timezone(self):
        return self._timezone

    @timezone.setter
    def timezone(self, value):
        self._timezone = value

    @property
    def watchlist_cfg(self):
        return self._watchlist_cfg

    @watchlist_cfg.setter
    def watchlist_cfg(self, value):
        self._watchlist_cfg = value


class Functions:
    def __init__(
        self,
        buy=None,
        sell=None,
        fetch_chain_data=None,
        fetch_chain_info=None,
        fetch_option_market_data=None,
        get_asset_quantity=None,
        load=None,
        save=None,
    ):
        self.buy = buy
        self.sell = sell
        self.fetch_chain_data = fetch_chain_data
        self.fetch_chain_info = fetch_chain_info
        self.fetch_option_market_data = fetch_option_market_data
        self.get_asset_quantity = get_asset_quantity
        self.load = load
        self.save = save


class Account:
    def __init__(self, account_name=None):
        self._account_name = account_name
        self._positions = Positions()

        self._asset_value = 0
        self._cash = 0
        self._equity = 0

        self._buying_power = 0
        self._multiplier = 1

    def init(self, dict):
        self._equity = dict["equity"]
        self._cash = dict["cash"]
        self._buying_power = dict["buying_power"]
        self._multiplier = dict["multiplier"]

    def update(self):
        self._asset_value = self._positions.value
        self._equity = self._asset_value + self._cash

    @property
    def account_name(self):
        return self._account_name

    @property
    def positions(self):
        return self._positions

    @property
    def equity(self):
        return self._equity

    @property
    def cash(self):
        return self._cash

    @property
    def buying_power(self):
        return self._buying_power

    @property
    def multiplier(self):
        return self._multiplier


class Positions:
    def __init__(self, stock=[], option=[], crypto=[]):
        self._stock = stock
        self._option = option
        self._crypto = crypto

    def update(self, stock=None, option=None, crypto=None):
        if stock is not None:
            self._stock = stock
        if option is not None:
            self._option = option
        if crypto is not None:
            self._crypto = crypto

    @property
    def stock(self):
        return self._stock

    @property
    def option(self):
        return self._option

    @property
    def crypto(self):
        return self._crypto

    @property
    def all(self):
        return self._stock + self._option + self._crypto

    @property
    def stock_crypto(self):
        return self._stock + self._crypto

    @property
    def value(self):
        return sum(p.value for p in self.all)

    def __str__(self):
        return f"Positions: \n\tStocks: {self._stock}\n\tOptions: {self._option}\n\tCrypto: {self._crypto}"


class Position:
    def __init__(self, symbol, quantity, avg_price):
        self._symbol = symbol
        self._quantity = quantity
        self._avg_price = avg_price

        self._current_price = 0
        self._value = 0
        self._profit = 0
        self._profit_percent = 0

    def update(self, current_price: float):
        self._current_price = current_price
        self._value = self._current_price * self._quantity
        self._profit = self._value - self._avg_price * self._quantity
        self._profit_percent = self._profit / self._avg_price

    def buy(self, quantity, price):
        self._avg_price = (self._avg_price * self._quantity + price * quantity) / (
            self._quantity + quantity
        )
        self._quantity += quantity

    def sell(self, quantity, price):
        self._quantity -= quantity

    @property
    def symbol(self):
        return self._symbol

    @property
    def quantity(self):
        return self._quantity

    @property
    def value(self):
        return self._value

    @property
    def avg_price(self):
        return self._avg_price


class OptionPosition(Position):
    def __init__(
        self, symbol, quantity, avg_price, strike, expiration, option_type, multiplier
    ):
        super().__init__(symbol, quantity, avg_price)
        self._base_symbol = occ_to_data(symbol)[0]
        self._strike = strike
        self._expiration = expiration
        self._option_type = option_type
        self._multiplier = multiplier

    @property
    def base_symbol(self):
        return self._base_symbol


def interval_enum_to_string(enum):
    try:
        name = enum.name
        unit, val = name.split("_")
        return val + unit
    except:
        return str(enum)


def is_freq(time, interval):
    """Determine if algorithm should be invoked for the
    current time, given the interval. For example, if interval is 30MIN,
    algorithm should be called when minutes are 0 and 30, like 11:30 or 12:00.
    """
    time = time.astimezone(tz.utc)

    if interval == Interval.MIN_1:
        return True

    minutes = time.minute
    hours = time.hour
    if interval == Interval.DAY_1:
        # TODO: Use API to get real-time market hours
        return minutes == 50 and hours == 19
    elif interval == Interval.HR_1:
        return minutes == 0
    val, _ = expand_interval(interval)

    return minutes % val == 0


def expand_interval(interval: Interval):
    """Given a IntEnum interval, returns the unit of time and the number of units."""
    string = interval.name
    unit, value = string.split("_")
    return int(value), unit


def expand_string_interval(interval: str):
    """Given a string interval, returns the unit of time and the number of units.
    For example, "3DAY" should return (3, "DAY")
    """
    num = [c for c in interval if c.isdigit()]
    value = int("".join(num))
    unit = interval[len(num) :]
    return value, unit


def interval_to_timedelta(interval: Interval) -> dt.timedelta:
    """Converts an IntEnum interval into a timedelta object of equal value."""
    expanded_units = {"DAY": "days", "HR": "hours", "MIN": "minutes"}
    value, unit = expand_interval(interval)
    params = {expanded_units[unit]: value}
    return dt.timedelta(**params)


def symbol_type(symbol):
    """Determines the type of the asset the symbol represents.
    This can be 'STOCK', 'CRYPTO', or 'OPTION'
    """
    if len(symbol) > 6:
        return "OPTION"
    elif symbol[0] == "@":
        return "CRYPTO"
    else:
        return "STOCK"


def occ_to_data(symbol: str):
    original_symbol = symbol
    debugger.debug(f"Converting {symbol} to data")
    try:
        sym = ""
        symbol = symbol.replace(" ", "")
        i = 0
        while symbol[i].isalpha():
            i += 1
        sym = symbol[:i]
        symbol = symbol[i:]
        debugger.debug(f"{sym}, {symbol}")

        date = dt.datetime.strptime(symbol[:6], "%y%m%d")
        debugger.debug(f"{date}, {symbol}")
        option_type = "call" if symbol[6] == "C" else "put"
        debugger.debug(f"{option_type}, {symbol}")
        price = float(symbol[7:]) / 1000
        debugger.debug(f"{price}, {symbol}")
        return sym, date, option_type, price
    except Exception as e:
        debugger.error(f"Error parsing OCC symbol: {original_symbol}, {e}")
        # return None, None, None, None
        raise Exception(f"Error parsing OCC symbol: {original_symbol}, {e}")


# =========== DataFrame utils ===========


def normalize_pandas_dt_index(df: pd.DataFrame) -> pd.Index:
    return df.index.floor("min")


def aggregate_df(df, interval: Interval) -> pd.DataFrame:
    sym = df.columns[0][0]
    df = df[sym]
    op_dict = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    val, unit = expand_interval(interval)
    val = str(val)
    if unit == "1HR":
        val = "H"
    elif unit == "MIN":
        val += "T"
    else:
        val = "D"
    df = df.resample(val).agg(op_dict)
    df.columns = pd.MultiIndex.from_product([[sym], df.columns])

    return df.dropna()


# ========== Date utils ==========


def now() -> dt.datetime:
    """
    Returns the current time precise to the minute in the UTC timezone
    """
    return dt.datetime.now(tz.utc).replace(microsecond=0, second=0)


def epoch_zero() -> dt.datetime:
    """
    Returns a datetime object corresponding to midnight 1/1/1970 UTC
    """
    return dt.datetime(1970, 1, 1, tzinfo=tz.utc)


def date_to_str(day) -> str:
    return day.strftime("%Y-%m-%d")


def str_to_date(day) -> str:
    return dt.datetime.strptime(day, "%Y-%m-%d")


def str_to_datetime(date: str) -> dt.datetime:
    """
    :date: A string in the format YYYY-MM-DD hh:mm
    """
    if len(date) <= 10:
        return dt.datetime.strptime(date, "%Y-%m-%d")
    return dt.datetime.strptime(date, "%Y-%m-%d %H:%M")


def convert_input_to_datetime(datetime, timezone: ZoneInfo):

    if datetime is None:
        return None
    elif isinstance(datetime, Timestamp):
        datetime = tz.localize(datetime.timestamp)
    elif isinstance(datetime, str):
        datetime = str_to_datetime(datetime)
    elif isinstance(datetime, dt.datetime):
        datetime = datetime.replace(tzinfo=timezone)
    else:
        raise ValueError(f"Cannot convert {datetime} to datetime.")

    datetime = datetime.replace(tzinfo=timezone)
    datetime = datetime.astimezone(tz.utc)

    return datetime


def convert_input_to_timedelta(period):
    """Converts period into a timedelta object.
    Period can be a string, timedelta object, or a Timerange object."""
    if period is None:
        return None
    elif isinstance(period, Timerange):
        return period.timerange
    elif isinstance(period, str):
        expanded_units = {"DAY": "days", "HR": "hours", "MIN": "minutes"}
        val, unit = expand_string_interval(period)
        return dt.timedelta(**{expanded_units[unit]: val})
    elif isinstance(period, dt.timedelta):
        return period
    else:
        raise ValueError(f"Cannot convert {period} to timedelta.")


def has_timezone(date: dt.datetime) -> bool:
    return date.tzinfo is not None and date.tzinfo.utcoffset(date) is not None


def pandas_timestamp_to_local(df: pd.DataFrame, timezone: ZoneInfo) -> pd.DataFrame:
    """
    Converts the timestamp of a Pandas dataframe to a timezone naive DateTime object in local time.
    """
    df.index = df.index.map(lambda x: datetime_utc_to_local(x, timezone))
    return df


def pandas_datetime_to_utc(df: pd.DataFrame, timezone: ZoneInfo) -> pd.DataFrame:
    """
    Converts timezone naive datetime index of dataframes to a timezone aware datetime index
    adjusted to UTC timezone.
    """
    df.index = df.index.map(lambda x: x.replace(tzinfo=timezone).astimezone(tz.utc))
    return df


def datetime_utc_to_local(date_time: dt.datetime, timezone: ZoneInfo) -> dt.datetime:
    """
    Converts a datetime object in UTC to local time, represented as a
    timezone naive datetime object.
    """
    # If date_time is a Dataframe timestamp, we must first convert to a normal Datetime object
    if not isinstance(date_time, dt.datetime):
        date_time = date_time.to_pydatetime()

    new_tz = date_time.astimezone(timezone)
    return new_tz.replace(tzinfo=None)


class Timestamp:
    def __init__(self, *args) -> None:
        if len(args) == 1:
            timestamp = args[0]
            if isinstance(timestamp, str):
                self.timestamp = str_to_datetime(timestamp)
            elif isinstance(timestamp, dt.datetime):
                self.timestamp = timestamp
            else:
                raise ValueError(f"Invalid timestamp type {type(timestamp)}")
        elif len(args) > 1:
            self.timestamp = dt.datetime(*args)

    def __sub__(self, other):
        return Timerange(self.timestamp - other.timestamp)


class Timerange:
    def __init__(self, *args) -> None:
        if len(args) == 1:
            timerange = args[1]
            if isinstance(timerange, dt.timedelta):
                self.timerange = timerange
            else:
                raise ValueError(f"Invalid timestamp type {type(timerange)}")
        elif len(args) > 1:
            range_list = ["days", "hours", "minutes"]
            dict = {range_list[i]: arg for i, arg in enumerate(args)}
            self.timerange = dt.timedelta(**dict)


# ========== Misc. utils ==========
def mark_up(x):
    return round(x * 1.05, 2)


def mark_down(x):
    return round(x * 0.95, 2)


def is_crypto(symbol: str) -> bool:
    return symbol[0] == "@"


############ Functions used for testing #################


def gen_data(symbol: str, points: int = 50) -> pd.DataFrame:
    n = now()
    index = [n - dt.timedelta(minutes=1) * i for i in range(points)][::-1]
    df = pd.DataFrame(index=index, columns=["low", "high", "close", "open", "volume"])
    df.index.rename("timestamp", inplace=True)
    df["low"] = [random.random() for _ in range(points)]
    df["high"] = [random.random() for _ in range(points)]
    df["close"] = [random.random() for _ in range(points)]
    df["open"] = [random.random() for _ in range(points)]
    df["volume"] = [random.random() for _ in range(points)]
    # df.index = normalize_pandas_dt_index(df)
    df.columns = pd.MultiIndex.from_product([[symbol], df.columns])

    return df


def not_gh_action(func):
    def wrapper(*args, **kwargs):
        if "GITHUB_ACTIONS" in os.environ:
            return
        func(*args, **kwargs)
        return wrapper
