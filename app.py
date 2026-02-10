import csv
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.engine import Engine
from core.models import DEFAULT_VISIBLE_COLUMNS, default_settings
from core.storage import ensure_data_dir, load_settings, load_watchlist, save_settings, save_watchlist
from data.binance_client import BinanceClientFacade, MockBinanceClient, RealBinanceClient
from data.mexc_client import MexcClientFacade, MockMexcClient, RealMexcClient


class AddPairsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add pair")

        layout = QVBoxLayout(self)

        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("BTCUSDT, ETHUSDT\nSOLUSDT ...")
        layout.addWidget(self.input)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_text(self) -> str:
        return self.input.toPlainText()


class SettingsDialog(QDialog):
    PRESETS = {
        "Conservative": {
            "levels": 15,
            "imbalance_long": 2.2,
            "imbalance_short": 0.45,
            "tape_threshold": 0.70,
            "binance_move_pct": 0.18,
            "binance_move_window_sec": 12,
            "window_seconds": 12,
            "update_interval_ms": 1000,
            "tp_pct": 0.25,
            "sl_pct": 0.20,
        },
        "Balanced": {
            "levels": 10,
            "imbalance_long": 1.8,
            "imbalance_short": 0.55,
            "tape_threshold": 0.60,
            "binance_move_pct": 0.10,
            "binance_move_window_sec": 10,
            "window_seconds": 10,
            "update_interval_ms": 800,
            "tp_pct": 0.30,
            "sl_pct": 0.20,
        },
        "Aggressive": {
            "levels": 8,
            "imbalance_long": 1.5,
            "imbalance_short": 0.65,
            "tape_threshold": 0.55,
            "binance_move_pct": 0.07,
            "binance_move_window_sec": 8,
            "window_seconds": 8,
            "update_interval_ms": 500,
            "tp_pct": 0.35,
            "sl_pct": 0.25,
        },
    }

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._applying_preset = False

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.preset = QComboBox()
        self.preset.addItems(["Custom", "Conservative", "Balanced", "Aggressive"])

        self.levels = QSpinBox()
        self.levels.setRange(1, 1000)
        self.levels.setValue(int(settings["levels"]))

        self.imbalance_long = QDoubleSpinBox()
        self.imbalance_long.setRange(0.0, 100.0)
        self.imbalance_long.setDecimals(4)
        self.imbalance_long.setSingleStep(0.01)
        self.imbalance_long.setValue(float(settings["imbalance_long"]))

        self.imbalance_short = QDoubleSpinBox()
        self.imbalance_short.setRange(0.0, 100.0)
        self.imbalance_short.setDecimals(4)
        self.imbalance_short.setSingleStep(0.01)
        self.imbalance_short.setValue(float(settings["imbalance_short"]))

        self.tape_threshold = QDoubleSpinBox()
        self.tape_threshold.setRange(0.0, 1.0)
        self.tape_threshold.setDecimals(4)
        self.tape_threshold.setSingleStep(0.01)
        self.tape_threshold.setValue(float(settings["tape_threshold"]))

        self.binance_move_pct = QDoubleSpinBox()
        self.binance_move_pct.setRange(0.0, 100.0)
        self.binance_move_pct.setDecimals(4)
        self.binance_move_pct.setSingleStep(0.01)
        self.binance_move_pct.setValue(float(settings["binance_move_pct"]))

        self.binance_move_window_sec = QSpinBox()
        self.binance_move_window_sec.setRange(1, 300)
        self.binance_move_window_sec.setValue(int(settings.get("binance_move_window_sec", 10)))

        self.window_seconds = QSpinBox()
        self.window_seconds.setRange(1, 300)
        self.window_seconds.setValue(int(settings.get("window_seconds", 10)))

        self.tp_pct = QDoubleSpinBox()
        self.tp_pct.setRange(0.0, 100.0)
        self.tp_pct.setDecimals(4)
        self.tp_pct.setSingleStep(0.01)
        self.tp_pct.setValue(float(settings["tp_pct"]))

        self.sl_pct = QDoubleSpinBox()
        self.sl_pct.setRange(0.0, 100.0)
        self.sl_pct.setDecimals(4)
        self.sl_pct.setSingleStep(0.01)
        self.sl_pct.setValue(float(settings["sl_pct"]))

        self.update_interval_ms = QSpinBox()
        self.update_interval_ms.setRange(100, 60000)
        self.update_interval_ms.setValue(int(settings["update_interval_ms"]))

        self.entry_mode = QComboBox()
        self.entry_mode.addItems(["mid", "best"])
        entry_mode_value = str(settings.get("entry_mode", "mid")).lower()
        if entry_mode_value not in ("mid", "best"):
            entry_mode_value = "mid"
        self.entry_mode.setCurrentText(entry_mode_value)

        self.use_real_binance = QCheckBox("Use real Binance (REST)")
        self.use_real_binance.setChecked(bool(settings.get("use_real_binance", False)))

        self.use_real_mexc = QCheckBox("Use real MEXC (REST)")
        self.use_real_mexc.setChecked(bool(settings.get("use_real_mexc", False)))

        self.spoof_filter = QCheckBox("Spoof filter (v1)")
        self.spoof_filter.setChecked(bool(settings.get("spoof_filter", False)))

        self.reset_defaults_button = QPushButton("Reset defaults")

        self.visible_column_checks: dict[str, QCheckBox] = {}
        visible_columns = settings.get("visible_columns", DEFAULT_VISIBLE_COLUMNS)
        for column_name in DEFAULT_VISIBLE_COLUMNS:
            checkbox = QCheckBox(column_name)
            checkbox.setChecked(column_name in visible_columns)
            if column_name == "Symbol":
                checkbox.setChecked(True)
                checkbox.setEnabled(False)
            self.visible_column_checks[column_name] = checkbox

        form.addRow("Preset", self.preset)
        form.addRow("levels", self.levels)
        form.addRow("imbalance_long", self.imbalance_long)
        form.addRow("imbalance_short", self.imbalance_short)
        form.addRow("tape_threshold", self.tape_threshold)
        form.addRow("binance_move_pct", self.binance_move_pct)
        form.addRow("binance_move_window_sec", self.binance_move_window_sec)
        form.addRow("window_seconds", self.window_seconds)
        form.addRow("tp_pct", self.tp_pct)
        form.addRow("sl_pct", self.sl_pct)
        form.addRow("update_interval_ms", self.update_interval_ms)
        form.addRow("Entry mode (mid / best bid-ask)", self.entry_mode)
        form.addRow(self.use_real_binance)
        form.addRow(self.use_real_mexc)
        form.addRow(self.spoof_filter)
        form.addRow("Visible columns", QWidget())
        for column_name in DEFAULT_VISIBLE_COLUMNS:
            form.addRow(f"  {column_name}", self.visible_column_checks[column_name])
        form.addRow(self.reset_defaults_button)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.preset.currentTextChanged.connect(self._apply_selected_preset)
        self.reset_defaults_button.clicked.connect(self._reset_defaults)
        self._connect_manual_change_events()

    def _signal_fields(self) -> tuple:
        return (
            self.levels,
            self.imbalance_long,
            self.imbalance_short,
            self.tape_threshold,
            self.binance_move_pct,
            self.binance_move_window_sec,
            self.window_seconds,
            self.update_interval_ms,
            self.tp_pct,
            self.sl_pct,
        )

    def _connect_manual_change_events(self) -> None:
        for field in self._signal_fields():
            field.valueChanged.connect(self._set_custom_if_manual)

    def _set_custom_if_manual(self, *_args) -> None:
        if self._applying_preset:
            return
        if self.preset.currentText() != "Custom":
            self.preset.setCurrentText("Custom")

    def _apply_signal_values(self, values: dict) -> None:
        self._applying_preset = True
        self.levels.setValue(int(values["levels"]))
        self.imbalance_long.setValue(float(values["imbalance_long"]))
        self.imbalance_short.setValue(float(values["imbalance_short"]))
        self.tape_threshold.setValue(float(values["tape_threshold"]))
        self.binance_move_pct.setValue(float(values["binance_move_pct"]))
        self.binance_move_window_sec.setValue(int(values["binance_move_window_sec"]))
        self.window_seconds.setValue(int(values["window_seconds"]))
        self.update_interval_ms.setValue(int(values["update_interval_ms"]))
        self.tp_pct.setValue(float(values["tp_pct"]))
        self.sl_pct.setValue(float(values["sl_pct"]))
        self._applying_preset = False

    def _apply_selected_preset(self, preset_name: str) -> None:
        if preset_name == "Custom":
            return
        preset = self.PRESETS.get(preset_name)
        if preset is None:
            return
        self._apply_signal_values(preset)

    def _reset_defaults(self) -> None:
        defaults = default_settings()
        default_values = {
            "levels": defaults.levels,
            "imbalance_long": defaults.imbalance_long,
            "imbalance_short": defaults.imbalance_short,
            "tape_threshold": defaults.tape_threshold,
            "binance_move_pct": defaults.binance_move_pct,
            "binance_move_window_sec": defaults.binance_move_window_sec,
            "window_seconds": defaults.window_seconds,
            "update_interval_ms": defaults.update_interval_ms,
            "tp_pct": defaults.tp_pct,
            "sl_pct": defaults.sl_pct,
        }
        self._apply_signal_values(default_values)
        self.preset.setCurrentText("Custom")

    def get_values(self) -> dict:
        return {
            "levels": int(self.levels.value()),
            "imbalance_long": float(self.imbalance_long.value()),
            "imbalance_short": float(self.imbalance_short.value()),
            "tape_threshold": float(self.tape_threshold.value()),
            "binance_move_pct": float(self.binance_move_pct.value()),
            "binance_move_window_sec": int(self.binance_move_window_sec.value()),
            "window_seconds": int(self.window_seconds.value()),
            "tp_pct": float(self.tp_pct.value()),
            "sl_pct": float(self.sl_pct.value()),
            "update_interval_ms": int(self.update_interval_ms.value()),
            "entry_mode": self.entry_mode.currentText(),
            "use_real_binance": bool(self.use_real_binance.isChecked()),
            "use_real_mexc": bool(self.use_real_mexc.isChecked()),
            "spoof_filter": bool(self.spoof_filter.isChecked()),
            "visible_columns": [
                column_name
                for column_name, checkbox in self.visible_column_checks.items()
                if checkbox.isChecked() or column_name == "Symbol"
            ],
        }


