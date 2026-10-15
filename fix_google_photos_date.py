#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Photos Takeout Date Fixer
================================

Google Takeout exports your photos and videos, but the original dates are
lost: every file ends up with the date of the export instead of the date the
photo was taken. The real date is stored in a separate JSON "sidecar" file
that Takeout places next to each media file.

This script:
  1. Walks through a Takeout folder (recursively).
  2. Finds the JSON sidecar that belongs to each photo/video.
  3. Reads the original "photo taken" timestamp from that JSON.
  4. Sets the file's dates (created / modified / accessed, where the
     operating system allows it) to that original date.
  5. Deletes the JSON sidecar it used (optional, see --keep-json).

It never modifies the contents of your photos or videos.

Supported platforms: Windows, macOS, Linux (Python 3.6+, standard library only)

Sidecar naming patterns handled
-------------------------------
  photo.jpg                ->  photo.jpg.supplemental-metadata.json
  photo.jpg                ->  photo.jpg.json                      (older Takeouts)
  photo(1).jpg             ->  photo.jpg.supplemental-metadata(1).json
  photo(1).jpg             ->  photo.jpg(1).json                   (older Takeouts)

Note on duplicates: when Takeout finds several files with the same name it
adds "(1)", "(2)", ... Those numbers appear at the END of the media file's
name (before the extension) but in the MIDDLE of the JSON's name (before
".json"). Handling that difference is the purpose of find_json_for().

Usage
-----
    python fix_google_photos_dates.py "/path/to/Takeout/Google Photos"
    python fix_google_photos_dates.py "/path/to/folder" --keep-json
    python fix_google_photos_dates.py "/path/to/folder" --no-color

If no folder is given, the script asks for one interactively.
Colours are turned off automatically when output is piped to a file,
or when the NO_COLOR environment variable is set.

License
-------
Add your chosen open-source license here (for example MIT or Apache-2.0)
and include a matching LICENSE file in your repository.
"""

import os
import re
import sys
import json
import shutil
import argparse
import platform
import subprocess
from datetime import datetime, timezone


# ============================================================
# CONFIGURATION
# ============================================================

# OPTIONAL: set a default folder here. If it is empty, the folder is taken
# from the command line, or typed in when the script asks for it.
DEFAULT_FOLDER = ""

# Takeout's sidecar name is "<media file name>" + JSON_STEM + ".json".
JSON_STEM = ".supplemental-metadata"
JSON_SUFFIX = JSON_STEM + ".json"

# "Windows", "Darwin" (macOS) or "Linux". Decides how dates are applied.
SYSTEM = platform.system()


# ============================================================
# COLOURS (ANSI escape codes)
# ============================================================

class C:
    """ANSI escape codes used for coloured terminal output."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"


# Switched on by setup_colors() only when the terminal can display colours.
USE_COLOR = False


def setup_colors(disable=False):
    """
    Decide whether coloured output should be used.

    Colours are disabled when:
      * --no-color was passed (disable=True),
      * the NO_COLOR environment variable is set (https://no-color.org), or
      * stdout is not a terminal (for example when piped into a file).
    """
    global USE_COLOR

    if disable or os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        USE_COLOR = False
        return

    if SYSTEM == "Windows":
        # Running any shell command (even an empty one) switches on ANSI
        # escape-sequence support in the Windows 10+ console.
        os.system("")

    USE_COLOR = True


def paint(text, *styles):
    """Wrap text in the given colour codes, or return it unchanged if colours are off."""
    if not USE_COLOR or not styles:
        return text
    return "".join(styles) + text + C.RESET


# ============================================================
# WINDOWS: set Created / Accessed / Modified via the Windows API
# ============================================================
# Python's os.utime() can only change the modified and accessed times.
# Windows also stores a "creation" time, which can only be changed by
# calling the Win32 SetFileTime function directly through ctypes.

