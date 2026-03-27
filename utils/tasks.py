# python
from celery import Celery
import PyPDF2

from utils import db
from utils.gemini import infer_structure_gemini
from utils.ollama import infer_structure_ollama

celery = Celery("tasks", broker="redis://localhost:6379/0")


# python
@celery.task(name="process_material_task")
def process_material_task(material_id: int, file_path: str, use_ollama: bool):
    try:
        reader = PyPDF2.PdfReader(file_path)
        last_known_section = "Introduction"  # Starting point

        for page in reader.pages:
            text = page.extract_text()
            if not text or len(text.strip()) < 50:
                continue

            # The AI takes the raw text and the last section name
            # It returns: {"Section Name": "Content..."}
            if use_ollama:
                structured_data = infer_structure_ollama(text, last_known_section)
            else:
                structured_data = infer_structure_gemini(text, last_known_section)

            for title, content in structured_data.items():
                # Update our tracker so the NEXT page knows where it's at
                last_known_section = title

                # Check if this section already exists for this material to append
                # or just insert a new row (Forensic choice: New row is easier for vector search later)
                db.insert(
                    "INSERT INTO Sections (material_id, section_name, content) VALUES (%s, %s, %s)",
                    (material_id, title, str(content).strip()),
                )

        db.execute(
            "UPDATE Materials SET processed_by_ai = 1 WHERE id = %s", (material_id,)
        )

    except Exception as e:
        print(f"Background Process Failed: {e}")
