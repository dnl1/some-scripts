#!/usr/bin/env python3

from __future__ import annotations

import argparse
import curses
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote_plus, urldefrag, urljoin
from urllib.request import Request, urlopen


BASE_URL_DEFAULT = "https://files.lyberry.com/audio/sounds/Vengeance%20Samples/"
DOWNLOAD_PATH_DEFAULT = "/mnt/c/Vengeance Samples"
USER_AGENT = "some-scripts/1.0"
CACHE_DIR_DEFAULT = Path.home() / ".cache" / "some-scripts"
ROOT_DIRECTORIES_CACHE_NAME = "vengeance-root-directories.json"
INVENTORY_CACHE_DIR_NAME = "vengeance-inventories"


def status(message: str) -> None:
    print(message, flush=True)


def clean_component(value: str) -> str:
    decoded = unquote_plus(value).strip()
    illegal_chars = '\\/:*?"<>|'
    return "".join("_" if char in illegal_chars else char for char in decoded)


def sanitize_relative_path(raw_path: str) -> str:
    parts = [clean_component(part) for part in raw_path.split("/") if part]
    return "/".join(parts)


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = dict(attrs)
        href = attr_map.get("href")
        if href:
            self.links.append(href)


def fetch_html(url: str, timeout: int = 60) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_links(url: str) -> list[str]:
    html = fetch_html(url)
    parser = LinkParser()
    parser.feed(html)

    filtered_links: list[str] = []
    seen_links: set[str] = set()
    for href in parser.links:
        if not href:
            continue
        href = urldefrag(href)[0].strip()
        if not href:
            continue
        if href.startswith("?"):
            continue
        if href.startswith("/"):
            continue
        if href in {".", "./", ".."}:
            continue
        if "../" in href:
            continue
        while href.startswith("./"):
            href = href[2:]
        if not href:
            continue
        if href in seen_links:
            continue
        seen_links.add(href)
        filtered_links.append(href)
    return filtered_links


def default_root_cache_path() -> Path:
    return CACHE_DIR_DEFAULT / ROOT_DIRECTORIES_CACHE_NAME


def default_inventory_cache_dir() -> Path:
    return CACHE_DIR_DEFAULT / INVENTORY_CACHE_DIR_NAME


@dataclass(frozen=True)
class RemoteFile:
    relative_path: str
    url: str


def list_root_directories(url: str) -> list[tuple[str, str]]:
    root_directories: list[tuple[str, str]] = []

    for href in fetch_links(url):
        if not href.endswith("/"):
            continue
        directory_name = sanitize_relative_path(href[:-1])
        if not directory_name:
            continue
        root_directories.append((directory_name, urljoin(url, href)))

    root_directories.sort(key=lambda item: item[0].lower())
    return root_directories


def load_cached_root_directories(cache_path: Path, expected_url: str) -> list[tuple[str, str]]:
    with cache_path.open("r", encoding="utf-8") as cache_file:
        payload = json.load(cache_file)

    if payload.get("base_url") != expected_url:
        raise ValueError("cache was created for a different base URL")

    directories = payload.get("directories")
    if not isinstance(directories, list):
        raise ValueError("cache does not contain a valid directory list")

    cached_root_directories: list[tuple[str, str]] = []
    for item in directories:
        if not isinstance(item, dict):
            raise ValueError("cache contains an invalid entry")
        directory_name = item.get("name")
        directory_url = item.get("url")
        if not isinstance(directory_name, str) or not isinstance(directory_url, str):
            raise ValueError("cache contains an invalid directory record")
        cached_root_directories.append((directory_name, directory_url))

    if not cached_root_directories:
        raise ValueError("cache directory list is empty")

    cached_root_directories.sort(key=lambda item: item[0].lower())
    return cached_root_directories


def save_cached_root_directories(cache_path: Path, base_url: str, root_directories: list[tuple[str, str]]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "base_url": base_url,
        "directories": [
            {"name": directory_name, "url": directory_url}
            for directory_name, directory_url in root_directories
        ],
    }
    with cache_path.open("w", encoding="utf-8") as cache_file:
        json.dump(payload, cache_file, ensure_ascii=True, indent=2)
        cache_file.write("\n")


