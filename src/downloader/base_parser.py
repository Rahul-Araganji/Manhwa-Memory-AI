from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple
from playwright.sync_api import Page

class BaseParser(ABC):
    @abstractmethod
    def get_name(self) -> str:
        """Returns the name/identifier of this parser."""
        pass

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Returns True if this parser can handle the given URL."""
        pass

    @abstractmethod
    def get_chapters(self, page: Page, series_url: str) -> List[Dict[str, Any]]:
        """
        Scrapes the series page and returns a list of chapters.
        Each chapter should be a dictionary:
        {
            "chapter_num": float,
            "title": str,
            "url": str
        }
        """
        pass

    @abstractmethod
    def get_pages(self, page: Page, chapter_url: str) -> List[str]:
        """
        Scrapes the chapter page and returns a list of image URLs.
        """
        pass
