from dataclasses import dataclass, field


DEFAULT_VISIBLE_COLUMNS = [
    "Pin",
    "Symbol",
    "Status",
    "Side",
    "Reason",
    "Binance Δ%",
    "MEXC Imbalance",
    "Tape%",
    "Entry",
    "TP",
    "SL",
    "Updated",
]


@dataclass
class Settings:
    levels: int = 10
    imbalance_long: float = 1.8
    imbalance_short: float = 0.55
    window_seconds: int = 10
    tape_threshold: float = 0.60
    binance_move_pct: float = 0.10
    binance_move_window_sec: int = 10
    tp_pct: float = 0.30
    sl_pct: float = 0.20
    update_interval_ms: int = 1000
    entry_mode: str = "mid"
    spoof_filter: bool = False
    use_real_binance: bool = False
    use_real_mexc: bool = False
    pinned_symbols: list[str] = field(default_factory=list)
    compact_mode: bool = False
    visible_columns: list[str] = field(default_factory=lambda: DEFAULT_VISIBLE_COLUMNS.copy())


def default_settings() -> Settings:
    return Settings()
