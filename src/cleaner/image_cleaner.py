import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from PIL import Image
import imagehash

from src.config import Config
from src.database.db_manager import DatabaseManager

logger = logging.getLogger("manga_memory.cleaner")

class ImageCleaner:
    def __init__(self, config: Config, db: DatabaseManager):
        self.config = config
        self.db = db
        self.remove_duplicates = self.config.cleaner["remove_duplicates"]
        self.duplicate_threshold = self.config.cleaner["duplicate_threshold"]
        self.remove_credits = self.config.cleaner["remove_credits"]
        # Convert blacklisted hex hashes to ImageHash objects
        self.blacklisted_hashes = [
            imagehash.hex_to_hash(h) for h in self.config.cleaner["blacklisted_hashes"]
        ]

    def _get_image_hash(self, img_path: Path) -> Tuple[Optional[imagehash.ImageHash], Optional[str]]:
        try:
            with Image.open(img_path) as img:
                # Use average hash for speed and robust similarity detection
                h = imagehash.average_hash(img)
                return h, str(h)
        except Exception as e:
            logger.error(f"Failed to calculate hash for {img_path}: {e}")
            return None, None

    def clean_chapter(self, series_name: str, chapter_num: float) -> Tuple[int, int]:
        """
        Cleans duplicate and credit pages from a chapter folder.
        Updates the chapter status in the database to 'cleaned'.
        Returns a tuple of (duplicates_removed, credits_removed).
        """
        series_id = self.db.get_or_create_series(series_name)
        chapter = self.db.get_chapter(series_id, chapter_num)
        if not chapter:
            logger.error(f"Chapter {chapter_num} of series '{series_name}' not found in database.")
            return 0, 0

        download_dir_str = chapter["download_dir"]
        if not download_dir_str or not os.path.exists(download_dir_str):
            logger.error(f"Download directory for chapter {chapter_num} does not exist: {download_dir_str}")
            return 0, 0

        chapter_dir = Path(download_dir_str)
        # Find all images, sorted by name (page order)
        image_extensions = (".jpg", ".jpeg", ".png", ".webp")
        image_files = sorted(
            [f for f in chapter_dir.iterdir() if f.is_file() and f.suffix.lower() in image_extensions],
            key=lambda x: x.name
        )

        if not image_files:
            logger.warning(f"No images found in chapter folder {chapter_dir}")
            return 0, 0

        duplicates_removed = 0
        credits_removed = 0
        
        # Keep track of hashes in this chapter to find duplicates
        hashes: List[Tuple[Path, imagehash.ImageHash]] = []
        
        # Phase 1: Compute hashes and filter credit pages
        for img_path in image_files:
            if not img_path.exists():
                continue
                
            h, h_str = self._get_image_hash(img_path)
            if not h:
                continue

            # Check against blacklisted (credit) hashes
            is_credit = False
            if self.remove_credits:
                for b_hash in self.blacklisted_hashes:
                    # Difference of hashes (Hamming distance)
                    if h - b_hash <= self.duplicate_threshold:
                        is_credit = True
                        break
            
            if is_credit:
                logger.info(f"Removing credit page: {img_path.name} (matches blacklisted hash)")
                try:
                    img_path.unlink()
                    self.db.add_clean_log(
                        chapter_id=chapter["id"],
                        action="credit_removed",
                        file_name=img_path.name,
                        details=f"Matched blacklisted hash {h_str}"
                    )
                    credits_removed += 1
                except Exception as e:
                    logger.error(f"Failed to delete {img_path}: {e}")
            else:
                hashes.append((img_path, h))

        # Phase 2: Filter duplicates (comparing consecutive pages)
        if self.remove_duplicates and len(hashes) > 1:
            i = 0
            while i < len(hashes) - 1:
                curr_path, curr_hash = hashes[i]
                next_path, next_hash = hashes[i + 1]

                # Check if they are near-identical
                diff = curr_hash - next_hash
                if diff <= self.duplicate_threshold:
                    # Remove the duplicate (usually keep the first one, or the one that is larger in size,
                    # but typically deleting the second one is fine as it's a double post of the same scan)
                    logger.info(f"Removing duplicate page: {next_path.name} (diff {diff} <= {self.duplicate_threshold} to {curr_path.name})")
                    try:
                        next_path.unlink()
                        self.db.add_clean_log(
                            chapter_id=chapter["id"],
                            action="duplicate_removed",
                            file_name=next_path.name,
                            details=f"Duplicate of {curr_path.name} (hash diff: {diff})"
                        )
                        duplicates_removed += 1
                        # Remove from our processing list so we don't compare against it
                        hashes.pop(i + 1)
                        # Don't increment i, so we compare current with the new next page
                        continue
                    except Exception as e:
                        logger.error(f"Failed to delete duplicate {next_path}: {e}")
                
                i += 1

        # Mark chapter as cleaned in database
        self.db.update_chapter(chapter["id"], status="cleaned")
        logger.info(f"Chapter {chapter_num} cleaned. Duplicates removed: {duplicates_removed}, Credits removed: {credits_removed}.")
        
        return duplicates_removed, credits_removed
