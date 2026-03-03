from datetime import datetime
import json
from fastapi import FastAPI, UploadFile, File, requests, HTTPException, Query
import PyPDF2
from models import AnswerIn, ExamListOut, ExamOut, GenerateExamRequest, QuestionOut
from utils.cleaner import remove_repeated_lines
from utils.db import db
from typing import List, Optional

# from utils.embeddings import embed_text
from utils.deepseek import generate_from_section, infer_structure
import os

from utils.generation import select_sections

app = FastAPI()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

GPU_API_URL = "http://<EC2_GPU_IP>:8001/process_document"


@app.post("/upload_material")
async def upload_material(file: UploadFile = File(...), use_gpu: bool = False):
    try:
        # Save file temporarily
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as f:
            f.write(await file.read())

        if use_gpu:
            # Forward to EC2 GPU for processing
            with open(file_path, "rb") as f:
                response = requests.post(GPU_API_URL, files={"file": f})
            json_data = response.json()
        else:
            output = {}
            pages = []

            # Open PDF
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text = page.extract_text() or ""
                    pages.append(text.strip())

                pages = remove_repeated_lines(pages, repeat_threshold=3)

            # Save raw pages JSON for inspection
            output_path = f"fulltext_{file.filename}.json"
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(pages, f, ensure_ascii=False, indent=4)

            # Process pages sequentially
            merged_document = {}
            detected_title = None

            for page_text in pages:
                # infer_structure now returns structured JSON like {'title': ..., 'Definition': ..., 'Models of Criminal Justice': ...}
                result = infer_structure(page_text)

                if not detected_title and result.get("title"):
                    detected_title = result["title"]

                for key, value in result.items():
                    if key == "title":
                        continue
                    if key in merged_document:
                        merged_document[key] += "\n\n" + value.strip()
                    else:
                        merged_document[key] = value.strip()

            # Final JSON
            json_data = {"title": detected_title, **merged_document}

            # Now printing gives a single clean structured JSON
            print(json.dumps(json_data, indent=2, ensure_ascii=False))

        # Extract sections from merged_document (skip the title)
        sections = [
            {"section_name": key, "content": value}
            for key, value in merged_document.items()
        ]

        title_embedding = embed_text(json_data["title"])
        embedding_str = json.dumps(title_embedding.tolist())

        document_id = None  # Will get this after inserting the MaterialVector

        query_doc = """
        INSERT INTO MaterialVector (document_path, title_content, title_embedding)
        VALUES (%s, %s, STRING_TO_VECTOR(%s))
        """

        document_id = db.insert(
            query_doc, (file_path, json_data["title"], embedding_str)
        )

        # SectionVector
        section_payloads = []
        for sec in sections:
            section_embedding = embed_text(sec["content"])
            embedding_str = json.dumps(section_embedding.tolist())
            section_payloads.append(
                {
                    "document_id": document_id,
                    "section_name": sec["section_name"],
                    "content": sec["content"],
                    "embedding": embedding_str,
                }
            )

        query_section = """
            INSERT INTO SectionVector (document_id, section_name, content, embedding)
            VALUES (%s, %s, %s, STRING_TO_VECTOR(%s))
            """

        for sec in section_payloads:
            db.insert(
                query_section,
                (
                    sec["document_id"],
                    sec["section_name"],
                    sec["content"],
                    sec["embedding"],
                ),
            )

        output_path = f"processed_{file.filename}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=4)

        print(f"Processing complete. Data saved to {output_path}")

        return {
            "status": "success",
            "filename": file.filename,
        }

    except Exception as e:
        return {"status": "error", "detail": str(e)}


# ----- Endpoint: fetch all documents -----
@app.get("/materials")
def get_materials():
    return db.select(
        "SELECT id, document_path, title_content, created_at FROM materialvector"
    )


@app.get("/sections/{document_id}")
def get_sections(document_id: int):
    return db.select(
        """
        SELECT id, section_name
        FROM SectionVector
        WHERE document_id=%s
    """,
        (document_id,),
    )


