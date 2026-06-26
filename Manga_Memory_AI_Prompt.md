# Manga Memory AI

Build a Python project called "Manga Memory AI".

## Goal

Create an automated pipeline that takes a manga/manhwa series URL and generates a persistent memory database and summaries that I can later use to refresh my memory without rereading hundreds of chapters.

## Requirements

### 1. Downloader

- Download all chapter images from a source website.
- Store images chapter-wise.
- Support resuming interrupted downloads.
- Avoid re-downloading existing chapters.
- Add rate limiting and retry logic.
- Make the website parser modular so new sites can be added later.

### 2. Data organization

Folder structure:

data/
  series_name/
    chapter_001/
      001.jpg
      002.jpg
    chapter_002/
      ...
    metadata.json

### 3. Cleaning stage

- Remove duplicate pages.
- Remove obvious credit pages and advertisement pages when possible.
- Log removed files.

### 4. OCR stage

- Extract text from every image.
- Combine page text into a single chapter text file.

Output:

ocr/
  chapter_001.txt
  chapter_002.txt

### 5. AI summarization

For every chapter generate:

- Summary
- Characters introduced
- Character relationships
- Important items/powers
- Mysteries introduced
- Key events

Store as JSON.

Example:

{
 "chapter":1,
 "summary":"",
 "characters":[],
 "relationships":[],
 "important_items":[],
 "mysteries":[],
 "key_events":[]
}

### 6. Arc summarization

Every 20 chapters automatically generate:

- Arc summary
- Character progression
- Major reveals
- Timeline
- Things to remember before continuing

### 7. Memory refresh feature

Commands:

memory refresh 100

Output:

- Story so far
- Main characters
- Character relationships
- Important reveals
- Unresolved mysteries
- Things to remember before chapter 101

### 8. Technical requirements

- Python
- Playwright for website automation
- Pillow for image processing
- imagehash for duplicate detection
- EasyOCR for OCR
- SQLite for storage
- Modular architecture
- CLI commands
- Proper logging
- Configuration file support
- Progress bars
- Error handling

### 9. Project structure

src/
 downloader/
 cleaner/
 ocr/
 summarizer/
 database/
 cli/

Generate production-quality code incrementally and explain the setup process.
