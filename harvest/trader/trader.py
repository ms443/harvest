# Builtins
import re
import threading
import sys
from sys import exit
from signal import signal, SIGINT
import time
import logging

# External libraries

# Submodule imports
from harvest.utils import *
from harvest.storage import BaseStorage
from harvest.api.yahoo import YahooStreamer
from harvest.api.dummy import DummyStreamer
from harvest.api.paper import PaperBroker
from harvest.algo import BaseAlgo
from harvest.storage import BaseStorage
from harvest.storage import BaseLogger
from harvest.server import Server

class Trader:
    """
    :watch: Watchlist containing all stock and cryptos to monitor.
        The user may or may not own them. Note it does NOT contain options. 
    :broker: Both the broker and streamer store a Broker object.
        Broker places orders and retrieves latest account info like equity.
    :streamer: Streamer retrieves the latest stock price and calls handler().
    """

    interval_list = ['1MIN', '5MIN', '15MIN', '30MIN', '1HR', '1DAY']

    def __init__(self, streamer=None, broker=None, storage=None, debug=False):      
        """Initializes the Trader. 
        """
        signal(SIGINT, self.exit)

        # Harvest only supports Python 3.8 or newer.
        if sys.version_info[0] < 3 or sys.version_info[1] < 8:
            raise Exception("Harvest requires Python 3.8 or above.")

        if streamer == None:
            self.streamer = YahooStreamer()
        else:
            self.streamer = streamer
  
        if broker == None:
            if isinstance(self.streamer, YahooStreamer) or isinstance(self.streamer, DummyStreamer):
                self.broker = PaperBroker()
            else:
                self.broker = self.streamer
        else:
            self.broker = broker

        self.timestamp_prev = now()
        self.timestamp = self.timestamp_prev

        self.watch = []             # Watchlist of securities.
        self.account = {}           # Local cache of account data.

        self.stock_positions = []   # Local cache of current stock positions.
        self.option_positions = []  # Local cache of current options positions.
        self.crypto_positions = []  # Local cache of current crypto positions.

        self.order_queue = []       # Queue of unfilled orders.

        if storage is None:
            self.storage = BaseStorage() 
        else:
            self.storage = storage                
        self.logger = BaseLogger()

        self.block_lock = threading.Lock() # Lock for streams that receive data asynchronously.

        self.algo = []
        self.is_save = False

        self.server = Server(self)

        self.debugger = logging.getLogger("harvest")
        self.debugger.setLevel("DEBUG")
        if debug:
            f_handler = logging.FileHandler("trader.log")
            f_handler.setLevel(logging.DEBUG)
            f_format = logging.Formatter('%(asctime)s : %(name)s : %(levelname)s : %(message)s')
            f_handler.setFormatter(f_format)
            self.debugger.addHandler(f_handler)
        
        self.debugger.debug("Test")
        
        c_handler = logging.StreamHandler()
        if debug:
            c_handler.setLevel(logging.DEBUG)
        else:
            c_handler.setLevel(logging.INFO)
        c_format = logging.Formatter('%(asctime)s : %(name)s : %(levelname)s : %(message)s')
        c_handler.setFormatter(c_format)
        self.debugger.addHandler(c_handler)

        self.debugger.warning("Test")

    def _setup(self, interval, aggregations, sync=True):
        """
        Initializes data and parameters necessary to run the program.
        :param str interval: Interval to run the algorithm.
        :param str List(str) aggregations: List of intervals to aggregate the data.
        :param bool sync: If True, fetches any open positions and orders from the specified broker. 
        """
        self.sync = sync
        self.interval = interval
        self.aggregations = aggregations

        if not self.streamer.has_interval(interval):
            raise Exception(f"""Interval '{interval}' is not supported by the selected streamer.\n 
                                The streamer only supports {self.streamer.interval_list}""")

        # Ensure that all aggregate intervals are greater than 'interval'
        int_i = self.interval_list.index(interval)
        for agg in aggregations:
            if self.interval_list.index(agg) <= int_i:
                raise Exception(f"""Interval '{interval}' is greater than aggregation interval '{agg}'\n
                                    All intervals in aggregations must be greater than specified interval '{interval}'""")

        # Initialize the account
        self._setup_account()

        # If sync is on, call the broker to load pending orders and all positions currently held.
        if sync:
            self._setup_stats()
            for s in self.stock_positions:
                self.watch.append(s['symbol'])
            for s in self.option_positions:
                self.watch.append(s['symbol'])
            for s in self.crypto_positions:
                self.watch.append(s['symbol'])
            for s in self.order_queue:
                self.watch.append(s['symbol'])     

        if len(self.watch) == 0:
            raise Exception(f"No securities were added to watchlist")

        # Remove duplicates in watchlist
        self.watch = list(set(self.watch))
        self.debugger.debug(f"Watchlist: {self.watch}")

        self.fetch_interval = self.streamer.fetch_interval
        self.debugger.debug(f"Interval: {interval}\nFetch interval: {self.fetch_interval}")

        if interval != self.fetch_interval:
            self.aggregations.insert(0, interval)
        self.debugger.debug(f"Aggregations: {self.aggregations}")

        if len(self.algo) == 0:
            self.debugger.debug(f"No algorithm specified. Using BaseAlgo")
            self.algo = [BaseAlgo()]
        
        self.storage_init()

        self.debugger.debug("Setup complete")

        self.load_watch = True
    
    def storage_init(self):
        """Initializes the storage.
        """
        for s in self.watch:
            for i in [self.fetch_interval] + self.aggregations:
                df = self.streamer.fetch_price_history(s, i)
                self.storage.store(s, i, df)

    def _setup_account(self):
        """Initializes local cache of account info. 
        For testing, it should manually be specified
        """
        ret = self.broker.fetch_account()
        self.account = ret
    
    def _setup_stats(self):
        """Initializes local cache of stocks, options, and crypto positions.
        """
        
        # Get any pending orders 
        ret = self.broker.fetch_order_queue()
        self.order_queue = ret
        self.debugger.debug(f"Fetched orders:\n{self.order_queue}")

        # Get positions
        pos = self.broker.fetch_stock_positions()
        self.stock_positions = pos
        pos = self.broker.fetch_option_positions()
        self.option_positions = pos
        pos = self.broker.fetch_crypto_positions()
        self.crypto_positions = pos
        self.debugger.debug(f"Fetched positions:\n{self.stock_positions}\n{self.option_positions}\n{self.crypto_positions}")

        # Update option stats
        self.broker.update_option_positions(self.option_positions)
        self.debugger.debug(f"Updated option positions:\n{self.option_positions}")

    def start(self, interval='5MIN', aggregations=[], sync = True, kill_switch: bool=False, server=False): 
        """Entry point to start the system. 
        
        :param str? interval: The interval to run the algorithm. defaults to '5MIN'
        :param list[str]? aggregations: A list of intervals. The Trader will aggregate data to the intervals specified in this list.
            For example, if this is set to ['5MIN', '30MIN'], and interval is '1MIN', the algorithm will have access to 
            5MIN, 30MIN aggregated data in addition to 1MIN data. defaults to None
        :param bool? sync: If true, the system will sync with the broker and fetch current positions and pending orders. defaults to true. 
        :kill_switch: If true, kills the infinite loop in streamer. Primarily used for testing. defaults to False.

        """
        self.debugger.debug(f"Starting Harvest...")

        self.broker.setup(self.watch, interval, self, self.main)
        self.streamer.setup(self.watch, interval, self, self.main)
        self._setup(interval, aggregations, sync)

        self.debugger.debug(f"Initializing algorithms...")
        for a in self.algo:
            a.trader = self
            a.watch = self.watch
            a.fetch_interval = self.fetch_interval
            a.setup()

        self.blocker = {}
        for w in self.watch:
            self.blocker[w] = False
        self.block_queue = {}
        self.needed = self.watch.copy()

        self.is_save = True
        
        if server:
            self.server.start()

        self.streamer.start(kill_switch)

    def timeout(self):
        self.debugger.debug("Begin timeout timer")
        time.sleep(1)
        if not self.all_recv:
            self.debugger.debug("Force flush")
            self.flush()

    def main(self, df_dict):

        self.debugger.debug(f"Received: \n{df_dict}")

        if len(self.needed) == len(self.watch):
            self.timestamp_prev = self.timestamp
            self.timestamp = now()
            first = True

        symbols = [k for k, v in df_dict.items()]
        self.debugger.debug(f"Got data for: {symbols}")
        self.needed = list(set(self.needed) - set(symbols))
        self.debugger.debug(f"Still need data for: {self.needed}")
 
        self.block_queue.update(df_dict)
        self.debugger.debug(self.block_queue)
        
        # If all data has been received, pass on the data
        if len(self.needed) == 0:
            self.debugger.debug("All data received")
            self.needed = self.watch.copy()
            self.main_helper(self.block_queue)
            self.block_queue = {}
            self.needed = self.watch.copy()
            self.all_recv = True
            return 
        
        # If there are data that has not been received, 
        # start a timer 
        if first:
            timer = threading.Thread(target=self.timeout, daemon=True)
            timer.start()
            self.all_recv = False
        
        
    def flush(self):
        # For missing data, repeat the existing one
        got  = list(set(self.watch) - set(self.needed))[0]
        timestamp = self.block_queue[got].index[-1]
        for n in self.needed:
            data = self.storage.load(n, self.fetch_interval).iloc[[-1]].copy()
            data.index = [timestamp]
            self.block_queue[n] = data
        self.needed = self.watch.copy()
        self.main_helper(self.block_queue)
        self.block_queue = {}
        return

    def main_helper(self, df_dict):

        new_day = self.timestamp.date() > self.timestamp_prev.date()
        
        # Periodically refresh access tokens
        if self.timestamp.hour % 12 == 0 and self.timestamp.minute == 0:
            self.streamer.refresh_cred()
        
        # Save the data locally
        for s in self.watch:
            self.storage.store(s, self.fetch_interval, df_dict[s])
        
        # Aggregate the data to other intervals
        for s in self.watch:
            for i in self.aggregations:
                self.storage.aggregate(s, self.fetch_interval, i)

        # If an order was processed, fetch the latest position info.
        # Otherwise, calculate current positions locally
        update = self._update_order_queue()
        self._update_stats(df_dict, new=update, option_update=True)
        
        if not self.is_freq(self.timestamp):
            return

        meta = {
            'new_day': new_day
        }

        new_algo = []
        for a in self.algo:
            # try:
            a.main()
                # new_algo.append(a)
            # except Exception as e:
            #     warning(f"Algorithm {a} failed, removing from algorithm list.\nException: {e}")
        # self.algo = new_algo

        self.broker.exit()
        self.streamer.exit()

    def is_freq(self, time):
        """Helper function to determine if algorithm should be invoked for the
        current timestamp. For example, if interval is 30MIN,
        algorithm should be called when minutes are 0 and 30.
        """
        time = time.astimezone(pytz.timezone('UTC'))
        if self.fetch_interval == self.interval:
            return True 

        if self.interval == '1MIN':
            return True 
        
        minutes = time.minute
        hours = time.hour
        if self.interval == '1HR':
            if minutes == 0:
                return True 
            else:
                return False
        
        if self.interval == '1DAY':
            # TODO: Use API to get real-time market hours
            if minutes == 50 and hours == 19:
                return True 
            else:
                return False

        val = int(re.sub("[^0-9]", "", self.interval))
        if minutes % val == 0:
            return True 
        else: 
            return False

    def _update_order_queue(self):
        """Check to see if outstanding orders have been accpted or rejected
        and update the order queue accordingly.
        """
        self.debugger.debug(f"Updating order queue: {self.order_queue}")
        for i, order in enumerate(self.order_queue):
            if 'type' not in order:
                raise Exception(f"key error in {order}\nof {self.order_queue}")
            if order['type'] == 'STOCK':
                stat = self.broker.fetch_stock_order_status(order["id"])
            elif order['type'] == 'OPTION':
                stat = self.broker.fetch_option_order_status(order["id"])
            elif order['type'] == 'CRYPTO':
                stat = self.broker.fetch_crypto_order_status(order["id"])
            self.debugger.debug(f"Updating status of order {order['id']}")
            self.order_queue[i] = stat

        self.debugger.debug(f"Updated order queue: {self.order_queue}")
        new_order = []
        order_filled = False
        for order in self.order_queue:
            if order['status'] == 'filled':
                order_filled = True  
            else:
                new_order.append(order)
        self.order_queue = new_order

        # if an order was processed, update the positions and account info
        return order_filled
           
    def _update_stats(self, df_dict, new=False, option_update=False):
        """Update local cache of stocks, options, and crypto positions
        """
        # Update entries in local cache
        # API should also be called if load_watch is false, as there is a high chance 
        # that data in local cache are not representative of the entire portfolio,
        # meaning total equity cannot be calculated locally
        if new or not self.load_watch:
            pos = self.broker.fetch_stock_positions()
            self.stock_positions = [p for p in pos if p['symbol'] in self.watch]
            pos = self.broker.fetch_option_positions()
            self.option_positions = [p for p in pos if p['symbol'] in self.watch]
            pos = self.broker.fetch_crypto_positions()
            self.crypto_positions = [p for p in pos if p['symbol'] in self.watch]
            ret = self.broker.fetch_account()
            self.account = ret

        if option_update:
            self.broker.update_option_positions(self.option_positions)
        
        self.debugger.debug(f"Stock positions: {self.stock_positions}")
        self.debugger.debug(f"Option positions: {self.option_positions}")
        self.debugger.debug(f"Crypto positions: {self.crypto_positions}")

        if new or not self.load_watch:
            return 
        else:
            net_value = 0
            for p in self.stock_positions + self.crypto_positions:
                key = p['symbol']
                price = df_dict[key][key]['close'][0]
                p['current_price'] = price 
                value = price * p['quantity']
                p['market_value'] = value
                net_value = net_value + value
            
            equity = net_value + self.account['cash']
            self.account['equity'] = equity

    def fetch_chain_info(self, *args, **kwargs):
        return self.streamer.fetch_chain_info(*args, **kwargs)
    
    def fetch_chain_data(self, *args, **kwargs):
        return self.streamer.fetch_chain_data(*args, **kwargs)
    
    def fetch_option_market_data(self, *args, **kwargs):
        return self.streamer.fetch_option_market_data(*args, **kwargs)

    def buy(self, symbol: str, quantity: int, in_force: str, extended: bool):
        ret = self.broker.buy(symbol, quantity, in_force, extended)
        if ret == None:
            self.debugger.debug("BUY failed")
            return None
        self.order_queue.append(ret)
        self.debugger.debug(f"BUY: {self.timestamp}, {symbol}, {quantity}")
        self.debugger.debug(f"BUY order queue: {self.order_queue}")
        asset_type = 'crypto' if is_crypto(symbol) else 'stock'
        self.logger.add_transaction(self.timestamp, 'buy', asset_type, symbol, quantity)
        return ret

    def sell(self, symbol: str, quantity: int, in_force: str, extended: bool):
        ret = self.broker.sell(symbol, quantity, in_force, extended)
        if ret == None:
            self.debugger.debug("SELL failed")
            return None
        self.order_queue.append(ret)
        self.debugger.debug(f"SELL: {self.timestamp}, {symbol}, {quantity}")
        self.debugger.debug(f"SELL order queue: {self.order_queue}")
        asset_type = 'crypto' if is_crypto(symbol) else 'stock'
        self.logger.add_transaction(self.timestamp, 'sell', asset_type, symbol, quantity)
        return ret


    def buy_option(self, symbol: str, quantity: int, in_force: str):
        ret = self.broker.buy_option(symbol, quantity, in_force)
        if ret == None:
            raise Exception("BUY failed")
        self.order_queue.append(ret)
        self.debugger.debug(f"BUY: {self.timestamp}, {symbol}, {quantity}")
        self.debugger.debug(f"BUY order queue: {self.order_queue}")
        self.logger.add_transaction(self.timestamp, 'buy', 'option', symbol, quantity)
        return ret

    def sell_option(self, symbol: str, quantity: int, in_force: str):
        ret = self.broker.sell_option(symbol, quantity, in_force)
        if ret == None:
            raise Exception("SELL failed")
        self.order_queue.append(ret)
        self.debugger.debug(f"SELL: {self.timestamp}, {symbol}, {quantity}")
        self.debugger.debug(f"SELL order queue: {self.order_queue}")
        self.logger.add_transaction(self.timestamp, 'sell', 'option', symbol, quantity)
        return ret
    
    def set_algo(self, algo):
        """Specifies the algorithm to use.

        :param Algo algo: The algorithm to use. You can either pass in a single Algo class, or a 
            list of Algo classes. 
        """
        if isinstance(algo, list):
            self.algo = algo
        else:
            self.algo = [algo]
    
    def set_symbol(self, symbol):
        """Specifies the symbol(s) to watch.
        
        Cryptocurrencies should be prepended with an `@` to differentiate them from stocks. 
        For example, '@ETH' will refer to Etherium, while 'ETH' will refer to Ethan Allen Interiors. 
        If this method was previously called, the symbols specified earlier will be replaced with the
        new symbols.
        
        :symbol str symbol: Ticker Symbol(s) of stock or cryptocurrency to watch. 
            It can either be a string, or a list of strings. 
        """
        if isinstance(symbol, list):
            self.watch = symbol
        else:
            self.watch = [symbol]
    
    def exit(self, signum, frame):
        # TODO: Gracefully exit
        self.debugger.debug("\nStopping Harvest...")
        exit(0)
    
    