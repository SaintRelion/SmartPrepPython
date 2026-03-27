import ollama
import json

OLLAMA_MODEL = "qwen3.5:0.8b"


def infer_structure_ollama(chunk: str, previous_section: str = "Introduction"):
    """
    Forensic Structure Inference using Local Ollama.
    """
    system_instruction = """
    Analyze raw text from a CJS document. 
    Ignore headers, footers, and page numbers.
    Return ONLY a JSON object where keys are headings and values are content.
    """

    prompt = f"""
    The previous section was: "{previous_section}".
    Analyze this chunk:
    1. Continue "{previous_section}" if the text belongs there.
    2. Identify new headings if present.
    
    TEXT:
    {chunk}
    """

    try:
        response = ollama.generate(
            model=OLLAMA_MODEL,
            system=system_instruction,
            prompt=prompt,
            format="json",  # Forces Ollama to return valid JSON
            options={"temperature": 0.2, "top_p": 0.9},
        )

        return json.loads(response["response"])
    except Exception as e:
        print(f"Ollama Extraction Error: {e}")
        return {previous_section: chunk}


def generate_exam_ollama(difficulty, section_name, content, num_items):
    """
    Generate questions using Local Ollama.
    """
    difficulty_guide = {
        "Easy": "basic recall",
        "Moderate": "application",
        "Hard": "critical scenario analysis",
    }

    prompt = f"""
    Generate {num_items} multiple-choice questions from: {section_name}
    Difficulty: {difficulty_guide.get(difficulty, "basic")}
    
    CONTENT:
    {content}
    
    Return a JSON array of objects: 
    [ {{"question_text": "", "choices": {{"A":"", "B":"", "C":"", "D":""}}, "correct_answer": "A"}} ]
    """

    try:
        response = ollama.generate(
            model=OLLAMA_MODEL,
            prompt=prompt,
            format="json",
            options={"temperature": 0.8},
        )
        return json.loads(response["response"])
    except Exception as e:
        print(f"Ollama Generation Error: {e}")
        return []
