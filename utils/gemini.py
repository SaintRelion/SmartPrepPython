import os
from dotenv import load_dotenv

load_dotenv()

from google import genai
from google.genai import types
import json

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

MODEL_ID = "gemini-2.0-flash"
SYSTEM_INSTRUCTION = """
Analyze raw text chunks from a CJS document.
Rules:
- Identify headings and the text following them.
- Merge broken paragraphs.
- Output ONLY valid JSON where keys are headings and values are content.
- If a section continues from the previous chunk, use the previous heading.
"""


def infer_structure_gemini(chunk: str, previous_section: str = None):
    user_prompt = f"""
    You are an expert document parser. 
    The previous section we processed was titled: "{previous_section}".
    
    Analyze this new text chunk:
    1. If the chunk starts with a new heading, use that heading as the JSON key.
    2. If the chunk is a continuation of "{previous_section}", use "{previous_section}" as the key.
    3. If there are multiple sections, list them all.
    
    Return ONLY valid JSON.
    
    TEXT:
    {chunk}
    """

    # 3. New Generation Syntax
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            temperature=0.2,  # Lower temperature for better structural parsing
        ),
    )

    try:
        # Access content via response.text or response.parsed
        return json.loads(response.text)
    except Exception as e:
        print(f"Gemini JSON Error: {e}")
        return {"Introduction": chunk}  # Fallback


def generate_from_section(difficulty, section, num_items):
    difficulty_map = {
        "Easy": "basic recall and facts",
        "Moderate": "application of concepts",
        "Hard": "critical analysis and scenario-based questions",
    }

    prompt = f"""
    Generate {num_items} multiple-choice questions from the section: {section['section_name']}
    Difficulty: {difficulty_map.get(difficulty)}
    
    Content:
    {section["content"]}
    
    Return a JSON array of objects with:
    'question_text', 'choices' (4 options), and 'correct_answer' (string).
    """

    # 4. Generate Exam Questions
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.7,  # Higher temperature for creative question generation
        ),
    )

    return json.loads(response.text)
