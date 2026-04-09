import json
import re
from typing import Any, Dict, List
from ollama import Client

OLLAMA_HOST = "http://13.219.64.180:11434"
OLLAMA_MODEL = "qwen3.5:35b"

client = Client(host=OLLAMA_HOST, timeout=300.0)


def infer_structure_ollama(chunk: str, previous_section: str = None):
    system_instruction = f"""
    You are a Document Structure Extractor. 
    Analyze the text and return ONLY a FLAT JSON object.

    STRICT HIERARCHY RULES:
    1. HEADING DETECTION: Actively scan for NEW topics (e.g., "I.", "Section 12", "CUSTODIAL INVESTIGATION"). Use these as NEW keys.
    2. CONTINUATION: Only use "{previous_section}" if the text is clearly a mid-sentence continuation of the previous chunk.
    3. KEY LENGTH: Keep keys (headings) under 10 words. NEVER use a paragraph as a key.
    4. JSON FORMATTING: Do not use nested objects. Use the format: {{"Heading": "Content"}}.

    CLEANING RULES:
    1. Ignore repeating headers/footers and page numbers.
    2. Use "||" for tables.
    3. IMPORTANT: Escape all double quotes (\") inside the text to prevent JSON errors.
    """

    prompt = f"""
    INPUT TEXT:
    {chunk}

    TASK:
    1. Extract the logical headings and their corresponding body text.
    2. If the text continues a previous topic, use the exact key provided in the system instructions.
    3. Use "||" to separate columns if you encounter a table.
    4. Remove all page headers, footers, institutional names, and repeated addresses.
    5. Ensure the output is a single-level JSON object.
    """

    response = client.generate(
        model=OLLAMA_MODEL,
        system=system_instruction,
        prompt=prompt,
        stream=False,
        think=False,
        format="json",
        options={"temperature": 0.1, "num_ctx": 8192},
    )

    raw_response = response["response"].strip()

    try:
        # Standard attempt
        return json.loads(raw_response)
    except json.JSONDecodeError:
        # FORENSIC REPAIR:
        # Sometimes Ollama forgets to escape internal quotes in long strings.
        # This regex tries to escape quotes that are NOT part of the JSON structure.
        print("Manual JSON repair initiated...")

        # 1. Remove any potential trailing commas before closing braces
        repaired = re.sub(r",\s*}", "}", raw_response)

        # 2. Try to handle the specific char 1007 issue:
        # If it's a long block of text, the AI might have missed an escape.
        try:
            # Using strict=False allows control characters (like newlines) inside strings
            return json.loads(repaired, strict=False)
        except:
            # Last resort: return a "Safe" dictionary so the worker doesn't skip the page
            return {previous_section or "Unstructured Content": raw_response}


def clean_json_response(raw_str):
    """Forensic repair for Ollama's common JSON mistakes."""
    # Remove thinking tags and markdown
    clean = re.sub(r"<think>.*?</think>", "", raw_str, flags=re.DOTALL)
    clean = re.sub(r"```json|```", "", clean).strip()

    # Simple bracket balancing
    if clean.startswith("[") and not clean.endswith("]"):
        clean += "]"
    if clean.startswith("{") and not clean.endswith("}"):
        clean += "}"

    try:
        return json.loads(clean)
    except:
        # If it's really messy, try to extract anything that looks like a JSON array
        match = re.search(r"\[.*\]", clean, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
        return None


def generate_exam_ollama(
    difficulty: str, section_name: str, content: str, num_items: int
) -> List[Dict[str, Any]]:
    system_instruction = (
        "You are a Criminology Board Examiner. Return ONLY a raw JSON array. "
        "RULES: 1. No preamble. 2. 'choices' must be an object with keys A,B,C,D. "
        "3. 'correct_answer' must be the letter only (A, B, C, or D). "
        "4. Escape all double quotes in text."
    )

    prompt = f"Generate {num_items} MCQs for {section_name} ({difficulty}).\nContent: {content[:4000]}"

    response = client.generate(
        model=OLLAMA_MODEL,
        system=system_instruction,
        prompt=prompt,
        stream=False,
        think=False,
        format="json",
        options={"temperature": 0.2, "num_ctx": 8192, "num_predict": 3000},
    )

    return clean_json_response(response["response"])
