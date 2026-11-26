from __future__ import annotations

import csv
import json
import math
import os
import socket
import threading
import sys
from pathlib import Path
import qrcode

from werkzeug.serving import make_server

from PySide6.QtCore import Qt, QUrl
from PySide6.QtQml import QJSEngine

from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QFrame,
    QComboBox,
    QFileDialog,
    QDialog,
    QDoubleSpinBox,
    QInputDialog,
)


BASE_DIR = Path(__file__).resolve().parent

APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "TimeSenseApp"
CACHE_DIR = Path.home() / "Library" / "Caches" / "TimeSenseApp"
MATPLOTLIB_CACHE_DIR = CACHE_DIR / "matplotlib"

SERVER_CONFIG_PATH = APP_SUPPORT_DIR / "server_config.json"
APP_CONFIG_PATH = APP_SUPPORT_DIR / "app_config.json"
STATS_CONFIG_PATH = APP_SUPPORT_DIR / "stats_config.json"

LEGACY_SERVER_CONFIG_PATH = BASE_DIR / "config" / "server_config.json"
LEGACY_APP_CONFIG_PATH = BASE_DIR / "static" / "app_config.json"

DEFAULT_OUTPUT_DIR = "~/Documents/TimeSenseApp_data"
DEFAULT_STATS_OUTPUT_DIR = "~/Documents/TimeSenseApp_graph_csv"
CSV_READ_ENCODINGS = ["utf-8-sig", "utf-8", "cp932"]

_MATPLOTLIB_FONT_CONFIGURED = False
_MATPLOTLIB_QT_CLASSES = None


def configure_matplotlib_cache() -> None:
    """Keep matplotlib's font cache across packaged-app launches."""
    try:
        MATPLOTLIB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # PyInstaller's matplotlib runtime hook points MPLCONFIGDIR at a
        # temporary directory. Override it before matplotlib is imported so
        # the expensive font cache can be reused by the next app launch.
        os.environ["MPLCONFIGDIR"] = str(MATPLOTLIB_CACHE_DIR)
    except OSError:
        # Matplotlib can still fall back to its runtime-provided cache path.
        pass


configure_matplotlib_cache()


def load_json(path: Path, default: dict, fallback_path: Path | None = None) -> dict:
    if not path.exists():
        if fallback_path is not None and fallback_path.exists():
            try:
                with fallback_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    save_json(path, data)
                    return data
            except Exception:
                pass

        save_json(path, default)
        return dict(default)

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            merged = dict(default)
            merged.update(data)
            return merged
    except Exception:
        pass

    return dict(default)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def table_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setTextAlignment(Qt.AlignCenter)
    return item


def setup_matplotlib_japanese_font() -> None:
    """Configure Japanese-capable fallback fonts once per application run."""
    global _MATPLOTLIB_FONT_CONFIGURED

    if _MATPLOTLIB_FONT_CONFIGURED:
        return

    try:
        import matplotlib
    except Exception:
        return

    # Let matplotlib choose the first installed font. Avoid enumerating every
    # system font on every preview, which is particularly slow in a frozen app.
    preferred_fonts = [
        "Hiragino Sans",
        "Hiragino Kaku Gothic ProN",
        "Yu Gothic",
        "Meiryo",
        "Noto Sans CJK JP",
        "Noto Sans JP",
        "IPAexGothic",
    ]
    existing_fallbacks = list(matplotlib.rcParams.get("font.sans-serif", []))
    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = preferred_fonts + existing_fallbacks
    matplotlib.rcParams["axes.unicode_minus"] = False
    _MATPLOTLIB_FONT_CONFIGURED = True


def get_matplotlib_qt_classes():
    """Import and cache the matplotlib Qt classes used by previews."""
    global _MATPLOTLIB_QT_CLASSES

    if _MATPLOTLIB_QT_CLASSES is not None:
        return _MATPLOTLIB_QT_CLASSES

    try:
        from matplotlib.figure import Figure
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
            from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
        except Exception:
            from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
            from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
    except Exception as exc:
        raise RuntimeError(
            "matplotlib and its Qt backend are required for preview."
        ) from exc

    setup_matplotlib_japanese_font()
    _MATPLOTLIB_QT_CLASSES = (Figure, FigureCanvas, NavigationToolbar)
    return _MATPLOTLIB_QT_CLASSES


class PasteableTableWidget(QTableWidget):
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste_from_clipboard()
            return

        super().keyPressEvent(event)

    def paste_from_clipboard(self) -> None:
        text = QApplication.clipboard().text()

        if not text.strip():
            return

        rows = [
            line.split("\t")
            for line in text.splitlines()
            if line.strip()
        ]

        if not rows:
            return

        start_row = self.currentRow()
        start_col = self.currentColumn()

        if start_row < 0:
            start_row = 0

        if start_col < 0:
            start_col = 0

        required_rows = start_row + len(rows)

        while self.rowCount() < required_rows:
            self.insertRow(self.rowCount())

        for r, cols in enumerate(rows):
            for c, value in enumerate(cols):
                row = start_row + r
                col = start_col + c

                if col >= self.columnCount():
                    continue

                self.setItem(row, col, table_item(value.strip()))