def get_root_directories(url: str, cache_path: Path, refresh_cache: bool) -> list[tuple[str, str]]:
    if not refresh_cache and cache_path.is_file():
        try:
            cached_root_directories = load_cached_root_directories(cache_path, url)
            status(f"Using cached root directories: {cache_path}")
            return cached_root_directories
        except Exception as exc:
            status(f"Ignoring invalid root cache {cache_path}: {exc}")

    status(f"Listing remote directories: {url}")
    root_directories = list_root_directories(url)
    save_cached_root_directories(cache_path, url, root_directories)
    status(f"Saved root directory cache: {cache_path}")
    return root_directories


def crawl_directory(
    url: str,
    relative_prefix: str = "",
    visited_directories: set[str] | None = None,
    listed_directories: list[int] | None = None,
) -> list[RemoteFile]:
    if visited_directories is None:
        visited_directories = set()
    if listed_directories is None:
        listed_directories = [0]

    normalized_url = urldefrag(url)[0]
    if normalized_url in visited_directories:
        return []
    visited_directories.add(normalized_url)
    listed_directories[0] += 1

    location = relative_prefix.rstrip("/") or "/"
    status(f"  Listing remote directory [{listed_directories[0]}]: {location}")

    remote_files: list[RemoteFile] = []

    for href in fetch_links(url):
        full_url = urljoin(url, href)
        if href.endswith("/"):
            child_prefix = f"{relative_prefix}{sanitize_relative_path(href[:-1])}/"
            remote_files.extend(crawl_directory(full_url, child_prefix, visited_directories, listed_directories))
            continue

        relative_path = f"{relative_prefix}{sanitize_relative_path(href)}"
        remote_files.append(RemoteFile(relative_path=relative_path, url=full_url))

    return remote_files


def inventory_cache_path(cache_dir: Path, directory_name: str, directory_url: str) -> Path:
    slug = "".join(char if char.isalnum() else "-" for char in directory_name.lower()).strip("-")
    slug = "-".join(part for part in slug.split("-") if part) or "directory"
    cache_key = hashlib.sha1(directory_url.encode("utf-8")).hexdigest()[:12]
    return cache_dir / f"{slug}-{cache_key}.json"


def load_cached_inventory(cache_path: Path, expected_url: str) -> list[RemoteFile]:
    with cache_path.open("r", encoding="utf-8") as cache_file:
        payload = json.load(cache_file)

    if payload.get("directory_url") != expected_url:
        raise ValueError("cache was created for a different directory URL")

    files = payload.get("files")
    if not isinstance(files, list):
        raise ValueError("cache does not contain a valid file list")

    cached_files: list[RemoteFile] = []
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("cache contains an invalid file entry")
        relative_path = item.get("relative_path")
        url = item.get("url")
        if not isinstance(relative_path, str) or not isinstance(url, str):
            raise ValueError("cache contains an invalid file record")
        cached_files.append(RemoteFile(relative_path=relative_path, url=url))

    return cached_files


def save_cached_inventory(cache_path: Path, directory_url: str, remote_files: list[RemoteFile]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "directory_url": directory_url,
        "files": [
            {"relative_path": remote_file.relative_path, "url": remote_file.url}
            for remote_file in remote_files
        ],
    }
    with cache_path.open("w", encoding="utf-8") as cache_file:
        json.dump(payload, cache_file, ensure_ascii=True, indent=2)
        cache_file.write("\n")


def get_directory_inventory(
    directory_name: str,
    directory_url: str,
    cache_dir: Path,
    refresh_cache: bool,
) -> list[RemoteFile]:
    cache_path = inventory_cache_path(cache_dir, directory_name, directory_url)
    if not refresh_cache and cache_path.is_file():
        try:
            cached_files = load_cached_inventory(cache_path, directory_url)
            status(f"Using cached inventory: {directory_name}")
            return cached_files
        except Exception as exc:
            status(f"Ignoring invalid inventory cache {cache_path}: {exc}")

    status(f"Scanning directory: {directory_name}")
    remote_files = crawl_directory(directory_url, f"{directory_name}/")
    save_cached_inventory(cache_path, directory_url, remote_files)
    status(f"Saved inventory cache: {directory_name}")
    return remote_files


