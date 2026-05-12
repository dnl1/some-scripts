# some-scripts

Utility scripts for inventorying and downloading samples from the Vengeance package.

The Python script works on Linux and Windows. On Windows it defaults to `~/Downloads/Vengeance Samples`, and the `curses` selector stays optional.

## Files

- `download-vengeance-samples.py`: main Python version, easier to maintain and extend.
- `download-vengeance-samples.sh`: shell version kept as a simpler alternative.
- `download-vengeance-samples.ps1`: original PowerShell version.

## Quick Start

```bash
python3 download-vengeance-samples.py --inventory-only
python3 download-vengeance-samples.py
python3 download-vengeance-samples.py --yes
python3 download-vengeance-samples.py --directories "House Essentials,Minimal"
```

## Interactive Selector

When run without `--directories`, the Python script opens a native Python selector for the root directories listed at the remote URL.

The root directory list is cached in `vengeance-root-directories.json` inside this repository, so later runs can open the selector without waiting for the remote index again. If a folder is missing from the snapshot, the selector also exposes a `Load more from remote` option that refreshes this file.

After you choose folders, each folder inventory is also cached locally. If the remote content rarely changes, later runs can skip the recursive scan and jump straight to the missing-file comparison.

Controls:

- `text`: filter directories by name.
- `/text`: filter directories by name.
- `1,2,3`: add visible directories by number.
- `more`: show 50 more visible matches.
- `clear`: reset the current filter.
- `done`: confirm the accumulated selection.
- `list`: show the current accumulated selection.
- `reset`: clear the accumulated selection.
- `remove 1,2`: remove items from the current selection by selection index.
- `remove Exact Name`: remove an item from the current selection by exact selected name.
- `load`: refresh the root directory snapshot from the server.
- `q`: cancel.

If you prefer the older full-screen selector, use `--selector curses`. On Windows this depends on a Python installation that includes `curses`.

## Behavior

- The script lists directories from the remote root.
- You choose which directories to scan.
- It inventories all remote files under the selected directories.
- It checks whether each file already exists in the destination path.
- Existing files are skipped and not downloaded again.

## Options

- `--base-url`: override the base URL for the remote directory listing.
- `--download-path`: override the local destination directory.
- `--directories`: provide directories to download as a comma-separated list; accepts names or numeric indexes.
- `--root-cache`: override the cache file used for the root directory list.
- `--refresh-root-cache`: force a fresh fetch of the root directory list before showing the selector.
- `--inventory-cache-dir`: override the directory used for cached folder inventories.
- `--refresh-inventory-cache`: force a fresh recursive scan for the selected folders.
- `--inventory-only`: only list missing files.
- `--yes`: download without asking for confirmation.
