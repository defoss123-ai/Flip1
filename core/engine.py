import time
from dataclasses import dataclass
from datetime import datetime

from core.models import Settings
from core.signals import calc_tp_sl, compute_status
from data.binance_client import MockBinanceClient
from data.mexc_client import MockMexcClient


@dataclass
class RowUpdate:
    symbol: str
    status_emoji: str
    side: str
    reason: str
    binance_delta_str: str
    mexc_imbalance_str: str
    tape_str: str
    entry_str: str
    tp_str: str
    sl_str: str
    updated_str: str
    level: str


class Engine:
    def __init__(
        self,
        settings: dict,
        binance_client: MockBinanceClient,
        mexc_client: MockMexcClient,
    ) -> None:
        self.settings = settings
        self.binance_client = binance_client
        self.mexc_client = mexc_client
        self._prev_top_volume: dict[str, dict[str, float]] = {}

    def _is_spoof_detected(
        self,
        symbol: str,
        side: str,
        imbalance: float,
        settings_obj: Settings,
    ) -> bool:
        spoof_detected = False
        now_ts = time.time()
        k_levels = max(1, min(3, int(settings_obj.levels)))

        snapshot = self.mexc_client.get_orderbook_snapshot(symbol, settings_obj.levels)
        bids = snapshot.get("bids", [])
        asks = snapshot.get("asks", [])

        bid_top = sum(float(level[1]) for level in bids[:k_levels])
        ask_top = sum(float(level[1]) for level in asks[:k_levels])

        prev = self._prev_top_volume.get(symbol)
        if prev is not None and (now_ts - prev.get("ts", 0.0)) <= 3.0:
            prev_bid_top = float(prev.get("bid", 0.0))
            prev_ask_top = float(prev.get("ask", 0.0))

            if side == "LONG" and prev_bid_top > 0:
                bid_collapsed = bid_top < prev_bid_top * 0.35
                if bid_collapsed and (
                    imbalance >= float(settings_obj.imbalance_long)
                    or bid_collapsed
                ):
                    spoof_detected = True

            if side == "SHORT" and prev_ask_top > 0:
                ask_collapsed = ask_top < prev_ask_top * 0.35
                if ask_collapsed:
                    spoof_detected = True

        self._prev_top_volume[symbol] = {"bid": bid_top, "ask": ask_top, "ts": now_ts}
        return spoof_detected

    def tick(self, symbols: list[str]) -> list[RowUpdate]:
        updates: list[RowUpdate] = []
        settings_obj = Settings(**self.settings)

        for symbol in symbols:
            normalized_symbol = symbol.strip().upper()
            bin_delta = self.binance_client.get_price_delta_pct(normalized_symbol)
            base_mid = self.binance_client.get_mock_mid_price(normalized_symbol)
            imbalance = self.mexc_client.get_orderbook_imbalance(normalized_symbol, settings_obj.levels)
            tape_buy = self.mexc_client.get_tape_buy_pct(normalized_symbol, settings_obj.window_seconds)

            status_emoji, side, level = compute_status(settings_obj, bin_delta, imbalance, tape_buy)

            spoof_blocked = False
            if level == "GREEN" and bool(settings_obj.spoof_filter):
                if self._is_spoof_detected(normalized_symbol, side, imbalance, settings_obj):
                    status_emoji = "🟡"
                    level = "YELLOW"
                    spoof_blocked = True

            entry = base_mid
            if settings_obj.entry_mode == "best" and level == "GREEN" and side in ("LONG", "SHORT"):
                best_bid = base_mid * 0.9995
                best_ask = base_mid * 1.0005
                try:
                    best_bid, best_ask = self.mexc_client.get_best_bid_ask(normalized_symbol)
                except Exception:
                    pass

                if best_bid > 0 and best_ask > 0:
                    if side == "LONG":
                        entry = best_ask
                    elif side == "SHORT":
                        entry = best_bid

            reason = "MEXC_TRIGGER_OK"
            if level == "RED":
                reason = "BINANCE_FILTER"
            elif level == "YELLOW":
                reason = "SPOOF_BLOCK" if spoof_blocked else "MEXC_TRIGGER_MISS"

            tp_str = ""
            sl_str = ""
            if level == "GREEN":
                tp, sl = calc_tp_sl(entry, side, settings_obj.tp_pct, settings_obj.sl_pct)
                tp_str = f"{tp:.4f}"
                sl_str = f"{sl:.4f}"

            updates.append(
                RowUpdate(
                    symbol=normalized_symbol,
                    status_emoji=status_emoji,
                    side=side,
                    reason=reason,
                    binance_delta_str=f"{bin_delta:.3f}%",
                    mexc_imbalance_str=f"{imbalance:.3f}",
                    tape_str=f"{tape_buy * 100:.1f}%",
                    entry_str=f"{entry:.4f}",
                    tp_str=tp_str,
                    sl_str=sl_str,
                    updated_str=datetime.now().strftime("%H:%M:%S"),
                    level=level,
                )
            )

        return updates
