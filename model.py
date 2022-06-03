"""
trading-server is a multi-asset, multi-strategy, event-driven execution
and backtesting platform (OEMS) for trading common markets.

Copyright (C) 2020  Sam Breznikar <sam@sdbgroup.io>

Licensed under GNU General Public License 3.0 or later.

Some rights reserved. See LICENSE.md, AUTHORS.md.
"""

from abc import ABC, abstractmethod
from features import Features as f
from event_types import SignalEvent
import traceback
import sys
import re


class Model(ABC):
    """
    Base class for strategy models.
    """

    def __init__(self):
        super().__init__()

    def get_operating_timeframes(self):
        """
        Return list of operating timeframes.
        """

        return self.operating_timeframes

    def get_lookback(self):
        """
        Return model's required lookback (number of
        previous bars to analyse) for a given timeframe.
        """

        return self.lookback

    def get_features(self):
        """
        Return list of features in use by the model.
        """

        return self.features

    def get_name(self):
        """
        Return model name.
        """

        return self.name

    def get_instruments(self):
        """
        Return dict of instrument amd venues the model is applicable to.
        """

        return self.instruments

    @abstractmethod
    def run(self):
        """
        Run model with given data.
        """

    @abstractmethod
    def get_required_timeframes(self, timeframes, result=False):
        """
        Given a list of operating timeframes, append additional required
        timeframe strings to the list (amend in-place, no new list created).

        To be overwritten in each model.

        Args:
            timeframes: list of current-period operating timeframes.
            result: boolean, if True, return a new list. Othewise append req
                    timeframes to the list passed in (timeframes).

        Returns:
            None.

        Raises:
            None.
        """


class EMACrossTestingOnly(Model):
    """
    For testing use only.

    Entry:
        Market entry when EMA's cross

    Stop-loss:
        None.

    Take-profit:
        Close trade and re-open in opposite direction on opposing signal.
    """

    name = "EMA Cross - Testing only"

    instruments = {
        "BitMEX": {
            "XBTUSD": "XBTUSD",
            # "ETHUSD": "ETHUSD",
            # "XRPUSD": "XRPUSD",
            },

        "Binance": {

            },

        "FTX": {

            }}

    # Timeframes the strategy runs on.
    operating_timeframes = [
        "1Min"]

    # Need to tune each timeframes ideal lookback, 150 default for now.
    lookback = {
        "1Min": 150, "3Min": 150, "5Min": 150, "15Min": 150, "30Min": 150,
        "1H": 150, "2H": 150, "3H": 150, "4H": 150, "6H": 150, "8H": 150,
        "12H": 150, "16H": 150, "1D": 150, "2D": 150, "3D": 150, "4D": 150,
        "7D": 150, "14D": 150}

    # First tuple element is feature type.
    # Second tuple element is feature function.
    # Third tuple element is feature param.
    features = [
        ("indicator", f.EMA, 10),
        ("indicator", f.EMA, 20)]

    def __init__(self, logger):
        super()

        self.logger = logger

    def run(self, op_data: dict, req_data: list, timeframe: str, symbol: str,
            exchange):
        """
        Run the model with the given data.

        Args:
            None:

        Returns:
            SignalEvent if signal is produced, otherwise None.

        Raises:
            None.

        """

        self.logger.info(
            "Running " + str(timeframe) + " " + self.get_name() + ".")

        if timeframe in self.operating_timeframes:

            features = list(zip(
                op_data[timeframe].index, op_data[timeframe]['open'],
                op_data[timeframe].EMA10, op_data[timeframe].EMA20))

            longs = {'price': [], 'time': []}
            shorts = {'price': [], 'time': []}

            # Check for EMA crosses.
            for i in range(len(op_data[timeframe].index)):
                fast = features[i][2]
                slow = features[i][3]
                fast_minus_1 = features[i - 1][2]
                slow_minus_1 = features[i - 1][3]
                fast_minus_2 = features[i - 2][2]
                slow_minus_2 = features[i - 2][3]

                if fast is not None and slow is not None:

                    # Short cross.
                    if slow > fast:
                        if slow_minus_1 < fast_minus_1 and slow_minus_2 < fast_minus_2:
                            shorts['price'].append(features[i][1])
                            shorts['time'].append(features[i][0])

                    # Long cross.
                    elif slow < fast:
                        if slow_minus_1 > fast_minus_1 and slow_minus_2 > fast_minus_2:
                            longs['price'].append(features[i][1])
                            longs['time'].append(features[i][0])

            if len(longs['time']) > 0 or len(shorts['time']) > 0:

                try:

                    signal = False

                    # Generate trade signal if current bar has an entry.
                    if features[-1][0] == longs['time'][-1]:
                        direction = "LONG"
                        entry_price = longs['price'][-1]
                        entry_ts = longs['time'][-1]
                        final_tp_price = entry_price + entry_price * 0.005
                        signal = True

                    elif features[-1][0] == shorts['time'][-1]:
                        direction = "SHORT"
                        entry_price = shorts['price'][-1]
                        entry_ts = shorts['time'][-1]
                        final_tp_price = entry_price - entry_price * 0.005
                        signal = True

                    if signal:

                        targets = [(final_tp_price, 100)]

                        return SignalEvent(symbol, int(entry_ts.timestamp()),
                                           direction, timeframe, self.name,
                                           exchange, entry_price, "Market", targets,
                                           None, None, False, None,
                                           op_data[timeframe])
                    else:
                        return None

                except IndexError:
                        traceback.print_exc()
                        print(type(features), len(features[-1]), features[-1][0])
                        print(type(longs), len(longs), longs['time'])
                        print(type(shorts), len(shorts), shorts['time'])
                        sys.exit(0)

    def get_required_timeframes(self, timeframes: list, result=False):
        """
        No additional (other than current) timeframes required for this model.
        """

        if result:
            return timeframes
        else:
            pass

