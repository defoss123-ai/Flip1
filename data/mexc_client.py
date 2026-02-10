import random
import time

import httpx


class MockMexcClient:
    def get_orderbook_imbalance(self, symbol: str, levels: int) -> float:
        return random.uniform(0.30, 2.80)

    def get_tape_buy_pct(self, symbol: str, window_seconds: int) -> float:
        return random.uniform(0.40, 0.90)

    def get_best_bid_ask(self, symbol: str) -> tuple[float, float]:
        mid = random.uniform(95.0, 105.0)
        return mid * 0.9995, mid * 1.0005

    def get_orderbook_snapshot(self, symbol: str, levels: int) -> dict:
        safe_levels = max(5, min(100, int(levels)))
        mid = random.uniform(95.0, 105.0)

        bids: list[tuple[float, float]] = []
        asks: list[tuple[float, float]] = []
        for i in range(safe_levels):
            step = (i + 1) * 0.02
            bid_price = max(0.0001, mid - step)
            ask_price = max(0.0001, mid + step)
            bids.append((bid_price, random.uniform(1.0, 15.0)))
            asks.append((ask_price, random.uniform(1.0, 15.0)))

        return {"bids": bids, "asks": asks}


class RealMexcClient:
    def __init__(self, timeout_sec: float = 2.0) -> None:
        self.client = httpx.Client(timeout=timeout_sec)
        self._trades_cache: dict[str, list[dict]] = {}
        self._last_fetch_ms: dict[str, int] = {}

    def close(self) -> None:
        self.client.close()

    def _get_depth(self, symbol: str, limit: int) -> dict:
        response = self.client.get(
            "https://api.mexc.com/api/v3/depth",
            params={"symbol": symbol.upper(), "limit": limit},
        )
        response.raise_for_status()
        return response.json()

    def _fetch_and_merge_trades(self, symbol: str, window_seconds: int, now_ms: int) -> None:
        response = self.client.get(
            "https://api.mexc.com/api/v3/trades",
            params={"symbol": symbol.upper(), "limit": 100},
        )
        response.raise_for_status()
        trades = response.json()

        normalized: list[dict] = []
        has_any_time = False

        for trade in trades:
            price = float(trade["price"])
            qty = float(trade["qty"])

            raw_time = trade.get("time")
            if raw_time is None:
                raw_time = trade.get("timestamp")
            if raw_time is None:
                continue

            time_ms = int(raw_time)
            has_any_time = True

            side = "UNKNOWN"
            if "isBuyerMaker" in trade:
                side = "SELL" if bool(trade["isBuyerMaker"]) else "BUY"

            normalized.append(
                {
                    "price": price,
                    "qty": qty,
                    "time_ms": time_ms,
                    "side": side,
                }
            )

        if trades and not has_any_time:
            raise RuntimeError("MEXC trades missing time")

        existing = self._trades_cache.get(symbol, [])
        merged = existing + normalized

        dedup: dict[tuple[int, float, float], dict] = {}
        for trade in merged:
            key = (int(trade["time_ms"]), float(trade["price"]), float(trade["qty"]))
            dedup[key] = trade

        keep_ms = max(int(window_seconds) * 3000, 30_000)
        min_keep_ts = now_ms - keep_ms

        pruned = [trade for trade in dedup.values() if int(trade["time_ms"]) >= min_keep_ts]
        pruned.sort(key=lambda t: int(t["time_ms"]))
        self._trades_cache[symbol] = pruned
        self._last_fetch_ms[symbol] = now_ms

    def get_best_bid_ask(self, symbol: str) -> tuple[float, float]:
        depth = self._get_depth(symbol, 5)
        bids = depth["bids"]
        asks = depth["asks"]

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        return best_bid, best_ask

    def get_orderbook_snapshot(self, symbol: str, levels: int) -> dict:
        safe_levels = max(5, min(100, int(levels)))
        depth = self._get_depth(symbol, safe_levels)

        bids_raw = depth["bids"]
        asks_raw = depth["asks"]

        bids = [(float(level[0]), float(level[1])) for level in bids_raw[:safe_levels]]
        asks = [(float(level[0]), float(level[1])) for level in asks_raw[:safe_levels]]
        return {"bids": bids, "asks": asks}

    def get_orderbook_imbalance(self, symbol: str, levels: int) -> float:
        safe_limit = max(5, min(100, int(levels)))
        depth = self._get_depth(symbol, safe_limit)

        bids = depth["bids"]
        asks = depth["asks"]

        n_levels = max(1, int(levels))
        bid_sum = sum(float(level[1]) for level in bids[:n_levels])
        ask_sum = sum(float(level[1]) for level in asks[:n_levels])

        if ask_sum == 0:
            return 0.0

        return float(bid_sum / ask_sum)

    def get_tape_buy_pct(self, symbol: str, window_seconds: int) -> float:
        now_ms = int(time.time() * 1000)
        fetch_interval_ms = 500

        last_fetch = self._last_fetch_ms.get(symbol)
        if last_fetch is None or (now_ms - last_fetch) >= fetch_interval_ms:
            self._fetch_and_merge_trades(symbol, window_seconds, now_ms)

        cached = self._trades_cache.get(symbol, [])
        if not cached:
            return 0.5

        min_ts = now_ms - int(window_seconds) * 1000
        window_trades = [trade for trade in cached if int(trade["time_ms"]) >= min_ts]
        if not window_trades:
            return 0.5

        has_unknown = any(trade.get("side") == "UNKNOWN" for trade in window_trades)
        mid = 0.0
        if has_unknown:
            best_bid, best_ask = self.get_best_bid_ask(symbol)
            mid = (best_bid + best_ask) / 2.0

        buy_vol = 0.0
        sell_vol = 0.0

        for trade in window_trades:
            qty = float(trade["qty"])
            side = trade.get("side", "UNKNOWN")

            if side == "BUY":
                buy_vol += qty
            elif side == "SELL":
                sell_vol += qty
            else:
                price = float(trade["price"])
                if price >= mid:
                    buy_vol += qty
                else:
                    sell_vol += qty

        total = buy_vol + sell_vol
        if total <= 0:
            return 0.5

        return buy_vol / total


