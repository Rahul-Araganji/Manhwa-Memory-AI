import re
import logging
from typing import List, Dict, Any
from playwright.sync_api import Page
from src.downloader.base_parser import BaseParser

logger = logging.getLogger("manga_memory.downloader.vortex")

class VortexParser(BaseParser):
    def get_name(self) -> str:
        return "vortex"

    def can_handle(self, url: str) -> bool:
        return "vortexscans.org" in url

    def get_chapters(self, page: Page, series_url: str) -> List[Dict[str, Any]]:
        # Auto-expand the chapters list by clicking "Show more" button if it exists
        logger.info("Expanding chapter list (clicking 'Show more' buttons)...")
        consecutive_failures = 0
        for i in range(25): # Click up to 25 times to reveal all chapters
            try:
                # Target the button with text 'Show more'
                btn = page.get_by_role("button", name="Show more")
                if btn.count() > 0 and btn.first.is_visible():
                    btn.first.scroll_into_view_if_needed()
                    btn.first.click(force=True, timeout=3000)
                    page.wait_for_timeout(1200) # wait for older chapters to render
                    consecutive_failures = 0
                else:
                    # Double-check after a brief wait to ensure it's not a loading state
                    page.wait_for_timeout(500)
                    btn = page.get_by_role("button", name="Show more")
                    if btn.count() == 0 or not btn.first.is_visible():
                        break
            except Exception as e:
                logger.debug(f"Clicking 'Show more' attempt {i+1} failed: {e}")
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    logger.warning("Failed to click 'Show more' 3 times consecutively. Stopping expansion.")
                    break
                page.wait_for_timeout(1000) # wait for DOM to settle

        # Extract all anchor tags
        href_data = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a')).map(a => ({
                href: a.href,
                text: a.innerText
            }));
        }""")

        chapters_dict = {}
        for item in href_data:
            href = item.get("href", "")
            text = item.get("text", "").strip()

            # Filter for chapter URLs
            if "/chapter-" in href:
                try:
                    # Extract chapter number from URL (e.g. .../chapter-40 -> 40.0)
                    ch_part = href.split("chapter-")[-1]
                    # Clean up query params if any
                    ch_part = ch_part.split("?")[0].split("#")[0]
                    # Replace dashes with dots for decimal chapters (e.g. chapter-10-5 -> 10.5)
                    ch_part = ch_part.replace("-", ".")
                    
                    # Extract float number
                    match = re.search(r"(\d+\.?\d*)", ch_part)
                    if match:
                        ch_num = float(match.group(1))
                        # Deduplicate and clean text titles (e.g., 'Chapter 40 6 days' -> 'Chapter 40')
                        title_match = re.search(r"(Chapter\s+\d+(\.\d+)?)", text, re.IGNORECASE)
                        title = title_match.group(1) if title_match else f"Chapter {ch_num}"
                        
                        chapters_dict[ch_num] = {
                            "chapter_num": ch_num,
                            "title": title,
                            "url": href
                        }
                except Exception as e:
                    logger.debug(f"Failed to parse chapter number from {href}: {e}")

        chapters = list(chapters_dict.values())
        logger.info(f"VortexParser scraped {len(chapters)} unique chapters.")
        return chapters

    def get_pages(self, page: Page, chapter_url: str) -> List[str]:
        # VortexScans serves manga pages dynamically. We wait for images to load
        # Wait for selectors that contain image sources
        page.wait_for_timeout(2000)
        
        # Scrape all image source URLs
        img_srcs = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('img')).map(img => img.src);
        }""")

        # Filter for actual manga pages (which contain '/upload/series/')
        manga_pages = []
        for src in img_srcs:
            if src and "/upload/series/" in src:
                manga_pages.append(src)
                
        # Deduplicate while preserving order
        seen = set()
        dedup_pages = []
        for p in manga_pages:
            if p not in seen:
                seen.add(p)
                dedup_pages.append(p)

        logger.info(f"VortexParser found {len(dedup_pages)} manga page images.")
        return dedup_pages
