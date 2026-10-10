# Google Photos Takeout Date Fixer

A small, dependency-free Python script that restores the original dates of your photos and videos after exporting them with **Google Takeout**. Works on **Windows, macOS and Linux**.

## The Issue

When you download your library from Google Photos through Google Takeout, the files usually lose their original dates. Photos and videos end up with the date you *downloaded* or *extracted* them, so:

- File Explorer / Finder sorts your photos in the wrong order
- Photo managers that fall back to file dates show everything as "recently added"
- The original date is only stored in a separate `.json` file next to each photo

## Solution

This script reads that JSON metadata and:

- **Sets the original date** on each file (Modified and Accessed everywhere, plus Created on Windows)
- **Shows both local time and UTC** for every file it fixes
- **Cleans up** by deleting each JSON file after it has been used (optional)
- **Prints a colour-coded report** so you can see exactly what happened

## Preview

```
============================================================
       GOOGLE PHOTOS TAKEOUT DATE FIXER
============================================================

Folder:
/home/me/Takeout/Google Photos/Photos from 2019

Platform: Linux
Searching for Google Photos metadata...

Checking: IMG_0001.jpg
  -> DATE SET: 2019-01-01 05:30:00 (local)  |  2019-01-01 00:00:00 UTC
  -> SOURCE: photoTakenTime
  -> JSON DELETED

Checking: IMG_0002.png
  -> JSON NOT FOUND
...
Files successfully processed : 1234
JSON not found               : 5
No timestamp found           : 0
Errors                       : 0
JSON files deleted           : 1234
JSON delete failed           : 0
```

In a real terminal the output is colour-coded (green = success, yellow = skipped, red = error).

## Tutorial

### 1. Preparation

You need your photos downloaded from Google Takeout and **extracted**:

1. Go to [takeout.google.com](https://takeout.google.com/) and click **Deselect all**.
2. Scroll down and select only **Google Photos**.
3. Scroll to the bottom and click **Next step**.
4. Choose how to receive the download (email link is the simplest) and a file size for the archives.
5. Click **Create export**, wait for Google's email, then download the archives.
6. Extract every archive. If your export was split into several archives, extract them all into the **same folder** so each photo sits next to its JSON file.

> [!NOTE]
> Point the script at the folder named **Google Photos**. It contains subfolders such as `Photos from 2019` and your album folders. The script searches all subfolders automatically.

> [!IMPORTANT]
> Back up your Takeout folder before you start. See the [warning below](#-warning-json-files-are-deleted-permanently).

### 2. Installation

1. Install **Python 3.7 or newer** from [python.org](https://www.python.org/downloads/) (on Windows, tick *"Add Python to PATH"* during setup). Check with:

   ```
   python --version
   ```

   On macOS and Linux the command may be `python3`.

2. Get the script, either by cloning the repo:

   ```
   git clone https://github.com/YOUR-USERNAME/google-photos-takeout-date-fixer.git
   cd google-photos-takeout-date-fixer
   ```

   or by downloading `fix_google_photos_dates.py` directly from this page.

There is nothing else to install. The script only uses Python's standard library.

### 3. Using the script

Run it and pass your Takeout folder:

```
python fix_google_photos_dates.py "/path/to/Takeout/Google Photos"
```

Windows example:

```
python fix_google_photos_dates.py "C:\Users\me\Pictures\Takeout\Google Photos"
```

If you don't pass a folder, the script asks you to type or paste one.

When it finishes, check a few photos in File Explorer or Finder to confirm the dates look right.

---

### Command line options

| Option | What it does |
| --- | --- |
| `folder` | Folder to process (searched recursively). Optional. The script asks if omitted. |
| `--keep-json` | Do **not** delete the JSON files after setting the dates. |
| `--no-color` | Turn off coloured output. |
| `-h`, `--help` | Show the help message. |

Colours also turn off automatically when output is piped to a file, or when the `NO_COLOR` environment variable is set.

Examples:

```
# Keep the JSON files (safest first run)
python fix_google_photos_dates.py "/path/to/Google Photos" --keep-json

# Save the log to a file
python fix_google_photos_dates.py "/path/to/Google Photos" > log.txt
```

## ⚠️ Warning: JSON files are deleted permanently

By default, a JSON file is **permanently deleted** (not sent to the Recycle Bin / Trash) right after its photo's date has been set successfully. JSON files that were not used, for example because of an error or a missing timestamp, are left untouched.

**Recommended:** run once on a small copy of your data, or use `--keep-json`, and verify the dates before deleting anything.

Your photos and videos themselves are never modified or deleted. Only their file timestamps change.

## Which dates are set on each system

| System | Dates set |
| --- | --- |
| Windows | Created, Modified, Accessed |
| macOS | Modified, Accessed. Created too if `SetFile` is installed (`xcode-select --install`). Without it, macOS usually still lowers the creation date to match. |
| Linux | Modified, Accessed. Linux has no settable creation date. |

## How it works

Google Takeout stores metadata next to each file:

```
photo.jpg
photo.jpg.supplemental-metadata.json
```

For every non-JSON file, the script:

1. Looks for `<file name>.supplemental-metadata.json` in the same folder
2. Reads `photoTakenTime` from it, falling back to `creationTime`
3. Sets the file's dates to that moment
4. Deletes the JSON file (unless `--keep-json` is used)

Takeout timestamps are UTC. The exact moment written to the file is correct on any computer, but File Explorer and Finder display it in your **local time zone**.

## Limitations

- **EXIF data is not changed.** The script sets file system dates only, so the "Date Taken" value inside the image stays as it was. If you need EXIF written too, use a tool such as [ExifTool](https://exiftool.org/).
- **Exact JSON name matching.** The JSON must be named exactly `<file name>.supplemental-metadata.json`. Takeout sometimes names JSON files for numbered duplicates (like `photo(1).jpg`) differently, and shortens very long names. Such files are reported as `JSON NOT FOUND`, skipped, and left unchanged. Edited copies such as `photo-edited.jpg` usually have no JSON of their own and are skipped too.
- **Creation date on Linux** can't be set (a Linux limitation).
- **Dates after copying.** Some tools, cloud uploads and file managers reset timestamps. Check after moving files.

## Troubleshooting

| Message | Meaning |
| --- | --- |
| `JSON NOT FOUND` | No matching `.supplemental-metadata.json` next to the file. The file is skipped. |
| `NO PHOTO DATE FOUND` | The JSON has no usable timestamp. The file is skipped and the JSON is kept. |
| `ERROR: Permission denied` | The file is read-only or locked by another program. Close it and run again. |
| `ERROR: Invalid JSON` | The JSON file is corrupted. The file is skipped. |
| `Folder does not exist` | Check the path. Wrap paths containing spaces in quotes. |
| Strange characters instead of colours | Run with `--no-color`. |
| `python` is not recognized | Reinstall Python and tick *Add Python to PATH*, or use `py` (Windows) / `python3` (macOS, Linux). |

## Contributing

Issues and pull requests are welcome. Ideas that would be especially useful:

- Matching for numbered duplicates and shortened JSON names
- Optional EXIF writing
- A `--dry-run` mode that reports what would change without changing anything

## License

Released under the [MIT License](LICENSE).

## Disclaimer

This project is not affiliated with Google LLC. It is provided as-is, without warranty. Always keep a backup of your original data. The authors are not responsible for any data loss.
