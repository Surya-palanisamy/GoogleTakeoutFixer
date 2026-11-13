#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Photos Takeout - Date Fixer (Windows, no ExifTool)
=========================================================

Reads the date from the Google Takeout JSON sidecar of every photo/video and
sets the Windows file times (Created, Modified, Accessed) to the real
"photo taken" date, in one go.

* Windows only (Win32 SetFileTime through ctypes)
* Photos/videos are never edited: only their file timestamps change
* You choose at runtime whether JSON sidecars should be kept or deleted
  after their date has been applied successfully (keeping is the default)

Usage
-----
    python fix_google_photos_date.py "D:\\Google Photos\\Photos from 2012"
    python fix_google_photos_date.py "D:\\folder" --workers 4
    python fix_google_photos_date.py "D:\\folder" --yes       (skip the YES prompt)
    python fix_google_photos_date.py "D:\\folder" --ascii     (plain symbols)
    python fix_google_photos_date.py "D:\\folder" --no-color

Run it without a folder and it will ask for one.
"""

import os
import re
import sys
import json
import time
import argparse
import platform
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor


# ============================================================
# WINDOWS CHECK
# ============================================================

SYSTEM = platform.system()

if SYSTEM != "Windows":
    print("This script only works on Windows.")
    print("Detected platform: %s" % SYSTEM)
    sys.exit(1)

import ctypes
from ctypes import wintypes

# Make sure box-drawing characters and bullets print correctly.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ============================================================
# CONFIGURATION
# ============================================================

DEFAULT_FOLDER = ""        # optional: put your folder path here
DEFAULT_WORKERS = 2

IST = timezone(timedelta(hours=5, minutes=30), "IST")   # Kolkata time

JSON_STEM = ".supplemental-metadata"
JSON_SUFFIX = JSON_STEM + ".json"

# Files that are never treated as photos/videos.
SKIP_EXTENSIONS = {".json", ".csv", ".html", ".txt"}


# ============================================================
# COLOURS AND SYMBOLS
# ============================================================

PALETTE = {
    'accent': ((56, 189, 248), 36),     # sky blue
    'violet': ((167, 139, 250), 35),    # soft violet
    'good':   ((52, 211, 153), 32),     # emerald
    'warn':   ((251, 191, 36), 33),     # amber
    'bad':    ((251, 113, 133), 31),    # rose
    'muted':  ((148, 163, 184), 90),    # slate
    'text':   ((226, 232, 240), 97),    # near white
}

SYMBOLS_UNICODE = {'ok': '✓', 'bad': '✗', 'warn': '▲', 'dot': '•', 'arrow': '→', 'gps': '◆',
                   'full': '█', 'empty': '░', 'h': '─', 'tl': '╭', 'tr': '╮', 'bl': '╰', 'br': '╯', 'v': '│'}
SYMBOLS_ASCII = {'ok': '+', 'bad': 'x', 'warn': '!', 'dot': '*', 'arrow': '->', 'gps': '*',
                 'full': '#', 'empty': '-', 'h': '-', 'tl': '+', 'tr': '+', 'bl': '+', 'br': '+', 'v': '|'}


class UI:
    sym = SYMBOLS_UNICODE
    color = False
    truecolor = False


def setup_ui(no_color=False, use_ascii=False):
    """Decide on colours (truecolor when the console supports it) and symbols."""
    UI.sym = SYMBOLS_ASCII if use_ascii else SYMBOLS_UNICODE

    if no_color or os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        UI.color = False
        return

    os.system("")                      # switches on ANSI support in the Windows console
    UI.color = True
    try:
        # Truecolor (24-bit) works on Windows 10 build 15063 and newer.
        UI.truecolor = sys.getwindowsversion().build >= 15063
    except Exception:
        UI.truecolor = False


def paint(text, key, bold=False):
    """Colour text with a palette entry; returns plain text when colours are off."""
    if not UI.color:
        return text
    rgb, ansi = PALETTE[key]
    code = "38;2;%d;%d;%d" % rgb if UI.truecolor else str(ansi)
    if bold:
        code = "1;" + code
    return "\033[%sm%s\033[0m" % (code, text)


def gradient(text, start='accent', end='violet'):
    """Smooth sky-blue -> violet gradient across the text (bold)."""
    if not UI.color:
        return text
    if not UI.truecolor:
        half = len(text) // 2
        return paint(text[:half], start, True) + paint(text[half:], end, True)
    (r1, g1, b1), _ = PALETTE[start]
    (r2, g2, b2), _ = PALETTE[end]
    n = max(len(text) - 1, 1)
    out = []
    for i, ch in enumerate(text):
        t = i / n
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        out.append("\033[1;38;2;%d;%d;%dm%s" % (r, g, b, ch))
    return "".join(out) + "\033[0m"


# ============================================================
# WINDOWS: set Created / Accessed / Modified
# ============================================================

FILE_WRITE_ATTRIBUTES = 0x100
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
FILE_SHARE_DELETE = 0x4
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD),
                ("dwHighDateTime", wintypes.DWORD)]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
kernel32.CreateFileW.restype = wintypes.HANDLE

kernel32.SetFileTime.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(FILETIME),
    ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME),
]
kernel32.SetFileTime.restype = wintypes.BOOL

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


def long_path(path):
    """Add the \\\\?\\ prefix so paths longer than 260 characters still work."""
    path = os.path.abspath(path)
    if path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):                  # network share
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def set_windows_file_times(file_path, timestamp):
    """Set Created, Accessed and Modified time from a Unix timestamp (UTC)."""
    handle = kernel32.CreateFileW(
        long_path(file_path),
        FILE_WRITE_ATTRIBUTES,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if handle is None or handle == INVALID_HANDLE_VALUE:
        raise OSError("Could not open file (Windows error %d)" % ctypes.get_last_error())

    try:
        # 11644473600 = seconds from 1601-01-01 to 1970-01-01; 1e7 ticks per second
        value = int((timestamp + 11644473600) * 10000000)
        if value < 0:
            raise ValueError("date is before 1601 - Windows cannot store it")
        ft = FILETIME(value & 0xFFFFFFFF, (value >> 32) & 0xFFFFFFFF)
        if not kernel32.SetFileTime(handle, ctypes.byref(ft),
                                    ctypes.byref(ft), ctypes.byref(ft)):
            raise OSError("SetFileTime failed (Windows error %d)" % ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)


# ============================================================
# FIND THE JSON THAT BELONGS TO A MEDIA FILE
# ============================================================

DUPLICATE_NAME_RE = re.compile(r"^(.*)\((\d+)\)(\.[^.]+)?$")
EDITED_RE = re.compile(r"^(.*)-edited(\.[^.]+)?$", re.IGNORECASE)

_dir_cache = {}


def _json_names_in(directory):
    """Names of all .json files in a folder (cached, so each folder is listed once)."""
    if directory not in _dir_cache:
        try:
            _dir_cache[directory] = [n for n in os.listdir(directory)
                                     if n.lower().endswith(".json")]
        except OSError:
            _dir_cache[directory] = []
    return _dir_cache[directory]


def find_json_for(media_path):
    """Return the sidecar JSON path for a media file, or None."""
    directory, filename = os.path.split(media_path)

    names = [filename + JSON_SUFFIX, filename + ".json"]

    # photo(1).jpg -> photo.jpg.supplemental-metadata(1).json
    m = DUPLICATE_NAME_RE.match(filename)
    if m:
        base, num, ext = m.group(1), m.group(2), m.group(3) or ""
        names.append("%s%s%s(%s).json" % (base, ext, JSON_STEM, num))
        names.append("%s%s(%s).json" % (base, ext, num))

    # photo-edited.jpg -> photo.jpg's sidecar
    m = EDITED_RE.match(filename)
    if m:
        original = (m.group(1) or "") + (m.group(2) or "")
        names.append(original + JSON_SUFFIX)
        names.append(original + ".json")

    for name in names:
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            return path

    # Takeout shortens very long sidecar names, e.g.
    # "photo.jpg.supplemental-metad.json" - accept a cut-off ".supplemental-metadata".
    prefix = filename + "."
    full_stem = JSON_STEM[1:]
    for name in _json_names_in(directory):
        if name.startswith(prefix):
            middle = name[len(prefix):-5]
            if middle and full_stem.startswith(middle):
                return os.path.join(directory, name)

    return None


# ============================================================
# READ THE TIMESTAMP FROM A JSON
# ============================================================

def read_json_info(json_path):
    """
    Returns (timestamp, has_gps). timestamp is None if the JSON has no usable date.
    Raises on unreadable / invalid JSON.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    ts = None
    for key in ("photoTakenTime", "creationTime"):
        value = (data.get(key) or {}).get("timestamp")
        if value:
            ts = int(value)
            break

    has_gps = False
    for key in ("geoData", "geoDataExif"):
        geo = data.get(key) or {}
        if geo.get("latitude") or geo.get("longitude"):
            has_gps = True
            break

    return ts, has_gps


