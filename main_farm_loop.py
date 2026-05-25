import subprocess
import time
from io import BytesIO
from typing import Optional, Tuple
import json
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import cv2
import numpy as np
from PIL import Image, ImageTk


PACKAGE_NAME = "com.supercell.clashofclans"
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "farm_config.json"
CUSTOM_TEMPLATE_DIR = APP_DIR / "templates" / "custom"


def resolve_app_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path

    return APP_DIR / path


def portable_adb_path() -> Optional[Path]:
    candidates = [
        APP_DIR / "adb" / "adb.exe",
        APP_DIR / "platform-tools" / "adb.exe",
        APP_DIR / "adb.exe",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def adb_executable() -> str:
    portable_adb = portable_adb_path()
    if portable_adb:
        return str(portable_adb)

    return "adb"


def configure_adb_environment() -> None:
    portable_adb = portable_adb_path()
    if not portable_adb:
        return

    adb_dir = str(portable_adb.parent)
    os.environ["ADBUTILS_ADB_PATH"] = str(portable_adb)
    os.environ["PATH"] = adb_dir + os.pathsep + os.environ.get("PATH", "")


configure_adb_environment()

import uiautomator2 as u2

TEMPLATE_FIELDS = {
    "attack_home": {
        "label": "Attack button on home screen",
        "path": "templates/attack_home.jpg",
        "threshold": 0.70,
    },
    "find_match": {
        "label": "Find a Match button",
        "path": "templates/find_match.jpg",
        "threshold": 0.70,
    },
    "attack_army": {
        "label": "Attack button on army screen",
        "path": "templates/attack_army.jpg",
        "threshold": 0.70,
    },
    "next_button": {
        "label": "Next button / base found",
        "path": "templates/next_button.jpg",
        "threshold": 0.75,
    },
    "troop_1": {
        "label": "Troop 1 button",
        "path": "templates/troop_balloon.jpg",
        "threshold": 0.75,
    },
    "troop_empty_1": {
        "label": "Troop 1 empty indicator",
        "path": "templates/troop_empty.jpg",
        "threshold": 0.70,
    },
    "troop_2": {
        "label": "Troop 2 button",
        "path": "templates/troop_balloon.jpg",
        "threshold": 0.75,
    },
    "troop_empty_2": {
        "label": "Troop 2 empty indicator",
        "path": "templates/troop_empty.jpg",
        "threshold": 0.70,
    },
    "troop_3": {
        "label": "Troop 3 button",
        "path": "templates/troop_balloon.jpg",
        "threshold": 0.75,
    },
    "troop_empty_3": {
        "label": "Troop 3 empty indicator",
        "path": "templates/troop_empty.jpg",
        "threshold": 0.70,
    },
    "return_home": {
        "label": "Return Home button",
        "path": "templates/return_home.jpg",
        "threshold": 0.75,
    },
}


TROOP_SLOTS = [
    {
        "name": "Troop 1",
        "button_key": "troop_1",
        "empty_key": "troop_empty_1",
    },
    {
        "name": "Troop 2",
        "button_key": "troop_2",
        "empty_key": "troop_empty_2",
    },
    {
        "name": "Troop 3",
        "button_key": "troop_3",
        "empty_key": "troop_empty_3",
    },
]


def default_config() -> dict:
    return {
        "device_id": "",
        "max_rounds": "",
        "delay_between_rounds_seconds": 10,
        "restart_wait_seconds": 25,
        "templates": {
            key: {
                "path": value["path"],
                "threshold": value["threshold"],
            }
            for key, value in TEMPLATE_FIELDS.items()
        },
    }


def load_config(config_path: str | Path = CONFIG_PATH) -> dict:
    config = default_config()
    path = resolve_app_path(config_path)

    if not path.exists():
        return config

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        print(f"Cannot load config, using defaults: {error}")
        return config

    config.update({key: value for key, value in loaded.items() if key != "templates"})
    loaded_templates = dict(loaded.get("templates", {}))
    legacy_template_keys = {
        "troop": "troop_1",
        "troop_empty": "troop_empty_1",
        "troop_2_empty": "troop_empty_2",
        "troop_3_empty": "troop_empty_3",
    }
    for old_key, new_key in legacy_template_keys.items():
        if old_key in loaded_templates and new_key not in loaded_templates:
            loaded_templates[new_key] = loaded_templates[old_key]

    for key, value in loaded_templates.items():
        if key in config["templates"] and isinstance(value, dict):
            config["templates"][key].update(value)

    return config


def save_config(config: dict, config_path: str | Path = CONFIG_PATH) -> None:
    path = resolve_app_path(config_path)
    path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def template_path(config: dict, key: str) -> str:
    return str(resolve_app_path(config["templates"][key]["path"]))


def template_threshold(config: dict, key: str) -> float:
    return float(config["templates"][key]["threshold"])


def list_adb_devices() -> tuple[list[str], list[tuple[str, str]]]:
    try:
        result = subprocess.run(
            [adb_executable(), "devices"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10
        )
    except Exception as error:
        print(f"List ADB devices error: {error}")
        return [], []

    if result.returncode != 0:
        print(result.stderr.decode(errors="ignore"))
        return [], []

    connected_devices: list[str] = []
    other_devices: list[tuple[str, str]] = []
    lines = result.stdout.decode(errors="ignore").splitlines()

    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue

        device_id, status = parts[0], parts[1]
        if status == "device":
            connected_devices.append(device_id)
        else:
            other_devices.append((device_id, status))

    return connected_devices, other_devices


def run_adb_text(args: list[str], timeout: int = 5) -> str:
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout
        )
    except Exception:
        return ""

    if result.returncode != 0:
        return ""

    return result.stdout.decode(errors="ignore").strip()


def get_device_property(device_id: str, property_name: str) -> str:
    return run_adb_text(
        [adb_executable(), "-s", device_id, "shell", "getprop", property_name],
        timeout=5
    )


def get_device_screen_size(device_id: str) -> str:
    output = run_adb_text(
        [adb_executable(), "-s", device_id, "shell", "wm", "size"],
        timeout=5
    )

    if "Physical size:" in output:
        return output.split("Physical size:", 1)[1].strip()

    return output


def get_adb_device_info(device_id: str) -> dict:
    manufacturer = get_device_property(device_id, "ro.product.manufacturer")
    model = get_device_property(device_id, "ro.product.model")
    android_version = get_device_property(device_id, "ro.build.version.release")
    screen_size = get_device_screen_size(device_id)

    return {
        "id": device_id,
        "manufacturer": manufacturer or "Unknown",
        "model": model or "Unknown",
        "android": android_version or "Unknown",
        "screen": screen_size or "Unknown",
        "status": "device",
    }


def format_device_label(info: dict) -> str:
    name = f"{info.get('manufacturer', 'Unknown')} {info.get('model', 'Unknown')}"
    return (
        f"{info.get('id', '')} | {name.strip()} | "
        f"Android {info.get('android', 'Unknown')} | {info.get('screen', 'Unknown')}"
    )


class AdbImageBot:
    def __init__(self, device_id: Optional[str] = None):
        self.device_id = device_id

    def _adb(self, args: list[str]) -> list[str]:
        command = [adb_executable()]
        if self.device_id:
            command.extend(["-s", self.device_id])
        command.extend(args)
        return command

    def run_adb(self, args: list[str], timeout: int = 10) -> Optional[str]:
        try:
            result = subprocess.run(
                self._adb(args),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout
            )

            if result.returncode != 0:
                print(result.stderr.decode(errors="ignore"))
                return None

            return result.stdout.decode(errors="ignore")

        except Exception as error:
            print(f"ADB error: {error}")
            return None

    def capture_screen(self) -> Optional[np.ndarray]:
        try:
            result = subprocess.run(
                self._adb(["exec-out", "screencap", "-p"]),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10
            )

            if result.returncode != 0:
                print(result.stderr.decode(errors="ignore"))
                return None

            image = Image.open(BytesIO(result.stdout)).convert("RGB")
            return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

        except Exception as error:
            print(f"Capture error: {error}")
            return None

    def find_image(
        self,
        template_path: str,
        threshold: float = 0.8
    ) -> Optional[Tuple[int, int]]:
        screen = self.capture_screen()
        if screen is None:
            return None

        template = cv2.imread(template_path)
        if template is None:
            print(f"Template not found: {template_path}")
            return None

        result = cv2.matchTemplate(
            screen,
            template,
            cv2.TM_CCOEFF_NORMED
        )

        _, max_value, _, max_location = cv2.minMaxLoc(result)

        print(f"Template: {template_path}, score: {max_value:.3f}")

        if max_value < threshold:
            return None

        template_height, template_width = template.shape[:2]
        center_x = max_location[0] + template_width // 2
        center_y = max_location[1] + template_height // 2

        return center_x, center_y

    def tap(self, x: int, y: int) -> bool:
        try:
            result = subprocess.run(
                self._adb(["shell", "input", "tap", str(x), str(y)]),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5
            )

            if result.returncode != 0:
                print(result.stderr.decode(errors="ignore"))
                return False

            print(f"Tapped at ({x}, {y})")
            return True

        except Exception as error:
            print(f"Tap error: {error}")
            return False

    def wait_and_tap_image(
        self,
        template_path: str,
        threshold: float = 0.8,
        interval_seconds: float = 5,
        timeout_seconds: int = 60,
        stop_event: Optional[threading.Event] = None
    ) -> bool:
        start_time = time.time()

        while time.time() - start_time <= timeout_seconds:
            if stop_event and stop_event.is_set():
                print("Stopped while waiting image")
                return False

            position = self.find_image(
                template_path=template_path,
                threshold=threshold
            )

            if position:
                x, y = position
                return self.tap(x, y)

            print(f"Image not found: {template_path}. Retry after {interval_seconds}s...")
            time.sleep(interval_seconds)

        print(f"Timeout: image not found: {template_path}")
        return False

    def wait_until_image_exists(
        self,
        template_path: str,
        threshold: float = 0.8,
        interval_seconds: float = 2,
        timeout_seconds: int = 90,
        stop_event: Optional[threading.Event] = None
    ) -> bool:
        start_time = time.time()

        while time.time() - start_time <= timeout_seconds:
            if stop_event and stop_event.is_set():
                print("Stopped while waiting image")
                return False

            position = self.find_image(
                template_path=template_path,
                threshold=threshold
            )

            if position:
                print(f"Image found: {template_path}")
                return True

            print(f"Waiting image: {template_path}. Retry after {interval_seconds}s...")
            time.sleep(interval_seconds)

        print(f"Timeout waiting image: {template_path}")
        return False


def build_adb_command(args: list[str], device_id: Optional[str] = None) -> list[str]:
    command = [adb_executable()]

    if device_id:
        command.extend(["-s", device_id])

    command.extend(args)
    return command


def force_stop_game(device_id: Optional[str] = None) -> bool:
    try:
        result = subprocess.run(
            build_adb_command([
                "shell",
                "am",
                "force-stop",
                PACKAGE_NAME
            ], device_id),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10
        )

        if result.returncode != 0:
            print(result.stderr.decode(errors="ignore"))
            return False

        print("Game force stopped")
        return True

    except Exception as error:
        print(f"Force stop error: {error}")
        return False


def is_game_process_running(device_id: Optional[str] = None) -> bool:
    try:
        result = subprocess.run(
            build_adb_command(["shell", "pidof", PACKAGE_NAME], device_id),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5
        )

        return result.returncode == 0 and bool(result.stdout.decode(errors="ignore").strip())

    except Exception as error:
        print(f"Check game process error: {error}")
        return False


def is_game_foreground(device_id: Optional[str] = None) -> bool:
    try:
        result = subprocess.run(
            build_adb_command(["shell", "dumpsys", "window"], device_id),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10
        )

        if result.returncode != 0:
            print(result.stderr.decode(errors="ignore"))
            return False

        output = result.stdout.decode(errors="ignore")
        focus_lines = [
            line
            for line in output.splitlines()
            if "mCurrentFocus" in line or "mFocusedApp" in line
        ]

        return any(PACKAGE_NAME in line for line in focus_lines)

    except Exception as error:
        print(f"Check foreground app error: {error}")
        return False


def launch_game(device_id: Optional[str] = None) -> bool:
    try:
        result = subprocess.run(
            build_adb_command([
                "shell",
                "monkey",
                "-p",
                PACKAGE_NAME,
                "-c",
                "android.intent.category.LAUNCHER",
                "1"
            ], device_id),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10
        )

        if result.returncode != 0:
            print(result.stderr.decode(errors="ignore"))
            return False

        print("Game launched")
        return True

    except Exception as error:
        print(f"Launch game error: {error}")
        return False


def ensure_game_open(
    device_id: Optional[str] = None,
    startup_wait_seconds: int = 25
) -> bool:
    if is_game_foreground(device_id):
        print("Game is already open. Skip launch.")
        return True

    if is_game_process_running(device_id):
        print("Game is running in background. Bring it to foreground...")
        if not launch_game(device_id):
            return False

        time.sleep(3)
        return True

    print("Game is not running. Opening game...")
    if not launch_game(device_id):
        return False

    print(f"Waiting game startup for {startup_wait_seconds}s...")
    time.sleep(startup_wait_seconds)
    return True


def restart_game(device_id: Optional[str] = None, startup_wait_seconds: int = 25) -> bool:
    print("\nRestart game")

    if not force_stop_game(device_id):
        print("Failed to force stop game")
        return False

    time.sleep(3)

    if not launch_game(device_id):
        print("Failed to launch game")
        return False

    print(f"Waiting game startup for {startup_wait_seconds}s...")
    time.sleep(startup_wait_seconds)

    return True


def connect_uiautomator2(device_id: Optional[str] = None):
    try:
        return u2.connect(device_id) if device_id else u2.connect()
    except Exception as error:
        print(f"uiautomator2 connect error: {error}")
        return None


def wait_until_base_found(
    bot: AdbImageBot,
    config: dict,
    stop_event: Optional[threading.Event] = None
) -> bool:
    return bot.wait_until_image_exists(
        template_path=template_path(config, "next_button"),
        threshold=template_threshold(config, "next_button"),
        interval_seconds=2,
        timeout_seconds=90,
        stop_event=stop_event
    )


def adjust_base_view(device_id: Optional[str] = None) -> bool:
    try:
        device = connect_uiautomator2(device_id)
        if device is None:
            return False

        width, height = device.window_size()

        start_x = int(width * 0.50)
        start_y = int(height * 0.82)

        end_x = int(width * 0.50)
        end_y = int(height * 0.30)

        print(
            f"Adjust base view swipe "
            f"from ({start_x}, {start_y}) "
            f"to ({end_x}, {end_y})"
        )

        device.swipe(
            start_x,
            start_y,
            end_x,
            end_y,
            duration=0.25
        )

        time.sleep(1)
        return True

    except Exception as error:
        print(f"Adjust base view error: {error}")
        return False


def zoom_out_home_view(device_id: Optional[str] = None) -> bool:
    try:
        device = connect_uiautomator2(device_id)
        if device is None:
            return False

        width, height = device.window_size()
        print("Zoom out before tapping Attack")

        if hasattr(device, "pinch_in"):
            device.pinch_in(percent=80, steps=12)
            time.sleep(1)
            return True

        print("uiautomator2 pinch_in is not available on this device")
        print(f"Screen size detected: {width}x{height}")
        return False

    except Exception as error:
        print(f"Zoom out error: {error}")
        return False


def select_troop(
    bot: AdbImageBot,
    config: dict,
    troop_slot: Optional[dict] = None,
    stop_event: Optional[threading.Event] = None
) -> bool:
    if troop_slot is None:
        troop_slot = TROOP_SLOTS[0]

    return bot.wait_and_tap_image(
        template_path=template_path(config, troop_slot["button_key"]),
        threshold=template_threshold(config, troop_slot["button_key"]),
        interval_seconds=2,
        timeout_seconds=30,
        stop_event=stop_event
    )


def is_troop_empty(
    bot: AdbImageBot,
    config: dict,
    troop_slot: Optional[dict] = None
) -> bool:
    if troop_slot is None:
        troop_slot = TROOP_SLOTS[0]

    return bot.find_image(
        template_path=template_path(config, troop_slot["empty_key"]),
        threshold=template_threshold(config, troop_slot["empty_key"])
    ) is not None


def hold_two_points_alternating(
    device,
    left_x: int,
    left_y: int,
    right_x: int,
    right_y: int,
    total_seconds: float = 10,
    hold_each_seconds: float = 2
) -> None:
    end_time = time.time() + total_seconds

    while time.time() < end_time:
        device.swipe(
            left_x,
            left_y,
            left_x,
            left_y,
            duration=hold_each_seconds
        )

        device.swipe(
            right_x,
            right_y,
            right_x,
            right_y,
            duration=hold_each_seconds
        )


def deploy_at_two_corner_points_until_empty(
    bot: AdbImageBot,
    device_id: Optional[str] = None,
    config: Optional[dict] = None,
    troop_slot: Optional[dict] = None,
    stop_event: Optional[threading.Event] = None
) -> bool:
    if config is None:
        config = default_config()

    if troop_slot is None:
        troop_slot = TROOP_SLOTS[0]

    device = connect_uiautomator2(device_id)
    if device is None:
        return False

    width, height = device.window_size()

    deploy_pairs = [
        {
            "name": "wide corner points",
            "left": (0.27, 0.42),
            "right": (0.74, 0.42),
        },
        {
            "name": "closer to village corners",
            "left": (0.31, 0.39),
            "right": (0.70, 0.39),
        },
        {
            "name": "inner corner points",
            "left": (0.35, 0.36),
            "right": (0.66, 0.36),
        },
        {
            "name": "lower wide corner points",
            "left": (0.27, 0.48),
            "right": (0.74, 0.48),
        },
        {
            "name": "lower inner corner points",
            "left": (0.34, 0.46),
            "right": (0.67, 0.46),
        },
    ]

    retry_delay_seconds = 0.5

    for pair in deploy_pairs:
        if stop_event and stop_event.is_set():
            print("Stopped before next deploy pair")
            return False

        if is_troop_empty(bot, config, troop_slot):
            print(f"{troop_slot['name']} is empty before next deploy pair")
            return True

        left_x = int(width * pair["left"][0])
        left_y = int(height * pair["left"][1])
        right_x = int(width * pair["right"][0])
        right_y = int(height * pair["right"][1])

        print(
            f"Deploy at {pair['name']}: "
            f"left=({left_x}, {left_y}), right=({right_x}, {right_y})"
        )

        hold_two_points_alternating(
            device=device,
            left_x=left_x,
            left_y=left_y,
            right_x=right_x,
            right_y=right_y,
            total_seconds=10,
            hold_each_seconds=1
        )

        time.sleep(retry_delay_seconds)

        if is_troop_empty(bot, config, troop_slot):
            print(f"{troop_slot['name']} is empty")
            return True

    print(f"{troop_slot['name']} is not empty after all deploy pairs")
    return False


def wait_and_return_home(
    bot: AdbImageBot,
    config: dict,
    stop_event: Optional[threading.Event] = None
) -> bool:
    print("Waiting for Return Home button...")

    success = bot.wait_and_tap_image(
        template_path=template_path(config, "return_home"),
        threshold=template_threshold(config, "return_home"),
        interval_seconds=5,
        timeout_seconds=300,
        stop_event=stop_event
    )

    if not success:
        print("Return Home button not found")
        return False

    print("Returned Home")
    time.sleep(5)

    return True


def run_single_farm_round(
    device_id: Optional[str] = None,
    config: Optional[dict] = None,
    stop_event: Optional[threading.Event] = None
) -> bool:
    if config is None:
        config = default_config()

    bot = AdbImageBot(device_id=device_id)

    if stop_event and stop_event.is_set():
        print("Stopped before zoom out")
        return False

    print("\nStep 0 - Zoom out home view")
    if not zoom_out_home_view(device_id=device_id):
        print("Zoom out skipped or failed. Continue farming.")

    steps = [
        {
            "name": "Step 1 - Tap Attack on home screen",
            "template_key": "attack_home",
            "delay_after": 3
        },
        {
            "name": "Step 2 - Tap Find a Match",
            "template_key": "find_match",
            "delay_after": 3
        },
        {
            "name": "Step 3 - Tap Attack on army screen",
            "template_key": "attack_army",
            "delay_after": 5
        }
    ]

    for step in steps:
        if stop_event and stop_event.is_set():
            print("Stopped before next step")
            return False

        print(f"\n{step['name']}")

        success = bot.wait_and_tap_image(
            template_path=template_path(config, step["template_key"]),
            threshold=template_threshold(config, step["template_key"]),
            interval_seconds=5,
            timeout_seconds=60,
            stop_event=stop_event
        )

        if not success:
            print(f"Failed: {step['name']}")
            return False

        time.sleep(step["delay_after"])

    print("\nStep 4 - Wait until base found")
    if not wait_until_base_found(bot, config, stop_event=stop_event):
        print("Base not found")
        return False

    print("Base found")

    print("\nStep 5 - Adjust base view")
    if not adjust_base_view(device_id=device_id):
        print("Failed to adjust base view")
        return False

    print("Base view adjusted")

    for troop_index, troop_slot in enumerate(TROOP_SLOTS, start=1):
        if stop_event and stop_event.is_set():
            print("Stopped before next troop")
            return False

        print(f"\nStep 6.{troop_index} - Select {troop_slot['name']}")
        if not select_troop(bot, config, troop_slot, stop_event=stop_event):
            print(f"Failed to select {troop_slot['name']}")
            return False

        print(f"{troop_slot['name']} selected")

        print(f"\nStep 7.{troop_index} - Deploy {troop_slot['name']} at two corner points")
        if not deploy_at_two_corner_points_until_empty(
            bot,
            device_id=device_id,
            config=config,
            troop_slot=troop_slot,
            stop_event=stop_event
        ):
            print(f"Failed to deploy all {troop_slot['name']}")
            return False

        print(f"{troop_slot['name']} deployed completely")

    print("\nStep 8 - Wait and Return Home")
    if not wait_and_return_home(bot, config, stop_event=stop_event):
        print("Failed to return home")
        return False

    print("Back to home screen")
    return True


def run_farm_loop(
    device_id: Optional[str] = None,
    max_rounds: Optional[int] = None,
    delay_between_rounds_seconds: int = 10,
    restart_wait_seconds: int = 25,
    config: Optional[dict] = None,
    stop_event: Optional[threading.Event] = None
) -> None:
    if config is None:
        config = default_config()

    round_index = 1

    while True:
        if stop_event and stop_event.is_set():
            print("Stop requested. Stop farming.")
            break

        if max_rounds is not None and round_index > max_rounds:
            print("Reached max rounds. Stop farming.")
            break

        print("\n" + "=" * 60)
        print(f"Start farm round {round_index}")
        print("=" * 60)

        try:
            success = run_single_farm_round(
                device_id=device_id,
                config=config,
                stop_event=stop_event
            )
        except Exception as error:
            print(f"Unexpected round error: {error}")
            success = False

        if stop_event and stop_event.is_set():
            print("Stop requested. Do not restart game.")
            break

        if success:
            print(f"Farm round {round_index} completed")
            time.sleep(delay_between_rounds_seconds)
            round_index += 1
            continue

        print(f"Farm round {round_index} failed")
        print("Restarting game and retrying same round...")

        if not restart_game(
            device_id=device_id,
            startup_wait_seconds=restart_wait_seconds
        ):
            print("Restart game failed. Wait and retry restart...")
            time.sleep(10)
            continue

        time.sleep(3)


class QueueWriter:
    def __init__(self, output_queue: queue.Queue):
        self.output_queue = output_queue

    def write(self, text: str) -> None:
        if text:
            self.output_queue.put(text)

    def flush(self) -> None:
        pass


class CropWindow:
    def __init__(
        self,
        parent: tk.Tk,
        image_path: str,
        template_key: str,
        on_save
    ):
        self.parent = parent
        self.image_path = Path(image_path)
        self.template_key = template_key
        self.on_save = on_save
        self.image = Image.open(self.image_path).convert("RGB")
        self.original_width, self.original_height = self.image.size
        self.scale = min(900 / self.original_width, 520 / self.original_height, 1.0)
        self.display_width = max(1, int(self.original_width * self.scale))
        self.display_height = max(1, int(self.original_height * self.scale))
        self.display_image = self.image.resize(
            (self.display_width, self.display_height),
            Image.Resampling.LANCZOS
        )
        self.photo = ImageTk.PhotoImage(self.display_image)
        self.start_x = 0
        self.start_y = 0
        self.rect_id: Optional[int] = None

        self.window = tk.Toplevel(parent)
        self.window.title(f"Crop - {TEMPLATE_FIELDS[template_key]['label']}")
        self.window.transient(parent)
        self.window.grab_set()

        self.x_var = tk.IntVar(value=0)
        self.y_var = tk.IntVar(value=0)
        self.width_var = tk.IntVar(value=self.original_width)
        self.height_var = tk.IntVar(value=self.original_height)

        self._build_ui()
        self._draw_rect_from_vars()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.window, padding=10)
        container.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(
            container,
            width=self.display_width,
            height=self.display_height,
            cursor="crosshair",
            highlightthickness=1,
            highlightbackground="#999999"
        )
        self.canvas.grid(row=0, column=0, columnspan=8, sticky=tk.NSEW)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)

        ttk.Label(container, text="x").grid(row=1, column=0, sticky=tk.W, pady=(10, 0))
        ttk.Spinbox(
            container,
            from_=0,
            to=self.original_width - 1,
            textvariable=self.x_var,
            width=8,
            command=self._draw_rect_from_vars
        ).grid(row=1, column=1, sticky=tk.W, pady=(10, 0))

        ttk.Label(container, text="y").grid(row=1, column=2, sticky=tk.W, pady=(10, 0))
        ttk.Spinbox(
            container,
            from_=0,
            to=self.original_height - 1,
            textvariable=self.y_var,
            width=8,
            command=self._draw_rect_from_vars
        ).grid(row=1, column=3, sticky=tk.W, pady=(10, 0))

        ttk.Label(container, text="width").grid(row=1, column=4, sticky=tk.W, pady=(10, 0))
        ttk.Spinbox(
            container,
            from_=1,
            to=self.original_width,
            textvariable=self.width_var,
            width=8,
            command=self._draw_rect_from_vars
        ).grid(row=1, column=5, sticky=tk.W, pady=(10, 0))

        ttk.Label(container, text="height").grid(row=1, column=6, sticky=tk.W, pady=(10, 0))
        ttk.Spinbox(
            container,
            from_=1,
            to=self.original_height,
            textvariable=self.height_var,
            width=8,
            command=self._draw_rect_from_vars
        ).grid(row=1, column=7, sticky=tk.W, pady=(10, 0))

        for variable in (self.x_var, self.y_var, self.width_var, self.height_var):
            variable.trace_add("write", lambda *_: self._draw_rect_from_vars())

        buttons = ttk.Frame(container)
        buttons.grid(row=2, column=0, columnspan=8, sticky=tk.E, pady=(10, 0))
        ttk.Button(buttons, text="Save Crop", command=self._save_crop).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Cancel", command=self.window.destroy).pack(
            side=tk.LEFT,
            padx=(8, 0)
        )

    def _on_mouse_down(self, event) -> None:
        self.start_x = self._clamp_display_x(event.x)
        self.start_y = self._clamp_display_y(event.y)
        self._update_canvas_rect(self.start_x, self.start_y, self.start_x, self.start_y)

    def _on_mouse_drag(self, event) -> None:
        current_x = self._clamp_display_x(event.x)
        current_y = self._clamp_display_y(event.y)
        self._update_canvas_rect(self.start_x, self.start_y, current_x, current_y)

    def _on_mouse_up(self, event) -> None:
        end_x = self._clamp_display_x(event.x)
        end_y = self._clamp_display_y(event.y)
        left = min(self.start_x, end_x)
        top = min(self.start_y, end_y)
        right = max(self.start_x, end_x)
        bottom = max(self.start_y, end_y)

        x = int(round(left / self.scale))
        y = int(round(top / self.scale))
        width = max(1, int(round((right - left) / self.scale)))
        height = max(1, int(round((bottom - top) / self.scale)))
        self._set_crop_values(x, y, width, height)

    def _clamp_display_x(self, value: int) -> int:
        return max(0, min(value, self.display_width))

    def _clamp_display_y(self, value: int) -> int:
        return max(0, min(value, self.display_height))

    def _set_crop_values(self, x: int, y: int, width: int, height: int) -> None:
        x = max(0, min(x, self.original_width - 1))
        y = max(0, min(y, self.original_height - 1))
        width = max(1, min(width, self.original_width - x))
        height = max(1, min(height, self.original_height - y))
        self.x_var.set(x)
        self.y_var.set(y)
        self.width_var.set(width)
        self.height_var.set(height)
        self._draw_rect_from_vars()

    def _draw_rect_from_vars(self) -> None:
        try:
            x = int(self.x_var.get())
            y = int(self.y_var.get())
            width = int(self.width_var.get())
            height = int(self.height_var.get())
        except (tk.TclError, ValueError):
            return

        x = max(0, min(x, self.original_width - 1))
        y = max(0, min(y, self.original_height - 1))
        width = max(1, min(width, self.original_width - x))
        height = max(1, min(height, self.original_height - y))

        left = int(round(x * self.scale))
        top = int(round(y * self.scale))
        right = int(round((x + width) * self.scale))
        bottom = int(round((y + height) * self.scale))
        self._update_canvas_rect(left, top, right, bottom)

    def _update_canvas_rect(self, left: int, top: int, right: int, bottom: int) -> None:
        if self.rect_id is None:
            self.rect_id = self.canvas.create_rectangle(
                left,
                top,
                right,
                bottom,
                outline="#00a2ff",
                width=2
            )
        else:
            self.canvas.coords(self.rect_id, left, top, right, bottom)

    def _save_crop(self) -> None:
        try:
            x = int(self.x_var.get())
            y = int(self.y_var.get())
            width = int(self.width_var.get())
            height = int(self.height_var.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("Invalid crop", "Crop values must be numbers.")
            return

        if width <= 0 or height <= 0:
            messagebox.showerror("Invalid crop", "Width and height must be greater than 0.")
            return

        right = min(self.original_width, x + width)
        bottom = min(self.original_height, y + height)
        if x < 0 or y < 0 or x >= right or y >= bottom:
            messagebox.showerror("Invalid crop", "Crop area is outside the image.")
            return

        CUSTOM_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        output_path = CUSTOM_TEMPLATE_DIR / f"{self.template_key}_{timestamp}.png"
        cropped = self.image.crop((x, y, right, bottom))
        cropped.save(output_path)
        self.on_save(str(output_path))
        self.window.destroy()


class FarmBotApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("COC Farm Bot")
        self.root.geometry("1180x720")

        self.config = load_config()
        self.path_vars: dict[str, tk.StringVar] = {}
        self.threshold_vars: dict[str, tk.DoubleVar] = {}
        self.log_queue: queue.Queue = queue.Queue()
        self.worker_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.connected_devices: list[str] = []
        self.other_devices: list[tuple[str, str]] = []
        self.device_info_by_id: dict[str, dict] = {}
        self.device_id_by_label: dict[str, str] = {}
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr

        self.device_var = tk.StringVar(value=str(self.config.get("device_id", "")))
        self.device_detail_var = tk.StringVar(value="No device selected")
        self.max_rounds_var = tk.StringVar(value=str(self.config.get("max_rounds", "")))
        self.delay_var = tk.IntVar(
            value=int(self.config.get("delay_between_rounds_seconds", 10))
        )
        self.restart_wait_var = tk.IntVar(
            value=int(self.config.get("restart_wait_seconds", 25))
        )

        self._build_ui()
        self._refresh_devices(show_status=False)
        self._update_selected_device_info()
        self.status_var.set(f"ADB: {adb_executable()}")
        self._drain_log_queue()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        settings = ttk.LabelFrame(container, text="Run Settings", padding=10)
        settings.pack(fill=tk.X)

        ttk.Label(settings, text="Device ID").grid(row=0, column=0, sticky=tk.W)
        self.device_combo = ttk.Combobox(
            settings,
            textvariable=self.device_var,
            width=58,
            values=[]
        )
        self.device_combo.grid(
            row=0,
            column=1,
            sticky=tk.EW,
            padx=(8, 8)
        )
        self.device_combo.bind("<<ComboboxSelected>>", self._on_device_selected)
        self.device_combo.bind("<KeyRelease>", self._on_device_selected)
        self.device_combo.bind("<FocusOut>", self._on_device_selected)
        ttk.Button(
            settings,
            text="Refresh",
            command=self._refresh_devices
        ).grid(
            row=0,
            column=2,
            sticky=tk.W,
            padx=(0, 18)
        )

        ttk.Label(settings, text="Max rounds").grid(row=0, column=3, sticky=tk.W)
        ttk.Entry(settings, textvariable=self.max_rounds_var, width=10).grid(
            row=0,
            column=4,
            sticky=tk.W,
            padx=(8, 18)
        )

        ttk.Label(settings, text="Delay between rounds").grid(
            row=0,
            column=5,
            sticky=tk.W
        )
        ttk.Spinbox(
            settings,
            from_=0,
            to=3600,
            textvariable=self.delay_var,
            width=8
        ).grid(row=0, column=6, sticky=tk.W, padx=(8, 18))

        ttk.Label(settings, text="Restart wait").grid(row=0, column=7, sticky=tk.W)
        ttk.Spinbox(
            settings,
            from_=0,
            to=3600,
            textvariable=self.restart_wait_var,
            width=8
        ).grid(row=0, column=8, sticky=tk.W, padx=(8, 0))

        settings.columnconfigure(1, weight=1)

        ttk.Label(
            settings,
            textvariable=self.device_detail_var
        ).grid(
            row=1,
            column=0,
            columnspan=9,
            sticky=tk.W,
            pady=(8, 0)
        )

        templates = ttk.LabelFrame(container, text="Images and Scores", padding=10)
        templates.pack(fill=tk.X, pady=(12, 0))

        ttk.Label(templates, text="Action").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(templates, text="Image").grid(row=0, column=1, sticky=tk.W)
        ttk.Label(templates, text="Score").grid(row=0, column=4, sticky=tk.W)

        for row_index, (key, field) in enumerate(TEMPLATE_FIELDS.items(), start=1):
            template_config = self.config["templates"][key]
            path_var = tk.StringVar(value=template_config["path"])
            threshold_var = tk.DoubleVar(value=float(template_config["threshold"]))
            self.path_vars[key] = path_var
            self.threshold_vars[key] = threshold_var

            ttk.Label(templates, text=field["label"]).grid(
                row=row_index,
                column=0,
                sticky=tk.W,
                pady=4
            )
            ttk.Entry(templates, textvariable=path_var).grid(
                row=row_index,
                column=1,
                sticky=tk.EW,
                padx=(8, 8),
                pady=4
            )
            ttk.Button(
                templates,
                text="Browse",
                command=lambda selected_key=key: self._browse_image(selected_key)
            ).grid(row=row_index, column=2, sticky=tk.W, pady=4)
            ttk.Button(
                templates,
                text="Crop",
                command=lambda selected_key=key: self._open_crop_window(selected_key)
            ).grid(row=row_index, column=3, sticky=tk.W, padx=(8, 0), pady=4)
            ttk.Spinbox(
                templates,
                from_=0.01,
                to=1.00,
                increment=0.01,
                textvariable=threshold_var,
                width=7,
                format="%.2f"
            ).grid(row=row_index, column=4, sticky=tk.W, padx=(8, 0), pady=4)

        templates.columnconfigure(1, weight=1)

        actions = ttk.Frame(container)
        actions.pack(fill=tk.X, pady=(12, 0))

        self.start_button = ttk.Button(
            actions,
            text="Start Farming",
            command=self._start_farming
        )
        self.start_button.pack(side=tk.LEFT)

        self.stop_button = ttk.Button(
            actions,
            text="Stop",
            command=self._stop_farming,
            state=tk.DISABLED
        )
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(actions, text="Save Config", command=self._save_config).pack(
            side=tk.LEFT,
            padx=(8, 0)
        )

        ttk.Button(actions, text="Load Config", command=self._load_config_into_ui).pack(
            side=tk.LEFT,
            padx=(8, 0)
        )

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(actions, textvariable=self.status_var).pack(side=tk.RIGHT)

        log_frame = ttk.LabelFrame(container, text="Log", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        self.log_text = ScrolledText(log_frame, height=18, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _browse_image(self, key: str) -> None:
        file_path = filedialog.askopenfilename(
            title="Select template image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.bmp"),
                ("All files", "*.*"),
            ]
        )

        if file_path:
            self.path_vars[key].set(file_path)

    def _refresh_devices(self, show_status: bool = True) -> None:
        devices, other_devices = list_adb_devices()
        self.connected_devices = devices
        self.other_devices = other_devices
        self.device_info_by_id = {
            device_id: get_adb_device_info(device_id)
            for device_id in devices
        }
        self.device_id_by_label = {
            format_device_label(info): device_id
            for device_id, info in self.device_info_by_id.items()
        }

        current_device = self._selected_device_id()
        labels = list(self.device_id_by_label.keys())

        self.device_combo.configure(values=labels)

        if current_device and current_device in devices:
            self.device_var.set(format_device_label(self.device_info_by_id[current_device]))
        elif not current_device and len(devices) == 1:
            self.device_var.set(format_device_label(self.device_info_by_id[devices[0]]))
        elif current_device and current_device not in devices:
            self.device_var.set(current_device)
            if show_status:
                self.status_var.set("Saved device is not connected")
        elif devices:
            self.device_var.set(format_device_label(self.device_info_by_id[devices[0]]))

        self._update_selected_device_info()

        if not show_status:
            return

        if devices:
            self.status_var.set(f"Found {len(devices)} device(s)")
        elif other_devices:
            statuses = ", ".join(f"{device}:{status}" for device, status in other_devices)
            self.status_var.set(f"No ready device. {statuses}")
        else:
            self.status_var.set("No ADB devices found")

    def _selected_device_id(self) -> str:
        value = self.device_var.get().strip()
        return self.device_id_by_label.get(value, value)

    def _on_device_selected(self, _event=None) -> None:
        self._update_selected_device_info()

    def _update_selected_device_info(self) -> None:
        device_id = self._selected_device_id()

        if not device_id:
            self.device_detail_var.set("Selected device: none")
            return

        info = self.device_info_by_id.get(device_id)
        if not info:
            self.device_detail_var.set(f"Selected device: {device_id} | not connected or manual input")
            return

        self.device_detail_var.set(
            "Selected device: "
            f"ID {info['id']} | "
            f"{info['manufacturer']} {info['model']} | "
            f"Android {info['android']} | "
            f"Screen {info['screen']} | "
            f"Status {info['status']}"
        )

    def _open_crop_window(self, key: str) -> None:
        image_path = self.path_vars[key].get().strip()

        if not image_path:
            messagebox.showerror("Missing image", "Select an image before cropping.")
            return

        resolved_image_path = resolve_app_path(image_path)
        if not resolved_image_path.exists():
            messagebox.showerror("Missing image", f"Image not found:\n{image_path}")
            return

        try:
            CropWindow(
                parent=self.root,
                image_path=str(resolved_image_path),
                template_key=key,
                on_save=lambda cropped_path: self._set_cropped_image(key, cropped_path)
            )
        except Exception as error:
            messagebox.showerror("Cannot open image", str(error))

    def _set_cropped_image(self, key: str, cropped_path: str) -> None:
        self.path_vars[key].set(cropped_path)
        self.status_var.set(f"Saved crop: {cropped_path}")

    def _build_config_from_ui(self) -> dict:
        config = default_config()
        config["device_id"] = self._selected_device_id()
        config["max_rounds"] = self.max_rounds_var.get().strip()
        config["delay_between_rounds_seconds"] = int(self.delay_var.get())
        config["restart_wait_seconds"] = int(self.restart_wait_var.get())

        if not config["device_id"] and len(self.connected_devices) > 1:
            raise ValueError("Multiple devices connected. Select one Device ID.")

        for key in TEMPLATE_FIELDS:
            threshold = float(self.threshold_vars[key].get())
            if threshold <= 0 or threshold > 1:
                raise ValueError(f"Score for {TEMPLATE_FIELDS[key]['label']} must be 0-1")

            config["templates"][key] = {
                "path": self.path_vars[key].get().strip(),
                "threshold": threshold,
            }

            if not config["templates"][key]["path"]:
                raise ValueError(f"Image is empty: {TEMPLATE_FIELDS[key]['label']}")

        return config

    def _save_config(self) -> None:
        try:
            config = self._build_config_from_ui()
            save_config(config)
            self.config = config
            self.status_var.set(f"Saved {CONFIG_PATH}")
        except Exception as error:
            messagebox.showerror("Invalid config", str(error))

    def _load_config_into_ui(self) -> None:
        self.config = load_config()
        self.device_var.set(str(self.config.get("device_id", "")))
        self.max_rounds_var.set(str(self.config.get("max_rounds", "")))
        self.delay_var.set(int(self.config.get("delay_between_rounds_seconds", 10)))
        self.restart_wait_var.set(int(self.config.get("restart_wait_seconds", 25)))

        for key in TEMPLATE_FIELDS:
            self.path_vars[key].set(self.config["templates"][key]["path"])
            self.threshold_vars[key].set(
                float(self.config["templates"][key]["threshold"])
            )

        self._refresh_devices(show_status=False)
        self.status_var.set(f"Loaded {CONFIG_PATH}")

    def _start_farming(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Already running", "Farm bot is already running.")
            return

        try:
            config = self._build_config_from_ui()
            save_config(config)
        except Exception as error:
            messagebox.showerror("Invalid config", str(error))
            return

        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.stop_event.clear()
        self.status_var.set("Running")

        self.worker_thread = threading.Thread(
            target=self._run_worker,
            args=(config,),
            daemon=True
        )
        self.worker_thread.start()

    def _run_worker(self, config: dict) -> None:
        sys.stdout = QueueWriter(self.log_queue)
        sys.stderr = QueueWriter(self.log_queue)

        try:
            device_id = config.get("device_id") or None
            max_rounds_text = str(config.get("max_rounds", "")).strip()
            max_rounds = int(max_rounds_text) if max_rounds_text else None
            startup_wait_seconds = int(config.get("restart_wait_seconds", 25))

            print("Checking game before first farm round...")
            if not ensure_game_open(
                device_id=device_id,
                startup_wait_seconds=startup_wait_seconds
            ):
                print("Failed to open game. Stop farming.")
                return

            run_farm_loop(
                device_id=device_id,
                max_rounds=max_rounds,
                delay_between_rounds_seconds=int(
                    config.get("delay_between_rounds_seconds", 10)
                ),
                restart_wait_seconds=startup_wait_seconds,
                config=config,
                stop_event=self.stop_event
            )
        except Exception as error:
            print(f"Farm worker error: {error}")
        finally:
            sys.stdout = self.original_stdout
            sys.stderr = self.original_stderr
            self.log_queue.put("\nFarm worker stopped.\n")
            self.root.after(0, self._worker_finished)

    def _worker_finished(self) -> None:
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self.status_var.set("Stopped")

    def _stop_farming(self) -> None:
        self.stop_event.set()
        self.status_var.set("Stopping")
        self.log_queue.put("\nStop requested. Waiting for current action to finish...\n")

    def _drain_log_queue(self) -> None:
        while True:
            try:
                text = self.log_queue.get_nowait()
            except queue.Empty:
                break

            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, text)
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)

        self.root.after(100, self._drain_log_queue)


def launch_gui() -> None:
    root = tk.Tk()
    FarmBotApp(root)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
