#!/usr/bin/env python3

from __future__ import annotations

import argparse
import curses
import os
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote_plus, urljoin
from urllib.request import Request, urlopen


BASE_URL_DEFAULT = "https://files.lyberry.com/audio/sounds/Vengeance%20Samples/"
DOWNLOAD_PATH_DEFAULT = "/mnt/c/Vengeance Samples"
USER_AGENT = "some-scripts/1.0"


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
    for href in parser.links:
        if not href:
            continue
        if href.startswith("?"):
            continue
        if href.startswith("/"):
            continue
        if "../" in href:
            continue
        filtered_links.append(href)
    return filtered_links


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


def crawl_directory(url: str, relative_prefix: str = "") -> list[RemoteFile]:
    remote_files: list[RemoteFile] = []

    for href in fetch_links(url):
        full_url = urljoin(url, href)
        if href.endswith("/"):
            child_prefix = f"{relative_prefix}{sanitize_relative_path(href[:-1])}/"
            remote_files.extend(crawl_directory(full_url, child_prefix))
            continue

        relative_path = f"{relative_prefix}{sanitize_relative_path(href)}"
        remote_files.append(RemoteFile(relative_path=relative_path, url=full_url))

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

    for token in (part.strip() for part in raw_value.split(",")):
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


def select_root_directories(root_directories: list[tuple[str, str]]) -> list[tuple[str, str]]:
    try:
        if sys.stdin.isatty() and sys.stdout.isatty():
            return curses.wrapper(run_directory_selector, root_directories)
    except curses.error:
        pass

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
    parser.add_argument("--yes", action="store_true", help="Download without prompting for confirmation")
    parser.add_argument("--inventory-only", action="store_true", help="Only list missing files")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    download_path = Path(os.path.expanduser(args.download_path))
    ensure_download_parent_exists(download_path)

    print(f"Listing remote directories: {args.base_url}")
    try:
        root_directories = list_root_directories(args.base_url)
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
            else select_root_directories(root_directories)
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("\nSelected directories:")
    for directory_name, _ in selected_directories:
        print(f"- {directory_name}")

    remote_files: list[RemoteFile] = []
    for directory_name, directory_url in selected_directories:
        print(f"Scanning directory: {directory_name}")
        try:
            remote_files.extend(crawl_directory(directory_url, f"{directory_name}/"))
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
