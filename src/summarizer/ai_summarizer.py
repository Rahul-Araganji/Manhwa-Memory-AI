import os
import json
import logging
from typing import List, Dict, Any, Optional, Tuple

from src.config import Config
from src.database.db_manager import DatabaseManager

logger = logging.getLogger("manga_memory.summarizer")

class AiSummarizer:
    def __init__(self, config: Config, db: DatabaseManager):
        self.config = config
        self.db = db
        self.api_key = self.config.gemini["api_key"]
        self.model_name = self.config.gemini["model"]
        self._client_type = None
        self._client = None
        self._init_client()

    def _init_client(self):
        if not self.api_key:
            # Try to grab from environment just in case config didn't catch it
            self.api_key = os.environ.get("GEMINI_API_KEY", "")
        
        if not self.api_key:
            logger.warning("No GEMINI_API_KEY found in config or environment. Gemini API calls will fail unless configured.")
            return

        # Attempt to load the new google-genai SDK first
        try:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
            self._client_type = "genai"
            logger.info("Initialized Gemini client using new 'google-genai' SDK.")
        except ImportError:
            # Fall back to google-generativeai SDK
            try:
                import google.generativeai as genai_legacy
                genai_legacy.configure(api_key=self.api_key)
                self._client = genai_legacy.GenerativeModel(self.model_name)
                self._client_type = "generativeai"
                logger.info("Initialized Gemini client using legacy 'google-generativeai' SDK.")
            except ImportError:
                logger.error("Neither 'google-genai' nor 'google-generativeai' is installed.")

    def _call_gemini_json(self, prompt: str) -> Dict[str, Any]:
        """Calls Gemini and returns a parsed JSON response."""
        if not self._client:
            raise ValueError("Gemini client is not initialized. Please set GEMINI_API_KEY.")

        # Ensure we request JSON in the generation config if possible
        if self._client_type == "genai":
            from google.genai import types
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            )
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config
            )
            text_response = response.text
        elif self._client_type == "generativeai":
            # For the legacy library, self._client is the GenerativeModel instance
            response = self._client.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json", "temperature": 0.2}
            )
            text_response = response.text
        else:
            raise ValueError("No active Gemini client available.")

        # Clean code blocks markdown if present (e.g. ```json ... ```)
        text_response = text_response.strip()
        if text_response.startswith("```"):
            lines = text_response.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            text_response = "\n".join(lines).strip()

        return json.loads(text_response)

    def summarize_chapter(self, series_name: str, chapter_num: float) -> Optional[Dict[str, Any]]:
        """
        Loads the OCR text file for the chapter, sends it to Gemini for structured summarization,
        saves results to the database, and marks status as 'summarized'.
        """
        series_id = self.db.get_or_create_series(series_name)
        chapter = self.db.get_chapter(series_id, chapter_num)
        if not chapter:
            logger.error(f"Chapter {chapter_num} of series '{series_name}' not found in database.")
            return None

        ocr_file_str = chapter["ocr_file"]
        if not ocr_file_str or not os.path.exists(ocr_file_str):
            logger.error(f"OCR file for chapter {chapter_num} does not exist: {ocr_file_str}")
            return None

        with open(ocr_file_str, "r", encoding="utf-8") as f:
            ocr_text = f.read()

        if not ocr_text.strip():
            logger.warning(f"OCR text file {ocr_file_str} is empty.")
            ocr_text = "[No text was extracted during OCR step.]"

        prompt = f"""You are an expert Manga/Manhwa analyst. Your task is to summarize the following manga chapter based on the provided OCR text.
Note that the OCR text might contain scanning errors, credit page text, watermarks, or sound effects. Ignore advertisements, credits, and sound effects, and focus on the actual story.

Series Name: {series_name}
Chapter: {chapter_num}

OCR Text:
{ocr_text}

You must respond with a JSON object matching this exact schema:
{{
  "chapter": {chapter_num},
  "summary": "A concise paragraph summarizing the plot events of this chapter.",
  "characters": ["Name of character introduced or prominent in this chapter"],
  "relationships": ["Character Name A is the rival of Character Name B"],
  "important_items": ["Item name / power name (brief explanation)"],
  "mysteries": ["Unresolved mystery or question introduced in this chapter"],
  "key_events": ["Key plot point 1", "Key plot point 2"]
}}
"""

        logger.info(f"Summarizing Chapter {chapter_num} using Gemini...")
        try:
            summary_data = self._call_gemini_json(prompt)
            
            # Save to SQLite
            self.db.save_chapter_summary(
                chapter_id=chapter["id"],
                summary=summary_data.get("summary", ""),
                characters=summary_data.get("characters", []),
                relationships=summary_data.get("relationships", []),
                important_items=summary_data.get("important_items", []),
                mysteries=summary_data.get("mysteries", []),
                key_events=summary_data.get("key_events", [])
            )
            logger.info(f"Successfully summarized and saved Chapter {chapter_num}.")
            return summary_data
        except Exception as e:
            logger.error(f"Failed to summarize Chapter {chapter_num}: {e}")
            return None

    def summarize_arc(self, series_name: str, start_chapter: float, end_chapter: float) -> Optional[Dict[str, Any]]:
        """
        Aggregates chapter summaries from SQLite for the given range, uses Gemini
        to create an Arc Summary, and saves it to the SQLite database.
        """
        series_id = self.db.get_or_create_series(series_name)
        
        # Load chapter summaries in range
        chapters = self.db.get_all_chapters(series_id)
        chapters_in_range = [
            ch for ch in chapters 
            if start_chapter <= ch["chapter_num"] <= end_chapter
        ]

        if not chapters_in_range:
            logger.error(f"No chapters found in range [{start_chapter}, {end_chapter}] for series '{series_name}'.")
            return None

        # Gather summary JSONs
        summaries_data = []
        for ch in chapters_in_range:
            summary = self.db.get_chapter_summary(ch["id"])
            if summary:
                # Simplify representation to save prompt tokens
                summaries_data.append({
                    "chapter": ch["chapter_num"],
                    "title": ch["title"],
                    "summary": summary["summary"],
                    "characters": summary["characters"],
                    "relationships": summary["relationships"],
                    "important_items": summary["important_items"],
                    "mysteries": summary["mysteries"],
                    "key_events": summary["key_events"]
                })

        if not summaries_data:
            logger.error(f"No chapter summaries found in range [{start_chapter}, {end_chapter}] for series '{series_name}'. Cannot generate arc summary.")
            return None

        prompt = f"""You are an expert Manga/Manhwa analyst. Your task is to generate a comprehensive Arc Summary for chapters {start_chapter} to {end_chapter} based on the chapter-by-chapter summaries provided below.

Series Name: {series_name}
Chapters: {start_chapter} to {end_chapter}

Chapter Summaries List:
{json.dumps(summaries_data, indent=2)}

You must respond with a JSON object matching this exact schema:
{{
  "arc_summary": "A comprehensive summary of the story arc spanning these chapters.",
  "character_progression": {{
    "Character Name": "Brief description of their development, power-ups, or status changes during this arc."
  }},
  "major_reveals": [
    "Key reveal or twist that happened in this arc"
  ],
  "timeline": [
    "Chapter X: Description of key plot event"
  ],
  "things_to_remember": [
    "Important plot points, unresolved questions, or setups to keep in mind before continuing past chapter {end_chapter}."
  ]
}}
"""

        logger.info(f"Generating Arc Summary for chapters {start_chapter} to {end_chapter}...")
        try:
            arc_data = self._call_gemini_json(prompt)
            
            # Save to SQLite
            self.db.save_arc_summary(
                series_id=series_id,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                summary=arc_data.get("arc_summary", ""),
                character_progression=arc_data.get("character_progression", {}),
                major_reveals=arc_data.get("major_reveals", []),
                timeline=arc_data.get("timeline", []),
                things_to_remember=arc_data.get("things_to_remember", [])
            )
            logger.info(f"Successfully generated and saved Arc Summary for chapters {start_chapter}-{end_chapter}.")
            return arc_data
        except Exception as e:
            logger.error(f"Failed to generate Arc Summary for chapters {start_chapter}-{end_chapter}: {e}")
            return None

    def generate_memory_refresh(self, series_name: str, target_chapter: float) -> Optional[Dict[str, Any]]:
        """
        Gathers all arc summaries up to target_chapter, plus any remaining individual chapter summaries
        up to target_chapter, and synthesizes a master "Memory Refresh" JSON report using Gemini.
        """
        series_id = self.db.get_or_create_series(series_name)
        
        # 1. Get all arcs and filter those ending <= target_chapter
        all_arcs = self.db.get_all_arcs(series_id)
        matching_arcs = [arc for arc in all_arcs if arc["end_chapter"] <= target_chapter]
        matching_arcs.sort(key=lambda x: x["start_chapter"])

        max_arc_end = 0.0
        if matching_arcs:
            max_arc_end = max(arc["end_chapter"] for arc in matching_arcs)

        # 2. Get any individual chapters between max_arc_end and target_chapter
        all_chapters = self.db.get_all_chapters(series_id)
        matching_chapters = [
            ch for ch in all_chapters 
            if max_arc_end < ch["chapter_num"] <= target_chapter and ch["status"] == "summarized"
        ]
        matching_chapters.sort(key=lambda x: x["chapter_num"])

        if not matching_arcs and not matching_chapters:
            logger.error(f"No summaries found up to chapter {target_chapter} for series '{series_name}'. Cannot generate memory refresh.")
            return None

        # Format arcs and chapters data for the prompt
        arcs_prompt_data = []
        for arc in matching_arcs:
            arcs_prompt_data.append({
                "range": f"Chapters {arc['start_chapter']} to {arc['end_chapter']}",
                "summary": arc["summary"],
                "major_reveals": arc["major_reveals"],
                "things_to_remember": arc["things_to_remember"]
            })

        chapters_prompt_data = []
        for ch in matching_chapters:
            summary = self.db.get_chapter_summary(ch["id"])
            if summary:
                chapters_prompt_data.append({
                    "chapter": ch["chapter_num"],
                    "summary": summary["summary"],
                    "key_events": summary["key_events"]
                })

        next_chapter = target_chapter + 1
        # Handle float chapters nicely (e.g. if target_chapter is 100.5, next is 101 or 101.5, simple int cast is fine for formatting)
        if target_chapter.is_integer():
            next_chapter = int(target_chapter) + 1

        prompt = f"""You are an expert Manga/Manhwa analyst. Your task is to generate a comprehensive "Memory Refresh" report for a reader who is about to read chapter {next_chapter}. They want to refresh their memory on everything that has occurred in the story up to chapter {target_chapter}.

Based on the summaries of the story arcs and recent chapters below, synthesize a high-quality, cohesive, and easy-to-read report.

Series Name: {series_name}
Target Chapter: {target_chapter} (Reader is about to read chapter {next_chapter})

Arc Summaries:
{json.dumps(arcs_prompt_data, indent=2)}

Recent Chapters Summaries (not covered in arcs):
{json.dumps(chapters_prompt_data, indent=2)}

You must respond with a JSON object matching this exact schema:
{{
  "story_so_far": "A cohesive, beautifully written narrative summary of the story's main plot progression up to chapter {target_chapter}.",
  "main_characters": [
    {{ "name": "Character Name", "description": "Brief summary of who they are, their role, and current status/power level." }}
  ],
  "character_relationships": [
    "Description of key relationships and how they stand now (e.g., Arthur and Kai are now cooperating, but still rivals)."
  ],
  "important_reveals": [
    "Key reveal or twist that has been uncovered up to chapter {target_chapter}."
  ],
  "unresolved_mysteries": [
    "Mystery or question that is still unsolved."
  ],
  "things_to_remember": [
    "Plot points, setups, or character locations to keep fresh in mind before reading chapter {next_chapter}."
  ]
}}
"""

        logger.info(f"Synthesizing Memory Refresh up to chapter {target_chapter}...")
        try:
            refresh_data = self._call_gemini_json(prompt)
            return refresh_data
        except Exception as e:
            logger.error(f"Failed to generate Memory Refresh: {e}")
            return None

