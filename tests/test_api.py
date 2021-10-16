# Builtins
from harvest.api.dummy import DummyStreamer
import pathlib
import unittest
import datetime as dt
import os

import pandas as pd

from harvest.api._base import StreamAPI
from harvest.api.dummy import DummyStreamer
from harvest.trader import PaperTrader
from harvest.utils import *


class TestAPI(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        with open("secret.yaml", "a") as f:
            f.write("data: 0")
            f.close()

    def test_timeout(self):
        stream = StreamAPI()
        stream.fetch_account = lambda: None
        stream.fetch_price_history = lambda x, y: pd.DataFrame()
        stream.fetch_account = lambda: {"cash": 100, "equity": 100}
        t = PaperTrader(stream)
        stream.trader = t
        stream.trader_main = t.main
        t.set_symbol(["A", "B"])

        t.start("1MIN", sync=False)

        # Save dummy data
        data = gen_data("A", 10)
        t.storage.store("A", Interval.MIN_1, data)
        data = gen_data("B", 10)
        t.storage.store("B", Interval.MIN_1, data)

        # Save the last datapoint of B
        a_cur = t.storage.load("A", Interval.MIN_1)
        b_cur = t.storage.load("B", Interval.MIN_1)

        # Only send data for A
        data = gen_data("A", 1)
        data.index = [stream.timestamp + dt.timedelta(minutes=1)]
        data = {"A": data}
        stream.main(data)

        # Wait for the timeout
        time.sleep(2)

        # Check if A has been added to storage
        self.assertEqual(
            a_cur["A"]["close"][-1],
            t.storage.load("A", Interval.MIN_1)["A"]["close"][-2],
        )
        self.assertEqual(
            data["A"]["A"]["close"][-1],
            t.storage.load("A", Interval.MIN_1)["A"]["close"][-1],
        )
        # Check if B has been duplicated
        self.assertEqual(
            b_cur["B"]["close"][-1],
            t.storage.load("B", Interval.MIN_1)["B"]["close"][-2],
        )
        self.assertEqual(
            b_cur["B"]["close"][-1],
            t.storage.load("B", Interval.MIN_1)["B"]["close"][-1],
        )

    def test_timeout_cancel(self):
        stream = StreamAPI()
        stream.fetch_account = lambda: None
        stream.fetch_price_history = lambda x, y: pd.DataFrame()
        stream.fetch_account = lambda: {"cash": 100, "equity": 100}
        t = PaperTrader(stream)
        stream.trader = t
        stream.trader_main = t.main
        t.set_symbol(["A", "B"])

        t.start("1MIN", sync=False)

        # Save dummy data
        data = gen_data("A", 10)
        t.storage.store("A", Interval.MIN_1, data)
        data = gen_data("B", 10)
        t.storage.store("B", Interval.MIN_1, data)

        # Save the last datapoint of B
        a_cur = t.storage.load("A", Interval.MIN_1)
        b_cur = t.storage.load("B", Interval.MIN_1)

        # Send data for A and B
        data_a = gen_data("A", 1)
        data_a.index = [a_cur.index[-1] + dt.timedelta(minutes=1)]
        data_a = {"A": data_a}
        data_b = gen_data("B", 1)
        data_b.index = [b_cur.index[-1] + dt.timedelta(minutes=1)]
        data_b = {"B": data_b}
        stream.main(data_a)

        # Wait
        time.sleep(0.1)
        stream.main(data_b)

        # Check if A has been added to storage
        self.assertEqual(
            a_cur["A"]["close"][-1],
            t.storage.load("A", Interval.MIN_1)["A"]["close"][-2],
        )
        self.assertEqual(
            data_a["A"]["A"]["close"][-1],
            t.storage.load("A", Interval.MIN_1)["A"]["close"][-1],
        )
        # Check if B has been added to storage
        self.assertEqual(
            b_cur["B"]["close"][-1],
            t.storage.load("B", Interval.MIN_1)["B"]["close"][-2],
        )
        self.assertEqual(
            data_b["B"]["B"]["close"][-1],
            t.storage.load("B", Interval.MIN_1)["B"]["close"][-1],
        )

    @classmethod
    def tearDownClass(self):
        os.remove("secret.yaml")


if __name__ == "__main__":
    unittest.main()