class SliderSettingsDialog(QDialog):
    def __init__(self, settings, lower, upper, initial, parent=None):
        super().__init__(parent)
        self.setWindowTitle("スライダー詳細設定")
        self.resize(1080, 780)
        self.result_settings = None
        self.lower, self.upper, self.initial = lower, upper, initial
        self.preview_step = settings.get("step", 1)
        outer_layout = QHBoxLayout(self)
        layout = QVBoxLayout()
        outer_layout.addLayout(layout, 1)
        layout.addWidget(QLabel("区間内の変化"))
        self.scale = QComboBox()
        self.scale.addItem("線形", "linear")
        self.scale.addItem("対数", "log")
        self.scale.setCurrentIndex(1 if settings.get("scale") == "log" else 0)
        layout.addWidget(self.scale)
        self.checks = {}
        for key, label in (("centerInitial", "initialを中央に配置"),
                           ("compressLeft", "左端を圧縮"), ("compressRight", "右端を圧縮"),
                           ("showValue", "数値を表示")):
            check = QCheckBox(label)
            check.setChecked(settings.get(key, True))
            self.checks[key] = check
            layout.addWidget(check)
        layout.addWidget(QLabel("数値の丸め方（表示・記録とも整数）"))
        self.rounding = QComboBox()
        for label, mode in (("桁に応じた5刻み（従来：10、15…100、150…）", "decade5"),
                            ("5の倍数（5、10、15…100、105…）", "multiple5"),
                            ("有効数字2桁（例：1234 → 1200）", "sig2"),
                            ("有効数字3桁（例：1234 → 1230）", "sig3")):
            self.rounding.addItem(label, mode)
        self.rounding.setCurrentIndex(max(0, self.rounding.findData(settings.get("roundingMode", "decade5"))))
        layout.addWidget(self.rounding)
        self.custom = QCheckBox("値と位置を直接指定する")
        self.custom.setChecked(settings.get("customPositions", False))
        layout.addWidget(self.custom)
        note = QLabel("直接指定時は圧縮・自動中央化を適用しません。\n"
                      "initialを中央にする場合は、その値を50%に指定してください。\n"
                      "0%＝min、100%＝maxを含め、値と位置を昇順に入力してください。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.points = PasteableTableWidget()
        self.points.setColumnCount(2)
        self.points.setHorizontalHeaderLabels(["値", "位置 (%)"])
        self.points.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.points)
        for point in settings.get("anchors") or [{"value": lower, "position": 0}, {"value": upper, "position": 100}]:
            self.add_point(point["value"], point["position"])
        row = QHBoxLayout()
        add = QPushButton("行を追加")
        add.clicked.connect(self.insert_point_after_selection)
        remove = QPushButton("選択行を削除")
        remove.clicked.connect(self.remove_points)
        row.addWidget(add); row.addWidget(remove)
        layout.addLayout(row)
        self.custom.toggled.connect(self.update_mode)
        self.update_mode()
        self.preview_engine = QJSEngine(self)
        source = (BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8")
        functions = source[source.index("    function formatSliderValue"):source.index("    function renderInputs")]
        result = self.preview_engine.evaluate(functions)
        if result.isError():
            raise RuntimeError(result.toString())
        layout.addWidget(QLabel("シミュレーション（実験データには記録されません）"))
        self.preview_value = QLabel()
        self.preview_value.setAlignment(Qt.AlignCenter)
        self.preview_value.setStyleSheet("font-size: 40px; font-weight: 600;")
        layout.addWidget(self.preview_value)
        self.preview_slider = QSlider(Qt.Horizontal)
        self.preview_slider.setRange(0, 10000)
        layout.addWidget(self.preview_slider)
        self.preview_status = QLabel()
        self.preview_status.setWordWrap(True)
        layout.addWidget(self.preview_status)
        reset = QPushButton("initialの位置に戻す")
        reset.clicked.connect(lambda: self.refresh_preview(reset=True))
        layout.addWidget(reset)
        Figure, FigureCanvas, _ = get_matplotlib_qt_classes()
        self.preview_figure = Figure(figsize=(5, 5), constrained_layout=True)
        self.preview_canvas = FigureCanvas(self.preview_figure)
        self.preview_canvas.setMinimumWidth(380)
        self.preview_axes = self.preview_figure.add_subplot(111)
        self.preview_raw_line, = self.preview_axes.plot([], [], color="0.6", linestyle="--", label="丸め前")
        self.preview_rounded_line, = self.preview_axes.plot([], [], color="#2469b3", label="表示・記録値")
        self.preview_marker, = self.preview_axes.plot([], [], "o", color="#d34d35", label="現在位置")
        self.preview_axes.set_xlabel("位置 (%)")
        self.preview_axes.set_ylabel("数値")
        self.preview_axes.set_xlim(0, 100)
        self.preview_axes.ticklabel_format(axis="y", style="plain", useOffset=False)
        self.preview_axes.grid(True, alpha=0.25)
        self.preview_axes.legend(loc="best")
        outer_layout.addWidget(self.preview_canvas, 1)
        self.preview_slider.valueChanged.connect(self.update_preview_value)
        self.scale.currentIndexChanged.connect(lambda *_: self.refresh_preview())
        self.rounding.currentIndexChanged.connect(lambda *_: self.refresh_preview())
        self.custom.toggled.connect(lambda *_: self.refresh_preview())
        for check in self.checks.values():
            check.toggled.connect(lambda *_: self.refresh_preview())
        self.points.itemChanged.connect(lambda *_: self.refresh_preview())
        self.points.model().rowsRemoved.connect(lambda *_: self.refresh_preview())
        self.refresh_preview(reset=True)
        actions = QHBoxLayout()
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        save = QPushButton("適用")
        save.clicked.connect(self.apply_settings)
        actions.addWidget(cancel); actions.addWidget(save)
        layout.addLayout(actions)

    def insert_point_after_selection(self):
        selected = self.points.selectedIndexes()
        current = self.points.currentIndex()
        row = current.row() + 1 if selected and current.isValid() else self.points.rowCount()
        self.add_point(row=row)
        self.points.setCurrentCell(row, 0)
        self.points.setFocus()

    def add_point(self, value="", position="", row=None):
        if row is None:
            row = self.points.rowCount()
        self.points.insertRow(row)
        self.points.setItem(row, 0, table_item(str(value)))
        self.points.setItem(row, 1, table_item(str(position)))

    def remove_points(self):
        for row in sorted({i.row() for i in self.points.selectedIndexes()}, reverse=True):
            self.points.removeRow(row)

    def update_mode(self, *_):
        custom = self.custom.isChecked()
        self.points.setEnabled(custom)
        for key in ("centerInitial", "compressLeft", "compressRight"):
            self.checks[key].setEnabled(not custom)

    @staticmethod
    def validate(settings, lower, upper, initial):
        if not all(math.isfinite(v) for v in (lower, upper, initial)) or not lower < upper or not lower <= initial <= upper:
            raise ValueError("min < max、min ≤ initial ≤ maxとなる値を入力してください。")
        if settings["scale"] == "log" and lower <= 0:
            raise ValueError("対数スケールのminは0より大きくしてください。")
        if settings.get("customPositions"):
            points = settings.get("anchors", [])
            if len(points) < 2:
                raise ValueError("位置の指定には2行以上必要です。")
            if (points[0]["value"], points[0]["position"]) != (lower, 0) or (points[-1]["value"], points[-1]["position"]) != (upper, 100):
                raise ValueError("最初の行をmin・0%、最後の行をmax・100%にしてください。")
            if not all(math.isfinite(p[k]) for p in points for k in ("value", "position")):
                raise ValueError("有限の数値を入力してください。")
            if any(a["value"] >= b["value"] or a["position"] >= b["position"] for a, b in zip(points, points[1:])):
                raise ValueError("値と位置は重複させず、両方とも昇順にしてください。")

    def read_settings(self):
        settings = {key: check.isChecked() for key, check in self.checks.items()}
        settings.update(scale=self.scale.currentData(), customPositions=self.custom.isChecked(),
                        roundingMode=self.rounding.currentData())
        points = []
        for row in range(self.points.rowCount()):
            texts = [self.points.item(row, col).text().strip() if self.points.item(row, col) else "" for col in range(2)]
            if not any(texts):
                continue
            points.append({"value": float(texts[0]), "position": float(texts[1])})
        settings["anchors"] = points
        self.validate(settings, self.lower, self.upper, self.initial)
        return settings

    def refresh_preview(self, reset=False):
        try:
            settings = self.read_settings()
            settings.update(min=self.lower, max=self.upper, initial=self.initial, step=self.preview_step)
            self.preview_engine.globalObject().setProperty("previewConfig", self.preview_engine.toScriptValue(settings))
            self.preview_slider.setEnabled(True)
            self.update_preview_graph()
            if reset:
                position = self.preview_engine.evaluate("sliderPosition(previewConfig, previewConfig.initial)").toNumber()
                self.preview_slider.setValue(round(position * 10000))
            self.update_preview_value()
        except (ValueError, TypeError) as error:
            self.preview_slider.setEnabled(False)
            self.preview_value.clear()
            for line in (self.preview_raw_line, self.preview_rounded_line, self.preview_marker):
                line.set_data([], [])
            self.preview_canvas.draw_idle()
            self.preview_status.setText("プレビューできません：" + str(error))

    def update_preview_graph(self):
        samples = self.preview_engine.evaluate("""
            (function () {
                const result = [];
                for (let i = 0; i <= 1000; i++) {
                    const value = sliderValue(previewConfig, i / 1000);
                    result.push([i / 10, value, Number(formatSliderValue(value, previewConfig))]);
                }
                return result;
            })()
        """).toVariant()
        self.preview_raw_line.set_data([p[0] for p in samples], [p[1] for p in samples])
        self.preview_rounded_line.set_data([p[0] for p in samples], [p[2] for p in samples])
        self.preview_marker.set_data([], [])
        self.preview_axes.relim()
        self.preview_axes.autoscale_view(scalex=False, scaley=True)
        self.preview_canvas.draw_idle()

    def update_preview_value(self, *_):
        if not self.preview_slider.isEnabled():
            return
        position = self.preview_slider.value() / 10000
        value = self.preview_engine.evaluate(f"formatSliderValue(sliderValue(previewConfig, {position}), previewConfig)")
        self.preview_marker.set_data([position * 100], [float(value.toString())])
        self.preview_canvas.draw_idle()
        self.preview_value.setText(value.toString())
        self.preview_value.setVisible(self.checks["showValue"].isChecked())
        self.preview_status.setText(f"位置：{position * 100:.1f}%　範囲：{self.lower:g} ～ {self.upper:g}")

    def apply_settings(self):
        try:
            self.result_settings = self.read_settings()
            self.accept()
        except (ValueError, TypeError) as error:
            QMessageBox.warning(self, "設定を確認してください", str(error))


class LauncherWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("TSE App Launcher v7")
        self.resize(900, 760)

        self.server_thread: threading.Thread | None = None
        self.flask_server = None

        self.server_config = {}
        self.app_config = {}
        self._preview_csv_cache: dict[
            str,
            tuple[int, int, list[str], list[dict[str, str]]],
        ] = {}

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)

        self.show_time_checkbox = QCheckBox("Show time display")
        self.shuffle_buttons_checkbox = QCheckBox("Shuffle button order")

        self.button_columns_spin = QSpinBox()
        self.button_columns_spin.setRange(1, 10)

        self.selection_mode_combo = QComboBox()
        self.selection_mode_combo.addItems(["tcata", "tds"])

        self.slider_table = PasteableTableWidget()
        self.button_table = PasteableTableWidget()

        self.local_url_edit = QLineEdit()
        self.network_url_edit = QLineEdit()
        self.output_dir_edit = QLineEdit()

        self.stats_input_dir_edit = QLineEdit()
        self.stats_output_dir_edit = QLineEdit()

        self.stats_sampling_rate_spin = QDoubleSpinBox()
        self.stats_sampling_rate_spin.setRange(0.001, 1000.0)
        self.stats_sampling_rate_spin.setDecimals(3)
        self.stats_sampling_rate_spin.setSingleStep(1.0)
        self.stats_sampling_rate_spin.setValue(10.0)

        self.stats_time_mode_combo = QComboBox()
        self.stats_time_mode_combo.addItems(["min_duration", "max_duration"])

        self.stats_group_by_combo = QComboBox()
        self.stats_group_by_combo.addItem("sample_id", "sample_id")
        self.stats_group_by_combo.addItem("subject_id", "subject_id")
        self.stats_group_by_combo.addItem("data_title", "data_title")
        self.stats_group_by_combo.addItem("sample_id + subject_id", "sample_id,subject_id")
        self.stats_group_by_combo.addItem("all", "")

        self.stats_tds_raw_value_combo = QComboBox()
        self.stats_tds_raw_value_combo.addItems(["input_id", "input_label"])

        self.stats_rate_item_value_combo = QComboBox()
        self.stats_rate_item_value_combo.addItems(["input_label", "input_id"])

        self.stats_export_ti_raw_checkbox = QCheckBox("Export TI raw")
        self.stats_export_ti_mean_checkbox = QCheckBox("Export TI mean")
        self.stats_export_ti_sd_checkbox = QCheckBox("Export TI sd")
        self.stats_export_tds_raw_checkbox = QCheckBox("Export TDS raw")
        self.stats_export_tds_rate_checkbox = QCheckBox("Export TDS rate")
        self.stats_export_tcata_rate_checkbox = QCheckBox("Export TCATA rate")
        for checkbox in [
            self.stats_export_ti_raw_checkbox,
            self.stats_export_ti_mean_checkbox,
            self.stats_export_ti_sd_checkbox,
            self.stats_export_tds_raw_checkbox,
            self.stats_export_tds_rate_checkbox,
            self.stats_export_tcata_rate_checkbox,
        ]:
            checkbox.setChecked(True)

        self.preview_group_combo = QComboBox()
        self.preview_group_combo.currentTextChanged.connect(self.update_preview_ti_items)
        self.preview_graph_combo = QComboBox()
        self.preview_graph_combo.addItems(["TI mean", "TDS rate", "TCATA rate"])
        self.preview_graph_combo.currentTextChanged.connect(self.update_preview_ti_items)
        self.preview_ti_item_combo = QComboBox()
        self.preview_ti_item_combo.addItem("all")

        self.status_label = QLabel("Status: stopped")

        self.start_button = QPushButton("Start Server")
        self.shutdown_button = QPushButton("Shutdown Server")
        self.save_button = QPushButton("Save Settings")

        self.show_time_action: QAction | None = None
        self.output_dir_display_action: QAction | None = None
        self.port_display_action: QAction | None = None
        self.url_display_action: QAction | None = None

        self._build_ui()
        self._build_menu_bar()
        self.load_settings_into_ui()
        self.load_stats_settings_into_ui()
        self.update_urls()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)

        tabs = QTabWidget()
        root_layout.addWidget(tabs)

        # =========================================================
        # Tab 1: Experiment Setup
        # =========================================================
        experiment_tab = QWidget()
        experiment_layout = QVBoxLayout(experiment_tab)

        sliders_label = QLabel("Sliders")
        sliders_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        experiment_layout.addWidget(sliders_label)

        self.slider_table.setColumnCount(8)
        self.slider_table.setHorizontalHeaderLabels(
            ["id", "label", "min", "max", "step", "initial", "詳細設定", "採用"]
        )
        self.slider_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        experiment_layout.addWidget(self.slider_table)

        slider_button_layout = QHBoxLayout()

        add_slider_button = QPushButton("Add Slider")
        remove_slider_button = QPushButton("Remove Selected Slider")

        add_slider_button.clicked.connect(self.add_slider_row)
        remove_slider_button.clicked.connect(self.remove_selected_slider_rows)

        slider_button_layout.addWidget(add_slider_button)
        slider_button_layout.addWidget(remove_slider_button)
        self.slider_enabled_all = self.add_enabled_toggle(slider_button_layout, self.slider_table, 7)
        slider_button_layout.addStretch()

        experiment_layout.addLayout(slider_button_layout)
        self.add_separator(experiment_layout)

        button_label = QLabel("Buttons")
        button_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        experiment_layout.addWidget(button_label)

        self.button_table.setColumnCount(3)
        self.button_table.setHorizontalHeaderLabels(["id", "label", "採用"])
        self.button_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        experiment_layout.addWidget(self.button_table)

        button_button_layout = QHBoxLayout()

        add_button_button = QPushButton("Add Button")
        remove_button_button = QPushButton("Remove Selected Button")

        add_button_button.clicked.connect(self.add_button_row)
        remove_button_button.clicked.connect(self.remove_selected_button_rows)

        button_button_layout.addWidget(add_button_button)
        button_button_layout.addWidget(remove_button_button)
        self.button_enabled_all = self.add_enabled_toggle(button_button_layout, self.button_table, 2)
        button_button_layout.addStretch()

        button_button_layout.addWidget(QLabel("Selection mode"))
        button_button_layout.addWidget(self.selection_mode_combo)

        button_button_layout.addWidget(QLabel("Button columns"))
        button_button_layout.addWidget(self.button_columns_spin)

        button_button_layout.addWidget(self.shuffle_buttons_checkbox)
        button_button_layout.addWidget(self.show_time_checkbox)

        experiment_layout.addLayout(button_button_layout)

        experiment_action_layout = QHBoxLayout()
        self.save_button.clicked.connect(self.save_settings_from_ui)
        experiment_action_layout.addWidget(self.save_button)
        experiment_action_layout.addStretch()
        experiment_layout.addLayout(experiment_action_layout)

        tabs.addTab(experiment_tab, "Experiment Setup")

        # =========================================================
        # Tab 2: Server
        # =========================================================
        server_tab = QWidget()
        server_layout = QVBoxLayout(server_tab)

        output_label = QLabel("Output")
        output_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        server_layout.addWidget(output_label)

        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("Output folder"))
        output_layout.addWidget(self.output_dir_edit)

        browse_output_button = QPushButton("Browse Output Folder")
        browse_output_button.clicked.connect(self.browse_output_dir)
        output_layout.addWidget(browse_output_button)

        open_output_button = QPushButton("Open Output Folder")
        open_output_button.clicked.connect(self.open_output_dir)
        output_layout.addWidget(open_output_button)

        server_layout.addLayout(output_layout)
        self.add_separator(server_layout)

        url_label = QLabel("Server")
        url_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        server_layout.addWidget(url_label)

        self.local_url_edit.setReadOnly(True)
        self.network_url_edit.setReadOnly(True)

        self.port_spin.valueChanged.connect(self.update_urls)

        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("Port"))
        port_layout.addWidget(self.port_spin)
        port_layout.addStretch()
        server_layout.addLayout(port_layout)

        local_url_layout = QHBoxLayout()
        local_url_layout.addWidget(QLabel("Local URL"))
        local_url_layout.addWidget(self.local_url_edit)
        copy_local_button = QPushButton("Copy")
        copy_local_button.clicked.connect(lambda: self.copy_text(self.local_url_edit.text()))
        local_url_layout.addWidget(copy_local_button)
        server_layout.addLayout(local_url_layout)

        network_url_layout = QHBoxLayout()
        network_url_layout.addWidget(QLabel("Network URL"))
        network_url_layout.addWidget(self.network_url_edit)
        copy_network_button = QPushButton("Copy")
        copy_network_button.clicked.connect(lambda: self.copy_text(self.network_url_edit.text()))
        network_url_layout.addWidget(copy_network_button)
        server_layout.addLayout(network_url_layout)

        server_action_layout = QHBoxLayout()
        self.start_button.clicked.connect(self.start_server)
        self.shutdown_button.clicked.connect(self.stop_server)
        self.shutdown_button.setEnabled(False)

        show_qr_button = QPushButton("Show QR")
        show_qr_button.clicked.connect(self.show_network_qr)

        server_save_button = QPushButton("Save Settings")
        server_save_button.clicked.connect(self.save_settings_from_ui)

        server_action_layout.addWidget(server_save_button)
        server_action_layout.addWidget(self.start_button)
        server_action_layout.addWidget(self.shutdown_button)
        server_action_layout.addWidget(show_qr_button)
        server_action_layout.addStretch()
        server_layout.addLayout(server_action_layout)

        server_layout.addStretch()
        tabs.addTab(server_tab, "Server")

        # =========================================================
        # Tab 3: Stats Export
        # =========================================================
        stats_tab = QWidget()
        stats_layout = QVBoxLayout(stats_tab)

        settings_label = QLabel("Stats settings")
        settings_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        stats_layout.addWidget(settings_label)

        self.stats_input_dir_edit.setReadOnly(True)
        self.stats_output_dir_edit.setReadOnly(True)

        stats_input_layout = QHBoxLayout()
        stats_input_layout.addWidget(QLabel("Input folder"))
        stats_input_layout.addWidget(self.stats_input_dir_edit)
        browse_stats_input_button = QPushButton("Browse")
        browse_stats_input_button.clicked.connect(self.browse_stats_input_dir)
        stats_input_layout.addWidget(browse_stats_input_button)
        stats_layout.addLayout(stats_input_layout)

        stats_output_layout = QHBoxLayout()
        stats_output_layout.addWidget(QLabel("Output folder"))
        stats_output_layout.addWidget(self.stats_output_dir_edit)
        browse_stats_output_button = QPushButton("Browse")
        browse_stats_output_button.clicked.connect(self.browse_stats_output_dir)
        stats_output_layout.addWidget(browse_stats_output_button)
        stats_layout.addLayout(stats_output_layout)

        stats_option_layout_1 = QHBoxLayout()
        stats_option_layout_1.addWidget(QLabel("Sampling rate [Hz]"))
        stats_option_layout_1.addWidget(self.stats_sampling_rate_spin)
        stats_option_layout_1.addWidget(QLabel("Time range"))
        stats_option_layout_1.addWidget(self.stats_time_mode_combo)
        stats_option_layout_1.addWidget(QLabel("Group by"))
        stats_option_layout_1.addWidget(self.stats_group_by_combo)
        stats_option_layout_1.addStretch()
        stats_layout.addLayout(stats_option_layout_1)

        stats_option_layout_2 = QHBoxLayout()
        stats_option_layout_2.addWidget(QLabel("TDS raw"))
        stats_option_layout_2.addWidget(self.stats_tds_raw_value_combo)
        stats_option_layout_2.addWidget(QLabel("Rate item"))
        stats_option_layout_2.addWidget(self.stats_rate_item_value_combo)
        stats_option_layout_2.addStretch()
        stats_layout.addLayout(stats_option_layout_2)

        self.add_separator(stats_layout)

        export_label = QLabel("CSV export")
        export_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        stats_layout.addWidget(export_label)

        export_layout_1 = QHBoxLayout()
        export_layout_1.addWidget(self.stats_export_ti_raw_checkbox)
        export_layout_1.addWidget(self.stats_export_ti_mean_checkbox)
        export_layout_1.addWidget(self.stats_export_ti_sd_checkbox)
        export_layout_1.addStretch()
        stats_layout.addLayout(export_layout_1)

        export_layout_2 = QHBoxLayout()
        export_layout_2.addWidget(self.stats_export_tds_raw_checkbox)
        export_layout_2.addWidget(self.stats_export_tds_rate_checkbox)
        export_layout_2.addWidget(self.stats_export_tcata_rate_checkbox)
        export_layout_2.addStretch()
        stats_layout.addLayout(export_layout_2)

        stats_button_layout = QHBoxLayout()
        save_stats_button = QPushButton("Save Stats Settings")
        save_stats_button.clicked.connect(self.save_stats_settings_from_ui)
        create_stats_button = QPushButton("Create Stats CSV")
        create_stats_button.clicked.connect(self.create_stats_csv)
        open_stats_output_button = QPushButton("Open Stats Output Folder")
        open_stats_output_button.clicked.connect(self.open_stats_output_dir)
        stats_button_layout.addWidget(save_stats_button)
        stats_button_layout.addWidget(create_stats_button)
        stats_button_layout.addWidget(open_stats_output_button)
        stats_button_layout.addStretch()
        stats_layout.addLayout(stats_button_layout)

        self.add_separator(stats_layout)

        preview_label = QLabel("Preview")
        preview_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        stats_layout.addWidget(preview_label)

        preview_layout_1 = QHBoxLayout()
        preview_layout_1.addWidget(QLabel("Output group"))
        preview_layout_1.addWidget(self.preview_group_combo)
        refresh_preview_button = QPushButton("Refresh")
        refresh_preview_button.clicked.connect(lambda: self.refresh_preview_options(show_warnings=True))
        preview_layout_1.addWidget(refresh_preview_button)
        preview_layout_1.addStretch()
        stats_layout.addLayout(preview_layout_1)

        preview_layout_2 = QHBoxLayout()
        preview_layout_2.addWidget(QLabel("Graph"))
        preview_layout_2.addWidget(self.preview_graph_combo)
        preview_layout_2.addWidget(QLabel("TI item"))
        preview_layout_2.addWidget(self.preview_ti_item_combo)
        preview_button = QPushButton("Preview Selected Graph")
        preview_button.clicked.connect(self.preview_selected_graph)
        preview_layout_2.addWidget(preview_button)
        preview_layout_2.addStretch()
        stats_layout.addLayout(preview_layout_2)

        stats_layout.addStretch()
        tabs.addTab(stats_tab, "Stats Export")

        root_layout.addWidget(self.status_label)
        self.setCentralWidget(root)

    def _build_menu_bar(self) -> None:
        settings_menu = self.menuBar().addMenu("Settings")

        self.show_time_action = QAction("Show Time Display", self)
        self.show_time_action.setCheckable(True)
        self.show_time_action.toggled.connect(self.set_show_time_display_from_menu)
        settings_menu.addAction(self.show_time_action)

        settings_menu.addSeparator()

        self.port_display_action = QAction("Port Number: ", self)
        self.port_display_action.setEnabled(False)
        settings_menu.addAction(self.port_display_action)

        set_port_action = QAction("Set Port Number...", self)
        set_port_action.triggered.connect(self.set_port_number_from_menu)
        settings_menu.addAction(set_port_action)

        settings_menu.addSeparator()

        self.url_display_action = QAction("Network URL: ", self)
        self.url_display_action.setEnabled(False)
        settings_menu.addAction(self.url_display_action)

        show_urls_action = QAction("Show URLs...", self)
        show_urls_action.triggered.connect(self.show_urls_dialog)
        settings_menu.addAction(show_urls_action)

        copy_local_url_action = QAction("Copy Local URL", self)
        copy_local_url_action.triggered.connect(lambda: self.copy_text(self.local_url_edit.text()))
        settings_menu.addAction(copy_local_url_action)

        copy_network_url_action = QAction("Copy Network URL", self)
        copy_network_url_action.triggered.connect(lambda: self.copy_text(self.network_url_edit.text()))
        settings_menu.addAction(copy_network_url_action)

        settings_menu.addSeparator()

        save_action = QAction("Save Settings", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.save_settings_from_ui)
        settings_menu.addAction(save_action)

    def update_settings_menu_state(self) -> None:
        if self.show_time_action is not None:
            self.show_time_action.blockSignals(True)
            self.show_time_action.setChecked(self.show_time_checkbox.isChecked())
            self.show_time_action.blockSignals(False)

        output_dir = self.output_dir_edit.text().strip() or DEFAULT_OUTPUT_DIR
        if self.output_dir_display_action is not None:
            self.output_dir_display_action.setText(f"Output Folder: {output_dir}")

        if self.port_display_action is not None:
            self.port_display_action.setText(f"Port Number: {int(self.port_spin.value())}")

        if self.url_display_action is not None:
            network_url = self.network_url_edit.text().strip()
            self.url_display_action.setText(f"Network URL: {network_url}")

    def set_show_time_display_from_menu(self, checked: bool) -> None:
        self.show_time_checkbox.setChecked(checked)
        self.save_settings_from_ui()

    def set_port_number_from_menu(self) -> None:
        if self.flask_server is not None:
            QMessageBox.warning(
                self,
                "Port Number",
                "Stop the server before changing the port number.",
            )
            return

        current_port = int(self.port_spin.value())
        port, accepted = QInputDialog.getInt(
            self,
            "Set Port Number",
            "PORT_NUM",
            current_port,
            1024,
            65535,
            1,
        )

        if not accepted:
            return

        self.port_spin.setValue(port)
        self.save_settings_from_ui()

    def show_output_folder(self) -> None:
        output_dir = self.output_dir_edit.text().strip() or DEFAULT_OUTPUT_DIR
        resolved_output_dir = str(Path(output_dir).expanduser())

        QMessageBox.information(
            self,
            "Output Folder",
            f"Configured output folder:\n{output_dir}\n\nResolved path:\n{resolved_output_dir}",
        )

    def show_urls_dialog(self) -> None:
        self.update_urls()

        dialog = QDialog(self)
        dialog.setWindowTitle("URLs")

        layout = QVBoxLayout(dialog)

        local_label_title = QLabel("Local URL")
        local_label_title.setStyleSheet("font-weight: bold;")
        layout.addWidget(local_label_title)

        local_url_label = QLabel(self.local_url_edit.text())
        local_url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(local_url_label)

        copy_local_button = QPushButton("Copy Local URL")
        copy_local_button.clicked.connect(lambda: self.copy_text(self.local_url_edit.text()))
        layout.addWidget(copy_local_button)

        network_label_title = QLabel("iPad / Network URL")
        network_label_title.setStyleSheet("font-weight: bold;")
        layout.addWidget(network_label_title)

        network_url_label = QLabel(self.network_url_edit.text())
        network_url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(network_url_label)

        copy_network_button = QPushButton("Copy Network URL")
        copy_network_button.clicked.connect(lambda: self.copy_text(self.network_url_edit.text()))
        layout.addWidget(copy_network_button)

        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.close)
        layout.addWidget(close_button)

        dialog.exec()

    def load_settings_into_ui(self) -> None:
        default_server_config = {
            "host": "0.0.0.0",
            "port": 5001,
            "debug": False,
            "output_dir": DEFAULT_OUTPUT_DIR,
        }

        default_app_config = {
            "showTimeDisplay": False,
            "sliders": [
                {
                    "id": "slider_1",
                    "label": "scale 1",
                    "min": 0,
                    "max": 100,
                    "step": 1,
                    "initial": 50,
                }
            ],
            "buttons": [
                {"id": "button_1", "label": "item_1"},
                {"id": "button_2", "label": "item_2"},
                {"id": "button_3", "label": "item_3"},
                {"id": "button_4", "label": "item_4"},
                {"id": "button_5", "label": "item_5"},
                {"id": "button_6", "label": "item_6"},
            ],
            "buttonColumns": 3,
            "selectionMode": "tcata",
            "shuffleButtons": False,
        }

        self.server_config = load_json(
            SERVER_CONFIG_PATH,
            default_server_config,
            LEGACY_SERVER_CONFIG_PATH,
        )
        self.app_config = load_json(
            APP_CONFIG_PATH,
            default_app_config,
            LEGACY_APP_CONFIG_PATH,
        )

        self.port_spin.setValue(int(self.server_config.get("port", 5001)))
        self.output_dir_edit.setText(str(self.server_config.get("output_dir", DEFAULT_OUTPUT_DIR)))

        self.show_time_checkbox.setChecked(
            bool(self.app_config.get("showTimeDisplay", False))
        )
        self.button_columns_spin.setValue(int(self.app_config.get("buttonColumns", 3)))

        self.shuffle_buttons_checkbox.setChecked(bool(self.app_config.get("shuffleButtons", False)))

        self.slider_table.setRowCount(0)
        for slider in self.app_config.get("sliders", []):
            self.add_slider_row(
                slider_id=str(slider.get("id", "")),
                label=str(slider.get("label", "")),
                min_value=str(slider.get("min", 0)),
                max_value=str(slider.get("max", 100)),
                step_value=str(slider.get("step", 1)),
                initial_value=str(slider.get("initial", 0)),
                scale=str(slider.get("scale", "linear")),
                compress_left=bool(slider.get("compressLeft", slider.get("compressEnds", True))),
                compress_right=bool(slider.get("compressRight", slider.get("compressEnds", True))),
                center_initial=bool(slider.get("centerInitial", True)),
                enabled=bool(slider.get("enabled", True)),
                details=slider,
            )

        self.button_table.setRowCount(0)
        for button in self.app_config.get("buttons", []):
            self.add_button_row(
                button_id=str(button.get("id", "")),
                label=str(button.get("label", "")),
                enabled=bool(button.get("enabled", True)),
            )

        selection_mode = str(self.app_config.get("selectionMode", "tcata")).lower()
        if selection_mode not in ["tcata", "tds"]:
            selection_mode = "tcata"
        self.selection_mode_combo.setCurrentText(selection_mode)
        self.update_settings_menu_state()

    def get_default_stats_config(self) -> dict:
        input_dir = self.output_dir_edit.text().strip() or DEFAULT_OUTPUT_DIR
        return {
            "root_dir": input_dir,
            "output_dir": DEFAULT_STATS_OUTPUT_DIR,
            "sampling_rate_hz": 10.0,
            "time_range_mode": "min_duration",
            "group_by": "sample_id",
            "tds_raw_value": "input_id",
            "rate_item_value": "input_label",
            "export_ti_raw": True,
            "export_ti_mean": True,
            "export_ti_sd": True,
            "export_tds_raw": True,
            "export_tds_rate": True,
            "export_tcata_rate": True,
        }

    @staticmethod
    def set_combo_by_data(combo: QComboBox, value: str, default_index: int = 0) -> None:
        for i in range(combo.count()):
            if str(combo.itemData(i)) == value:
                combo.setCurrentIndex(i)
                return

        combo.setCurrentIndex(default_index)

    def load_stats_settings_into_ui(self) -> None:
        stats_config = load_json(
            STATS_CONFIG_PATH,
            self.get_default_stats_config(),
        )

        self.stats_input_dir_edit.setText(str(stats_config.get("root_dir", self.output_dir_edit.text().strip() or DEFAULT_OUTPUT_DIR)))
        self.stats_output_dir_edit.setText(str(stats_config.get("output_dir", DEFAULT_STATS_OUTPUT_DIR)))
        self.stats_sampling_rate_spin.setValue(float(stats_config.get("sampling_rate_hz", 10.0)))

        time_range_mode = str(stats_config.get("time_range_mode", "min_duration")).strip()
        if time_range_mode not in ["min_duration", "max_duration"]:
            time_range_mode = "min_duration"
        self.stats_time_mode_combo.setCurrentText(time_range_mode)

        group_by = str(stats_config.get("group_by", "sample_id")).strip()
        self.set_combo_by_data(self.stats_group_by_combo, group_by, default_index=0)

        tds_raw_value = str(stats_config.get("tds_raw_value", "input_id")).strip()
        if tds_raw_value not in ["input_id", "input_label"]:
            tds_raw_value = "input_id"
        self.stats_tds_raw_value_combo.setCurrentText(tds_raw_value)

        rate_item_value = str(stats_config.get("rate_item_value", "input_label")).strip()
        if rate_item_value not in ["input_id", "input_label"]:
            rate_item_value = "input_label"
        self.stats_rate_item_value_combo.setCurrentText(rate_item_value)

        self.stats_export_ti_raw_checkbox.setChecked(bool(stats_config.get("export_ti_raw", True)))
        self.stats_export_ti_mean_checkbox.setChecked(bool(stats_config.get("export_ti_mean", True)))
        self.stats_export_ti_sd_checkbox.setChecked(bool(stats_config.get("export_ti_sd", True)))
        self.stats_export_tds_raw_checkbox.setChecked(bool(stats_config.get("export_tds_raw", True)))
        self.stats_export_tds_rate_checkbox.setChecked(bool(stats_config.get("export_tds_rate", True)))
        self.stats_export_tcata_rate_checkbox.setChecked(bool(stats_config.get("export_tcata_rate", True)))

        self.refresh_preview_options(show_warnings=False)

    def collect_stats_config(self) -> dict:
        root_dir = self.stats_input_dir_edit.text().strip() or self.output_dir_edit.text().strip() or DEFAULT_OUTPUT_DIR
        output_dir = self.stats_output_dir_edit.text().strip() or DEFAULT_STATS_OUTPUT_DIR

        return {
            "root_dir": root_dir,
            "output_dir": output_dir,
            "sampling_rate_hz": float(self.stats_sampling_rate_spin.value()),
            "time_range_mode": self.stats_time_mode_combo.currentText(),
            "group_by": str(self.stats_group_by_combo.currentData() or ""),
            "tds_raw_value": self.stats_tds_raw_value_combo.currentText(),
            "rate_item_value": self.stats_rate_item_value_combo.currentText(),
            "export_ti_raw": self.stats_export_ti_raw_checkbox.isChecked(),
            "export_ti_mean": self.stats_export_ti_mean_checkbox.isChecked(),
            "export_ti_sd": self.stats_export_ti_sd_checkbox.isChecked(),
            "export_tds_raw": self.stats_export_tds_raw_checkbox.isChecked(),
            "export_tds_rate": self.stats_export_tds_rate_checkbox.isChecked(),
            "export_tcata_rate": self.stats_export_tcata_rate_checkbox.isChecked(),
        }

    def save_stats_settings_from_ui(self) -> None:
        try:
            stats_config = self.collect_stats_config()
            save_json(STATS_CONFIG_PATH, stats_config)
            self.status_label.setText("Status: stats settings saved")
        except Exception as e:
            QMessageBox.critical(self, "Stats save error", str(e))

    @staticmethod
    def sync_enabled_toggle(table, column, toggle):
        states = [table.cellWidget(row, column).isChecked()
                  for row in range(table.rowCount())
                  if table.cellWidget(row, column) is not None]
        state = (Qt.Checked if states and all(states) else
                 Qt.PartiallyChecked if any(states) else Qt.Unchecked)
        toggle.blockSignals(True)
        toggle.setCheckState(state)
        toggle.blockSignals(False)

    def add_enabled_toggle(self, layout, table, column):
        toggle = QCheckBox("すべて採用")
        toggle.setTristate(True)
        def apply_all(state):
            enabled = state != Qt.Unchecked.value
            for row in range(table.rowCount()):
                checkbox = table.cellWidget(row, column)
                if checkbox is not None:
                    checkbox.setChecked(enabled)
            self.sync_enabled_toggle(table, column, toggle)
        toggle.stateChanged.connect(apply_all)
        table.model().rowsRemoved.connect(
            lambda *_: self.sync_enabled_toggle(table, column, toggle))
        layout.addWidget(toggle)
        return toggle

    def add_enabled_cell(self, table, row, column, enabled, toggle):
        checkbox = QCheckBox()
        checkbox.setChecked(enabled)
        table.setCellWidget(row, column, checkbox)
        checkbox.toggled.connect(lambda _: self.sync_enabled_toggle(table, column, toggle))
        self.sync_enabled_toggle(table, column, toggle)

    def add_slider_row(
        self,
        slider_id: str | None = None,
        label: str | None = None,
        min_value: str = "0",
        max_value: str = "100",
        step_value: str = "1",
        initial_value: str = "0",
        scale: str = "linear",
        compress_left: bool = True,
        compress_right: bool = True,
        center_initial: bool = True,
        enabled: bool = True,
        details: dict | None = None,
    ) -> None:
        row = self.slider_table.rowCount()
        self.slider_table.insertRow(row)

        if slider_id is None:
            slider_id = f"slider_{row + 1}"
        if label is None:
            label = f"Slider {row + 1}"

        values = [slider_id, label, min_value, max_value, step_value, initial_value]

        for col, value in enumerate(values):
            self.slider_table.setItem(row, col, table_item(str(value)))

        settings = {"scale": scale, "compressLeft": compress_left,
                    "compressRight": compress_right, "centerInitial": center_initial,
                    "showValue": True, "customPositions": False, "anchors": [],
                    "roundingMode": "decade5"}
        if details:
            settings.update({key: details[key] for key in settings if key in details})
        button = QPushButton("設定…")
        button.setProperty("sliderSettings", settings)
        button.clicked.connect(lambda: self.edit_slider_settings(button))
        self.slider_table.setCellWidget(row, 6, button)
        self.add_enabled_cell(self.slider_table, row, 7, enabled, self.slider_enabled_all)

    def edit_slider_settings(self, button):
        row = next((r for r in range(self.slider_table.rowCount())
                    if self.slider_table.cellWidget(r, 6) is button), None)
        if row is None:
            return
        try:
            lower, upper, initial = [float(self.get_table_text(self.slider_table, row, col)) for col in (2, 3, 5)]
        except ValueError:
            QMessageBox.warning(self, "設定を確認してください", "min・max・initialに数値を入力してください。")
            return
        dialog = SliderSettingsDialog({**button.property("sliderSettings"),
                                       "step": self.parse_number(self.get_table_text(self.slider_table, row, 4))},
                                      lower, upper, initial, self)
        if dialog.exec() == QDialog.Accepted:
            button.setProperty("sliderSettings", dialog.result_settings)

    def remove_selected_slider_rows(self) -> None:
        rows = sorted(
            {index.row() for index in self.slider_table.selectedIndexes()},
            reverse=True,
        )

        for row in rows:
            self.slider_table.removeRow(row)

    def add_button_row(
        self,
        button_id: str | None = None,
        label: str | None = None,
        enabled: bool = True,
    ) -> None:
        row = self.button_table.rowCount()
        self.button_table.insertRow(row)

        if button_id is None:
            button_id = f"button_{row + 1}"
        if label is None:
            label = f"button_{row + 1}"

        self.button_table.setItem(row, 0, table_item(button_id))
        self.button_table.setItem(row, 1, table_item(label))
        self.add_enabled_cell(self.button_table, row, 2, enabled, self.button_enabled_all)

    def remove_selected_button_rows(self) -> None:
        rows = sorted(
            {index.row() for index in self.button_table.selectedIndexes()},
            reverse=True,
        )

        for row in rows:
            self.button_table.removeRow(row)

    def add_separator(self, layout) -> None:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

    def collect_sliders(self) -> list[dict]:
        sliders = []

        for row in range(self.slider_table.rowCount()):
            slider_id = self.get_table_text(self.slider_table, row, 0)
            label = self.get_table_text(self.slider_table, row, 1)
            min_value = self.get_table_text(self.slider_table, row, 2)
            max_value = self.get_table_text(self.slider_table, row, 3)
            step_value = self.get_table_text(self.slider_table, row, 4)
            initial_value = self.get_table_text(self.slider_table, row, 5)

            if not slider_id:
                raise ValueError(f"Slider id is empty at row {row + 1}")

            settings = self.slider_table.cellWidget(row, 6).property("sliderSettings")
            SliderSettingsDialog.validate(settings, float(min_value), float(max_value), float(initial_value))

            sliders.append(
                {
                    "id": slider_id,
                    "label": label or slider_id,
                    **settings,
                    "enabled": self.slider_table.cellWidget(row, 7).isChecked(),
                    "min": self.parse_number(min_value),
                    "max": self.parse_number(max_value),
                    "step": self.parse_number(step_value),
                    "initial": self.parse_number(initial_value),
                }
            )

        return sliders

    def collect_buttons(self) -> list[dict]:
        buttons = []

        for row in range(self.button_table.rowCount()):
            button_id = self.get_table_text(self.button_table, row, 0)
            label = self.get_table_text(self.button_table, row, 1)

            if not button_id:
                raise ValueError(f"Button id is empty at row {row + 1}")

            buttons.append(
                {
                    "id": button_id,
                    "label": label or button_id,
                    "enabled": self.button_table.cellWidget(row, 2).isChecked(),
                }
            )

        return buttons

    @staticmethod
    def get_table_text(table: QTableWidget, row: int, col: int) -> str:
        item = table.item(row, col)
        if item is None:
            return ""
        return item.text().strip()

    @staticmethod
    def parse_number(text: str):
        text = str(text).strip()

        if text == "":
            return 0

        value = float(text)

        if value.is_integer():
            return int(value)

        return value

    def save_settings_from_ui(self) -> None:
        try:
            port = int(self.port_spin.value())

            output_dir = self.output_dir_edit.text().strip()
            if not output_dir:
                output_dir = DEFAULT_OUTPUT_DIR

            server_config = {
                "host": "0.0.0.0",
                "port": port,
                "debug": False,
                "output_dir": output_dir,
            }

            app_config = {
                "showTimeDisplay": self.show_time_checkbox.isChecked(),
                "sliders": self.collect_sliders(),
                "buttons": self.collect_buttons(),
                "buttonColumns": int(self.button_columns_spin.value()),
                "selectionMode": self.selection_mode_combo.currentText(),
                "shuffleButtons": self.shuffle_buttons_checkbox.isChecked(),
            }

            save_json(SERVER_CONFIG_PATH, server_config)
            save_json(APP_CONFIG_PATH, app_config)

            self.server_config = server_config
            self.app_config = app_config

            self.update_urls()
            self.update_settings_menu_state()
            self.status_label.setText("Status: settings saved")

        except Exception as e:
            QMessageBox.critical(self, "Save error", str(e))

    def update_urls(self) -> None:
        port = int(self.port_spin.value())
        lan_ip = get_lan_ip()

        self.local_url_edit.setText(f"http://127.0.0.1:{port}")
        self.network_url_edit.setText(f"http://{lan_ip}:{port}")
        self.update_settings_menu_state()

    def start_server(self) -> None:
        if self.flask_server is not None:
            QMessageBox.information(self, "Server", "Server is already running.")
            return

        self.save_settings_from_ui()

        try:
            import server_v2 as server

            port = int(self.port_spin.value())
            host = "0.0.0.0"

            self.flask_server = make_server(
                host,
                port,
                server.app,
                threaded=True,
            )

            self.server_thread = threading.Thread(
                target=self.flask_server.serve_forever,
                daemon=True,
            )
            self.server_thread.start()

            self.start_button.setEnabled(False)
            self.shutdown_button.setEnabled(True)

            self.status_label.setText("Status: server running")
            self.update_urls()

        except Exception as e:
            self.flask_server = None
            self.server_thread = None
            QMessageBox.critical(self, "Start error", str(e))

    def stop_server(self) -> None:
        if self.flask_server is None:
            self.status_label.setText("Status: stopped")
            return

        try:
            self.flask_server.shutdown()
        except Exception:
            pass

        self.flask_server = None
        self.server_thread = None

        self.start_button.setEnabled(True)
        self.shutdown_button.setEnabled(False)
        self.status_label.setText("Status: stopped")

    def open_output_dir(self) -> None:
        output_dir = self.output_dir_edit.text().strip() or DEFAULT_OUTPUT_DIR
        path = Path(output_dir).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def browse_output_dir(self) -> None:
        current_dir = self.output_dir_edit.text().strip()

        if not current_dir:
            current_dir = str(Path.home() / "Documents" / "TimeSenseApp_data")
        else:
            current_dir = str(Path(current_dir).expanduser())

        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Select output folder",
            current_dir,
        )

        if selected_dir:
            self.output_dir_edit.setText(selected_dir)
            self.save_settings_from_ui()

    def browse_stats_input_dir(self) -> None:
        current_dir = self.stats_input_dir_edit.text().strip() or self.output_dir_edit.text().strip() or DEFAULT_OUTPUT_DIR
        current_dir = str(Path(current_dir).expanduser())

        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Select stats input folder",
            current_dir,
        )

        if selected_dir:
            self.stats_input_dir_edit.setText(selected_dir)
            self.save_stats_settings_from_ui()

    def browse_stats_output_dir(self) -> None:
        current_dir = self.stats_output_dir_edit.text().strip() or DEFAULT_STATS_OUTPUT_DIR
        current_dir = str(Path(current_dir).expanduser())

        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Select stats output folder",
            current_dir,
        )

        if selected_dir:
            self.stats_output_dir_edit.setText(selected_dir)
            self.save_stats_settings_from_ui()

    def create_stats_csv(self) -> None:
        try:
            self.save_stats_settings_from_ui()
            stats_config = self.collect_stats_config()

            import stats_v5

            result = stats_v5.run_stats(
                root_dir=stats_config["root_dir"],
                output_dir=stats_config["output_dir"],
                sampling_rate_hz=float(stats_config["sampling_rate_hz"]),
                time_range_mode=stats_config["time_range_mode"],
                group_by=stats_config["group_by"],
                tds_raw_value=stats_config["tds_raw_value"],
                rate_item_value=stats_config["rate_item_value"],
                export_ti_raw=bool(stats_config["export_ti_raw"]),
                export_ti_mean=bool(stats_config["export_ti_mean"]),
                export_ti_sd=bool(stats_config["export_ti_sd"]),
                export_tds_raw=bool(stats_config["export_tds_raw"]),
                export_tds_rate=bool(stats_config["export_tds_rate"]),
                export_tcata_rate=bool(stats_config["export_tcata_rate"]),
                save_config=True,
            )

            QMessageBox.information(
                self,
                "Stats CSV",
                (
                    "Stats CSV files were created.\n\n"
                    f"Input trials: {result.n_trials}\n"
                    f"Output files: {result.n_output_files}\n"
                    f"Output folder:\n{result.output_dir}"
                ),
            )
            self.status_label.setText(f"Status: stats CSV created ({result.n_output_files} files)")
            self.refresh_preview_options(show_warnings=False)

        except Exception as e:
            QMessageBox.critical(self, "Stats CSV error", str(e))

    def open_stats_output_dir(self) -> None:
        output_dir = self.stats_output_dir_edit.text().strip() or DEFAULT_STATS_OUTPUT_DIR
        path = Path(output_dir).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def find_preview_group_dirs(self) -> list[Path]:
        output_dir = Path(self.stats_output_dir_edit.text().strip() or DEFAULT_STATS_OUTPUT_DIR).expanduser()
        if not output_dir.exists():
            return []

        preview_files = {"TI_mean.csv", "TDS_rate.csv", "TCATA_rate.csv"}
        group_dirs: list[Path] = []

        if any((output_dir / name).exists() for name in preview_files):
            group_dirs.append(output_dir)

        for child in sorted(output_dir.iterdir()):
            if child.is_dir() and any((child / name).exists() for name in preview_files):
                group_dirs.append(child)

        return group_dirs

    def refresh_preview_options(self, show_warnings: bool = True) -> None:
        output_dir = Path(self.stats_output_dir_edit.text().strip() or DEFAULT_STATS_OUTPUT_DIR).expanduser()
        group_dirs = self.find_preview_group_dirs()

        self.preview_group_combo.blockSignals(True)
        self.preview_group_combo.clear()

        for group_dir in group_dirs:
            try:
                label = str(group_dir.relative_to(output_dir))
            except Exception:
                label = group_dir.name
            if label == ".":
                label = output_dir.name
            self.preview_group_combo.addItem(label, str(group_dir))

        self.preview_group_combo.blockSignals(False)
        self.update_preview_ti_items()

        if show_warnings and not group_dirs:
            QMessageBox.information(
                self,
                "Preview",
                "No previewable CSV files were found. Run Create Stats CSV first.",
            )

    def selected_preview_group_dir(self) -> Path | None:
        data = self.preview_group_combo.currentData()
        if not data:
            return None
        return Path(str(data)).expanduser()

    def update_preview_ti_items(self) -> None:
        current_graph = self.preview_graph_combo.currentText()
        self.preview_ti_item_combo.setEnabled(current_graph == "TI mean")
        self.preview_ti_item_combo.clear()
        self.preview_ti_item_combo.addItem("all")

        group_dir = self.selected_preview_group_dir()
        if group_dir is None:
            return

        mean_path = group_dir / "TI_mean.csv"
        if not mean_path.exists():
            return

        try:
            header, _rows = self.read_csv_table(mean_path)
        except Exception:
            return

        for column in header:
            if column != "t_sec":
                self.preview_ti_item_combo.addItem(column)

    @staticmethod
    def parse_optional_float(text: str) -> float | None:
        text = str(text).strip()
        if text == "":
            return None
        try:
            return float(text)
        except Exception:
            return None

    def read_csv_table(self, path: Path) -> tuple[list[str], list[dict[str, str]]]:
        stat = path.stat()
        cache_key = str(path.resolve())
        cached = self._preview_csv_cache.get(cache_key)
        if cached is not None:
            cached_mtime_ns, cached_size, header, rows = cached
            if cached_mtime_ns == stat.st_mtime_ns and cached_size == stat.st_size:
                return header, rows

        for encoding in CSV_READ_ENCODINGS:
            try:
                with path.open("r", newline="", encoding=encoding) as f:
                    reader = csv.DictReader(f)
                    header = list(reader.fieldnames or [])
                    rows = [dict(row) for row in reader]
                self._preview_csv_cache[cache_key] = (
                    stat.st_mtime_ns,
                    stat.st_size,
                    header,
                    rows,
                )
                return header, rows
            except UnicodeDecodeError:
                continue

        with path.open("r", newline="", encoding=CSV_READ_ENCODINGS[-1], errors="replace") as f:
            reader = csv.DictReader(f)
            header = list(reader.fieldnames or [])
            rows = [dict(row) for row in reader]
        self._preview_csv_cache[cache_key] = (
            stat.st_mtime_ns,
            stat.st_size,
            header,
            rows,
        )
        return header, rows

    def preview_selected_graph(self) -> None:
        group_dir = self.selected_preview_group_dir()
        if group_dir is None:
            self.refresh_preview_options(show_warnings=True)
            return

        graph_type = self.preview_graph_combo.currentText()
        self.status_label.setText("Status: loading preview...")
        QApplication.processEvents()

        try:
            if graph_type == "TI mean":
                self.preview_ti_mean(group_dir)
            elif graph_type == "TDS rate":
                self.preview_rate(group_dir / "TDS_rate.csv", "TDS rate preview")
            elif graph_type == "TCATA rate":
                self.preview_rate(group_dir / "TCATA_rate.csv", "TCATA rate preview")
            else:
                raise ValueError(f"Unknown preview graph type: {graph_type}")
        except Exception as e:
            QMessageBox.critical(self, "Preview error", str(e))
        finally:
            self.status_label.setText("Status: preview ready")

    def preview_rate(self, csv_path: Path, title: str) -> None:
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file was not found:\n{csv_path}")

        header, rows = self.read_csv_table(csv_path)
        item_columns = [column for column in header if column != "t_sec"]
        if not item_columns:
            raise ValueError(f"No item columns were found in {csv_path.name}")

        fig, ax = self.create_matplotlib_figure()
        plotted = False

        for column in item_columns:
            x_values = []
            y_values = []
            for row in rows:
                x = self.parse_optional_float(row.get("t_sec", ""))
                y = self.parse_optional_float(row.get(column, ""))
                if x is None or y is None:
                    continue
                x_values.append(x)
                y_values.append(y)
            if x_values:
                ax.plot(x_values, y_values, label=column)
                plotted = True

        if not plotted:
            raise ValueError(f"No plottable numeric data were found in {csv_path.name}")

        ax.set_title(title)
        ax.set_xlabel("Time [s]")
        ax.set_ylabel("Selection rate")
        ax.set_ylim(0, 1)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best")
        self.show_figure_dialog(fig, title)

    def preview_ti_mean(self, group_dir: Path) -> None:
        mean_path = group_dir / "TI_mean.csv"
        sd_path = group_dir / "TI_sd.csv"

        if not mean_path.exists():
            raise FileNotFoundError(f"CSV file was not found:\n{mean_path}")

        mean_header, mean_rows = self.read_csv_table(mean_path)
        sd_header: list[str] = []
        sd_rows: list[dict[str, str]] = []
        if sd_path.exists():
            sd_header, sd_rows = self.read_csv_table(sd_path)

        item_columns = [column for column in mean_header if column != "t_sec"]
        if not item_columns:
            raise ValueError("No TI item columns were found in TI_mean.csv")

        selected_item = self.preview_ti_item_combo.currentText().strip()
        if selected_item and selected_item != "all":
            item_columns = [selected_item]

        fig, ax = self.create_matplotlib_figure()
        plotted = False

        for column in item_columns:
            x_values = []
            y_values = []
            sd_values = []

            for i, row in enumerate(mean_rows):
                x = self.parse_optional_float(row.get("t_sec", ""))
                y = self.parse_optional_float(row.get(column, ""))
                if x is None or y is None:
                    continue

                x_values.append(x)
                y_values.append(y)

                sd_value = None
                if column in sd_header and i < len(sd_rows):
                    sd_value = self.parse_optional_float(sd_rows[i].get(column, ""))
                sd_values.append(sd_value)

            if not x_values:
                continue

            line = ax.plot(x_values, y_values, label=column)[0]
            plotted = True

            if selected_item != "all" and any(value is not None for value in sd_values):
                lower = []
                upper = []
                valid_x = []
                for x, y, sd in zip(x_values, y_values, sd_values):
                    if sd is None:
                        continue
                    valid_x.append(x)
                    lower.append(y - sd)
                    upper.append(y + sd)
                if valid_x:
                    ax.fill_between(valid_x, lower, upper, alpha=0.2, color=line.get_color())

        if not plotted:
            raise ValueError("No plottable numeric data were found in TI_mean.csv")

        title = "TI mean preview"
        if selected_item and selected_item != "all":
            title = f"TI mean preview: {selected_item}"

        ax.set_title(title)
        ax.set_xlabel("Time [s]")
        ax.set_ylabel("Score")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best")
        self.show_figure_dialog(fig, title)

    @staticmethod
    def create_matplotlib_figure():
        Figure, _FigureCanvas, _NavigationToolbar = get_matplotlib_qt_classes()
        fig = Figure(figsize=(8, 5))
        fig.subplots_adjust(left=0.10, right=0.96, bottom=0.11, top=0.92)
        ax = fig.add_subplot(111)
        return fig, ax

    def show_figure_dialog(self, fig, title: str) -> None:
        _Figure, FigureCanvas, NavigationToolbar = get_matplotlib_qt_classes()

        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(900, 650)

        layout = QVBoxLayout(dialog)
        canvas = FigureCanvas(fig)
        toolbar = NavigationToolbar(canvas, dialog)
        layout.addWidget(toolbar)
        layout.addWidget(canvas)

        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.close)
        layout.addWidget(close_button)

        canvas.draw()
        dialog.exec()

    def show_network_qr(self) -> None:
        url = self.network_url_edit.text().strip()

        if not url:
            QMessageBox.warning(self, "QR error", "Network URL is empty.")
            return

        qr_image = qrcode.make(url)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        qr_path = CACHE_DIR / "_tmp_network_qr.png"
        qr_image.save(qr_path)

        dialog = QDialog(self)
        dialog.setWindowTitle("URL QR Code")

        layout = QVBoxLayout(dialog)

        url_label = QLabel(url)
        url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(url_label)

        qr_label = QLabel()
        pixmap = QPixmap(str(qr_path))
        qr_label.setPixmap(pixmap.scaled(360, 360, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        qr_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(qr_label)

        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.close)
        layout.addWidget(close_button)

        dialog.exec()

    @staticmethod
    def copy_text(text: str) -> None:
        QApplication.clipboard().setText(text)

    def closeEvent(self, event):
        self.stop_server()
        event.accept()


def main() -> None:
    app = QApplication(sys.argv)
    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
