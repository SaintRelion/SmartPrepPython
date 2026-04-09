# python
import os
import json
import random
import requests
import PyPDF2
from celery import Celery
from utils.db import db
from utils.ollama import generate_exam_ollama, infer_structure_ollama

# Use REDIS_URL from .env or default to Index 1
REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
app = Celery("tasks", broker=REDIS_URL, backend=REDIS_URL)


@app.task(name="process_material_task")
def process_material_task(material_id: int, file_path: str):
    print(f"\n[MATERIAL] >>> Processing ID: {material_id}")
    db.execute("UPDATE materials SET processed_by_ai = 1 WHERE id = %s", (material_id,))
    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Missing PDF: {file_path}")
        reader = PyPDF2.PdfReader(file_path)
        document_buffer = {}
        current_section = "Introduction"
        for page_num, page in enumerate(reader.pages):
            text = page.extract_text()
            if not text or len(text.strip()) < 50:
                continue
            chunks = [text[i : i + 1500] for i in range(0, len(text), 1500)]
            for chunk_idx, chunk in enumerate(chunks):
                print(f"[MATERIAL] Page {page_num+1} | Chunk {chunk_idx+1}")
                structured_data = infer_structure_ollama(chunk, current_section)
                if not structured_data:
                    continue
                for title, content in structured_data.items():
                    safe_title = str(title)[:100].strip()
                    if safe_title == current_section and safe_title in document_buffer:
                        document_buffer[safe_title] += "\n" + str(content)
                    else:
                        document_buffer[safe_title] = str(content)
                    current_section = safe_title
        for title, content in document_buffer.items():
            db.insert(
                "INSERT INTO sections (material_id, section_name, content) VALUES (%s, %s, %s)",
                (material_id, title, content),
            )
        db.execute(
            "UPDATE materials SET processed_by_ai = 2 WHERE id = %s", (material_id,)
        )
        print(f"[MATERIAL] <<< SUCCESS ID: {material_id}")
    except Exception as e:
        print(f"[MATERIAL] !!! FAILURE: {e}")
        db.execute(
            "UPDATE materials SET processed_by_ai = 0 WHERE id = %s", (material_id,)
        )
    finally:
        try:
            requests.post("http://localhost:8000/notify-update", timeout=5)
        except:
            pass


@app.task(name="process_exam_generation_task")
def process_exam_generation_task(exam_id: int):
    print(f"\n[EXAM GEN] >>> Starting Exam ID: {exam_id}")
    db.execute("UPDATE examinations SET processed_by_ai = 1 WHERE id = %s", (exam_id,))
    try:
        exam = db.select("SELECT * FROM examinations WHERE id = %s", (exam_id,))[0]
        mat_config = json.loads(exam["material_config"])
        for mat_id_str, total_requested in mat_config.items():
            mat_id = int(mat_id_str)
            sections = db.select(
                "SELECT id, section_name, content FROM sections WHERE material_id = %s",
                (mat_id,),
            )
            if not sections:
                continue
            remaining, attempts, sec_idx = total_requested, 0, 0
            while remaining > 0 and attempts < (total_requested * 3):
                sec = sections[sec_idx]
                num_to_gen = min(5, remaining)
                print(
                    f"[EXAM GEN] Attempt {attempts+1} | Section: {sec['section_name'][:30]} | Rem: {remaining}"
                )

                content = sec["content"]
                if len(content) > 4000:
                    start = random.randint(0, len(content) - 4000)
                    content = content[start : start + 4000]

                raw_qs = generate_exam_ollama(
                    exam["difficulty"], sec["section_name"], content, num_to_gen
                )

                if raw_qs:
                    # Let's see exactly what we got
                    print(f"[DEBUG] Raw AI Output Type: {type(raw_qs)}")

                    qs = (
                        raw_qs
                        if isinstance(raw_qs, list)
                        else raw_qs.get("questions", [raw_qs])
                    )

                    for q in qs:
                        if remaining <= 0:
                            break
                        try:
                            # Print the keys so we know exactly what Llama named them
                            print(
                                f"[DEBUG] Item Keys: {list(q.keys()) if isinstance(q, dict) else 'NOT A DICT'}"
                            )

                            q_text = q.get("question_text") or q.get("question")
                            q_ans = q.get("correct_answer") or q.get("answer")
                            q_choices = q.get("choices") or q.get("options")

                            # If it still fails here, we need to know WHY
                            if not q_text:
                                print("   - [SKIP] No Question Text found.")
                                continue

                            db.insert(
                                "INSERT INTO questions (examination_id, material_id, section_id, question_text, choices, correct_answer, difficulty) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                                (
                                    exam_id,
                                    mat_id,
                                    sec["id"],
                                    q_text,
                                    json.dumps(q_choices),
                                    q_ans,
                                    exam["difficulty"],
                                ),
                            )
                            remaining -= 1
                            print(f"   - [SUCCESS] Inserted. Remaining: {remaining}")
                        except Exception as insert_error:
                            # THIS IS THE MOST IMPORTANT PRINT
                            print(f"   - [CRITICAL INSERT ERROR]: {insert_error}")
                            continue
                sec_idx = (sec_idx + 1) % len(sections)
                attempts += 1
        db.execute(
            "UPDATE examinations SET processed_by_ai = 2 WHERE id = %s", (exam_id,)
        )
        print(f"[EXAM GEN] <<< COMPLETED ID: {exam_id}")
    except Exception as e:
        print(f"[EXAM GEN] !!! FAILURE: {e}")
        db.execute(
            "UPDATE examinations SET processed_by_ai = 0 WHERE id = %s", (exam_id,)
        )
    finally:
        try:
            requests.post("http://localhost:8000/notify-update", timeout=5)
        except:
            pass
