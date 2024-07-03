import os
import json
import time
import datetime as dt
import numpy as np
import pandas as pd
import warnings

# Ignores warning about REGEX pattern.
warnings.simplefilter(action="ignore", category=UserWarning)


# Set pandas options to display in normal notation
pd.set_option("display.float_format", "{:,.2f}".format)

import yfinance as yf

from OpenInsiderScraper.open_insider_scraper import OpenInsiderScraper


class InsiderAnalysis:
    def __init__(
        self,
        last_name: str,
        ticker: str,
        first_name: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> None:
        if start_date == "" and end_date == "":
            self.end = dt.datetime.now()
            delta = self._get_time_delta(5, "Y")
            self.start = self.end - delta
        else:
            self.start = dt.datetime.strptime(start_date, "%Y-%m-%d")
            self.end = dt.datetime.strptime(end_date, "%Y-%m-%d")

        self.oi = OpenInsiderScraper()
        self.ticker = ticker.upper()
        self.company_insider_trades = self.oi.get_insider_trades(self.ticker)
        self.full_name = self._get_full_name(last_name=last_name)
        self.titles = self._get_all_titles()
        self.insider_trades = self.company_insider_trades[
            self.company_insider_trades["insider_name"] == self.full_name
        ]
        self.purchases = self.get_purchases()
        self.sales = self.get_sales()
        # Tracks information about the number of shares bought & sold along with their values.
        self.buy_sells = self._get_buy_sells()

    def __str__(self):
        return f"""
    Full Name: {self.full_name}
    Titles: {self.titles}
    
    [Trades Overview]
    ----------------
    Purchases 
    ----
    Number of Purchases: {self.buy_sells['buy']['total']}
    Value Bought($): {"{:,.0f}".format(self.buy_sells['buy']['value'])}
    Shares Bought: {'{:,.0f}'.format(self.buy_sells['buy']['shares'])}
    
    Sales 
    ----
    Number of Sales: {self.buy_sells['sell']['total']}
    Value Sold($): {'{:,.0f}'.format(self.buy_sells['sell']['value'])}
    Shares Sold: {'{:,.0f}'.format(self.buy_sells['sell']['shares'])}
    
    """

    def get_trades(self):
        return self.insider_trades

    def get_purchases(self):
        pattern = r"^P - Purchase(\+OE)?$"
        filtered_df = self.insider_trades[
            self.insider_trades["trade_type"].str.contains(pattern, regex=True)
        ]
        return filtered_df

    def get_sales(self):
        pattern = r"^S - Sale(\+OE)?$"
        # Filtering rows where trade_type is "S" or "S - Sale+OE"
        filtered_df = self.insider_trades[
            self.insider_trades["trade_type"].str.contains(pattern, regex=True)
        ]
        return filtered_df

    def backtest_purchases(self, post_performance_ranges: list = [1, 5, 30, 90, 365]):
        df = self._backtest_insider_trades(self.purchases, post_performance_ranges)
        return df

    def backtest_sales(self, post_performance_ranges: list = [1, 5, 30, 90, 365]):
        df = self._backtest_insider_trades(self.sales, post_performance_ranges)
        return df

    def _backtest_insider_trades(
        self, df: pd.DataFrame, post_performance_ranges: list = [1, 5, 30, 90, 365]
    ):

        price_data = yf.download(self.ticker)
        current_price = price_data["Adj Close"].iloc[-1]

        rows = []
        for i in df.iterrows():

            date, value = i

            trade_date_price = price_data.loc[value["trade_date"], "Adj Close"].item()
            row = {
                "filing_date": date,
                "trade_date": value["trade_date"],
                "price": value["price"],
                "adj_price": trade_date_price,
            }

            for p in post_performance_ranges:
                dt_date = dt.datetime.strptime(date, "%Y-%m-%d %H:%M:%S")
                delta = self._get_time_delta(p, "D")
                end_date = dt_date + delta
                df_slice = price_data.loc[dt_date:end_date]

                try:

                    end_price = df_slice["Adj Close"].iloc[-1]
                    change = ((end_price - trade_date_price) / trade_date_price) * 100
                    row[p] = change.item()
                except IndexError:
                    row[p] = np.nan

            row["current"] = (
                (current_price - trade_date_price) / trade_date_price
            ) * 100

            rows.append(row)
        try:
            df = pd.DataFrame(rows)
            df.set_index("filing_date", inplace=True)
            return df
        except KeyError:
            df = pd.DataFrame(rows)
            return df

    def _get_data_export_path(self):
        try:
            internal_path = f"{os.getcwd()}\\config.json"
            with open(internal_path, "r") as file:
                data = json.load(file)
        except FileNotFoundError:
            external_path = f"{os.getcwd()}\\InsiderAnalysis\\config.json"
            with open(external_path, "r") as file:
                data = json.load(file)
        return data["data_export_path"]

    def _get_full_name(self, last_name: str, first_name: str = ""):
        """
        Get the name of the insider according to what they file under.

        Parameters
        ----------
        last_name : str
            Last name of the insider.
        first_name : str, optional
            First name of the insider. *NOTE* In most cases just passing the last name is enough, but in cases where insiders share the same last name, you can optionally add their first name for a more precise search.  default ""

        Returns
        -------
        _type_
            _description_
        """

        insider_info = self.company_insider_trades[["insider_name", "title"]]
        full_name = ""
        for i in insider_info.iterrows():
            date, value = i
            insider_name = value["insider_name"]
            if first_name == "":
                parsed_name = insider_name.split(" ")
                # Capitalize both variables to make matching easier.
                if parsed_name[0].upper() == last_name.upper():
                    full_name = insider_name
                    break
            else:
                if last_name in insider_name and first_name in insider_name:
                    full_name = insider_name
        return full_name

    def _get_all_titles(self):

        insider_info = self.company_insider_trades[["insider_name", "title"]]
        insider_info = insider_info[insider_info["insider_name"] == self.full_name]
        known_titles = []
        for i in insider_info.iterrows():
            date, value = i
            title = value["title"]
            if title not in known_titles:
                title = title.replace("_", "")
                known_titles.append(title)
        return known_titles

    def _get_buy_sells(self):

        # Buy vars
        total_buys = len(self.purchases)
        buy_sum = self.purchases["value"].sum().item()
        shares_bought = self.purchases["quantity"].sum().item()
        # Sell vars
        total_sells = len(self.sales)
        sell_sum = self.sales["value"].sum().item()
        shares_sold = self.sales["quantity"].sum().item()
        # Net vars
        net_trades = total_buys - total_sells
        net_sum = buy_sum - sell_sum
        net_quantity = shares_bought - shares_sold

        data = {
            "buy": {"trades": total_buys, "value": buy_sum, "shares": shares_bought},
            "sell": {"trades": total_sells, "value": sell_sum, "shares": shares_sold},
            "net": {"trades": net_trades, "value": net_sum, "shares": net_quantity},
        }
        return data

    def _get_time_delta(self, period: int, period_unit: str):
        """
        Create a "timedelta" for date calculations.

        Parameters
        ----------
        period : int
            Number of periods.
        period_unit : str
            The unit of the period. For example, if period=5, and period_unit="Y", then the full period will be 5 years.

        Returns
        -------
        dt.timedelta
            Time delta with the adjusted amount of days according to the 'period_unit'.
        """
        if period_unit == "Y":
            return dt.timedelta(days=(365 * period))
        elif period_unit == "M":
            return dt.timedelta(days=(30 * period))
        elif period_unit == "D":
            return dt.timedelta(days=period)

    """-----------------------------------"""

    def _parse_trade_type(self, trade_type: str):
        parsed_trade_type = trade_type.split(" ")
        if parsed_trade_type == "P":
            return "P"
        elif parsed_trade_type == "S":
            return "S"

    """-----------------------------------"""
    """-----------------------------------"""


if __name__ == "__main__":

    start = time.time()
    insider = InsiderAnalysis("Huang", "NVDA")
