import json
from typing import Any, Dict, List
from ollama import Client

OLLAMA_HOST = "http://13.219.64.180:11434"
OLLAMA_MODEL = "qwen3.5:35b"

client = Client(host=OLLAMA_HOST, timeout=300.0)


def infer_structure_ollama(chunk: str, previous_section: str = None):
    system_instruction = f"""
    You are a Document Structure Extractor. 
    Analyze the text and return ONLY a FLAT JSON object.

    CONTEXT RULE:
    The last section identified was "{previous_section}". 
    - If the current text starts as a continuation of "{previous_section}", use "{previous_section}" as the key for that content.
    - If the text moves to a new topic, identify the new Heading and use it as a new key.

    CLEANING & FORMATTING RULES:
    1. Ignore all repeating headers/footers (school names, addresses, page numbers).
    2. For any tables or grid-like data, represent them using "||" as column separators.
    3. Bundle lists into the string value of their parent heading.
    4. No nested JSON. No thinking tags. Output ONLY JSON.
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

    return json.loads(response["response"])


def generate_exam_ollama(
    difficulty: str, section_name: str, content: str, num_items: int
) -> List[Dict[str, Any]]:
    system_instruction: str = (
        "You are a Criminology Board Examiner. Your task is to generate valid JSON only. "
        "CRITICAL RULES:\n"
        "1. Output MUST be a FLAT JSON ARRAY [].\n"
        "2. Each object MUST have exactly 3 keys: 'question_text', 'choices', and 'correct_answer'.\n"
        "3. NEVER nest 'correct_answer' inside the 'choices' object.\n"
        "4. DO NOT include any preamble, thinking tags, or markdown code blocks."
    )

    prompt = f"""
    ### TASK
    Generate exactly {num_items} multiple-choice questions for the Criminologist Licensure Examination (CLE).
    
    ### PARAMETERS
    - DIFFICULTY: {difficulty}
    - SECTION: {section_name}
    
    ### CONTENT_TO_PROCESS
    <content>
    {content}
    </content>
    
    ### REQUIRED_JSON_STRUCTURE_EXAMPLE
    [
      {{
        "question_text": "Sample question here?",
        "choices": {{"A": "Choice 1", "B": "Choice 2", "C": "Choice 3", "D": "Choice 4"}},
        "correct_answer": "A"
      }}
    ]

    ### EXECUTION
    Generate {num_items} questions now following the exact structure above:
    """

    response = client.generate(
        model=OLLAMA_MODEL,
        system=system_instruction,
        prompt=prompt,
        stream=False,
        think=False,
        format="json",
        options={
            "temperature": 0.7,
            "num_ctx": 8192,
            "num_predict": 4096,
        },
    )

    # If infer works with this line, generate will too
    return json.loads(response["response"])
