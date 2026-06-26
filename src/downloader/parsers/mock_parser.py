import os
from pathlib import Path
from typing import List, Dict, Any
from playwright.sync_api import Page
from PIL import Image, ImageDraw, ImageFont
from src.downloader.base_parser import BaseParser

# Synthetic stories for mock testing
MOCK_CHAPTERS_DATA = {
    1.0: {
        "title": "The Awakening of Arthur",
        "pages": [
            "Manga Memory AI Test Suite.\nChapter 1: The Awakening.\nArthur, a young boy from Oak Village, discovers a hidden cave in the Whispering Woods.\nInside the cave, Arthur finds a glowing blue sword.",
            "Arthur touches the glowing blue sword and feels a surge of magical power.\nA mysterious voice echoes: 'You are the chosen one, Arthur.'\nSuddenly, Kai, Arthur's childhood rival, enters the cave and looks shocked."
        ]
    },
    2.0: {
        "title": "The Rival's Challenge",
        "pages": [
            "Chapter 2: The Rivalry.\nKai confronts Arthur, demanding he hand over the glowing blue sword.\nKai says, 'You are weak, Arthur! You cannot control such power.'\nArthur refuses to yield, holding the sword tight.",
            "Suddenly, a giant stone golem wakes up in the cave.\nThe golem attacks both Arthur and Kai.\nArthur uses the sword's power to shield them both.\nKai realizes they must work together to survive."
        ]
    }
}

class MockParser(BaseParser):
    def get_name(self) -> str:
        return "mock"

    def can_handle(self, url: str) -> bool:
        return url.startswith("mock://") or "mock" in url

    def get_chapters(self, page: Page, series_url: str) -> List[Dict[str, Any]]:
        # Simulated scrapable chapters list
        return [
            {"chapter_num": float(ch_num), "title": data["title"], "url": f"mock://chapter_{ch_num}"}
            for ch_num, data in MOCK_CHAPTERS_DATA.items()
        ]

    def get_pages(self, page: Page, chapter_url: str) -> List[str]:
        # Ex: "mock://chapter_1.0"
        try:
            ch_num = float(chapter_url.split("_")[-1])
        except ValueError:
            ch_num = 1.0
        
        pages_count = len(MOCK_CHAPTERS_DATA.get(ch_num, {}).get("pages", []))
        return [f"{chapter_url}/page_{i+1}" for i in range(pages_count)]

    @staticmethod
    def generate_mock_image(chapter_url: str, page_url: str, output_path: str) -> None:
        """Generates a synthetic image containing the story text for OCR verification."""
        try:
            ch_num = float(chapter_url.split("_")[-1])
        except ValueError:
            ch_num = 1.0
        
        try:
            page_idx = int(page_url.split("_")[-1]) - 1
        except ValueError:
            page_idx = 0
            
        story_text = MOCK_CHAPTERS_DATA.get(ch_num, {}).get("pages", ["No text"])[page_idx]
        
        # Create a blank white image
        width, height = 800, 1000
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        
        # Draw some border and decoration to make it look like a page
        draw.rectangle([10, 10, width-10, height-10], outline="black", width=3)
        draw.line([10, 100, width-10, 100], fill="gray", width=2)
        
        # Draw header
        draw.text((30, 40), f"Mock Manga Series - Ch {ch_num} - Page {page_idx+1}", fill="black")
        
        # Draw story text (simple word wrapping and printing)
        lines = []
        words = story_text.split()
        current_line = []
        for word in words:
            if "\n" in word:
                parts = word.split("\n")
                current_line.append(parts[0])
                lines.append(" ".join(current_line))
                current_line = [parts[1]]
            else:
                current_line.append(word)
                if len(" ".join(current_line)) > 45:
                    lines.append(" ".join(current_line))
                    current_line = []
        if current_line:
            lines.append(" ".join(current_line))
            
        y_text = 150
        for line in lines:
            draw.text((50, y_text), line, fill="black")
            y_text += 40
            
        # Add a mock "credit/ad" signature occasionally to test cleaner rules
        if page_idx == 0:
            # We add a common water-mark on first pages
            draw.text((50, 900), "Downloaded from MOCK-SCANLATIONS.com (ad page)", fill="gray")
            
        # Ensure path directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, "JPEG")
