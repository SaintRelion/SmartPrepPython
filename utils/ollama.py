import json

from ollama import Client

OLLAMA_HOST = "http://13.219.64.180:11434"
OLLAMA_MODEL = "qwen3.5:35b"

client = Client(host=OLLAMA_HOST, timeout=300.0)


def analyze_item_ollama(
    question: str,
    choices: dict,
    correct_answer: str,
    source_context: str,
    slot_name: str,
) -> dict:

    system_instruction: str = (
        f"You are an expert Criminology Professor specializing in {slot_name}. "
        "Analyze the MCQ provided. We have provided segments from the original source material. "
        "CRITICAL: The source material may contain 'noise' (headers, page numbers, or OCR artifacts); "
        "ignore the noise and focus on the technical substance. "
        f"If the context is missing, use standard principles of {slot_name} and RA 9514."
        "\n\nTASK:\n"
        "Return a JSON object with explanations for A, B, C, and D."
    )

    prompt: str = f"""
    [SOURCE MATERIAL CATEGORY]
    {slot_name}

    [SOURCE CONTEXT FROM PDF]
    {source_context[:8000]} 

    [ITEM TO ANALYZE]
    Question: {question}
    Choices: {choices}
    Correct Answer: {correct_answer}

    Result Format: 
    {{
        "A": "Detailed explanation...",
        "B": "Detailed explanation...",
        "C": "Detailed explanation...",
        "D": "Detailed explanation..."
    }}
    """

    # --- DEBUG PRINT: WHAT WE ARE PASSING ---
    # print("\n" + "=" * 50)
    # print(">>> SENDING TO OLLAMA")
    # print(f"SYSTEM: {system_instruction[:200]}...")
    # print(f"PROMPT (TRUNCATED): {prompt[:500]}...")
    # print("=" * 50 + "\n")

    try:
        response = client.generate(
            model=OLLAMA_MODEL,
            system=system_instruction,
            prompt=prompt,
            format="json",
            stream=False,
            think=False,
        )

        raw_text = response.get("response", "")

        # --- DEBUG PRINT: RAW RESPONSE ---
        print(">>> RAW OLLAMA RESPONSE:")
        print(raw_text)
        print("=" * 50)

        if not raw_text:
            print("!!! WARNING: Ollama returned an empty response string.")
            return None

        return json.loads(raw_text)

    except json.JSONDecodeError as je:
        print(f"!!! JSON DECODE ERROR: {je}")
        print(f"Attempted to decode: {raw_text}")
        return None
    except Exception as e:
        print(f"!!! OLLAMA CALL ERROR: {e}")
        return None