class MainWindow(QMainWindow):
    FLASH_TICKS = 2

    COLUMN_NAMES = DEFAULT_VISIBLE_COLUMNS.copy()
    HEADER_LABELS = [
        "Pin",
        "Symbol",
        "Status(🔴/🟡/🟢)",
        "Side(LONG/SHORT)",
        "Reason",
        "Binance Δ%",
        "MEXC Imbalance",
        "Tape%",
        "Entry",
        "TP",
        "SL",
        "Updated",
    ]

    COL_PIN = 0
    COL_SYMBOL = 1
    COL_STATUS = 2
    COL_SIDE = 3
    COL_REASON = 4
    COL_BINANCE = 5
    COL_IMBALANCE = 6
    COL_TAPE = 7
    COL_ENTRY = 8
    COL_TP = 9
    COL_SL = 10
    COL_UPDATED = 11

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Simple PyQt6 GUI")
        self.resize(1280, 520)

        ensure_data_dir()
        self.watchlist = load_watchlist()
        self.settings = load_settings().__dict__.copy()
        self.settings.setdefault("pinned_symbols", [])
        self.settings.setdefault("compact_mode", False)
        self.settings.setdefault("visible_columns", DEFAULT_VISIBLE_COLUMNS.copy())

        self.sort_col = self.COL_SYMBOL
        self.sort_ascending = True
        self.last_updates_by_symbol: dict[str, object] = {}
        self.last_update_ts_by_symbol: dict[str, float] = {}

        self.binance_mock = MockBinanceClient()
        self.binance_real = RealBinanceClient() if self.settings.get("use_real_binance", False) else None
        self.binance = BinanceClientFacade(self.binance_real, self.binance_mock, self.settings)

        self.mexc_mock = MockMexcClient()
        self.mexc_real = RealMexcClient() if self.settings.get("use_real_mexc", False) else None
        self.mexc = MexcClientFacade(self.mexc_real, self.mexc_mock, self.settings)

        self.engine = Engine(self.settings, self.binance, self.mexc)
        self._previous_levels: dict[str, str] = {}
        self._flash_ticks: dict[str, int] = {}

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_mock_data)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        button_layout = QHBoxLayout()
        main_layout.addLayout(button_layout)

        self.add_pair_button = QPushButton("Add pair")
        self.remove_button = QPushButton("Remove")
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        self.settings_button = QPushButton("Settings")
        self.export_button = QPushButton("Export")
        self.alerts_checkbox = QCheckBox("Alerts")
        self.alerts_checkbox.setChecked(True)
        self.pause_unfocused_checkbox = QCheckBox("Pause when unfocused")
        self.pause_unfocused_checkbox.setChecked(True)
        self.compact_mode_checkbox = QCheckBox("Compact mode")
        self.compact_mode_checkbox.setChecked(bool(self.settings.get("compact_mode", False)))
        self.lbl_health_binance = QLabel()
        self.lbl_health_mexc = QLabel()

        for button in (
            self.add_pair_button,
            self.remove_button,
            self.start_button,
            self.stop_button,
            self.settings_button,
            self.export_button,
            self.alerts_checkbox,
            self.pause_unfocused_checkbox,
            self.compact_mode_checkbox,
        ):
            button_layout.addWidget(button)

        button_layout.addStretch(1)
        button_layout.addWidget(self.lbl_health_binance)
        button_layout.addWidget(self.lbl_health_mexc)

        search_layout = QHBoxLayout()
        self.search_label = QLabel("Search:")
        self.search_input = QLineEdit()
        search_layout.addWidget(self.search_label)
        search_layout.addWidget(self.search_input)
        main_layout.addLayout(search_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.HEADER_LABELS))
        self.table.setHorizontalHeaderLabels(self.HEADER_LABELS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)

        main_layout.addWidget(self.table)

        self.populate_table_from_watchlist()
        self._update_health_labels()
        self.apply_column_visibility()

        self.add_pair_button.clicked.connect(self.add_pair)
        self.remove_button.clicked.connect(self.remove_selected_rows)
        self.start_button.clicked.connect(self.start_updates)
        self.stop_button.clicked.connect(self.stop_updates)
        self.settings_button.clicked.connect(self.open_settings)
        self.export_button.clicked.connect(self.export_table)
        self.search_input.textChanged.connect(self._apply_filter)
        self.compact_mode_checkbox.toggled.connect(self._on_compact_mode_toggled)
        self.table.cellClicked.connect(self._on_table_cell_clicked)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)

        self._update_start_stop_buttons()

    def _rebuild_binance_client(self) -> None:
        if self.binance_real is not None:
            self.binance_real.close()
            self.binance_real = None

        if self.settings.get("use_real_binance", False):
            self.binance_real = RealBinanceClient()

        self.binance = BinanceClientFacade(self.binance_real, self.binance_mock, self.settings)

    def _rebuild_mexc_client(self) -> None:
        if self.mexc_real is not None:
            self.mexc_real.close()
            self.mexc_real = None

        if self.settings.get("use_real_mexc", False):
            self.mexc_real = RealMexcClient()

        self.mexc = MexcClientFacade(self.mexc_real, self.mexc_mock, self.settings)

    def _rebuild_engine(self) -> None:
        self.engine = Engine(self.settings, self.binance, self.mexc)

    def _update_health_labels(self) -> None:
        self.lbl_health_binance.setText(self.binance.status_line())
        self.lbl_health_mexc.setText(self.mexc.status_line())

    def _on_compact_mode_toggled(self, checked: bool) -> None:
        self.settings["compact_mode"] = bool(checked)
        save_settings(self.settings)
        self.apply_column_visibility()

    def apply_column_visibility(self) -> None:
        visible_columns = self.settings.get("visible_columns", DEFAULT_VISIBLE_COLUMNS)
        visible_set = set(visible_columns)
        visible_set.add("Symbol")

        compact_mode = bool(self.settings.get("compact_mode", False))
        compact_hidden = {"TP", "SL", "Updated"}

        for col, column_name in enumerate(self.COLUMN_NAMES):
            is_visible = column_name in visible_set
            if compact_mode and column_name in compact_hidden:
                is_visible = False
            self.table.setColumnHidden(col, not is_visible)

    def _pinned_symbols(self) -> list[str]:
        pinned = self.settings.get("pinned_symbols", [])
        if isinstance(pinned, list):
            return [str(sym).strip().upper() for sym in pinned if str(sym).strip()]
        return []

    def _is_pinned(self, symbol: str) -> bool:
        return symbol.upper() in set(self._pinned_symbols())

    def _update_pinned_symbols(self, pinned_symbols: list[str]) -> None:
        self.settings["pinned_symbols"] = pinned_symbols
        save_settings(self.settings)

    def _sort_key_for_symbol(self, symbol: str):
        update = self.last_updates_by_symbol.get(symbol)
        if self.sort_col == self.COL_SYMBOL:
            return symbol
        if self.sort_col == self.COL_PIN:
            return 1 if self._is_pinned(symbol) else 0
        if self.sort_col == self.COL_STATUS:
            level = getattr(update, "level", "RED") if update is not None else "RED"
            rank = {"RED": 1, "YELLOW": 2, "GREEN": 3}
            return rank.get(level, 0)
        if self.sort_col == self.COL_SIDE:
            return getattr(update, "side", "") if update is not None else ""
        if self.sort_col == self.COL_REASON:
            return getattr(update, "reason", "") if update is not None else ""
        if self.sort_col == self.COL_BINANCE:
            try:
                return float(getattr(update, "binance_delta_str", "0").replace("%", ""))
            except ValueError:
                return 0.0
        if self.sort_col == self.COL_IMBALANCE:
            try:
                return float(getattr(update, "mexc_imbalance_str", "0"))
            except ValueError:
                return 0.0
        if self.sort_col == self.COL_TAPE:
            try:
                return float(getattr(update, "tape_str", "0").replace("%", ""))
            except ValueError:
                return 0.0
        if self.sort_col == self.COL_ENTRY:
            try:
                return float(getattr(update, "entry_str", "0"))
            except ValueError:
                return 0.0
        if self.sort_col == self.COL_TP:
            tp_value = getattr(update, "tp_str", "") if update is not None else ""
            try:
                return float(tp_value) if tp_value else 0.0
            except ValueError:
                return 0.0
        if self.sort_col == self.COL_SL:
            sl_value = getattr(update, "sl_str", "") if update is not None else ""
            try:
                return float(sl_value) if sl_value else 0.0
            except ValueError:
                return 0.0
        if self.sort_col == self.COL_UPDATED:
            return self.last_update_ts_by_symbol.get(symbol, 0.0)
        return symbol

    def _get_display_symbols(self) -> list[str]:
        watchlist_symbols = [sym.strip().upper() for sym in self.watchlist if sym.strip()]
        watchlist_set = set(watchlist_symbols)

        pinned_in_watchlist = [sym for sym in self._pinned_symbols() if sym in watchlist_set]
        normal_symbols = [sym for sym in watchlist_symbols if sym not in set(pinned_in_watchlist)]

        pinned_sorted = sorted(pinned_in_watchlist, key=self._sort_key_for_symbol, reverse=not self.sort_ascending)
        normal_sorted = sorted(normal_symbols, key=self._sort_key_for_symbol, reverse=not self.sort_ascending)

        return pinned_sorted + normal_sorted

    def populate_table_from_watchlist(self) -> None:
        display_symbols = self._get_display_symbols()
        self.table.setRowCount(0)

        for row, symbol in enumerate(display_symbols):
            self.table.insertRow(row)
            update = self.last_updates_by_symbol.get(symbol)
            pin_mark = "⭐" if self._is_pinned(symbol) else ""

            if update is None:
                values = [
                    pin_mark,
                    symbol,
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
                level = "RED"
            else:
                values = [
                    pin_mark,
                    symbol,
                    getattr(update, "status_emoji", ""),
                    getattr(update, "side", ""),
                    getattr(update, "reason", ""),
                    self._format_signed_delta(getattr(update, "binance_delta_str", "")),
                    getattr(update, "mexc_imbalance_str", ""),
                    getattr(update, "tape_str", ""),
                    getattr(update, "entry_str", ""),
                    getattr(update, "tp_str", ""),
                    getattr(update, "sl_str", ""),
                    getattr(update, "updated_str", ""),
                ]
                level = getattr(update, "level", "RED")

            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, col, item)

            flash_remaining = self._flash_ticks.get(symbol, 0)
            flash_active = self.alerts_checkbox.isChecked() and flash_remaining > 0
            self._set_row_color(row, level, flash_active)

        self._apply_filter()
        self.apply_column_visibility()

    def _apply_filter(self) -> None:
        needle = self.search_input.text().strip().lower()
        for row in range(self.table.rowCount()):
            symbol_item = self.table.item(row, self.COL_SYMBOL)
            side_item = self.table.item(row, self.COL_SIDE)
            reason_item = self.table.item(row, self.COL_REASON)
            symbol_text = symbol_item.text().lower() if symbol_item is not None else ""
            side_text = side_item.text().lower() if side_item is not None else ""
            reason_text = reason_item.text().lower() if reason_item is not None else ""
            visible = not needle or needle in symbol_text or needle in side_text or needle in reason_text
            self.table.setRowHidden(row, not visible)

    def _set_row_color(self, row: int, level: str, flash_active: bool = False) -> None:
        if level == "RED":
            color = QColor(255, 230, 230)
        elif level == "YELLOW":
            color = QColor(255, 248, 220)
        else:
            color = QColor(180, 245, 180) if flash_active else QColor(230, 255, 230)

        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item is not None:
                item.setBackground(color)
                font = item.font()
                font.setBold(flash_active)
                item.setFont(font)

    def _on_table_cell_clicked(self, row: int, col: int) -> None:
        if col != self.COL_PIN:
            return

        symbol_item = self.table.item(row, self.COL_SYMBOL)
        if symbol_item is None:
            return

        symbol = symbol_item.text().strip().upper()
        if not symbol:
            return

        pinned = self._pinned_symbols()
        if symbol in pinned:
            pinned = [sym for sym in pinned if sym != symbol]
        else:
            pinned.append(symbol)

        self._update_pinned_symbols(pinned)
        self.populate_table_from_watchlist()

    def _on_header_clicked(self, section: int) -> None:
        if self.sort_col == section:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_col = section
            self.sort_ascending = True
        self.populate_table_from_watchlist()

    def _log_green_alert(self, update) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        binance_signed = self._format_signed_delta(update.binance_delta_str)
        line = (
            f"{timestamp} | {update.symbol} | GREEN | {update.side} | reason={update.reason}"
            f" | binance={binance_signed} | imb={update.mexc_imbalance_str}"
            f" | tape={update.tape_str} | entry={update.entry_str}"
            f" | tp={update.tp_str or '...'} | sl={update.sl_str or '...'}\n"
        )
        try:
            alerts_path = Path("data") / "alerts.log"
            alerts_path.parent.mkdir(parents=True, exist_ok=True)
            with alerts_path.open("a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass

    def add_pair(self) -> None:
        dialog = AddPairsDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        raw_text = dialog.get_text()
        tokens = [token.strip().upper() for token in re.split(r"[,;\s]+", raw_text) if token.strip()]

        added = 0
        skipped = 0
        existing = set(self.watchlist)

        for symbol in tokens:
            if symbol in existing:
                skipped += 1
                continue
            self.watchlist.append(symbol)
            existing.add(symbol)
            added += 1

        save_watchlist(self.watchlist)
        self.populate_table_from_watchlist()
        QMessageBox.information(self, "Add pair", f"Added: {added}, Skipped (existing/invalid): {skipped}")

    def remove_selected_rows(self) -> None:
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return

        symbols_to_remove: set[str] = set()
        for index in selected_rows:
            item = self.table.item(index.row(), self.COL_SYMBOL)
            if item is not None:
                symbol = item.text().strip().upper()
                if symbol:
                    symbols_to_remove.add(symbol)

        if not symbols_to_remove:
            return

        self.watchlist = [symbol for symbol in self.watchlist if symbol.upper() not in symbols_to_remove]

        pinned = [sym for sym in self._pinned_symbols() if sym not in symbols_to_remove]
        if pinned != self._pinned_symbols():
            self._update_pinned_symbols(pinned)

        save_watchlist(self.watchlist)
        self.populate_table_from_watchlist()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            previous_use_real_binance = bool(self.settings.get("use_real_binance", False))
            previous_use_real_mexc = bool(self.settings.get("use_real_mexc", False))

            changed_values = dialog.get_values()
            self.settings.update(changed_values)
            save_settings(self.settings)

            if self.timer.isActive():
                self.timer.setInterval(int(self.settings["update_interval_ms"]))

            binance_toggled = previous_use_real_binance != bool(self.settings.get("use_real_binance", False))
            mexc_toggled = previous_use_real_mexc != bool(self.settings.get("use_real_mexc", False))

            if binance_toggled:
                self._rebuild_binance_client()
            if mexc_toggled:
                self._rebuild_mexc_client()

            if binance_toggled or mexc_toggled:
                self._rebuild_engine()
            else:
                self.engine.settings = self.settings

            self.compact_mode_checkbox.blockSignals(True)
            self.compact_mode_checkbox.setChecked(bool(self.settings.get("compact_mode", False)))
            self.compact_mode_checkbox.blockSignals(False)
            self._update_health_labels()
            self.populate_table_from_watchlist()
            self.apply_column_visibility()

    def start_updates(self) -> None:
        self.timer.start(int(self.settings["update_interval_ms"]))
        self._update_start_stop_buttons()

    def stop_updates(self) -> None:
        self.timer.stop()
        self._update_start_stop_buttons()

    def _update_start_stop_buttons(self) -> None:
        running = self.timer.isActive()
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)

    def update_mock_data(self) -> None:
        if self.pause_unfocused_checkbox.isChecked() and (self.isMinimized() or not self.isActiveWindow()):
            return

        if not self.alerts_checkbox.isChecked():
            self._flash_ticks.clear()

        updates = self.engine.tick(self.watchlist)
        self._update_health_labels()

        for update in updates:
            symbol = update.symbol.strip().upper()
            self.last_updates_by_symbol[symbol] = update
            self.last_update_ts_by_symbol[symbol] = time.time()

            prev_level = self._previous_levels.get(symbol)
            is_new_green = prev_level != "GREEN" and update.level == "GREEN"
            if self.alerts_checkbox.isChecked() and is_new_green:
                QApplication.beep()
                self._flash_ticks[symbol] = self.FLASH_TICKS
                self._log_green_alert(update)

            flash_remaining = self._flash_ticks.get(symbol, 0)
            if flash_remaining > 0:
                next_ticks = flash_remaining - 1
                if next_ticks > 0:
                    self._flash_ticks[symbol] = next_ticks
                else:
                    self._flash_ticks.pop(symbol, None)

            self._previous_levels[symbol] = update.level

        self.populate_table_from_watchlist()

    def _table_headers(self) -> list[str]:
        headers: list[str] = []
        for col in range(self.table.columnCount()):
            header_item = self.table.horizontalHeaderItem(col)
            headers.append(header_item.text() if header_item is not None else f"col_{col}")
        return headers

    def _table_rows(self) -> list[list[str]]:
        rows: list[list[str]] = []
        for row in range(self.table.rowCount()):
            row_values: list[str] = []
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                row_values.append(item.text() if item is not None else "")
            rows.append(row_values)
        return rows

    def export_table(self) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_csv = str(Path.cwd() / f"screener_{timestamp}.csv")

        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export table",
            default_csv,
            "CSV (*.csv);;JSON (*.json)",
        )
        if not path:
            return

        chosen_path = Path(path)
        lower_path = chosen_path.suffix.lower()

        if not lower_path:
            if "JSON" in selected_filter.upper():
                chosen_path = chosen_path.with_suffix(".json")
            else:
                chosen_path = chosen_path.with_suffix(".csv")

        headers = self._table_headers()
        rows = self._table_rows()

        try:
            if chosen_path.suffix.lower() == ".json":
                payload = [dict(zip(headers, row_values)) for row_values in rows]
                chosen_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                with chosen_path.open("w", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(headers)
                    writer.writerows(rows)

            QMessageBox.information(self, "Export", f"Exported: {chosen_path}")
        except OSError as exc:
            QMessageBox.critical(self, "Export error", f"Failed to export:\n{exc}")

    def _format_signed_delta(self, delta_str: str) -> str:
        if not delta_str.endswith("%"):
            return delta_str

        try:
            value = float(delta_str[:-1])
        except ValueError:
            return delta_str

        return f"{value:+.3f}%"

    def closeEvent(self, event) -> None:
        if self.binance_real is not None:
            self.binance_real.close()
        if self.mexc is not None:
            self.mexc.close()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
