from collections import Counter
from typing import List


def remove_repeated_lines(pages: List[str], repeat_threshold: int = 3) -> List[str]:
    all_lines_per_page = [page.splitlines() for page in pages]

    # Count in how many pages each line appears
    line_page_count = Counter()
    for lines in all_lines_per_page:
        unique_lines = set(line.strip() for line in lines if line.strip())
        for line in unique_lines:
            line_page_count[line] += 1

    # Remove lines that appear in >= repeat_threshold pages
    cleaned_pages = []
    for lines in all_lines_per_page:
        new_lines = [
            line
            for line in lines
            if line.strip() and line_page_count[line.strip()] < repeat_threshold
        ]
        cleaned_pages.append("\n".join(new_lines))

    return cleaned_pages
