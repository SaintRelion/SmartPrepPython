from datetime import datetime
import os
import re
import PyPDF2
import json
from celery import Celery
from celery.utils.log import get_task_logger
from api.analytics.helper import get_calculated_exam_stats
from utils.db import db
from utils.ollama import (
    analyze_attempt_ollama,
    analyze_item_distribution_ollama,
    analyze_item_ollama,
)
from redis import Redis

logger = get_task_logger(__name__)

# Redis defaults to localhost for direct/local execution.
# Docker Compose overrides REDIS_HOST to the internal Redis service name.
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
REDIS_DB = os.getenv("REDIS_DB", "1")
REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

app = Celery("tasks", broker=REDIS_URL, backend=REDIS_URL)
redis_client = Redis.from_url(REDIS_URL)

app.conf.beat_schedule = {
    "run-exam-item-analysis-every-3-minutes": {
        "task": "analyze_unprocessed_exam_items_task",
        "schedule": 180.0,
    },
    "run-attempt-analysis-every-2-minutes": {
        "task": "analyze_unprocessed_attempts_task",
        "schedule": 120.0,
    },
    "run-question-item-analysis-every-3-minutes": {
        "task": "analyze_unprocessed_question_items_task",
        "schedule": 180.0,  # seconds
    },
}


@app.task(name="analyze_unprocessed_exam_items_task", queue="exam_item_queue")
def analyze_unprocessed_exam_items_task():
    lock_id = "lock_exam_item_analysis"
    acquire_lock = redis_client.set(lock_id, "true", nx=True, ex=600)
    if not acquire_lock:
        logger.info("Item analysis task already running. Skipping.")
        return "skipped"
    try:
        pending = db.select("""
            SELECT examination_id, date
            FROM examination_item_analysis
            WHERE NULLIF(TRIM(COALESCE(analysis, '')), '') IS NULL
            GROUP BY examination_id, date
            LIMIT 5
        """)

        logger.info(
            f"[item_analysis] Pending batches found: {len(pending) if pending else 0}"
        )

        if not pending:
            logger.info("[item_analysis] Nothing to process. Exiting.")
            return

        for batch in pending:
            try:
                exam_id = batch["examination_id"]
                date = str(batch["date"])

                logger.info(f"[item_analysis] Processing exam_id={exam_id} date={date}")

                rows = db.select(
                    """
                    SELECT id, question_id, distribution
                    FROM examination_item_analysis
                    WHERE examination_id = %s AND date = %s
                    AND NULLIF(TRIM(COALESCE(analysis, '')), '') IS NULL
                    """,
                    (exam_id, date),
                )

                logger.info(
                    f"[item_analysis] exam_id={exam_id} date={date} — rows to analyze: {len(rows) if rows else 0}"
                )

                if not rows:
                    logger.warning(
                        f"[item_analysis] No rows for exam_id={exam_id} date={date}, skipping."
                    )
                    continue

                question_ids = [r["question_id"] for r in rows]
                placeholders = ",".join(["%s"] * len(question_ids))
                questions = db.select(
                    f"SELECT id, question_text, correct_answer FROM questionnaire_items WHERE id IN ({placeholders})",
                    tuple(question_ids),
                )
                question_map = {str(q["id"]): q for q in questions}

                logger.info(
                    f"[item_analysis] exam_id={exam_id} — question meta fetched: {len(questions)}, mapped: {len(question_map)}"
                )

                missing_meta = [
                    str(r["question_id"])
                    for r in rows
                    if str(r["question_id"]) not in question_map
                ]
                if missing_meta:
                    logger.warning(
                        f"[item_analysis] exam_id={exam_id} — missing question meta for IDs: {missing_meta}"
                    )

                written, skipped = 0, 0

                for r in rows:
                    qid = str(r["question_id"])
                    dist = json.loads(r["distribution"])
                    meta = question_map.get(qid, {})
                    total = sum(dist.get(k, 0) for k in ("A", "B", "C", "D"))

                    item = {
                        "question_id": qid,
                        "question_text": meta.get("question_text", ""),
                        "correct_answer": meta.get("correct_answer", ""),
                        "distribution": {
                            "A": dist.get("A", 0),
                            "B": dist.get("B", 0),
                            "C": dist.get("C", 0),
                            "D": dist.get("D", 0),
                            "total": total,
                        },
                    }

                    logger.info(
                        f"[item_analysis] exam_id={exam_id} — analyzing question_id={qid} row_id={r['id']}"
                    )

                    result = analyze_item_distribution_ollama(
                        examination_id=exam_id,
                        date=date,
                        items=[item],
                    )

                    if not result:
                        logger.warning(
                            f"[item_analysis] exam_id={exam_id} — no result for question_id={qid} row_id={r['id']}, skipping."
                        )
                        skipped += 1
                        continue

                    analysis_map = result.get("analysis", {})
                    per_question = analysis_map.get(qid, "")

                    if not per_question:
                        logger.warning(
                            f"[item_analysis] exam_id={exam_id} — Ollama returned empty analysis for question_id={qid}. Keys returned: {list(analysis_map.keys())}"
                        )
                        skipped += 1
                    else:
                        logger.info(
                            f"[item_analysis] exam_id={exam_id} — question_id={qid} analysis: {per_question}"
                        )
                        written += 1

                    db.update(
                        """
                        UPDATE examination_item_analysis
                        SET analysis = %s, calculated_at = NOW()
                        WHERE id = %s
                        """,
                        (per_question, r["id"]),
                    )

                logger.info(
                    f"[item_analysis] exam_id={exam_id} date={date} — done. written={written} skipped={skipped}"
                )

            except Exception as e:
                logger.error(
                    f"[item_analysis] Error processing batch {batch}: {e}",
                    exc_info=True,
                )
                continue
    finally:
        redis_client.delete(lock_id)


