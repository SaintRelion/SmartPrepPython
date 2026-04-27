# test.py
import os
import json
from utils.db import db
from tasks import _isolate_relevant_paragraph, _load_category_materials


def test_all_pending_isolation():
    log_file = "debug_isolation.log"
    if os.path.exists(log_file):
        os.remove(log_file)

    print("Fetching all pending items...")
    sql = """
        SELECT qi.id, qi.question_text, qi.choices, q.category_id 
        FROM questionnaire_items qi
        JOIN questionnaire q ON qi.questionnaire_id = q.id
        WHERE qi.analysis_status IS NULL OR qi.analysis_status = 'pending'
        ORDER BY q.category_id, qi.id
    """
    items = db.select(sql)

    if not items:
        print("No pending items found.")
        return

    current_cat_id = -1
    full_text = ""

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"=== BATCH ISOLATION DEBUG: {len(items)} ITEMS ===\n")

        for item in items:
            print(f"Processing Item {item['id']}...")

            # Load material only when category changes
            if item["category_id"] != current_cat_id:
                full_text = _load_category_materials(item["category_id"])
                current_cat_id = item["category_id"]

            try:
                choices = (
                    json.loads(item["choices"])
                    if isinstance(item["choices"], str)
                    else item["choices"]
                )
            except:
                choices = {}

            # Call strict isolation
            result = _isolate_relevant_paragraph(choices, full_text)

            f.write(f"\n{'='*80}\n")
            f.write(f"ITEM ID: {item['id']}\n")
            f.write(f"QUESTION: {item['question_text']}\n")

            if result:
                f.write(f"\n--- ISOLATED CONTEXT ---\n{result}\n")
            else:
                f.write(
                    "\nRESULT: FAILED (No chunk contained ALL words for any choice)\n"
                )
            f.write("=" * 80 + "\n")

    print(f"Done. Batch debug results saved to {log_file}")


if __name__ == "__main__":
    test_all_pending_isolation()
