# some-scripts

Utility scripts for inventorying and downloading samples from the Vengeance package.

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

When run without `--directories`, the Python script opens an interactive terminal selector for the root directories listed at the remote URL.

The root directory list is cached locally after the first successful fetch, so later runs can open the selector without waiting for the remote index again. Use `--refresh-root-cache` when you want to rebuild that list.

After you choose folders, each folder inventory is also cached locally. If the remote content rarely changes, later runs can skip the recursive scan and jump straight to the missing-file comparison.

Controls:

- `Up` / `Down`: move through the list.
- `Space`: toggle the current directory.
- `Enter`: confirm the selection.
- Type text: filter directories by name.
- `Backspace`: clear the last character from the filter.
- `a`: select all currently visible directories.
- `n`: clear all currently visible directories.
- `q` or `Esc`: cancel.

If the terminal does not support `curses`, the script falls back to a simple prompt where you can enter directory names separated by commas.

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