@app.task(name="analyze_unprocessed_attempts_task", queue="exam_attempts_queue")
def analyze_unprocessed_attempts_task():
    lock_id = "lock_exam_attempt_analysis"
    acquire_lock = redis_client.set(lock_id, "true", nx=True, ex=600)

    if not acquire_lock:
        logger.info("Attempt analysis task running. Skipping.")
        return "skipped"

    try:
        sql = """
            SELECT id, user_id, examination_id, attempt_index 
            FROM examination_attempt_analysis 
            WHERE analysis IS NULL OR analysis = ''
            LIMIT 10
        """
        pending_attempts = db.select(sql)

        if not pending_attempts:
            return

        for attempt in pending_attempts:
            try:
                # 1. Fetch this specific user's stats
                stats = get_calculated_exam_stats(
                    examination_id=attempt["examination_id"], user_id=attempt["user_id"]
                )

                topics = stats["topic_breakdown"]

                worst_first_topics = sorted(topics, key=lambda x: x["percentage"])

                analysis_result = analyze_attempt_ollama(
                    exam_name="Exam",  # Fetch this from your DB if needed
                    overall_accuracy=stats["overall_competency"],
                    topic_breakdown=worst_first_topics,  # Now it has the full context!
                )

                if analysis_result and "summary" in analysis_result:
                    db.execute(
                        "UPDATE examination_attempt_analysis SET analysis=%s WHERE id=%s",
                        (json.dumps(analysis_result), attempt["id"]),
                    )
                logger.info(f"Attempt {attempt['id']} analyzed successfully.")

            except Exception as e:
                logger.error(f"Failed to analyze attempt {attempt['id']}: {e}")

    finally:
        redis_client.delete(lock_id)


@app.task(name="analyze_unprocessed_question_items_task", queue="question_item_queue")
def analyze_unprocessed_question_items_task():
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

            if all(word in chunk_lower for word in tech_words):
                all_found_contexts.append(chunk)
                break  # Move to the next choice once a context is found

    return "\n---\n".join(all_found_contexts)
