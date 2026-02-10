import random
import time

import httpx


class MockBinanceClient:
    def get_price_delta_pct(self, symbol: str) -> float:
        return random.uniform(-0.35, 0.35)

    def get_mock_mid_price(self, symbol: str) -> float:
        symbol_upper = symbol.upper()
        if "BTC" in symbol_upper:
            return random.uniform(42000 - 200, 42000 + 200)
        if "ETH" in symbol_upper:
            return random.uniform(2300 - 30, 2300 + 30)
        return random.uniform(100 - 5, 100 + 5)


class RealBinanceClient:
    def __init__(self, timeout_sec: float = 2.0) -> None:
        self.client = httpx.Client(timeout=timeout_sec)
        self.last_price_by_symbol: dict[str, float] = {}
        self.last_ts_by_symbol: dict[str, float] = {}

    def close(self) -> None:
        self.client.close()

    def get_price(self, symbol: str) -> float:
        symbol_upper = symbol.upper()
        response = self.client.get(
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbol": symbol_upper},
        )
        response.raise_for_status()
        data = response.json()
        return float(data["price"])

    def get_price_delta_pct(self, symbol: str, window_sec: int) -> float:
        symbol_upper = symbol.upper()
        current_price = self.get_price(symbol_upper)
        now_ts = time.time()

        last_price = self.last_price_by_symbol.get(symbol_upper)
        last_ts = self.last_ts_by_symbol.get(symbol_upper)

        self.last_price_by_symbol[symbol_upper] = current_price
        self.last_ts_by_symbol[symbol_upper] = now_ts

        if last_price is None or last_ts is None:
            return 0.0

        if (now_ts - last_ts) < float(window_sec):
            return 0.0

        return ((current_price - last_price) / last_price) * 100.0

    def get_mock_mid_price(self, symbol: str) -> float:
        return self.get_price(symbol)


class BinanceClientFacade:
    def __init__(self, real_client_or_none, mock_client: MockBinanceClient, settings: dict) -> None:
        self.real_client_or_none = real_client_or_none
        self.mock_client = mock_client
        self.settings = settings
        self.error_count: int = 0
        self.fallback_count: int = 0
        self.last_real_ok_ts: float | None = None
        self._last_real_call_ms: dict[str, int] = {}
        self.real_min_interval_ms: int = 500
        self._last_delta_by_symbol: dict[str, float] = {}
        self._last_mid_by_symbol: dict[str, float] = {}

    def _real_enabled(self) -> bool:
        return bool(self.settings.get("use_real_binance", False)) and self.real_client_or_none is not None

    def _mark_ok(self) -> None:
        self.last_real_ok_ts = time.time()

    def _mark_fallback(self) -> None:
        self.error_count += 1
        self.fallback_count += 1

    def _is_rate_limited(self, symbol: str) -> bool:
        now_ms = int(time.time() * 1000)
        last_call_ms = self._last_real_call_ms.get(symbol)
        if last_call_ms is None:
            return False
        return (now_ms - last_call_ms) < self.real_min_interval_ms

    def _mark_real_call(self, symbol: str) -> None:
        self._last_real_call_ms[symbol] = int(time.time() * 1000)

    def get_price_delta_pct(self, symbol: str) -> float:
        symbol_upper = symbol.upper()
        if self._real_enabled():
            if self._is_rate_limited(symbol_upper):
                return self._last_delta_by_symbol.get(symbol_upper, 0.0)
            try:
                value = self.real_client_or_none.get_price_delta_pct(
                    symbol_upper,
                    int(self.settings["binance_move_window_sec"]),
                )
                self._mark_real_call(symbol_upper)
                self._mark_ok()
                self._last_delta_by_symbol[symbol_upper] = value
                return value
            except Exception:
                self._mark_real_call(symbol_upper)
                self._mark_fallback()
                return self.mock_client.get_price_delta_pct(symbol_upper)
        return self.mock_client.get_price_delta_pct(symbol_upper)

    def get_mock_mid_price(self, symbol: str) -> float:
        symbol_upper = symbol.upper()
        if self._real_enabled():
            if self._is_rate_limited(symbol_upper):
                return self._last_mid_by_symbol.get(symbol_upper, self.mock_client.get_mock_mid_price(symbol_upper))
            try:
                value = self.real_client_or_none.get_mock_mid_price(symbol_upper)
                self._mark_real_call(symbol_upper)
                self._mark_ok()
                self._last_mid_by_symbol[symbol_upper] = value
                return value
            except Exception:
                self._mark_real_call(symbol_upper)
                self._mark_fallback()
                return self.mock_client.get_mock_mid_price(symbol_upper)
        return self.mock_client.get_mock_mid_price(symbol_upper)

    def mode(self) -> str:
        if self._real_enabled():
            return "REAL"
        return "MOCK"

    def status_line(self) -> str:
        if not self._real_enabled():
            return "Binance MOCK"
        ok_part = "-"
        if self.last_real_ok_ts is not None:
            ok_part = time.strftime("%H:%M:%S", time.localtime(self.last_real_ok_ts))
        return f"Binance REAL | ok:{ok_part} | err:{self.error_count} | fb:{self.fallback_count}"
