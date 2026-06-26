import os
import sys
import time
import uuid
import logging
import threading
from pathlib import Path
from typing import Optional
from flask import Flask, jsonify, request, render_template_string

# Force UTF-8 encoding for standard output on Windows
if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.config import Config
from src.database.db_manager import DatabaseManager

app = Flask(__name__)

# Active background tasks status
active_tasks = {}
active_tasks_lock = threading.Lock()

# Custom Logging Handler to forward logs to our GUI task window
class FlaskTaskLogHandler(logging.Handler):
    def __init__(self, logs_list):
        super().__init__()
        self.logs_list = logs_list
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S"))

    def emit(self, record):
        try:
            msg = self.format(record)
            self.logs_list.append(msg)
        except Exception:
            self.handleError(record)

def run_pipeline_thread(task_id: str, series_id: int, step: str, start_chapter: Optional[float], 
                        end_chapter: Optional[float]):
    """Background worker thread to run pipeline tasks."""
    config = Config()
    db = DatabaseManager(config.db_path)
    
    with active_tasks_lock:
        active_tasks[task_id]["status"] = "running"
        logs_list = active_tasks[task_id]["logs"]

    # Attach our custom log handler to collect logs for this task
    log_handler = FlaskTaskLogHandler(logs_list)
    root_logger = logging.getLogger()
    root_logger.addHandler(log_handler)
    
    try:
        series = db.get_series(series_id)
        if not series:
            raise ValueError(f"Series with ID {series_id} not found.")

        series_name = series["name"]
        series_url = series["url"]

        # Downloader phase
        if step in ["download", "all"]:
            logging.info(f"--- STARTING DOWNLOAD STEP for '{series_name}' ---")
            from src.downloader.downloader import DownloaderManager
            downloader = DownloaderManager(config, db)
            downloader.download_series(series_name, series_url, start_chapter, end_chapter)
            logging.info("--- DOWNLOAD STEP COMPLETED ---")

        # Reload chapters list after download
        chapters = db.get_all_chapters(series_id)
        
        # Cleaner phase
        if step in ["clean", "all"]:
            logging.info(f"--- STARTING CLEAN STEP for '{series_name}' ---")
            from src.cleaner.image_cleaner import ImageCleaner
            cleaner = ImageCleaner(config, db)
            chapters_to_clean = [
                ch for ch in chapters 
                if ch["status"] == "downloaded" or (start_chapter <= ch["chapter_num"] <= end_chapter if start_chapter is not None else True)
            ]
            for ch in chapters_to_clean:
                cleaner.clean_chapter(series_name, ch["chapter_num"])
            logging.info("--- CLEAN STEP COMPLETED ---")

        # OCR phase
        if step in ["ocr", "all"]:
            logging.info(f"--- STARTING OCR STEP for '{series_name}' ---")
            from src.ocr.ocr_engine import OcrEngine
            ocr_engine = OcrEngine(config, db)
            # Re-fetch chapters to see updated clean status
            chapters = db.get_all_chapters(series_id)
            chapters_to_ocr = [
                ch for ch in chapters 
                if ch["status"] == "cleaned" or (start_chapter <= ch["chapter_num"] <= end_chapter if start_chapter is not None else True)
            ]
            for ch in chapters_to_ocr:
                ocr_engine.ocr_chapter(series_name, ch["chapter_num"])
            logging.info("--- OCR STEP COMPLETED ---")

        # Summarizer phase
        if step in ["summarize", "all"]:
            logging.info(f"--- STARTING SUMMARIZATION STEP for '{series_name}' ---")
            from src.summarizer.ai_summarizer import AiSummarizer
            summarizer = AiSummarizer(config, db)
            chapters = db.get_all_chapters(series_id)
            chapters_to_sum = [
                ch for ch in chapters 
                if ch["status"] == "ocr_completed" or (start_chapter <= ch["chapter_num"] <= end_chapter if start_chapter is not None else True)
            ]
            for ch in chapters_to_sum:
                summarizer.summarize_chapter(series_name, ch["chapter_num"])
                
                # Check for automatic arc summaries (every 20 chapters)
                from src.cli.main import check_and_trigger_arc_summaries
                check_and_trigger_arc_summaries(series_name, db, summarizer)
            logging.info("--- SUMMARIZATION STEP COMPLETED ---")

        with active_tasks_lock:
            active_tasks[task_id]["status"] = "completed"
            logging.info("--- TASK COMPLETED SUCCESSFULLY ---")

    except Exception as e:
        logging.error(f"Task failed with error: {e}")
        with active_tasks_lock:
            active_tasks[task_id]["status"] = "failed"
            active_tasks[task_id]["error"] = str(e)
    finally:
        # Clean up the handler
        root_logger.removeHandler(log_handler)


# --- REST API Routing ---

@app.route("/api/series", methods=["GET"])
def list_series():
    config = Config()
    db = DatabaseManager(config.db_path)
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM series ORDER BY name ASC;")
        rows = cursor.fetchall()
        series_list = []
        for r in rows:
            series_dict = dict(r)
            # Fetch count of chapters
            cursor.execute("SELECT COUNT(*) as count FROM chapters WHERE series_id = ?;", (r["id"],))
            series_dict["chapters_count"] = cursor.fetchone()["count"]
            series_list.append(series_dict)
        return jsonify(series_list)

