# test_material_debug.py
import os
from datetime import datetime
from utils.db import db
from tasks import _load_category_materials, _get_structural_chunks


def debug_full_material_dump(category_id: int):
    log_file = "material_structure_debug.log"

    # Fresh start for the log
    if os.path.exists(log_file):
        os.remove(log_file)

    print(f"Scraping Category {category_id}...")
    full_text = _load_category_materials(category_id)

    if not full_text:
        print("No text found. Check DB paths.")
        return

    print("Generating structural chunks...")
    chunks = _get_structural_chunks(full_text)

    print(f"Writing {len(chunks)} chunks to {log_file}...")

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"=== FULL STRUCTURAL DUMP: CATEGORY {category_id} ===\n")
        f.write(f"TIMESTAMP: {datetime.now()}\n")
        f.write(f"TOTAL CHUNKS: {len(chunks)}\n")
        f.write("=" * 80 + "\n\n")

        for i, chunk in enumerate(chunks):
            f.write(f"--- CHUNK #{i+1} START ---\n")
            # WRITE ALL OF THEM OUT
            f.write(chunk)
            f.write(f"\n--- CHUNK #{i+1} END ---\n")
            f.write("-" * 80 + "\n\n")

    print("Success. Open 'material_structure_debug.log' to see the full grouping.")


if __name__ == "__main__":
    # Target Category 1 (where the PNP vs Fire Science issue is)
    debug_full_material_dump(1)
