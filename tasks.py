import os
import re
import PyPDF2
import json
from celery import Celery
from celery.utils.log import get_task_logger
from utils.db import db
from utils.ollama import analyze_item_ollama
from redis import Redis

logger = get_task_logger(__name__)

# Use REDIS_URL from .env or default to Index 1
REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
app = Celery("tasks", broker=REDIS_URL, backend=REDIS_URL)

redis_client = Redis.from_url(REDIS_URL)

app.conf.beat_schedule = {
    "run-analysis-every-3-minutes": {
        "task": "analyze_unprocessed_items_task",
        "schedule": 180.0,  # seconds
    },
}


@app.task(name="analyze_unprocessed_items_task")
def analyze_unprocessed_items_task():
    lock_id = "lock_analyze_task"

    # 2. Try to acquire lock (nx=True means 'only if not exists')
    # ex=600 gives the lock a 10-minute timeout so it doesn't get stuck forever if a worker crashes
    acquire_lock = redis_client.set(lock_id, "true", nx=True, ex=600)

    if not acquire_lock:
        logger.info("Task is already running. Skipping this trigger.")
        return "skipped"

    try:
        logger.info("Lock acquired. Starting analysis...")

        sql = """
            SELECT 
                qi.id, qi.question_text, qi.choices, qi.correct_answer, 
                sr.id as sr_id, sr.slot_name, sr.material_path
            FROM questionnaire_items qi
            JOIN source_references sr ON qi.questionnaire_id = sr.id
            LEFT JOIN item_analysis ia ON qi.id = ia.item_id
            WHERE ia.item_id IS NULL 
            AND (qi.analysis_status IN ('pending', 'failed') OR qi.analysis_status IS NULL)
            LIMIT 10
        """
        pending_items: list = db.select(sql)

        if not pending_items:
            return

        pdf_cache = {}

        for item in pending_items:
            try:
                print(f"\n--- Processing Item {item['id']} ---")

                # Update status to 'processing' so we know the worker is active on this ID
                db.execute(
                    "UPDATE questionnaire_items SET analysis_status='processing' WHERE id=%s",
                    (item["id"],),
                )

                path = item["material_path"]
                if path not in pdf_cache:
                    pdf_cache[path] = _read_pdf_text(path)

                slot_text = pdf_cache[path]
                choices_dict = (
                    json.loads(item["choices"])
                    if isinstance(item["choices"], str)
                    else item["choices"]
                )
                context_chunks = _find_context_in_text(slot_text, choices_dict)

                analysis_result = analyze_item_ollama(
                    question=item["question_text"],
                    choices=choices_dict,
                    correct_answer=item["correct_answer"],
                    source_context=context_chunks,
                    slot_name=item["slot_name"],
                )

                if analysis_result and "A" in analysis_result:
                    # 1. Insert into analysis table
                    insert_sql = "INSERT INTO item_analysis (item_id, reasoning, source_reference) VALUES (%s, %s, %s)"
                    db.execute(
                        insert_sql,
                        (item["id"], json.dumps(analysis_result), item["sr_id"]),
                    )

                    # 2. Update status to 'done' (Matches your ENUM)
                    db.execute(
                        "UPDATE questionnaire_items SET analysis_status='done' WHERE id=%s",
                        (item["id"],),
                    )
                    print(f">>> [SUCCESS] Item {item['id']} marked as 'done'.")
                else:
                    print(f">>> [ERROR] Invalid AI response for Item {item['id']}.")
                    db.execute(
                        "UPDATE questionnaire_items SET analysis_status='failed' WHERE id=%s",
                        (item["id"],),
                    )

            except Exception as e:
                print(f">>> [FATAL] Item {item['id']} failed: {str(e)}")
                db.execute(
                    "UPDATE questionnaire_items SET analysis_status='failed' WHERE id=%s",
                    (item["id"],),
                )
    finally:
        redis_client.delete(lock_id)
        logger.info("Task complete. Lock released.")


def _read_pdf_text(path: str) -> str:
    """Helper to extract text from a single PDF path."""
    if not os.path.exists(path):
        return ""
    text = ""
    with open(path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            content = page.extract_text()
            if content:
                text += content + "\n"
    return text


def _get_structural_chunks(full_text: str) -> list[str]:
    """Groups text by Master Anchors and ignores standalone page numbers."""
    if not full_text:
        return []
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]
    chunks, current_block = [], []
    master_anchor_pattern = re.compile(
        r"^([IVXLCDM]+\.|(\d+\.[\d\.]+)|[A-Z]\.|\d+\.)", re.IGNORECASE
    )
    noise_pattern = re.compile(r"^\d+$")

    for line in lines:
        if noise_pattern.match(line):
            continue
        if master_anchor_pattern.match(line):
            if current_block:
                chunks.append("\n".join(current_block))
            current_block = [line]
        else:
            if not current_block:
                current_block = [line]
            else:
                current_block.append(line)
    if current_block:
        chunks.append("\n".join(current_block))
    return chunks


def _find_context_in_text(full_text: str, choices: dict) -> str:
    chunks = _get_structural_chunks(full_text)
    if not chunks or not choices:
        return ""

    # Words to ignore (connectors)
    ignore = {
        "in",
        "a",
        "the",
        "of",
        "and",
        "or",
        "to",
        "for",
        "with",
        "is",
        "on",
        "at",
        "by",
        "none",
        "these",
        "above",
    }
    all_found_contexts = []

    for letter, choice_text in choices.items():
        # Split choice into words: "standpipe system" -> ["standpipe", "system"]
        words = re.findall(r"\w+", str(choice_text).lower())
        tech_words = [w for w in words if w not in ignore and len(w) > 2]

        if not tech_words:
            continue

        for chunk in chunks:
            chunk_lower = chunk.lower()

            # HARD REQUIREMENT: Every single tech word MUST be present in this chunk
            if all(word in chunk_lower for word in tech_words):
                all_found_contexts.append(chunk)
                break  # Move to the next choice once a context is found

    return "\n---\n".join(all_found_contexts)