@app.route("/api/series", methods=["POST"])
def add_series():
    data = request.json or {}
    name = data.get("name")
    url = data.get("url")
    if not name or not url:
        return jsonify({"error": "Name and URL are required."}), 400
        
    config = Config()
    db = DatabaseManager(config.db_path)
    series_id = db.get_or_create_series(name, url)
    return jsonify({"id": series_id, "name": name, "url": url})

@app.route("/api/series/<int:series_id>", methods=["GET"])
def get_series_detail(series_id):
    config = Config()
    db = DatabaseManager(config.db_path)
    series = db.get_series(series_id)
    if not series:
        return jsonify({"error": "Series not found"}), 404
        
    chapters = db.get_all_chapters(series_id)
    arcs = db.get_all_arcs(series_id)
    
    return jsonify({
        "series": series,
        "chapters": chapters,
        "arcs": arcs
    })

@app.route("/api/series/<int:series_id>/delete", methods=["POST"])
def delete_series(series_id):
    config = Config()
    db = DatabaseManager(config.db_path)
    series = db.get_series(series_id)
    if not series:
        return jsonify({"error": "Series not found"}), 404
        
    # Remove files from folder
    clean_series_name = series["name"].replace(" ", "_")
    series_dir = Path(config.downloader["base_dir"]) / clean_series_name
    ocr_dir = Path("ocr") / clean_series_name
    
    import shutil
    try:
        if series_dir.exists():
            shutil.rmtree(series_dir)
        if ocr_dir.exists():
            shutil.rmtree(ocr_dir)
    except Exception as e:
        print(f"Warning: Failed to delete folders during series cleanup: {e}")

    with db._get_connection() as conn:
        conn.execute("DELETE FROM series WHERE id = ?;", (series_id,))
        conn.commit()

    return jsonify({"success": True})

@app.route("/api/series/<int:series_id>/chapters/<string:chapter_num>/delete", methods=["POST"])
def delete_chapter(series_id, chapter_num):
    config = Config()
    db = DatabaseManager(config.db_path)
    series = db.get_series(series_id)
    if not series:
        return jsonify({"error": "Series not found"}), 404
        
    try:
        ch_num = float(chapter_num)
    except ValueError:
        return jsonify({"error": "Invalid chapter number"}), 400
        
    chapter = db.get_chapter(series_id, ch_num)
    if not chapter:
        return jsonify({"error": "Chapter not found"}), 404
        
    # Delete folder from disk
    download_dir_str = chapter.get("download_dir")
    if download_dir_str:
        download_dir = Path(download_dir_str)
        if download_dir.exists():
            import shutil
            try:
                shutil.rmtree(download_dir)
            except Exception as e:
                print(f"Warning: Failed to delete chapter folder: {e}")
                
    # Delete OCR file from disk
    ocr_file_str = chapter.get("ocr_file")
    if ocr_file_str:
        ocr_path = Path(ocr_file_str)
        if ocr_path.exists():
            try:
                ocr_path.unlink()
            except Exception as e:
                print(f"Warning: Failed to delete OCR file: {e}")
    else:
        # Fallback to standard OCR path structure
        clean_series_name = series["name"].replace(" ", "_")
        if ch_num.is_integer():
            ch_txt = f"chapter_{int(ch_num):03d}.txt"
        else:
            ch_txt = f"chapter_{int(ch_num):03d}_{str(ch_num).split('.')[-1]}.txt"
        ocr_path = Path("ocr") / clean_series_name / ch_txt
        if ocr_path.exists():
            try:
                ocr_path.unlink()
            except Exception as e:
                print(f"Warning: Failed to delete OCR file: {e}")

    # Remove from SQLite database (summaries are automatically cascade-deleted!)
    with db._get_connection() as conn:
        conn.execute("DELETE FROM chapters WHERE series_id = ? AND chapter_num = ?;", (series_id, ch_num))
        conn.commit()
        
    return jsonify({"success": True})


@app.route("/api/pipeline/run", methods=["POST"])
def run_pipeline():
    data = request.json or {}
    series_id = data.get("series_id")
    step = data.get("step", "all")
    start_chapter = data.get("start_chapter")
    end_chapter = data.get("end_chapter")

    if not series_id:
        return jsonify({"error": "Series ID is required."}), 400

    try:
        start_chapter = float(start_chapter) if start_chapter else None
    except ValueError:
        start_chapter = None

    try:
        end_chapter = float(end_chapter) if end_chapter else None
    except ValueError:
        end_chapter = None

    task_id = str(uuid.uuid4())
    
    with active_tasks_lock:
        active_tasks[task_id] = {
            "status": "pending",
            "step": step,
            "logs": ["Task initialized in background..."],
            "error": None
        }

    # Spawn thread
    t = threading.Thread(
        target=run_pipeline_thread,
        args=(task_id, series_id, step, start_chapter, end_chapter)
    )
    t.daemon = True
    t.start()

    return jsonify({"task_id": task_id})

