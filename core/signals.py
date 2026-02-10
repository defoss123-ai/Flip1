from core.models import Settings


def compute_status(
    settings: Settings,
    binance_delta_pct: float,
    mexc_imbalance: float,
    tape_buy_pct: float,
) -> tuple[str, str, str]:
    if abs(binance_delta_pct) < settings.binance_move_pct:
        return "🔴", "", "RED"

    allowed_long = binance_delta_pct >= settings.binance_move_pct
    allowed_short = binance_delta_pct <= -settings.binance_move_pct

    if allowed_long:
        long_ok = (
            mexc_imbalance >= settings.imbalance_long
            and tape_buy_pct >= settings.tape_threshold
            and (not settings.spoof_filter)
        )
        if long_ok:
            return "🟢", "LONG", "GREEN"
        return "🟡", "LONG", "YELLOW"

    if allowed_short:
        short_ok = (
            mexc_imbalance <= settings.imbalance_short
            and tape_buy_pct <= (1 - settings.tape_threshold)
            and (not settings.spoof_filter)
        )
        if short_ok:
            return "🟢", "SHORT", "GREEN"
        return "🟡", "SHORT", "YELLOW"

    return "🔴", "", "RED"


def calc_tp_sl(entry: float, side: str, tp_pct: float, sl_pct: float) -> tuple[float | str, float | str]:
    if side == "LONG":
        tp = entry * (1 + tp_pct / 100.0)
        sl = entry * (1 - sl_pct / 100.0)
        return tp, sl

    if side == "SHORT":
        tp = entry * (1 - tp_pct / 100.0)
        sl = entry * (1 + sl_pct / 100.0)
        return tp, sl

    return "", ""
