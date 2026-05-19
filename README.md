# COC Farm Bot

GUI tool for automating a Clash of Clans farming loop on an Android device or emulator. The bot uses ADB for screen capture/tap commands, OpenCV template matching for UI detection, and uiautomator2 for swipe/deploy gestures.

## Features

- Select an ADB device from the GUI when multiple devices are connected.
- Show device details such as manufacturer, model, Android version, and screen size.
- Configure template images and matching scores without editing code.
- Crop template images directly from the GUI.
- Save and load settings from `farm_config.json`.
- Automatically open Clash of Clans before farming if it is not already open.
- Stop the bot without force-stopping or restarting the game.

## Project Structure

```text
.
├── main_farm_loop.py       # Main GUI and bot logic
├── farm_config.json        # Saved GUI configuration
├── templates/              # Default template images
│   └── custom/             # Cropped images saved from the GUI
├── requirements.txt        # Python dependencies
└── build_portable.ps1      # Optional Windows build script
```

## Requirements

- Windows
- Python 3.10+
- Android Debug Bridge (`adb`)
- Android phone or emulator with Clash of Clans installed
- USB debugging enabled on the device

Python packages:

```text
opencv-python
numpy
uiautomator2
pillow
```

## Setup

Install dependencies:

```powershell
pip install -r requirements.txt
```

Check that ADB can see your device:

```powershell
adb devices
```

The device should appear with status:

```text
device
```

If it appears as `unauthorized`, unlock the phone and allow USB debugging authorization.

Initialize uiautomator2 if needed:

```powershell
python -m uiautomator2 init
```

## Run

From the project folder:

```powershell
python .\main_farm_loop.py
```

## GUI Usage

1. Click `Refresh` to load connected ADB devices.
2. Select the target device from `Device ID`.
3. Configure:
   - `Max rounds`: leave empty to run indefinitely.
   - `Delay between rounds`: seconds to wait after a completed round.
   - `Restart wait`: seconds to wait when the game needs to open or restart.
4. For each action, choose a template image and score.
5. Use `Crop` to cut the exact UI region for better template matching.
6. Click `Save Config`.
7. Click `Start Farming`.
8. Click `Stop` to stop the bot without restarting the game.

## Template Matching

The bot finds UI elements by comparing the current screen against template images.

Lower score values are more permissive but can cause wrong taps. Higher score values are stricter but may fail if the UI differs slightly.

Typical scores:

```text
0.70 - 0.80
```

Configured templates:

- Attack button on home screen
- Find a Match button
- Attack button on army screen
- Next button / base found indicator
- Troop button
- Troop empty indicator
- Return Home button

## Notes

- The tool expects Clash of Clans package name:

```text
com.supercell.clashofclans
```

- Template images are resolution/UI dependent. If you use another phone, emulator, language, or aspect ratio, you may need to capture and crop new templates.
- `tesseract-ocr-w64-setup-5.5.0.20241111.exe` is not required by the current code.
- The current zoom-out step is optional. If uiautomator2 does not support `pinch_in` on the device, the bot logs the issue and continues.

## Optional Build

Build a Windows app folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_portable.ps1
```

Output:

```text
dist\FarmBot\FarmBot.exe
```

For portability, include ADB next to the app:

```text
dist\FarmBot\adb\
  adb.exe
  AdbWinApi.dll
  AdbWinUsbApi.dll
```

## Disclaimer

This project is for personal automation experiments. Use it responsibly and understand the risks of automating interactions with games or online services.
