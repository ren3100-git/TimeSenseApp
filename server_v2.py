from flask import Flask, render_template, request, jsonify, send_file
from pathlib import Path
import csv
from datetime import datetime
import re
import json
import threading
import random

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent

APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "TimeSenseApp"
CONFIG_PATH = APP_SUPPORT_DIR / "server_config.json"
APP_CONFIG_PATH = APP_SUPPORT_DIR / "app_config.json"

LEGACY_CONFIG_PATH = BASE_DIR / "config" / "server_config.json"
LEGACY_APP_CONFIG_PATH = BASE_DIR / "static" / "app_config.json"

DEFAULT_OUTPUT_DIR = "~/Documents/TimeSenseApp_data"

csv_write_lock = threading.Lock()
active_trial_dirs: dict[tuple[str, str], Path] = {}
active_trial_meta: dict[tuple[str, str], dict] = {}

DATA_COLUMNS = [
    "t_sec",
    "input_type",
    "input_id",
    "input_label",
    "value",
    "event",
    "server_datetime",
]

META_KEYS = [
    "data_title",
    "subject_id",
    "sample_id",
    "trial_no",
    "trial_id",
    "device_id",
    "start_time",
    "finish_time",
    "duration_sec",
    "selection_mode",
    "shuffle_buttons",
    "note",
]


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(path: Path, default: dict, fallback_path: Path | None = None) -> dict:
    if not path.exists():
        if fallback_path is not None and fallback_path.exists():
            with fallback_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            save_json(path, data)
            return data

        save_json(path, default)
        return default

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_default_app_config() -> dict:
    return {
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
        "selectionMode": "tds",
        "shuffleButtons": False,
    }


def load_app_config() -> dict:
    return load_json(
        APP_CONFIG_PATH,
        get_default_app_config(),
        LEGACY_APP_CONFIG_PATH,
    )


def load_server_config() -> dict:
    default_config = {
        "host": "0.0.0.0",
        "port": 5001,
        "debug": False,
        "output_dir": DEFAULT_OUTPUT_DIR,
    }

    user_config = load_json(CONFIG_PATH, default_config, LEGACY_CONFIG_PATH)
    default_config.update(user_config)
    return default_config


def get_output_dir() -> Path:
    server_config = load_server_config()
    output_dir_text = server_config.get("output_dir", DEFAULT_OUTPUT_DIR)

    output_dir = Path(output_dir_text).expanduser()

    if not output_dir.is_absolute():
        output_dir = BASE_DIR / output_dir

    output_dir.mkdir(parents=True, exist_ok=True)

    return output_dir


def safe_filename_name(text: str) -> str:
    text = str(text).strip()

    if not text:
        text = "untitled_trial"

    text = re.sub(r"[^\w\-]+", "_", text)
    text = text.strip("_")

    if not text:
        text = "untitled_trial"

    return text


def build_trial_folder_base_name(data: dict) -> str:
    subject_id = str(data.get("subject_id", "")).strip()
    sample_id = str(data.get("sample_id", "")).strip()
    trial_no = str(data.get("trial_no", "")).strip()
    trial_id = str(data.get("trial_id", "")).strip()

    parts = [part for part in [subject_id, sample_id, trial_no] if part]

    if parts:
        return safe_filename_name("_".join(parts))

    return safe_filename_name(trial_id or "untitled_trial")


def get_available_trial_dir(data: dict) -> Path:
    output_dir = get_output_dir()
    base_name = build_trial_folder_base_name(data)

    index = 1
    while True:
        if index <= 1:
            trial_dir = output_dir / base_name
        else:
            trial_dir = output_dir / f"{base_name}_{index}"

        if not trial_dir.exists():
            trial_dir.mkdir(parents=True, exist_ok=False)
            return trial_dir

        index += 1


def get_trial_key(device_id: str, trial_id: str) -> tuple[str, str]:
    safe_device_id = safe_filename_name(device_id or "unknown_device")
    safe_trial_id = safe_filename_name(trial_id or "untitled_trial")

    return safe_device_id, safe_trial_id


def get_trial_dir_for_event(data: dict, device_id: str, trial_id: str, event_name: str) -> Path:
    key = get_trial_key(device_id, trial_id)

    if event_name == "start":
        trial_dir = get_available_trial_dir(data)
        active_trial_dirs[key] = trial_dir
        return trial_dir

    if key in active_trial_dirs:
        return active_trial_dirs[key]

    # If an event arrives before start, still save it in a new trial folder.
    trial_dir = get_available_trial_dir(data)
    active_trial_dirs[key] = trial_dir
    return trial_dir


def ensure_data_csv_exists(data_csv_path: Path) -> None:
    if not data_csv_path.exists():
        with data_csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=DATA_COLUMNS)
            writer.writeheader()


def get_input_label(input_type: str, input_id: str, event_name: str) -> str:
    input_type = str(input_type).strip().lower()
    input_id = str(input_id).strip()

    if not input_id:
        return event_name

    config = load_app_config()

    if input_type == "slider":
        candidates = config.get("sliders", [])
    elif input_type == "button":
        candidates = config.get("buttons", [])
    else:
        candidates = []

    for item in candidates:
        if str(item.get("id", "")).strip() == input_id:
            return str(item.get("label", input_id)).strip() or input_id

    return input_id