def load_local_files(download_path: Path) -> set[str]:
    if not download_path.is_dir():
        return set()

    local_files: set[str] = set()
    for file_path in download_path.rglob("*"):
        if file_path.is_file():
            local_files.add(file_path.relative_to(download_path).as_posix())
    return local_files


def ensure_download_parent_exists(download_path: Path) -> None:
    parent = download_path.parent
    if not parent.is_dir():
        raise SystemExit(f"Error: parent directory does not exist: {parent}")


def print_summary(remote_files: list[RemoteFile], local_files: set[str], missing_files: list[RemoteFile]) -> None:
    print("\nSummary:")
    print(f"  Remote files found: {len(remote_files)}")
    print(f"  Local files found:  {len(local_files)}")
    print(f"  Missing downloads:  {len(missing_files)}")


def print_missing_files(missing_files: list[RemoteFile]) -> None:
    print("\nMissing files:")
    for index, remote_file in enumerate(missing_files, start=1):
        print(f"{index}. {remote_file.relative_path}")
        print(f"   source: {remote_file.url}")


def print_root_directories(root_directories: list[tuple[str, str]]) -> None:
    print("\nDirectories available at the root:")
    for index, (directory_name, _) in enumerate(root_directories, start=1):
        print(f"{index}. {directory_name}")


def parse_directory_selection(raw_value: str, root_directories: list[tuple[str, str]]) -> list[tuple[str, str]]:
    selected: list[tuple[str, str]] = []
    seen_directory_names: set[str] = set()
    directory_map = {
        directory_name.lower(): (directory_name, directory_url)
        for directory_name, directory_url in root_directories
    }

    normalized_value = raw_value.replace(",", "\n")
    for token in (part.strip() for part in normalized_value.splitlines()):
        if not token:
            continue

        directory: tuple[str, str] | None = None
        if token.isdigit():
            index = int(token)
            if 1 <= index <= len(root_directories):
                directory = root_directories[index - 1]
        else:
            directory = directory_map.get(token.lower())

        if directory is None:
            raise ValueError(f"Invalid selection: {token}")

        directory_name = directory[0]
        if directory_name not in seen_directory_names:
            selected.append(directory)
            seen_directory_names.add(directory_name)

    if not selected:
        raise ValueError("No directories were selected.")

    return selected