class MexcClientFacade:
    def __init__(self, real_client_or_none, mock_client: MockMexcClient, settings: dict) -> None:
        self.real_client_or_none = real_client_or_none
        self.mock_client = mock_client
        self.settings = settings
        self.error_count: int = 0
        self.fallback_count: int = 0
        self.last_real_ok_ts: float | None = None
        self._last_real_call_ms_depth: dict[str, int] = {}
        self._last_real_call_ms_trades: dict[str, int] = {}
        self.min_interval_depth_ms: int = 600
        self.min_interval_trades_ms: int = 600
        self._last_imbalance_by_symbol: dict[str, float] = {}
        self._last_tape_by_symbol: dict[str, float] = {}
        self._last_best_by_symbol: dict[str, tuple[float, float]] = {}
        self._last_snapshot_by_symbol: dict[str, dict] = {}

    def _real_enabled(self) -> bool:
        return bool(self.settings.get("use_real_mexc", False)) and self.real_client_or_none is not None

    def _mark_ok(self) -> None:
        self.last_real_ok_ts = time.time()

    def _mark_fallback(self) -> None:
        self.error_count += 1
        self.fallback_count += 1

    def _is_rate_limited_depth(self, symbol: str) -> bool:
        now_ms = int(time.time() * 1000)
        last_call_ms = self._last_real_call_ms_depth.get(symbol)
        if last_call_ms is None:
            return False
        return (now_ms - last_call_ms) < self.min_interval_depth_ms

    def _is_rate_limited_trades(self, symbol: str) -> bool:
        now_ms = int(time.time() * 1000)
        last_call_ms = self._last_real_call_ms_trades.get(symbol)
        if last_call_ms is None:
            return False
        return (now_ms - last_call_ms) < self.min_interval_trades_ms

    def _mark_real_call_depth(self, symbol: str) -> None:
        self._last_real_call_ms_depth[symbol] = int(time.time() * 1000)

    def _mark_real_call_trades(self, symbol: str) -> None:
        self._last_real_call_ms_trades[symbol] = int(time.time() * 1000)

    def get_orderbook_imbalance(self, symbol: str, levels: int) -> float:
        symbol_upper = symbol.upper()
        if self._real_enabled():
            if self._is_rate_limited_depth(symbol_upper):
                return self._last_imbalance_by_symbol.get(
                    symbol_upper,
                    self.mock_client.get_orderbook_imbalance(symbol_upper, levels),
                )
            try:
                value = self.real_client_or_none.get_orderbook_imbalance(symbol_upper, levels)
                self._mark_real_call_depth(symbol_upper)
                self._mark_ok()
                self._last_imbalance_by_symbol[symbol_upper] = value
                return value
            except Exception:
                self._mark_real_call_depth(symbol_upper)
                self._mark_fallback()
                return self.mock_client.get_orderbook_imbalance(symbol_upper, levels)
        return self.mock_client.get_orderbook_imbalance(symbol_upper, levels)

    def get_tape_buy_pct(self, symbol: str, window_seconds: int) -> float:
        symbol_upper = symbol.upper()
        if self._real_enabled():
            if self._is_rate_limited_trades(symbol_upper):
                return self._last_tape_by_symbol.get(symbol_upper, 0.5)
            try:
                value = self.real_client_or_none.get_tape_buy_pct(symbol_upper, window_seconds)
                self._mark_real_call_trades(symbol_upper)
                self._mark_ok()
                self._last_tape_by_symbol[symbol_upper] = value
                return value
            except Exception:
                self._mark_real_call_trades(symbol_upper)
                self._mark_fallback()
                return self.mock_client.get_tape_buy_pct(symbol_upper, window_seconds)
        return self.mock_client.get_tape_buy_pct(symbol_upper, window_seconds)

    def get_best_bid_ask(self, symbol: str) -> tuple[float, float]:
        symbol_upper = symbol.upper()
        if self._real_enabled():
            if self._is_rate_limited_depth(symbol_upper):
                return self._last_best_by_symbol.get(
                    symbol_upper,
                    self.mock_client.get_best_bid_ask(symbol_upper),
                )
            try:
                value = self.real_client_or_none.get_best_bid_ask(symbol_upper)
                self._mark_real_call_depth(symbol_upper)
                self._mark_ok()
                self._last_best_by_symbol[symbol_upper] = value
                return value
            except Exception:
                self._mark_real_call_depth(symbol_upper)
                self._mark_fallback()
        try:
            return self.mock_client.get_best_bid_ask(symbol_upper)
        except Exception:
            return 0.0, 0.0

    def get_orderbook_snapshot(self, symbol: str, levels: int) -> dict:
        symbol_upper = symbol.upper()
        if self._real_enabled():
            if self._is_rate_limited_depth(symbol_upper):
                return self._last_snapshot_by_symbol.get(
                    symbol_upper,
                    self.mock_client.get_orderbook_snapshot(symbol_upper, levels),
                )
            try:
                value = self.real_client_or_none.get_orderbook_snapshot(symbol_upper, levels)
                self._mark_real_call_depth(symbol_upper)
                self._mark_ok()
                self._last_snapshot_by_symbol[symbol_upper] = value
                return value
            except Exception:
                self._mark_real_call_depth(symbol_upper)
                self._mark_fallback()
                return self.mock_client.get_orderbook_snapshot(symbol_upper, levels)
        return self.mock_client.get_orderbook_snapshot(symbol_upper, levels)

    def close(self) -> None:
        if self.real_client_or_none is not None:
            self.real_client_or_none.close()

    def mode(self) -> str:
        if self._real_enabled():
            return "REAL"
        return "MOCK"

    def status_line(self) -> str:
        if not self._real_enabled():
            return "MEXC MOCK"
        ok_part = "-"
        if self.last_real_ok_ts is not None:
            ok_part = time.strftime("%H:%M:%S", time.localtime(self.last_real_ok_ts))
        return f"MEXC REAL | ok:{ok_part} | err:{self.error_count} | fb:{self.fallback_count}"