# ----- Endpoint: generate questions -----
@app.post("/generate-exam")
def generate_exam(req: GenerateExamRequest):
    # Create examination record
    exam_id = db.insert(
        """
        INSERT INTO Examinations
        (document_id, difficulty, focus, exam_type, total_items)
        VALUES (%s, %s, %s, %s, %s)
    """,
        (req.document_id, req.difficulty, req.focus, req.exam_type, req.items),
    )

    sections = select_sections(req)
    if not sections:
        return {"error": "No sections found for this document."}

    questions_per_section = req.items // len(sections)
    remainder = req.items % len(sections)  # leftover questions

    all_questions = []

    for i, s in enumerate(sections):
        n = questions_per_section
        if i < remainder:  # add 1 extra question to first 'remainder' sections
            n += 1
        section_questions = generate_from_section(req, s, n)
        for q in section_questions:
            q["_section_id"] = s["id"]

        all_questions.extend(section_questions)

    saved_questions = []
    for q in all_questions:
        section_id = q["_section_id"]  # now correctly mapped

        question_id = db.insert(
            """
            INSERT INTO Questions
            (examination_id, document_id, section_id,
            question_text, choices, correct_answer, difficulty)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
            (
                exam_id,
                req.document_id,
                section_id,
                q.get("question_text"),
                json.dumps(q.get("choices")),
                q.get("correct_answer"),
                req.difficulty,
            ),
        )

        saved_questions.append(
            {
                "id": question_id,
                "question_text": q.get("question_text"),
                "choices": q.get("choices"),
                "correct_answer": q.get("correct_answer"),
            }
        )

    return saved_questions


# region REVIEWEE
def safe_choices(val):
    if val is None:
        return []
    try:
        parsed = json.loads(val)
        # Sometimes DB stores 'null' as a string
        if parsed is None:
            return []
        return parsed
    except (json.JSONDecodeError, TypeError):
        return []


@app.get("/exams", response_model=List[ExamListOut])
def list_exams(
    exam_type: Optional[str] = Query(None, description="Filter by exam type"),
    focus: Optional[str] = Query(None, description="Filter by focus"),
):
    # Build dynamic WHERE clause
    where_clauses = []
    params = []

    if exam_type:
        where_clauses.append("exam_type=%s")
        params.append(exam_type)

    if focus:
        where_clauses.append("focus=%s")
        params.append(focus)

    sql = "SELECT id, focus, exam_type FROM Examinations"
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY id ASC"

    exam_rows = db.select(sql, tuple(params))

    return [
        ExamListOut(
            id=exam["id"],
            focus=exam.get("focus", ""),
            exam_type=exam.get("exam_type", ""),
        )
        for exam in exam_rows
    ]


@app.get("/exams/{exam_id}", response_model=ExamOut)
def get_exam(exam_id: int):
    # Fetch exam
    exam_rows = db.select("SELECT * FROM Examinations WHERE id=%s", (exam_id,))
    if not exam_rows:
        raise HTTPException(status_code=404, detail="Exam not found")
    exam = exam_rows[0]

    # Fetch questions
    question_rows = db.select(
        "SELECT * FROM Questions WHERE examination_id=%s ORDER BY id ASC", (exam_id,)
    )

    questions = [
        QuestionOut(
            id=q["id"],
            question_text=q["question_text"],
            choices=safe_choices(q.get("choices")),
        )
        for q in question_rows
    ]

    return ExamOut(
        id=exam["id"],
        document_id=exam["document_id"],
        difficulty=exam["difficulty"],
        focus=exam["focus"],
        exam_type=exam["exam_type"],
        total_items=exam["total_items"],
        questions=questions,
    )


def insert_answer(exam_id, question_id, student_answer, is_correct, answered_at):
    print(
        f"Inserting: exam_id={exam_id}, question_id={question_id}, "
        f"student_answer={student_answer}, is_correct={is_correct}, answered_at={answered_at}"
    )

    db.insert(
        """
        INSERT INTO ExaminationResults (examination_id, question_id, student_answer, is_correct, answered_at)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (exam_id, question_id, student_answer, is_correct, answered_at),
    )
    return True


@app.post("/answers")
def submit_answers(answers: list[AnswerIn]):
    if not answers:
        return {"status": "error", "message": "No answers provided"}

    exam_id = answers[0].examination_id
    now = datetime.utcnow()

    # Fetch correct answers from DB
    question_rows = db.select(
        "SELECT * FROM Questions WHERE examination_id=%s ORDER BY id ASC", (exam_id,)
    )

    # Map question_id -> correct_answer
    correct_map = {q["id"]: q["correct_answer"] for q in question_rows}

    submitted_count = 0
    correct_count = 0

    for ans in answers:
        correct_answer = correct_map.get(ans.question_id)
        if correct_answer is not None:
            # Compare submitted answer with correct answer (case-insensitive)
            is_correct = (
                ans.answer_text.strip().lower() == correct_answer.strip().lower()
            )
            insert_answer(
                exam_id=ans.examination_id,
                question_id=ans.question_id,
                student_answer=ans.answer_text,
                is_correct=is_correct,
                answered_at=now,
            )
            submitted_count += 1
            if is_correct:
                correct_count += 1

        else:
            print(
                f"Question not found: exam_id={ans.examination_id}, question_id={ans.question_id}"
            )

    score = {
        "correct": correct_count,
        "total": submitted_count,
        "percentage": (
            (correct_count / submitted_count * 100) if submitted_count > 0 else 0
        ),
    }

    return {"status": "success", "submitted": submitted_count, "score": score}


# FOR EC2 GPU LATER
# @app.post("/process_document")
# async def process_document(file: UploadFile = File(...)):
#     text_pages = []
#     with pdfplumber.open(file.file) as pdf:
#         for page in pdf.pages:
#             text_pages.append(page.extract_text())

#     # Simple chunking per page (could merge if needed)
#     sections = {}
#     for i, page_text in enumerate(text_pages):
#         section_name = f"Page {i+1}"  # could improve by detecting headings
#         sections[section_name] = {
#             "pages": str(i+1),
#             "embeddings": embed_text(page_text).tolist()  # Ollama embedding
#         }

#     # Title embedding
#     title_text = text_pages[0][:100]  # first 100 chars as title
#     title_embedding = embed_text(title_text).tolist()

#     return {
#         "title": {"content": title_text, "embeddings": title_embedding},
#         "sections": sections
#     }