class EQTrendFollowing(Model):
    """
    Long-short trend-following model based on EMA equilibrium and MACD.

    Rules:
        1: Price must be trending on trigger timeframe.
        2: Price must be trending on doubled trigger timeframe.
        3. MACD swings convergent with trigger timeframe swings.
        4. Price must have pulled back to the 10/20 EMA EQ.
        5. Small reversal bar must be present in the 10/20 EMA EQ.
        6. There is no old S/R level between entry and T1.

    Supplementary factors (higher probability of success):
        1: Price has pulled back into an old S/R level.
        2: First pullback in a new trend.

    Entry:
        Buy when price breaks the high/low of the trigger bar.
        Execute buyStop when reversal bar closes with 1 bar expiry.

    Stop-loss:
        At swing high/low of the trigger bar.

    Positon management:
        T1: 1R, close 50% of position. Trade is now risk free.
        T2: Stay in trade until stop-out. As price continues to trend, move
            stop-loss to each new swing high/low.
    """

    name = "10/20 EMA EQ Trend-following"

    # Instruments and venues the model runs on.
    instruments = {
        "BitMEX": {
            "XBTUSD": "XBTUSD",
            # "ETHUSD": "ETHUSD",
            # "XRPUSD": "XRPUSD",
            },

        "Binance": {

            },

        "FTX": {

            }}

    # Timeframes that the strategy runs on.
    operating_timeframes = [
        "1Min", "5Min", "15Min", "30Min", "1H", "2H", "3H", "4H",
        "6H", "8H", "12H", "16H", "1D", "2D", "3D", "7D", "14D"]

    # Need to tune each timeframes ideal lookback, 150 default for now.
    lookback = {
        "1Min": 150, "3Min": 150, "5Min": 150, "15Min": 150, "30Min": 150,
        "1H": 150, "2H": 150, "3H": 150, "4H": 150, "6H": 150, "8H": 150,
        "12H": 150, "16H": 150, "1D": 150, "2D": 150, "3D": 150, "4D": 150,
        "7D": 150, "14D": 150}

    # First tuple element is feature type.
    # Second tuple element is feature function.
    # Third tuple element is feature param.
    features = [
        ("indicator", f.EMA, 10),
        ("indicator", f.EMA, 20),
        ("indicator", f.MACD, None),
        # ("boolean", f.trending, None),
        # ("boolean", f.convergent, f.MACD)
        # ("boolean", f.j_curve, None)
        # f.sr_levels,
        # f.small_bar,
        # f.reversal_bar,
        # f.new_trend
        ]

    def __init__(self, logger):
        super()

        self.logger = logger

    def run(self, op_data: dict, req_data: list, timeframe: str , symbol: str,
            exchange):
        """
        Run the model with the given data.

        Args:
            None:

        Returns:
            SignalEvent if signal is produced, otherwise None.

        Raises:
            None.

        """

        self.logger.info(
            "Running " + str(timeframe) + " " + self.get_name() + ".")

        # TODO: model logic

        # Return a signal event every 1 min for testing.

        signal = None

        if signal:
            return SignalEvent(symbol, datetime, direction)
        else:
            return None

    def get_required_timeframes(self, timeframes: list, result=False):
        """
        Add the equivalent doubled timeframe for each timeframe in
        the given list of operating timeframes.

        eg. if "1H" is present, add "2H" to the list.
        """

        to_add = []

        for timeframe in timeframes:

            # 1Min use 3Min as the "doubled" trigger timeframe.
            if timeframe == "1Min":
                if "3Min" not in timeframes and "3Min" not in to_add:
                    to_add.append("3Min")

            # 3Min use 5Min as the "doubled" trigger timeframe.
            elif timeframe == "3Min":
                if "5Min" not in timeframes and "5Min" not in to_add:
                    to_add.append("5Min")

            # 5Min use 15Min as the "doubled" trigger timeframe.
            elif timeframe == "5Min":
                if "15Min" not in timeframes and "15Min" not in to_add:
                    to_add.append("15Min")

            # 30Min use 1H as the "doubled" trigger timeframe.
            elif timeframe == "30Min":
                if "1H" not in timeframes and "1H" not in to_add:
                    to_add.append("1H")

            # 12H and 16H use 1D as the "doubled" trigger timeframe.
            elif timeframe == "12H" or timeframe == "16H":
                if "1D" not in timeframes and "1D" not in to_add:
                    to_add.append("1D")

            # 3D use 7D as the "doubled" trigger timeframe.
            elif timeframe == "3D":
                if "7D" not in timeframes and "7D" not in to_add:
                    to_add.append("7D")

            # All other timeframes just double the numeric value.
            else:
                num = int(''.join(filter(str.isdigit, timeframe)))
                code = re.findall("[a-zA-Z]+", timeframe)
                to_add.append((str(num * 2) + code[0]))

        # Amend original list in-place, will contain op + req timeframes.
        if not result:

            for new_item in to_add:
                timeframes.append(new_item)

        # Return a new list containing only req timeframes.
        elif result:
            return [i for i in to_add]