def select_root_directories_with_fzf(root_directories: list[tuple[str, str]]) -> list[tuple[str, str]]:
    directory_names = [directory_name for directory_name, _ in root_directories]
    choices = "\n".join(directory_names)
    result = subprocess.run(
        [
            "fzf",
            "--multi",
            "--prompt",
            "Directories> ",
            "--header",
            "Tab marks, Enter confirms",
        ],
        input=choices,
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:
        raise ValueError("Selection cancelled by user.")

    return parse_directory_selection(result.stdout, root_directories)


def select_root_directories(root_directories: list[tuple[str, str]], selector_mode: str) -> list[tuple[str, str]]:
    use_fzf = selector_mode in {"auto", "fzf"}
    if use_fzf and shutil.which("fzf") and sys.stdin.isatty() and sys.stdout.isatty():
        return select_root_directories_with_fzf(root_directories)

    if selector_mode == "fzf":
        raise ValueError("fzf selector requested, but fzf is not available in this terminal.")

    try:
        if selector_mode in {"auto", "curses"} and sys.stdin.isatty() and sys.stdout.isatty():
            return curses.wrapper(run_directory_selector, root_directories)
    except curses.error:
        pass

    if selector_mode == "curses":
        raise ValueError("curses selector requested, but no interactive terminal is available.")

    print_root_directories(root_directories)
    print("\nFallback mode: enter directory names separated by commas.")

    while True:
        answer = input("Directories: ").strip()
        try:
            return parse_directory_selection(answer, root_directories)
        except ValueError as exc:
            print(f"Error: {exc}")


def draw_directory_selector(
    screen: curses.window,
    root_directories: list[tuple[str, str]],
    filtered_indexes: list[int],
    selected_indexes: set[int],
    current_index: int,
    scroll_offset: int,
    search_term: str,
) -> None:
    screen.erase()
    height, width = screen.getmaxyx()
    visible_rows = max(1, height - 4)

    title = "Arrows move, space toggles, Enter confirms, a selects all, n clears"
    screen.addnstr(0, 0, title, width - 1)
    search_line = f"Search: {search_term}"
    screen.addnstr(1, 0, search_line, width - 1)

    end_index = min(len(filtered_indexes), scroll_offset + visible_rows)
    for row, filtered_position in enumerate(range(scroll_offset, end_index), start=2):
        directory_index = filtered_indexes[filtered_position]
        directory_name = root_directories[directory_index][0]
        marker = "[x]" if directory_index in selected_indexes else "[ ]"
        line = f"{marker} {directory_name}"
        attributes = curses.A_REVERSE if filtered_position == current_index else curses.A_NORMAL
        screen.addnstr(row, 0, line, width - 1, attributes)

    footer = f"Selected: {len(selected_indexes)} | Visible: {len(filtered_indexes)}"
    screen.addnstr(height - 1, 0, footer, width - 1)
    screen.refresh()


def filter_root_directories(root_directories: list[tuple[str, str]], search_term: str) -> list[int]:
    lowered_search = search_term.lower()
    return [
        index
        for index, (directory_name, _) in enumerate(root_directories)
        if lowered_search in directory_name.lower()
    ]


def run_directory_selector(screen: curses.window, root_directories: list[tuple[str, str]]) -> list[tuple[str, str]]:
    curses.curs_set(0)
    screen.keypad(True)

    current_index = 0
    scroll_offset = 0
    search_term = ""
    selected_indexes: set[int] = set()

    while True:
        height, _ = screen.getmaxyx()
        visible_rows = max(1, height - 4)
        filtered_indexes = filter_root_directories(root_directories, search_term)

        if not filtered_indexes:
            current_index = 0
            scroll_offset = 0
        else:
            current_index = min(current_index, len(filtered_indexes) - 1)

            if current_index < scroll_offset:
                scroll_offset = current_index
            elif current_index >= scroll_offset + visible_rows:
                scroll_offset = current_index - visible_rows + 1

        draw_directory_selector(
            screen,
            root_directories,
            filtered_indexes,
            selected_indexes,
            current_index,
            scroll_offset,
            search_term,
        )
        key = screen.getch()

        if key in (curses.KEY_BACKSPACE, 127, 8):
            search_term = search_term[:-1]
            current_index = 0
            scroll_offset = 0
            continue

        if key == ord("a"):
            selected_indexes.update(filtered_indexes)
            continue

        if key == ord("n"):
            selected_indexes.difference_update(filtered_indexes)
            continue

        if key in (curses.KEY_UP, ord("k")):
            if filtered_indexes:
                current_index = max(0, current_index - 1)
            continue

        if key in (curses.KEY_DOWN, ord("j")):
            if filtered_indexes:
                current_index = min(len(filtered_indexes) - 1, current_index + 1)
            continue

        if key == ord(" "):
            if not filtered_indexes:
                continue
            directory_index = filtered_indexes[current_index]
            if directory_index in selected_indexes:
                selected_indexes.remove(directory_index)
            else:
                selected_indexes.add(directory_index)
            continue

        if key in (10, 13, curses.KEY_ENTER):
            if not selected_indexes:
                continue
            return [root_directories[index] for index in sorted(selected_indexes)]

        if key in (27, ord("q")):
            raise ValueError("Selection cancelled by user.")

        if 32 <= key <= 126:
            search_term += chr(key)
            current_index = 0
            scroll_offset = 0


def confirm_download() -> bool:
    while True:
        answer = input("Download missing files? [y/N] ").strip().lower()
        if answer in {"", "n", "no"}:
            return False
        if answer in {"y", "yes"}:
            return True


def download_file(url: str, target_path: Path, timeout: int = 300) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        print(f"[Already exists] {target_path}")
        return

    print(f"[Downloading] {target_path}")
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        with target_path.open("wb") as target_file:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                target_file.write(chunk)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inventory and download samples from the remote Vengeance index.",
    )
    parser.add_argument("--base-url", default=BASE_URL_DEFAULT, help="Base URL for the remote directory listing")
    parser.add_argument("--download-path", default=DOWNLOAD_PATH_DEFAULT, help="Local destination directory")
    parser.add_argument("--directories", help="Directories to download, comma-separated; accepts name or index")
    parser.add_argument(
        "--selector",
        choices=("auto", "fzf", "curses", "prompt"),
        default="auto",
        help="Directory selector to use when --directories is not provided",
    )
    parser.add_argument(
        "--root-cache",
        default=str(default_root_cache_path()),
        help="Path to the cached root directory list",
    )
    parser.add_argument(
        "--refresh-root-cache",
        action="store_true",
        help="Ignore the cached root directory list and fetch it again from the remote server",
    )
    parser.add_argument(
        "--inventory-cache-dir",
        default=str(default_inventory_cache_dir()),
        help="Directory used for cached per-folder inventories",
    )
    parser.add_argument(
        "--refresh-inventory-cache",
        action="store_true",
        help="Ignore cached per-folder inventories and scan selected folders again",
    )
    parser.add_argument("--yes", action="store_true", help="Download without prompting for confirmation")
    parser.add_argument("--inventory-only", action="store_true", help="Only list missing files")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    download_path = Path(os.path.expanduser(args.download_path))
    root_cache_path = Path(os.path.expanduser(args.root_cache))
    inventory_cache_dir = Path(os.path.expanduser(args.inventory_cache_dir))
    ensure_download_parent_exists(download_path)

    try:
        root_directories = get_root_directories(args.base_url, root_cache_path, args.refresh_root_cache)
    except Exception as exc:
        print(f"Failed to list remote directories: {exc}", file=sys.stderr)
        return 1

    if not root_directories:
        print("No directories were found at the remote root.", file=sys.stderr)
        return 1

    try:
        selected_directories = (
            parse_directory_selection(args.directories, root_directories)
            if args.directories
            else select_root_directories(root_directories, args.selector)
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    status("\nSelected directories:")
    for directory_name, _ in selected_directories:
        status(f"- {directory_name}")

    remote_files: list[RemoteFile] = []
    for directory_name, directory_url in selected_directories:
        try:
            before_count = len(remote_files)
            remote_files.extend(
                get_directory_inventory(
                    directory_name,
                    directory_url,
                    inventory_cache_dir,
                    args.refresh_inventory_cache,
                )
            )
            status(f"Finished directory: {directory_name} ({len(remote_files) - before_count} files found)")
        except Exception as exc:
            print(f"Failed to scan directory {directory_name}: {exc}", file=sys.stderr)
            return 1

    if not remote_files:
        print("No remote files were found.", file=sys.stderr)
        return 1

    local_files = load_local_files(download_path)
    missing_files = sorted(
        (remote_file for remote_file in remote_files if remote_file.relative_path not in local_files),
        key=lambda remote_file: remote_file.relative_path.lower(),
    )

    print_summary(remote_files, local_files, missing_files)

    if not missing_files:
        print(f"\nEverything already exists in {download_path}")
        return 0

    print_missing_files(missing_files)

    if args.inventory_only:
        print("\nInventory mode: no downloads will be started.")
        return 0

    print("\nStatus: the files above are available in the remote index and can be downloaded.")

    if not args.yes and not confirm_download():
        print("Download cancelled by user.")
        return 0

    for remote_file in missing_files:
        try:
            download_file(remote_file.url, download_path / remote_file.relative_path)
        except Exception as exc:
            print(f"[Failed] {remote_file.url} - {exc}", file=sys.stderr)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
