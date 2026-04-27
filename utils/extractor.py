# python
import json
import re

from utils.db import db


def extract_questionnaire(slot_id: int, file_path: str):
    print(f"[EXTRACTOR] Processing Slot ID: {slot_id}")
    saved_count = 0
    skipped_count = 0

    try:
        import PyPDF2

        reader = PyPDF2.PdfReader(file_path)
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text() + "\n"

        extracted_data = heuristic_exam_extractor(full_text)

        for item in extracted_data:
            # CHECK: Why are items being skipped?
            if item["answer"] and len(item["choices"]) >= 2:
                db.execute(
                    """INSERT INTO questionnaire_items 
                       (questionnaire_id, question_text, choices, correct_answer) 
                       VALUES (%s, %s, %s, %s)""",
                    (
                        slot_id,
                        item["question_text"],
                        json.dumps(item["choices"]),
                        item["answer"],
                    ),
                )
                saved_count += 1
            else:
                skipped_count += 1
                # Solo Dev Tip: Print the faulty question text to see why regex failed
                print(
                    f"[DEBUG] Skipping item: {item['question_text'][:50]}... "
                    f"Reason: Answer={item['answer']}, Choices={item['choices']}"
                )

        db.execute(
            "UPDATE source_references SET is_questionnaire_extracted = 1 WHERE id = %s",
            (slot_id,),
        )

        print(
            f"[EXTRACTOR] Total: {len(extracted_data)} | Saved: {saved_count} | Skipped: {skipped_count}"
        )

    except Exception as e:
        print(f"[EXTRACTOR] Failed: {e}")


def heuristic_exam_extractor(raw_text: str):
    # Patterns
    q_pattern = re.compile(r"^(\d+)[\.\)]\s*(.*)", re.IGNORECASE)
    choice_pattern = re.compile(r"^([A-D])\s*[\.\)]\s*(.*)", re.IGNORECASE)
    answer_pattern = re.compile(r"^A\s*n\s*s\s*w\s*e\s*r\s*:\s*(.*)", re.IGNORECASE)

    questions = []
    current_q = None

    lines = [line.strip() for line in raw_text.split("\n") if line.strip()]

    for line in lines:
        # 1. Detect Question
        q_match = q_pattern.match(line)
        if q_match:
            if current_q:
                questions.append(current_q)
            current_q = {
                "question_text": q_match.group(2),
                "choices": {},
                "answer": None,
            }
            continue

        if not current_q:
            continue

        # 2. Detect Choices
        c_match = choice_pattern.match(line)
        if c_match:
            current_q["choices"][c_match.group(1).upper()] = c_match.group(2).strip()
            continue

        # 3. Detect Answer (Smart Matching)
        a_match = answer_pattern.match(line)
        if a_match:
            ans_val = a_match.group(1).strip().replace("\r", "").replace("\n", "")
            clean_letter = re.search(r"\b([A-D])\b", ans_val.upper())

            if clean_letter:
                # It's a single letter: "Answer: D"
                current_q["answer"] = clean_letter.group(1)
            else:
                # It's full text: "Answer: preserving the site..."
                for letter, text in current_q["choices"].items():
                    if (
                        text.lower() in ans_val.lower()
                        or ans_val.lower() in text.lower()
                    ):
                        current_q["answer"] = letter
                        break
            continue

        # 4. Continuation of question text
        if not current_q["choices"]:
            current_q["question_text"] += " " + line

    if current_q:
        questions.append(current_q)
    return questions