@app.route("/api/tasks/<task_id>", methods=["GET"])
def get_task_status(task_id):
    with active_tasks_lock:
        task = active_tasks.get(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        return jsonify(task)

@app.route("/api/series/<int:series_id>/memory-refresh/<float:chapter_num>", methods=["GET"])
def get_memory_refresh(series_id, chapter_num):
    config = Config()
    db = DatabaseManager(config.db_path)
    series = db.get_series(series_id)
    if not series:
        return jsonify({"error": "Series not found"}), 404

    from src.summarizer.ai_summarizer import AiSummarizer
    summarizer = AiSummarizer(config, db)
    refresh_data = summarizer.generate_memory_refresh(series["name"], chapter_num)
    if not refresh_data:
        return jsonify({"error": "Could not generate memory refresh. Make sure summaries exist for chapters up to this point."}), 400
    
    return jsonify(refresh_data)

@app.route("/api/config", methods=["GET"])
def get_config_details():
    config = Config()
    # Mask API key for security, only send length or exists status
    key = config.gemini["api_key"]
    has_key = len(key) > 0
    masked_key = f"{key[:4]}...{key[-4:]}" if len(key) > 8 else ("Exists" if has_key else "Missing")
    return jsonify({
        "has_key": has_key,
        "masked_key": masked_key,
        "model": config.gemini["model"]
    })

@app.route("/api/config/save_key", methods=["POST"])
def save_api_key():
    data = request.json or {}
    key = data.get("api_key")
    if not key:
        return jsonify({"error": "API Key is required"}), 400
        
    config_path = Path("config.yaml")
    if not config_path.exists():
        return jsonify({"error": "config.yaml not found"}), 500

    import yaml
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}
            
        if "gemini" not in yaml_data:
            yaml_data["gemini"] = {}
        yaml_data["gemini"]["api_key"] = key
        
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(yaml_data, f, default_flow_style=False)
            
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": f"Failed to save API key: {e}"}), 500


from flask import send_from_directory

@app.route("/data/<path:filename>")
def serve_manga_image(filename):
    config = Config()
    base_dir = Path(config.downloader["base_dir"]).resolve()
    return send_from_directory(base_dir, filename)

@app.route("/favicon.ico")
def favicon():
    static_dir = Path(__file__).resolve().parent / "static"
    return send_from_directory(static_dir, "favicon.png", mimetype="image/png")

@app.route("/api/series/<int:series_id>/chapters/<string:chapter_num>/images", methods=["GET"])
def get_chapter_images(series_id, chapter_num):
    config = Config()
    db = DatabaseManager(config.db_path)
    series = db.get_series(series_id)
    if not series:
        return jsonify({"error": "Series not found"}), 404
        
    try:
        ch_num = float(chapter_num)
    except ValueError:
        return jsonify({"error": "Invalid chapter number"}), 400
        
    chapter = db.get_chapter(series_id, ch_num)
    if not chapter:
        return jsonify({"error": "Chapter not found"}), 404
        
    download_dir_str = chapter.get("download_dir")
    if not download_dir_str:
        return jsonify({"error": "Chapter not downloaded yet"}), 400
        
    download_dir = Path(download_dir_str)
    if not download_dir.exists():
        # Fallback to reconstructing standard folder path
        clean_series_name = series["name"].replace(" ", "_")
        if ch_num.is_integer():
            ch_folder = f"chapter_{int(ch_num):03d}"
        else:
            ch_folder = f"chapter_{int(ch_num):03d}_{str(ch_num).split('.')[-1]}"
        download_dir = Path(config.downloader["base_dir"]) / clean_series_name / ch_folder
        
    if not download_dir.exists():
        return jsonify({"error": "Chapter directory not found on disk"}), 404
        
    # Find all images and sort them alphabetically
    valid_exts = {".jpg", ".jpeg", ".png", ".webp"}
    images = []
    
    # Let's list files
    try:
        files = sorted(download_dir.iterdir())
        base_dir = Path(config.downloader["base_dir"]).resolve()
        for f in files:
            if f.is_file() and f.suffix.lower() in valid_exts:
                try:
                    rel_path = f.resolve().relative_to(base_dir)
                    images.append(f"/data/{rel_path.as_posix()}")
                except ValueError:
                    # Fallback path if it's not relative for some reason
                    images.append(f"/data/{series['name'].replace(' ', '_')}/{download_dir.name}/{f.name}")
    except Exception as e:
        return jsonify({"error": f"Failed to list images: {e}"}), 500
        
    return jsonify({
        "chapter_num": ch_num,
        "title": chapter.get("title", f"Chapter {ch_num}"),
        "images": images
    })

# --- Frontend Root ---
@app.route("/", methods=["GET"])
def home_ui():
    templates_dir = Path(__file__).resolve().parent / "templates"
    index_path = templates_dir / "index.html"
    if index_path.exists():
        with open(index_path, "r", encoding="utf-8") as f:
            return render_template_string(f.read())
    return "Error: index.html template not found. Please verify folder setup."

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="127.0.0.1", port=5000, debug=True)

