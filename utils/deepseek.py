import json

from models import GenerateExamRequest
from openai import OpenAI

DEESEEK_API_KEY = "sk-948033d465a2416e8ffc264e4dc06c89"
DEESEEK_API_URL = "https://api.deepseek.com"

client = OpenAI(api_key=DEESEEK_API_KEY, base_url=DEESEEK_API_URL)


def infer_structure(chunk: str, previous_section: str = None):
    system_prompt = """
You analyze raw text chunks from a document. The document is about: CLJ 1 INTRODUCTION TO THE CRIMINAL JUSTICE SYSTEM (CJS)

Rules:
- REMOVE any repeating headers or footers (lines appearing in multiple chunks).
- Merge broken lines into proper paragraphs if part of the same discussion: remove unnecessary single line breaks (\n) inside paragraphs.
- Detect headings in the text (lines that start with capitalized words or known section titles) and use them as keys in the JSON.
- The text under each heading becomes the value (string), preserving lists, bullets, and numbering.
- Preserve all meaningful content exactly, do NOT summarize or rewrite.
- If text exists before any heading, use "Introduction" or "Preface" as the key.
- Output a single JSON object representing the document structure.

Return ONLY valid JSON in this format, example:

{
  "title": "CLJ 1 INTRODUCTION TO THE CRIMINAL JUSTICE SYSTEM (CJS)",
  "Definition": "The Criminal Justice System (CJS) refers to ...",
  "Models of Criminal Justice": "1. Due Process Model\n• The accused is presumed innocent ...",
  "Five Stages of the Criminal Justice Process": "...",
  "CRIMINAL LAW AND THE CJS": "...",
  "Classifications of Criminal Law": "...",
  "Basic Principles of Criminal Law in CJS": "...",
  "THE CRIMINAL IN THE CJS": "..."
}
"""

    user_prompt = f"""
Previous section: {previous_section}

Text chunk:
{chunk}
"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        temperature=0,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        stream=False,
    )

    content = response.choices[0].message.content.strip()

    # Remove markdown fences
    if content.startswith("```"):
        content = content.split("```")[1]
        content = content.replace("json", "").strip()

    try:
        return json.loads(content)
    except Exception:
        print("RAW MODEL OUTPUT:", content)
        return {
            "title": None,
            "section_name": previous_section or "Unknown",
            "is_new_section": False,
            "content": chunk,
        }


def generate_from_section(req, section, num_items):
    difficulty_map = {
        "Quiz": "basic recall and understanding questions",
        "Long Exam": "mix of recall and application questions",
        "Midterm": "moderate difficulty requiring application and analysis",
        "Final": "higher-order thinking, analytical and integrative questions",
        "Board Review": "advanced, scenario-based, professional-level questions",
    }

    exam_type_map = {
        "Standard": "short answer format",
        "Multiple Choice": "multiple choice with exactly 4 options",
        "Mixed": "a combination of short answer and multiple choice",
    }

    system_prompt = """
You are a university-level exam generator.

Rules:
- Generate exam questions based ONLY on the section text provided.
- Do NOT include information that is not present in the section.
- Do NOT mention according to the section or content
- Return ONLY a valid JSON array in the specified format.
"""

    user_prompt = f"""
    Generate {num_items} questions from the following section:

    SECTION: {section['section_name']}

    Difficulty: {difficulty_map.get(req.difficulty)}
    Format: {exam_type_map.get(req.exam_type)}

    Rules:
    - Standard: answer in 2–5 sentences demonstrating reasoning based strictly on the section.
    - Multiple Choice: each question must have exactly 4 answer options, provide the options as full text, and indicate the correct answer in 'correct_answer'.
    - Mixed: some questions should be Standard-style answers (2–5 sentences) and some should be Multiple Choice (4 options each).
    - Return ONLY a valid JSON array in the following format:

    JSON FORMAT:
    [
    {{
        "question_text": "Question goes here",
        "choices": ["Option 1 text", "Option 2 text", "Option 3 text", "Option 4 text"],  # MCQs only; Standard questions can have null or empty list
        "correct_answer": "Option 1 text"  # For Standard questions, put the answer text
    }}
    ]

    SECTION TEXT:
    {section["content"]}
    """

    response = client.chat.completions.create(
        model="deepseek-chat",
        temperature=0.4,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = response.choices[0].message.content.strip()

    if content.startswith("```"):
        content = content.split("```")[1]
        content = content.replace("json", "").strip()

    try:
        return json.loads(content)
    except:
        print("MODEL ERROR:", content)
        return []
