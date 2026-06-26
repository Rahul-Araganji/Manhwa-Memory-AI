import os
import time
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Type
from playwright.sync_api import sync_playwright, Page, Browser
import requests

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

from src.config import Config
from src.database.db_manager import DatabaseManager
from src.downloader.base_parser import BaseParser
from src.downloader.parsers.mock_parser import MockParser
from src.downloader.parsers.vortex import VortexParser

logger = logging.getLogger("manga_memory.downloader")

class DownloaderManager:
    def __init__(self, config: Config, db: DatabaseManager):
        self.config = config
        self.db = db
        self.parsers: List[BaseParser] = [
            MockParser(),
            VortexParser()
            # New parser instances should be added here
        ]
        # Ensure base download directory exists
        self.base_dir = Path(self.config.downloader["base_dir"])
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _select_parser(self, url: str) -> BaseParser:
        for parser in self.parsers:
            if parser.can_handle(url):
                return parser
        # Default fallback or exception
        raise ValueError(f"No registered parser can handle URL: {url}")

    def download_image(self, url: str, output_path: Path, max_retries: int = 3) -> bool:
        """Downloads a single image from url and saves to output_path."""
        # For mock urls
        if url.startswith("mock://"):
            # Extract chapter url from page url (e.g. mock://chapter_1.0/page_1 -> mock://chapter_1.0)
            parts = url.split("/")
            chapter_url = "/".join(parts[:-1])
            MockParser.generate_mock_image(chapter_url, url, str(output_path))
            return True

        # Real web download
        delay = self.config.downloader["rate_limit_delay"]
        if delay > 0:
            time.sleep(delay)

        # Set correct Referer and disable Keep-Alive (Connection: close) to bypass CDN rate-limiting/throttling
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://vortexscans.org/",
            "Connection": "close"
        }

        # Attempt 1: curl-cffi (perfect Chrome impersonation to bypass TLS-based CDNs)
        if HAS_CURL_CFFI:
            for attempt in range(1, max_retries + 1):
                try:
                    # Note: curl_cffi has its own HTTP/2 and connection managers that handle keepalive gracefully,
                    # but we pass a clean Referer header and impersonate chrome.
                    response = curl_requests.get(
                        url, 
                        headers={"Referer": "https://vortexscans.org/"}, 
                        impersonate="chrome", 
                        timeout=25
                    )
                    if response.status_code == 200:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(output_path, "wb") as f:
                            f.write(response.content)
                        return True
                    else:
                        logger.warning(f"Failed to download image {url} via curl_cffi. Status code: {response.status_code}. Attempt {attempt}/{max_retries}")
                except Exception as e:
                    logger.debug(f"Error downloading image {url} via curl_cffi: {e}. Attempt {attempt}/{max_retries}")
                time.sleep(attempt * 0.5)

        # Attempt 2 (Fallback): requests.get with Connection: close
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.get(url, headers=headers, timeout=20)
                if response.status_code == 200:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(output_path, "wb") as f:
                        f.write(response.content)
                    return True
                else:
                    logger.warning(f"Failed to download image {url} via requests. Status code: {response.status_code}. Attempt {attempt}/{max_retries}")
            except Exception as e:
                logger.debug(f"Error downloading image {url} via requests: {e}. Attempt {attempt}/{max_retries}")
            
            # Attempt 3 (Fallback): urllib.request (uses Windows native Schannel SSL)
            try:
                import urllib.request
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as response:
                    if response.status == 200:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(output_path, "wb") as f:
                            f.write(response.read())
                        logger.info(f"Successfully downloaded image {url} via urllib fallback.")
                        return True
            except Exception as ue:
                logger.debug(f"Error downloading image {url} via urllib fallback: {ue}")

            # Attempt 4 (Fallback): curl.exe (native binary, immune to Python TLS fingerprinters)
            try:
                import subprocess
                cmd = ["curl.exe", "-s", "-L", "-o", str(output_path), "-H", "Referer: https://vortexscans.org/", "-H", "Connection: close", url]
                res = subprocess.run(cmd, capture_output=True, timeout=20)
                if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    logger.info(f"Successfully downloaded image {url} via curl.exe fallback.")
                    return True
            except Exception as ce:
                logger.debug(f"Error downloading image {url} via curl.exe fallback: {ce}")

            time.sleep(attempt * 1.5) # backoff
        return False

    def download_series(self, series_name: str, url: str, start_chapter: Optional[float] = None, 
                        end_chapter: Optional[float] = None) -> List[float]:
        """
        Main pipeline step for downloading a series.
        Finds the parser, runs Playwright to fetch chapter list, maps them, and downloads pages.
        Returns a list of downloaded chapter numbers.
        """
        parser = self._select_parser(url)
        logger.info(f"Using parser '{parser.get_name()}' for URL: {url}")

        series_id = self.db.get_or_create_series(series_name, url)
        series_dir = self.base_dir / series_name.replace(" ", "_")
        series_dir.mkdir(parents=True, exist_ok=True)

        downloaded_chapters = []

        with sync_playwright() as p:
            # Playwright launch config
            headless = self.config.downloader["headless"]
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.set_default_timeout(self.config.downloader["timeout_ms"])

            if not url.startswith("mock://"):
                logger.info(f"Navigating to series page: {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=45000)

            # Get chapter list
            scraped_chapters = parser.get_chapters(page, url)
            logger.info(f"Found {len(scraped_chapters)} chapters.")

            # Filter chapters based on bounds
            chapters_to_download = []
            for ch in scraped_chapters:
                num = ch["chapter_num"]
                if start_chapter is not None and num < start_chapter:
                    continue
                if end_chapter is not None and num > end_chapter:
                    continue
                chapters_to_download.append(ch)

            # Sort chapters ascending by chapter number
            chapters_to_download.sort(key=lambda x: x["chapter_num"])

            for idx, ch in enumerate(chapters_to_download):
                ch_num = ch["chapter_num"]
                ch_title = ch.get("title", f"Chapter {ch_num}")
                ch_url = ch["url"]

                # Check if already processed
                existing_ch = self.db.get_chapter(series_id, ch_num)
                if existing_ch and existing_ch["status"] in ["downloaded", "cleaned", "ocr_completed", "summarized"]:
                    logger.info(f"Chapter {ch_num} is already downloaded or processed (status: {existing_ch['status']}). Skipping.")
                    continue

                logger.info(f"Downloading Chapter {ch_num}: {ch_title}...")
                
                # Create chapter DB entry
                chapter_id = self.db.get_or_create_chapter(
                    series_id=series_id,
                    chapter_num=ch_num,
                    title=ch_title,
                    status="downloading"
                )

                # Format chapter folder name (e.g. chapter_001 or chapter_012.5)
                # Keep leading zeros for sorting
                if ch_num.is_integer():
                    ch_folder = f"chapter_{int(ch_num):03d}"
                else:
                    ch_folder = f"chapter_{int(ch_num):03d}_{str(ch_num).split('.')[-1]}"
                
                chapter_dir = series_dir / ch_folder
                chapter_dir.mkdir(parents=True, exist_ok=True)

                # Scrape pages
                try:
                    if not ch_url.startswith("mock://") and parser.get_name() != "vortex":
                        page.goto(ch_url, wait_until="domcontentloaded", timeout=45000)
                    page_urls = parser.get_pages(page, ch_url)
                except Exception as e:
                    logger.error(f"Failed to navigate or load pages for Chapter {ch_num}: {e}")
                    self.db.update_chapter(chapter_id=chapter_id, status="failed")
                    continue
                logger.info(f"Chapter {ch_num} has {len(page_urls)} pages.")

                success_count = 0
                from concurrent.futures import ThreadPoolExecutor, as_completed
                
                # Download pages concurrently using a ThreadPoolExecutor (configurable, default 32 parallel workers)
                max_workers = self.config.downloader.get("max_workers", 32)
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {}
                    for p_idx, p_url in enumerate(page_urls):
                        ext = "jpg" # default
                        # Simple extension detection
                        if "." in p_url.split("/")[-1]:
                            poss_ext = p_url.split("/")[-1].split(".")[-1].lower()
                            if poss_ext in ["jpg", "jpeg", "png", "webp"]:
                                ext = poss_ext

                        filename = f"{p_idx+1:03d}.{ext}"
                        image_path = chapter_dir / filename
                        
                        future = executor.submit(self.download_image, p_url, image_path)
                        futures[future] = p_url
                        
                    for future in as_completed(futures):
                        p_url = futures[future]
                        try:
                            success = future.result()
                            if success:
                                success_count += 1
                        except Exception as e:
                            logger.error(f"Error downloading page image {p_url}: {e}")
                
                if success_count > 0:
                    self.db.update_chapter(
                        chapter_id=chapter_id,
                        status="downloaded",
                        download_dir=str(chapter_dir)
                    )
                    downloaded_chapters.append(ch_num)
                    logger.info(f"Successfully downloaded Chapter {ch_num} ({success_count}/{len(page_urls)} pages).")
                else:
                    self.db.update_chapter(chapter_id=chapter_id, status="failed")
                    logger.error(f"Failed to download any pages for Chapter {ch_num}.")

            browser.close()

        # Update metadata.json in series directory
        metadata_path = series_dir / "metadata.json"
        metadata = {
            "series_name": series_name,
            "url": url,
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "chapters_count": len(self.db.get_all_chapters(series_id))
        }
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4)

        return downloaded_chapters