def build_meta(data: dict, device_id: str, trial_id: str, now_text: str) -> dict:
    app_config = load_app_config()

    return {
        "data_title": data.get("data_title", ""),
        "subject_id": data.get("subject_id", ""),
        "sample_id": data.get("sample_id", ""),
        "trial_no": data.get("trial_no", ""),
        "trial_id": trial_id,
        "device_id": device_id,
        "start_time": now_text,
        "finish_time": "",
        "duration_sec": "",
        "selection_mode": app_config.get("selectionMode", ""),
        "shuffle_buttons": app_config.get("shuffleButtons", ""),
        "note": data.get("note", ""),
    }


def write_meta_txt(meta_path: Path, meta: dict) -> None:
    lines = []

    for key in META_KEYS:
        lines.append(f"{key}: {meta.get(key, '')}")

    meta_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def get_or_create_meta(trial_dir: Path, key: tuple[str, str], data: dict, device_id: str, trial_id: str, now_text: str) -> dict:
    if key not in active_trial_meta:
        active_trial_meta[key] = build_meta(data, device_id, trial_id, now_text)
        write_meta_txt(trial_dir / "meta.txt", active_trial_meta[key])

    return active_trial_meta[key]


def update_meta_on_finish(meta: dict, now_text: str, t_sec_value) -> None:
    meta["finish_time"] = now_text

    if str(t_sec_value).strip() != "":
        meta["duration_sec"] = t_sec_value
        return

    start_time_text = str(meta.get("start_time", "")).strip()
    if not start_time_text:
        return

    try:
        start_time = datetime.fromisoformat(start_time_text)
        finish_time = datetime.fromisoformat(now_text)
        meta["duration_sec"] = round((finish_time - start_time).total_seconds(), 3)
    except Exception:
        pass


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/app_config")
def app_config():
    config = load_app_config()

    if bool(config.get("shuffleButtons", False)):
        buttons = list(config.get("buttons", []))
        random.shuffle(buttons)
        config["buttons"] = buttons

    return jsonify(config)


@app.route("/event", methods=["POST"])
def receive_event():
    data = request.get_json(force=True)

    device_id = str(data.get("device_id", "")).strip() or "unknown_device"
    trial_id = str(data.get("trial_id", "")).strip() or "untitled_trial"
    event_name = str(data.get("event", "")).strip()
    input_type = str(data.get("input_type", "")).strip()
    input_id = str(data.get("input_id", "")).strip()

    now_text = datetime.now().isoformat(timespec="seconds")
    key = get_trial_key(device_id, trial_id)

    row = {
        "t_sec": data.get("t_sec", ""),
        "input_type": input_type,
        "input_id": input_id,
        "input_label": get_input_label(input_type, input_id, event_name),
        "value": data.get("value", ""),
        "event": event_name,
        "server_datetime": now_text,
    }

    with csv_write_lock:
        trial_dir = get_trial_dir_for_event(
            data=data,
            device_id=device_id,
            trial_id=trial_id,
            event_name=event_name,
        )

        meta = get_or_create_meta(
            trial_dir=trial_dir,
            key=key,
            data=data,
            device_id=device_id,
            trial_id=trial_id,
            now_text=now_text,
        )

        data_csv_path = trial_dir / "data.csv"
        ensure_data_csv_exists(data_csv_path)

        with data_csv_path.open("a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=DATA_COLUMNS)
            writer.writerow(row)

        if event_name == "finish":
            update_meta_on_finish(meta, now_text, data.get("t_sec", ""))
            write_meta_txt(trial_dir / "meta.txt", meta)
            active_trial_dirs.pop(key, None)
            active_trial_meta.pop(key, None)

    return jsonify({
        "status": "ok",
        "saved_folder": trial_dir.name,
        "saved_file": "data.csv",
    })


@app.route("/results")
def results():
    rows = []

    for data_csv_path in sorted(get_output_dir().glob("*/data.csv")):
        with data_csv_path.open("r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row = {"source_folder": data_csv_path.parent.name, **row}
                rows.append(row)

    rows = rows[-200:]
    rows.reverse()

    columns = ["source_folder"] + DATA_COLUMNS

    return render_template("results.html", rows=rows, columns=columns)


@app.route("/download/<path:filename>")
def download_file(filename):
    output_dir = get_output_dir().resolve()
    try:
        requested_path = (output_dir / filename).resolve()
        requested_path.relative_to(output_dir)
    except (ValueError, OSError, RuntimeError):
        return "File not found", 404

    if not requested_path.is_file():
        return "File not found", 404

    return send_file(requested_path, as_attachment=True)


def run_server(host: str = "0.0.0.0", port: int = 5001, debug: bool = False) -> None:
    app.run(
        host=host,
        port=port,
        debug=debug,
        use_reloader=False,
    )


if __name__ == "__main__":
    server_config = load_server_config()

    host = server_config["host"]
    port = int(server_config["port"])
    debug = bool(server_config["debug"])

    print("")
    print("TSE App server v2")
    print(f"Local URL: http://127.0.0.1:{port}")
    print(f"Network URL: http://<this Mac IP address>:{port}")
    print("")

    run_server(host=host, port=port, debug=debug)
