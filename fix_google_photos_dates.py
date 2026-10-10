#!/usr/bin/env python3
"""
Google Photos Takeout Date Fixer (cross-platform, coloured output)

Reads the "<file>.supplemental-metadata.json" that Google Takeout places
next to each photo/video, sets the file's dates to the original photo date,
and then deletes the JSON file that was used.

Works on Windows, macOS and Linux.

Usage:
    python fix_google_photos_dates.py "/path/to/Takeout/Google Photos"
    python fix_google_photos_dates.py "/path/to/folder" --keep-json
    python fix_google_photos_dates.py "/path/to/folder" --no-color

If no folder is given, the script asks for one.
Colours are turned off automatically when output is piped to a file,
or when the NO_COLOR environment variable is set.
"""

import os
import sys
import json
import shutil
import argparse
import platform
import subprocess
from datetime import datetime, timezone


# ============================================================
# OPTIONAL: set a default folder here (or pass it on the
# command line / type it when asked)
# ============================================================

DEFAULT_FOLDER = ""

JSON_SUFFIX = ".supplemental-metadata.json"
SYSTEM = platform.system()  # "Windows", "Darwin" (macOS) or "Linux"


# ============================================================
# COLOURS (ANSI escape codes)
# ============================================================

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"


USE_COLOR = False


def setup_colors(disable=False):
    """Turn colours on only when the terminal can show them."""
    global USE_COLOR

    if disable or os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        USE_COLOR = False
        return

    if SYSTEM == "Windows":
        # Enables ANSI escape sequence support in Windows 10+ terminals
        os.system("")

    USE_COLOR = True


def paint(text, *styles):
    """Wrap text in colour codes (or return it unchanged if colours are off)."""
    if not USE_COLOR or not styles:
        return text
    return "".join(styles) + text + C.RESET


# ============================================================
# WINDOWS: set Created / Accessed / Modified via the Windows API
# ============================================================

if SYSTEM == "Windows":

    import ctypes
    from ctypes import wintypes

    FILE_WRITE_ATTRIBUTES = 0x100
    FILE_SHARE_READ = 0x1
    FILE_SHARE_WRITE = 0x2
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE

    kernel32.SetFileTime.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
    ]
    kernel32.SetFileTime.restype = wintypes.BOOL

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    def set_creation_time_windows(file_path, timestamp):
        handle = kernel32.CreateFileW(
            file_path,
            FILE_WRITE_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None,
        )

        if handle is None or handle == INVALID_HANDLE_VALUE:
            raise OSError("Could not open file for Windows timestamp update")

        try:
            value = int((timestamp + 11644473600) * 10000000)
            ft = FILETIME(value & 0xFFFFFFFF, (value >> 32) & 0xFFFFFFFF)

            ok = kernel32.SetFileTime(
                handle,
                ctypes.byref(ft),   # creation
                ctypes.byref(ft),   # last access
                ctypes.byref(ft),   # last write
            )

            if not ok:
                raise OSError("Windows SetFileTime failed")
        finally:
            kernel32.CloseHandle(handle)


# ============================================================
# SET FILE DATES (any platform)
# ============================================================

