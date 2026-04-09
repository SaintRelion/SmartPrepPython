# python
import os
import json
import requests
import PyPDF2
from celery import Celery
from utils.db import db
from utils.ollama import generate_exam_ollama, infer_structure_ollama

# Use REDIS_URL from .env or default to Index 1
REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
app = Celery("tasks", broker=REDIS_URL, backend=REDIS_URL)


def chunk_text(text, size=2500):
    """Splits text into chunks without cutting words in half."""
    return [text[i : i + size] for i in range(0, len(text), size)]


@app.task(name="process_material_task")
def process_material_task(material_id: int, file_path: str):
    try:
        db.execute(
            "UPDATE materials SET processed_by_ai = 1 WHERE id = %s", (material_id,)
        )
        try:
            requests.post("http://localhost:8000/notify-update", timeout=5)
        except Exception:
            pass

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF not found at {file_path}")

        document_buffer = {}
        current_section = None
        reader = PyPDF2.PdfReader(file_path)

        for page_num, page in enumerate(reader.pages):
            full_page_text = page.extract_text()
            if not full_page_text or len(full_page_text.strip()) < 50:
                continue

            chunks = chunk_text(full_page_text)

            for chunk_index, chunk in enumerate(chunks):
                print(
                    f"Processing Material {material_id} | Page {page_num+1} | Chunk {chunk_index+1}"
                )

                # The Refetch Loop we built earlier
                structured_data = None
                for attempt in range(3):
                    try:
                        structured_data = infer_structure_ollama(chunk, current_section)
                        if structured_data:
                            break
                    except Exception as e:
                        print(f"Retry {attempt+1} failed: {e}")

                if not structured_data:
                    continue

                # Induction Loop: Merging chunks into the buffer
                for title, content in structured_data.items():
                    # Sanitize key to prevent MySQL 1406
                    safe_title = str(title)[:200].strip()

                    if safe_title == current_section and safe_title in document_buffer:
                        document_buffer[safe_title] += "\n" + str(content)
                    else:
                        document_buffer[safe_title] = str(content)

                    current_section = safe_title

        # Final insertion to DB
        for title, content in document_buffer.items():
            db.insert(
                "INSERT INTO sections (material_id, section_name, content) VALUES (%s, %s, %s)",
                (material_id, title, content),
            )

        db.execute(
            "UPDATE materials SET processed_by_ai = 2 WHERE id = %s", (material_id,)
        )

    except Exception as e:
        print(f"CRITICAL FAILURE: {e}")
        db.execute(
            "UPDATE materials SET processed_by_ai = 0 WHERE id = %s", (material_id,)
        )
    finally:
        try:
            requests.post("http://localhost:8000/notify-update", timeout=5)
        except Exception:
            pass


@app.task(name="process_exam_generation_task")
def process_exam_generation_task(exam_id: int):
    db.execute("UPDATE examinations SET processed_by_ai = 1 WHERE id = %s", (exam_id,))

    try:
        # Use select[0] instead of fetchone if that's your helper's pattern
        exam_rows = db.select("SELECT * FROM examinations WHERE id = %s", (exam_id,))
        if not exam_rows:
            raise Exception(f"Exam {exam_id} not found in database.")

        exam = exam_rows[0]
        # Ensure we are parsing the config dictionary correctly
        mat_config = json.loads(exam["material_config"])

        for mat_id_str, total_requested in mat_config.items():
            mat_id = int(mat_id_str)
            sections = db.select(
                "SELECT id, section_name, content FROM sections WHERE material_id = %s",
                (mat_id,),
            )

            if not sections:
                continue

            remaining = total_requested
            sec_index = 0
            num_sections = len(sections)
            total_attempts = 0
            max_attempts = total_requested * 5

            while remaining > 0 and total_attempts < max_attempts:
                sec = sections[sec_index]

                # Determine batch size (Standard 5, or whatever is left)
                num_to_gen = min(5, remaining)

                print(
                    f"Requesting {num_to_gen} items from Sec: {sec['section_name']} (Remaining: {remaining})"
                )

                questions_raw = generate_exam_ollama(
                    difficulty=exam["difficulty"],
                    section_name=sec["section_name"],
                    content=sec["content"],
                    num_items=num_to_gen,
                )

                # Normalize (Handling the AI's "questions" wrapper shit)
                questions = []
                if isinstance(questions_raw, list):
                    questions = questions_raw
                elif isinstance(questions_raw, dict):
                    questions = questions_raw.get("questions", [questions_raw])

                # Forensic Insertion
                for q in questions:
                    if remaining <= 0:
                        break
                    if not isinstance(q, dict):
                        continue

                    try:
                        # Absolute check for required keys
                        q_text = q["question_text"]
                        q_choices = q["choices"]
                        q_ans = q["correct_answer"]

                        db.insert(
                            """INSERT INTO questions 
                            (examination_id, material_id, section_id, question_text, choices, correct_answer, difficulty) 
                            VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                            (
                                int(exam_id),
                                mat_id,
                                sec["id"],
                                q_text,
                                json.dumps(q_choices),
                                q_ans,
                                exam["difficulty"],
                            ),
                        )
                        remaining -= 1  # Successful DB commit
                    except KeyError:
                        continue  # Skip messy AI output

                # Circular Logic: Move to next or restart
                sec_index += 1
                if sec_index >= num_sections:
                    sec_index = 0  # Loop back to the first section

                total_attempts += 1

            if remaining > 0:
                print(
                    f"Warning: Material {mat_id} exhausted. Could only generate {total_requested - remaining} items."
                )

        db.execute(
            "UPDATE examinations SET processed_by_ai = 2 WHERE id = %s", (exam_id,)
        )

    except Exception as e:
        print(f"Task Failed: {e}")
        db.execute(
            "UPDATE examinations SET processed_by_ai = 0 WHERE id = %s", (exam_id,)
        )
    finally:
        try:
            requests.post("http://localhost:8000/notify-update", timeout=5)
        except:
            pass