if SYSTEM == "Windows":

    import ctypes
    from ctypes import wintypes

    # Win32 constants used when opening the file handle.
    FILE_WRITE_ATTRIBUTES = 0x100
    FILE_SHARE_READ = 0x1
    FILE_SHARE_WRITE = 0x2
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class FILETIME(ctypes.Structure):
        """Win32 FILETIME: a 64-bit count of 100-nanosecond ticks since 1601-01-01 (UTC)."""
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # Declare argument/return types so ctypes passes values correctly
    # (important for 64-bit Windows, where handles are 64-bit).
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
        """
        Set the Created, Last Accessed and Last Modified times of a file.

        `timestamp` is a normal Unix timestamp (seconds since 1970-01-01 UTC).
        It is converted to the Windows epoch (1601-01-01) and to 100 ns units.
        Raises OSError if the file cannot be opened or the call fails.
        """
        # Open the file with only the permission needed to change attributes.
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
            # 11644473600 = seconds between 1601-01-01 and 1970-01-01.
            # 10000000    = number of 100-nanosecond ticks per second.
            value = int((timestamp + 11644473600) * 10000000)
            ft = FILETIME(value & 0xFFFFFFFF, (value >> 32) & 0xFFFFFFFF)

            ok = kernel32.SetFileTime(
                handle,
                ctypes.byref(ft),   # creation time
                ctypes.byref(ft),   # last access time
                ctypes.byref(ft),   # last write (modified) time
            )

            if not ok:
                raise OSError("Windows SetFileTime failed")
        finally:
            # Always release the handle, even if SetFileTime failed.
            kernel32.CloseHandle(handle)


# ============================================================
# SET FILE DATES (any platform)
# ============================================================

def set_file_dates(file_path, date):
    """
    Apply `date` (a datetime) to a file, as far as the OS allows:

      Windows : Created + Modified + Accessed
      macOS   : Modified + Accessed (+ Created via SetFile if available;
                macOS also lowers the creation date automatically when
                the modified date is set to an earlier time)
      Linux   : Modified + Accessed (Linux has no settable creation date)

    Raises an exception if the dates cannot be set; the caller reports it.
    """
    timestamp = date.timestamp()

    # Modified + Accessed times work the same way on every platform.
    os.utime(file_path, (timestamp, timestamp))

    if SYSTEM == "Windows":
        # Also set the creation time, which os.utime() cannot do.
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
# FIND THE JSON THAT BELONGS TO A MEDIA FILE
# ============================================================

# Matches a media file name that ends with a duplicate counter, e.g.
#   "IMG_1234(1).jpg"  ->  base="IMG_1234", num="1", ext=".jpg"
#   "IMG_1234(2)"      ->  base="IMG_1234", num="2", ext=None (no extension)
DUPLICATE_NAME_RE = re.compile(r"^(.*)\((\d+)\)(\.[^.]+)?$")


def find_json_for(media_path):
    """
    Return the path of the metadata JSON that belongs to `media_path`,
    or None if no matching JSON exists.

    Candidates are tried from most to least common, and the first one that
    exists on disk wins:

      1. photo.jpg.supplemental-metadata.json      (current Takeout style)
      2. photo.jpg.json                            (older Takeout style)
      3. photo(1).jpg -> photo.jpg.supplemental-metadata(1).json
      4. photo(1).jpg -> photo.jpg(1).json         (older style, duplicates)

    Patterns 3 and 4 exist because Takeout moves the duplicate counter:
    it sits before the extension on the media file, but before ".json"
    on the sidecar.

    We deliberately do NOT fall back from "photo(1).jpg" to the un-numbered
    "photo.jpg...json": that sidecar describes a different photo, so using
    it would silently assign the wrong date.
    """
    directory, filename = os.path.split(media_path)

    candidates = [
        media_path + JSON_SUFFIX,   # photo.jpg.supplemental-metadata.json
        media_path + ".json",       # photo.jpg.json
    ]

    # If the media name carries a duplicate counter, move it to where
    # Takeout puts it in the JSON name.
    match = DUPLICATE_NAME_RE.match(filename)
    if match:
        base, num, ext = match.group(1), match.group(2), match.group(3) or ""
        candidates.append(
            os.path.join(directory, f"{base}{ext}{JSON_STEM}({num}).json")
        )
        candidates.append(
            os.path.join(directory, f"{base}{ext}({num}).json")
        )

    for path in candidates:
        if os.path.isfile(path):
            return path

    return None


# ============================================================
# MAIN
# ============================================================