# ============================================================
# OUTPUT HELPERS
# ============================================================

LABEL_W = 32


def fmt_duration(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%d:%02d" % (m, s)


def banner():
    s = UI.sym
    inner = 62
    title = 'GOOGLE PHOTOS TAKEOUT  %s  DATE FIXER' % s['dot']
    sub = 'Kolkata IST  %s  Windows Created + Modified + Accessed' % s['dot']
    print()
    print('  ' + paint(s['tl'] + s['h'] * inner + s['tr'], 'accent'))
    for text, grad in ((title, True), (sub, False)):
        pad = inner - 4 - len(text)
        body = gradient(text) if grad else paint(text, 'muted')
        print('  ' + paint(s['v'], 'accent') + '  ' + body + ' ' * pad + '  ' + paint(s['v'], 'violet'))
    print('  ' + paint(s['bl'] + s['h'] * inner + s['br'], 'violet'))
    print()


def kv(label, value, color='text'):
    print('  %s %s' % (paint('%-10s' % label, 'muted'), paint(value, color)))


def section(title):
    h = UI.sym['h']
    print()
    print('  ' + paint(h * 2, 'muted') + ' ' + paint(title, 'accent', True) + ' '
          + paint(h * (62 - len(title) - 4), 'muted'))


def row(symbol, symbol_color, label, value, value_color='text'):
    print('  %s %s%s' % (paint(UI.sym[symbol], symbol_color),
                         paint('%-*s' % (LABEL_W - 2, label), 'text'),
                         paint(str(value), value_color, True)))


def progress(done, total, start):
    width = 30
    filled = int(width * done / total) if total else width
    bar = paint(UI.sym['full'] * filled, 'violet') + paint(UI.sym['empty'] * (width - filled), 'muted')
    elapsed = max(time.time() - start, 0.001)
    sys.stdout.write('\r  %s %s  %s   ' % (
        bar,
        paint('%d/%d' % (done, total), 'text'),
        paint('%.1f files/s' % (done / elapsed), 'muted'),
    ))
    sys.stdout.flush()


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Restore original photo dates from Google Takeout JSON (Windows).")
    parser.add_argument("folder", nargs="?", help="Takeout folder (searched recursively)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help="Parallel workers (default %d)" % DEFAULT_WORKERS)
    parser.add_argument("--yes", action="store_true", help="Skip the YES confirmation")
    parser.add_argument("--ascii", action="store_true", help="Use plain ASCII symbols")
    parser.add_argument("--no-color", action="store_true", help="Turn off colours")
    args = parser.parse_args()

    setup_ui(no_color=args.no_color, use_ascii=args.ascii)
    workers = max(1, args.workers)

    interactive = args.folder is None and not DEFAULT_FOLDER
    folder = args.folder or DEFAULT_FOLDER

    banner()

    print(paint('ABOUT THIS TOOL', 'accent', True))
    print('  Restores the original photo/video dates using Google Takeout JSON files.')
    print('  Updates Windows Created, Modified and Accessed timestamps; media content is not edited.')
    print()
    print(paint('HOW TO RUN', 'accent', True))
    print('  1. Extract your Google Photos Takeout ZIP file.')
    print('  2. Open Command Prompt or PowerShell in the folder containing this script.')
    print('  3. Run: python fix_google_photos_date.py')
    print('     Or specify a folder: python fix_google_photos_date.py "D:\\Google Photos"')
    print('  4. Choose whether to keep or delete the JSON sidecars, then confirm the date update.')
    print('  Tip: Use --workers 4 to change the number of parallel workers.')
    print()

    if not folder:
        folder = input('  ' + paint('Enter the Takeout folder path: ', 'accent', True)
                       ).strip().strip('"').strip("'")
        print()

    def pause():
        if interactive:
            input('\n  ' + paint('Press ENTER to close...', 'muted'))

    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        print('  ' + paint('ERROR: Folder does not exist!', 'bad', True))
        print('  ' + paint(folder, 'warn'))
        pause()
        sys.exit(1)

    kv('Folder', folder, 'accent')
    kv('Mode', 'LIVE APPLY  (file dates will be changed)', 'warn')
    kv('Workers', str(workers))

    print()
    print(paint('What should happen to the JSON sidecar files?', 'accent', True))
    print('  [K] Keep JSON files (recommended / default)')
    print('  [D] Delete each JSON only after its media file date is updated successfully')
    while True:
        json_choice = input('  Your choice [K/D, default K]: ').strip().lower()
        if json_choice in ('', 'k', 'keep'):
            delete_json = False
            break
        if json_choice in ('d', 'delete'):
            delete_json = True
            break
        print('  Please enter K to keep or D to delete.')
    kv('JSON files', 'will be deleted after success' if delete_json else 'will be kept',
       'warn' if delete_json else 'good')

    # ---------------- SCAN ----------------
    scan_start = time.time()
    jobs = []                    # (media_path, json_path, timestamp)
    images_found = 0
    matched = 0
    with_gps = 0
    json_missing = 0
    no_timestamp = 0
    json_errors = 0

    for root, _dirs, files in os.walk(folder):
        for filename in files:
            if os.path.splitext(filename)[1].lower() in SKIP_EXTENSIONS:
                continue

            images_found += 1
            media_path = os.path.join(root, filename)
            json_path = find_json_for(media_path)

            if json_path is None:
                json_missing += 1
                continue

            try:
                ts, gps = read_json_info(json_path)
            except Exception:
                json_errors += 1
                continue

            matched += 1
            if gps:
                with_gps += 1

            if ts is None:
                no_timestamp += 1
                continue

            jobs.append((media_path, json_path, ts))

    section('SCAN RESULT')
    row('dot', 'text', 'Images found', images_found, 'text')
    row('ok', 'good', 'Matched with a JSON sidecar', matched, 'good')
    row('warn', 'warn', 'JSON not found', json_missing, 'warn')
    row('warn', 'warn', 'No timestamp in JSON', no_timestamp, 'warn')
    row('bad', 'bad', 'JSON read errors', json_errors, 'good' if json_errors == 0 else 'bad')
    print('  ' + paint('scanned in %s' % fmt_duration(time.time() - scan_start), 'muted'))

    if not jobs:
        print()
        print('  ' + paint('Nothing to do - no files with a usable date were found.', 'warn'))
        pause()
        return

    # ---------------- CONFIRM ----------------
    print()
    print('  ' + paint('WARNING: File dates (Created / Modified / Accessed) will be changed.', 'warn', True))
    if delete_json:
        print('  ' + paint('Photos are never edited. Each JSON sidecar is deleted after its date is set.', 'muted'))
    else:
        print('  ' + paint('Photos are never edited. JSON sidecars are kept.', 'muted'))

    if not args.yes:
        answer = input('  ' + paint('Type YES to continue: ', 'accent', True)).strip()
        if answer != 'YES':
            print('  ' + paint('Cancelled. Nothing was changed.', 'warn'))
            pause()
            return

    # ---------------- APPLY ----------------
    print()

    def work(job):
        media_path, json_path, ts = job
        try:
            datetime.fromtimestamp(ts, tz=timezone.utc)      # validates the timestamp
        except (OverflowError, OSError, ValueError) as e:
            return (False, False, "Bad timestamp: %s" % e)

        try:
            set_windows_file_times(media_path, ts)
        except PermissionError:
            return (False, False, "Permission denied")
        except Exception as e:
            return (False, False, str(e))

        deleted = False
        if delete_json:
            try:
                os.remove(json_path)
                deleted = True
            except Exception:
                pass                     # date is set; leftover JSON is harmless
        return (True, deleted, "")

    processed = 0
    errors = 0
    json_deleted = 0
    error_lines = []

    total = len(jobs)
    done = 0
    apply_start = time.time()
    progress(0, total, apply_start)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for job, (ok, deleted, message) in zip(jobs, pool.map(work, jobs)):
            done += 1
            if ok:
                processed += 1
                if deleted:
                    json_deleted += 1
            else:
                errors += 1
                error_lines.append((os.path.basename(job[0]), message))
            progress(done, total, apply_start)

    elapsed = time.time() - apply_start
    print()

    if error_lines:
        section('ERRORS')
        for name, msg in error_lines[:20]:
            print('  ' + paint(UI.sym['bad'], 'bad') + ' ' + paint(name, 'text')
                  + paint('  %s %s' % (UI.sym['arrow'], msg), 'muted'))
        if len(error_lines) > 20:
            print('  ' + paint('... and %d more' % (len(error_lines) - 20), 'muted'))

    # ---------------- SUMMARY ----------------
    total_errors = errors + json_errors
    section('SUMMARY')
    row('ok', 'good', 'Files successfully processed', processed, 'good')
    row('warn', 'warn', 'JSON not found', json_missing, 'warn')
    row('warn', 'warn', 'No timestamp found', no_timestamp, 'warn')
    row('bad', 'bad', 'Errors', total_errors, 'good' if total_errors == 0 else 'bad')

    rate = processed / elapsed if elapsed > 0 else 0
    print()
    print('  %s  %s   %s   %s' % (
        paint('Time', 'muted'),
        paint(fmt_duration(elapsed), 'accent', True),
        paint(UI.sym['dot'], 'muted'),
        paint('%.1f files/s' % rate, 'accent', True),
    ))
    print('  ' + paint('JSON files deleted: %d %s' % (json_deleted, UI.sym['dot']), 'muted'))
    print('  ' + paint('Set your Windows time zone to India Standard Time to see file '
                       'timestamps in Kolkata time.', 'muted'))

    pause()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print('  ' + paint('Stopped by user.', 'warn'))
        sys.exit(130)
