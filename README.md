# Google Photos Takeout Date Fixer

A small, dependency-free Python script that restores the original file timestamps of photos and videos exported with **Google Takeout**.

This version is designed for **Windows**. It reads the date from each media file's Google Takeout `.json` sidecar and updates the file's Windows **Created, Modified, and Accessed** timestamps.

> **Important:** This script changes file-system timestamps only. It does not edit the photo or video itself, and it does not write EXIF metadata.

## The issue

When you export your Google Photos library using Google Takeout, the downloaded or extracted files may have dates that reflect when they were downloaded or extracted rather than when the photos were originally taken.

Google Takeout stores additional metadata in a separate JSON file beside the media file. This script reads that metadata and uses it to restore the file timestamps.

## Features

- **Restores original dates** using `photoTakenTime`, falling back to `creationTime`.
- **Updates Windows timestamps:** Created, Modified, and Accessed.
- **Matches numbered duplicates**, such as `photo(1).jpg` with `photo.jpg.supplemental-metadata(1).json`.
- **Supports older JSON naming patterns**, including `photo.jpg.json`.
- **Handles some shortened Takeout sidecar names** when the shortened name still matches the expected metadata suffix.
- **Lets you choose whether to keep or delete JSON files** each time the program runs. Keeping them is the default.
- **Scans subfolders recursively**.
- **Shows a scan report, progress bar, and final summary**.
- **Supports multiple worker threads** to process files concurrently.
- Uses only Python's standard library. No third-party packages or ExifTool are required.

## Preview

The exact counts and paths depend on your Takeout export. A typical run looks like this:

```text
╭────────────────────────────────────────────────────────────────╮
│  GOOGLE PHOTOS TAKEOUT  •  DATE FIXER                           │
│  Kolkata IST  •  Windows Created + Modified + Accessed          │
╰────────────────────────────────────────────────────────────────╯

ABOUT THIS TOOL
  Restores the original photo/video dates using Google Takeout JSON files.
  Updates Windows Created, Modified and Accessed timestamps; media content is not edited.

HOW TO RUN
  1. Extract your Google Photos Takeout ZIP file.
  2. Open Command Prompt or PowerShell in the folder containing this script.
  3. Run: python fix_google_photos_date.py
  4. Choose whether to keep or delete the JSON sidecars, then confirm the date update.

Folder:    D:\Takeout
Mode:      LIVE APPLY  (file dates will be changed)
Workers:   2

What should happen to the JSON sidecar files?
  [K] Keep JSON files (recommended / default)
  [D] Delete each JSON only after its media file date is updated successfully
  Your choice [K/D, default K]:
```

After scanning, the script displays a scan result, asks you to type `YES` before changing dates (unless `--yes` is supplied), and then shows processing progress and a summary.

The terminal uses colour-coded output when supported. Colours are disabled automatically when output is not an interactive terminal.

## Tutorial

### 1. Prepare your Google Takeout export