def main():
    """Parse arguments, process every media file under the folder, print a report."""

    # ---------- Command-line arguments ----------
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

    # "Interactive" means the user started the script without a folder
    # (for example by double-clicking it), so the window should stay open
    # at the end instead of vanishing.
    interactive = args.folder is None and not DEFAULT_FOLDER

    # Folder priority: command line > DEFAULT_FOLDER > ask the user.
    folder = args.folder or DEFAULT_FOLDER
    if not folder:
        folder = input(
            paint("Enter the Takeout folder path: ", C.BOLD, C.CYAN)
        ).strip().strip('"').strip("'")  # drop quotes added by drag-and-drop

    def pause():
        """Wait for ENTER, but only in interactive mode."""
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

    # ---------- Counters for the final report ----------
    processed = 0           # media files whose dates were set
    json_not_found = 0      # media files with no matching JSON
    no_timestamp = 0        # JSON found, but it had no usable date
    errors = 0              # unreadable JSON, permission problems, etc.
    json_deleted = 0        # JSON files removed after use
    json_delete_failed = 0  # JSON files we could not remove

    bar = "=" * 60

    # ---------- Header ----------
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

    # ---------- Process every file in the folder tree ----------
    for root, dirs, files in os.walk(folder):

        for filename in files:

            # JSON files are metadata, not media: never treat them as photos.
            if filename.lower().endswith(".json"):
                continue

            media_path = os.path.join(root, filename)

            # Locate the matching sidecar (handles the "(1)" duplicate naming).
            json_path = find_json_for(media_path)

            print(f"{paint('Checking:', C.BLUE)} {filename}")

            if json_path is None:
                json_not_found += 1
                print(paint("  -> JSON NOT FOUND", C.YELLOW))
                print()
                continue

            # Show which JSON was matched, so the pairing can be verified.
            print(paint(f"  -> JSON: {os.path.basename(json_path)}", C.DIM))

            try:

                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # First choice: the moment the photo was actually taken.
                timestamp = data.get("photoTakenTime", {}).get("timestamp")
                timestamp_source = "photoTakenTime"

                # Fallback: when the file was uploaded/created in Google Photos.
                if not timestamp:
                    timestamp = data.get("creationTime", {}).get("timestamp")
                    timestamp_source = "creationTime"

                if not timestamp:
                    no_timestamp += 1
                    print(paint("  -> NO PHOTO DATE FOUND", C.YELLOW))
                    print()
                    continue

                # The timestamp is in UTC seconds. fromtimestamp() converts it
                # to this computer's local time, which is what file dates use.
                date = datetime.fromtimestamp(int(timestamp))

                set_file_dates(media_path, date)

                processed += 1

                # Also show the UTC time, so the result is easy to cross-check
                # against the "formatted" value inside the JSON.
                utc_date = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)

                print(
                    paint("  -> DATE SET: ", C.GREEN)
                    + paint(f"{date}", C.BOLD, C.GREEN)
                    + paint(f" (local)  |  {utc_date:%Y-%m-%d %H:%M:%S} UTC", C.DIM)
                )
                print(paint(f"  -> SOURCE: {timestamp_source}", C.MAGENTA))

                # Delete the JSON only after the date was set successfully,
                # so a failure never leaves a photo without its metadata.
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
                # The sidecar exists but is not valid JSON (corrupted/truncated).
                errors += 1
                print(paint("  -> ERROR: Invalid JSON", C.RED))
                print()

            except PermissionError:
                # Typically a read-only file, or a file open in another program.
                errors += 1
                print(paint("  -> ERROR: Permission denied", C.RED))
                print()

            except Exception as e:
                # Anything unexpected: report it and carry on with the next file.
                errors += 1
                print(paint(f"  -> ERROR: {e}", C.RED))
                print()

    # ---------- Final report ----------

    def stat(label, value, good_color=None):
        """
        Format one line of the final report.

        A value of 0 is shown dimmed for "problem" counters (nothing wrong)
        and green for "success" counters when `good_color` is given.
        Non-zero values use `good_color` (or dim if none is given).
        """
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


# Run main() only when executed as a script, not when imported as a module.
if __name__ == "__main__":
    main()