def set_file_dates(file_path, date):
    """
    Windows : Created + Modified + Accessed
    macOS   : Modified + Accessed (+ Created via SetFile if available;
              macOS also lowers the creation date automatically when
              the modified date is set to an earlier time)
    Linux   : Modified + Accessed (Linux has no settable creation date)
    """

    timestamp = date.timestamp()

    # Modified + Accessed (works everywhere)
    os.utime(file_path, (timestamp, timestamp))

    if SYSTEM == "Windows":
        set_creation_time_windows(file_path, timestamp)

    elif SYSTEM == "Darwin":
        # SetFile is part of the Xcode command line tools and may be missing.
        # Without it, macOS usually still lowers the creation date to match
        # the earlier modified date set above (main() prints a one-time note).
        setfile = shutil.which("SetFile")
        if setfile:
            subprocess.run(
                [setfile, "-d", date.strftime("%m/%d/%Y %H:%M:%S"), file_path],
                check=True,
                capture_output=True,
            )


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description="Restore original photo dates from Google Takeout metadata."
    )
    parser.add_argument(
        "folder",
        nargs="?",
        help="Folder containing the Takeout photos (searched recursively)",
    )
    parser.add_argument(
        "--keep-json",
        action="store_true",
        help="Do not delete the JSON files after setting the dates",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Turn off coloured output",
    )
    args = parser.parse_args()

    setup_colors(disable=args.no_color)

    interactive = args.folder is None and not DEFAULT_FOLDER

    folder = args.folder or DEFAULT_FOLDER
    if not folder:
        folder = input(
            paint("Enter the Takeout folder path: ", C.BOLD, C.CYAN)
        ).strip().strip('"').strip("'")

    def pause():
        if interactive:
            input(paint("Press ENTER to close...", C.DIM))

    if not os.path.isdir(folder):
        print()
        print(paint("ERROR: Folder does not exist!", C.BOLD, C.RED))
        print()
        print("Check this path:")
        print(paint(folder, C.YELLOW))
        print()
        pause()
        sys.exit(1)

    processed = 0
    json_not_found = 0
    no_timestamp = 0
    errors = 0
    json_deleted = 0
    json_delete_failed = 0

    bar = "=" * 60

    print()
    print(paint(bar, C.CYAN))
    print(paint("       GOOGLE PHOTOS TAKEOUT DATE FIXER", C.BOLD, C.CYAN))
    print(paint(bar, C.CYAN))
    print()
    print(paint("Folder:", C.BOLD))
    print(paint(folder, C.YELLOW))
    print()
    print(f"{paint('Platform:', C.BOLD)} {SYSTEM}")
    if SYSTEM == "Darwin" and not shutil.which("SetFile"):
        print(paint("NOTE: 'SetFile' not found, so the creation date is not set", C.YELLOW))
        print(paint("      explicitly. macOS usually still lowers it to match the", C.YELLOW))
        print(paint("      modified date. To set it explicitly, run:", C.YELLOW))
        print(paint("      xcode-select --install", C.YELLOW))
    print(paint("Dates come from UTC timestamps in the metadata; the 'local'", C.DIM))
    print(paint("time shown below depends on this computer's time zone.", C.DIM))
    print("Searching for Google Photos metadata...")
    print()

    for root, dirs, files in os.walk(folder):

        for filename in files:

            # Ignore JSON files
            if filename.lower().endswith(".json"):
                continue

            media_path = os.path.join(root, filename)
            json_path = media_path + JSON_SUFFIX

            print(f"{paint('Checking:', C.BLUE)} {filename}")

            if not os.path.isfile(json_path):
                json_not_found += 1
                print(paint("  -> JSON NOT FOUND", C.YELLOW))
                print()
                continue

            try:

                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # First preference: photoTakenTime
                timestamp = data.get("photoTakenTime", {}).get("timestamp")
                timestamp_source = "photoTakenTime"

                # Fallback: creationTime
                if not timestamp:
                    timestamp = data.get("creationTime", {}).get("timestamp")
                    timestamp_source = "creationTime"

                if not timestamp:
                    no_timestamp += 1
                    print(paint("  -> NO PHOTO DATE FOUND", C.YELLOW))
                    print()
                    continue

                date = datetime.fromtimestamp(int(timestamp))

                set_file_dates(media_path, date)

                processed += 1

                utc_date = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)

                print(
                    paint("  -> DATE SET: ", C.GREEN)
                    + paint(f"{date}", C.BOLD, C.GREEN)
                    + paint(f" (local)  |  {utc_date:%Y-%m-%d %H:%M:%S} UTC", C.DIM)
                )
                print(paint(f"  -> SOURCE: {timestamp_source}", C.MAGENTA))

                # Delete the JSON only after the date was set successfully
                if not args.keep_json:
                    try:
                        os.remove(json_path)
                        json_deleted += 1
                        print(paint("  -> JSON DELETED", C.CYAN))
                    except Exception as e:
                        json_delete_failed += 1
                        print(paint(f"  -> WARNING: Could not delete JSON: {e}", C.YELLOW))

                print()

            except json.JSONDecodeError:
                errors += 1
                print(paint("  -> ERROR: Invalid JSON", C.RED))
                print()

            except PermissionError:
                errors += 1
                print(paint("  -> ERROR: Permission denied", C.RED))
                print()

            except Exception as e:
                errors += 1
                print(paint(f"  -> ERROR: {e}", C.RED))
                print()

    def stat(label, value, good_color=None):
        """One line of the final report; numbers coloured by meaning."""
        if value == 0:
            color = C.DIM if good_color is None else C.GREEN
        else:
            color = good_color or C.DIM
        return f"{label:<29}: {paint(str(value), C.BOLD, color)}"

    print()
    print(paint(bar, C.CYAN))
    print(paint("                    FINISHED", C.BOLD, C.CYAN))
    print(paint(bar, C.CYAN))
    print()
    print(stat("Files successfully processed", processed, C.GREEN))
    print(stat("JSON not found", json_not_found, C.YELLOW))
    print(stat("No timestamp found", no_timestamp, C.YELLOW))
    print(stat("Errors", errors, C.RED))
    print(stat("JSON files deleted", json_deleted, C.CYAN))
    print(stat("JSON delete failed", json_delete_failed, C.RED))
    print()
    print(paint(bar, C.CYAN))
    print()
    print(paint("Important:", C.BOLD, C.YELLOW))
    print("The script changed file timestamps only.")
    print("It did NOT modify or delete your photos.")
    if args.keep_json:
        print("JSON files were kept (--keep-json).")
    else:
        print("It deleted a JSON file only after its date was set.")
        print("JSON files that were not used were left untouched.")
    if SYSTEM == "Linux":
        print("Note: Linux has no settable 'created' date; modified/accessed were set.")
    print()

    pause()


if __name__ == "__main__":
    main()