1. Visit [Google Takeout](https://takeout.google.com/).
2. Click **Deselect all**.
3. Select **Google Photos**.
4. Click **Next step**.
5. Choose how you want to receive the export and create it.
6. Download the archive files from Google's email.
7. Extract the archives.

If Google splits your export into multiple archives, extract all of them into the same destination folder while preserving the folder structure.

> **Tip:** Point the script at the main `Google Photos` folder. It searches that folder and its subfolders automatically.

### 2. Install Python

Install Python on Windows from [python.org](https://www.python.org/downloads/).

During installation, enable **Add Python to PATH**.

Open Command Prompt or PowerShell and check the installation:

```powershell
python --version
```

This script uses only the Python standard library. There are no additional packages to install.

### 3. Download the script

Download `fix_google_photos_date.py` and save it somewhere convenient.

Your folder can look like this:

```text
YourFolder/
├── fix_google_photos_date.py
└── Takeout/
    └── Google Photos/
        ├── Photos from 2019/
        ├── Photos from 2020/
        └── ...
```

### 4. Run the script

Open Command Prompt or PowerShell in the folder containing the script.

Run it without a folder argument:

```powershell
python fix_google_photos_date.py
```

The program will ask you to enter the path to your Google Photos Takeout folder.

Or provide the folder path directly:

```powershell
python fix_google_photos_date.py "D:\Takeout\Google Photos"
```

Use quotation marks around paths that contain spaces.

### 5. Choose what to do with JSON files

The program asks:

```text
What should happen to the JSON sidecar files?
  [K] Keep JSON files (recommended / default)
  [D] Delete each JSON only after its media file date is updated successfully
  Your choice [K/D, default K]:
```

- Press **Enter** or type `K` to keep JSON files.
- Type `D` to delete a JSON sidecar after its corresponding media file's timestamps have been updated successfully.

**Keeping JSON files is recommended for your first run.**

### 6. Confirm the changes

The script scans the folder and displays the number of files found, matched JSON sidecars, missing JSON files, JSON files without a usable timestamp, and JSON read errors.

It then asks you to type:

```text
Type YES to continue:
```

Only an exact `YES` proceeds. Any other response cancels the operation.

When processing finishes, check several files in File Explorer to verify their timestamps.

## Command-line options

| Option | Description |
| --- | --- |
| `folder` | Optional folder to process. All subfolders are searched. If omitted, the script asks for a folder path. |
| `--workers N` | Number of parallel worker threads. Default: `2`. |
| `--yes` | Skips the final `YES` confirmation. It does **not** skip the JSON keep/delete question. |
| `--ascii` | Uses plain ASCII symbols instead of Unicode box-drawing characters. |
| `--no-color` | Disables coloured terminal output. |
| `-h`, `--help` | Displays command-line help. |

### Examples

Process a folder using the default settings:

```powershell
python fix_google_photos_date.py "D:\Takeout\Google Photos"
```

Use four worker threads:

```powershell
python fix_google_photos_date.py "D:\Takeout\Google Photos" --workers 4
```

Use ASCII symbols:

```powershell
python fix_google_photos_date.py "D:\Takeout\Google Photos" --ascii
```

Disable colours:

```powershell
python fix_google_photos_date.py "D:\Takeout\Google Photos" --no-color
```

Skip the final confirmation prompt:

```powershell
python fix_google_photos_date.py "D:\Takeout\Google Photos" --yes
```

> `--yes` does not bypass the JSON keep/delete selection. The script still asks whether to keep or delete sidecar files.

## Warning: JSON deletion is permanent

If you choose `D`, the script permanently deletes each matching JSON sidecar after the corresponding media file's timestamps have been set successfully. The files are not moved to the Windows Recycle Bin.

JSON files are not deleted when:
- No matching sidecar is found.
- The JSON cannot be read.
- The JSON does not contain a usable timestamp.
- Updating the corresponding media file's timestamps fails.

**Recommended first run:**

1. Keep a backup of your original Takeout folder.
2. Test the script on a small copy of your export.
3. Choose `K` to keep all JSON sidecars.
4. Check the resulting file dates.
5. Only choose `D` when you are confident that the results are correct and you no longer need those JSON files.

Your photo and video contents are not edited or deleted by this script. Their Windows file timestamps are changed.

## Which dates are set?

| Platform | Supported dates |
| --- | --- |
| Windows | Created, Modified, and Accessed |

**Windows only:** The script uses the Windows `SetFileTime` API through Python's `ctypes` module. It exits with a message on macOS or Linux.

The script writes the timestamp represented by the Unix timestamp in the Takeout JSON. Windows displays that moment according to the computer's configured time zone. The program's banner and final reminder refer to India Standard Time (IST).

## How it works

Google Takeout stores metadata beside a media file. For example:

```text
photo.jpg
photo.jpg.supplemental-metadata.json
```

For each non-skipped file, the script:

1. Searches for a matching JSON sidecar in the same folder.
2. Reads `photoTakenTime.timestamp`.
3. If that value is unavailable, tries `creationTime.timestamp`.
4. Converts the Unix timestamp to Windows file time.
5. Sets the file's Created, Accessed, and Modified timestamps.
6. Keeps or deletes the JSON sidecar according to your selection.

The script searches directories recursively and processes matched files using a thread pool.

### JSON name matching

Google Takeout may add a number to duplicate filenames. For example:

```text
IMG_1234(1).jpg
IMG_1234.jpg.supplemental-metadata(1).json
```

The script checks several possible names, including:

| Media file | JSON sidecar checked |
| --- | --- |
| `photo.jpg` | `photo.jpg.supplemental-metadata.json` |
| `photo.jpg` | `photo.jpg.json` |
| `photo(1).jpg` | `photo.jpg.supplemental-metadata(1).json` |
| `photo(1).jpg` | `photo.jpg(1).json` |

It also has matching logic for `-edited` filenames and some shortened `.supplemental-metadata` sidecar names.

## Limitations

- **Windows only:** macOS and Linux are not supported by this version.
- **File timestamps only:** EXIF metadata such as the image's internal Date Taken field is not changed.
- **No ExifTool integration:** The script does not write metadata into image or video files.
- **Shortened sidecar names:** Only shortened names that satisfy the script's matching rule can be found. Other shortened names may be reported as missing.
- **Edited copies:** The script may associate a `-edited` file with the original file's JSON sidecar. Review your results if you have edited copies.
- **Time zone display:** Windows displays timestamps using the system's time zone. Set Windows to your intended time zone before checking the displayed dates.
- **File-system behaviour:** External drives, cloud-sync tools, copying, and other applications may alter timestamps after this script runs.

## Troubleshooting

| Message or symptom | What it means / what to do |
| --- | --- |
| `This script only works on Windows.` | The current version supports Windows only. |
| `Folder does not exist!` | Check the folder path and make sure it is wrapped in quotes if it contains spaces. |
| `JSON not found` | No matching sidecar was found. The media file is skipped. |
| `No timestamp in JSON` | The JSON did not contain a usable `photoTakenTime` or `creationTime` timestamp. |
| `JSON read errors` | One or more sidecar files could not be read or parsed. |
| `Permission denied` | Close applications using the file and check your Windows permissions. |
| Strange symbols in the terminal | Try the `--ascii` option. |
| Colours are difficult to read | Try the `--no-color` option. |
| `python` is not recognized | Reinstall Python with **Add Python to PATH** enabled, or use the Python launcher `py`. |

## Contributing

Suggestions, bug reports, and pull requests are welcome.

Useful future improvements could include:

- A dry-run mode that reports planned changes without applying them.
- More robust matching for shortened Google Takeout JSON filenames.
- Optional EXIF metadata writing.
- Cross-platform support for macOS and Linux.

## License

Add your chosen license file and update this section before publishing. If you intend to use the MIT License, include the full MIT License text in a file named `LICENSE`.

## Disclaimer

This project is not affiliated with Google LLC. It is provided as-is, without warranty. Always keep a backup of your original data before changing file timestamps or deleting JSON sidecars.
