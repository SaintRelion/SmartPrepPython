import json

import os
from ollama import Client

OLLAMA_HOST = os.getenv("OLLAMA_HOST")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:35b")

client = Client(host=OLLAMA_HOST, timeout=300.0)


def analyze_item_distribution_ollama(
    examination_id: int,
    date: str,
    items: list,
) -> dict:
    system_instruction: str = (
        "You are an expert Criminology Professor and psychometrician reviewing board exam results. "
        "You will receive aggregated answer choice distributions showing how many STUDENTS (reviewees) "
        "selected each option across an entire exam batch — not a single respondent. "
        "Your job is to write a concise psychometric diagnostic for each question based on the distribution pattern.\n\n"
        "GUIDELINES:\n"
        "- Always frame analysis in terms of the GROUP: 'students', 'most examinees', 'the class', etc.\n"
        "- Never say 'the respondent' — this is aggregate data from all reviewees in the batch.\n"
        "- Identify which distractor attracted the most pull and what conceptual confusion it suggests.\n"
        "- If correct_answer is known: note whether students converged on it or scattered across distractors.\n"
        "- If total=1: say 'only one student answered this item' and note their choice.\n"
        "- If all students picked the same option: note strong consensus — correct or not.\n"
        "- Focus on what the distribution reveals: guessing patterns, conceptual gaps, distractor effectiveness.\n"
        "- Tone: Direct, instructor-facing, actionable. 1-2 sentences per question.\n"
        "- Never mention missing data, data integrity, or unknown values.\n"
    )

    # Pre-compute per-item correct/incorrect context to guide the model
    items_with_context = []
    for item in items:
        dist = item["distribution"]
        correct = item.get("correct_answer", "").strip().upper()
        total = dist.get("total", 0)
        correct_count = (
            dist.get(correct, 0) if correct in ("A", "B", "C", "D") else None
        )
        top_choice = max(("A", "B", "C", "D"), key=lambda k: dist.get(k, 0))
        items_with_context.append(
            {
                **item,
                "total_responses": total,
                "top_selected_option": top_choice,
                "top_selected_count": dist.get(top_choice, 0),
                "correct_answer_count": correct_count,
                "majority_correct": (
                    (correct_count == max(dist.get(k, 0) for k in ("A", "B", "C", "D")))
                    if correct_count is not None
                    else None
                ),
            }
        )

    prompt: str = f"""
    [EXAM DATA]
    Examination ID: {examination_id}
    Batch Date: {date}
    Context: These distributions represent ALL student responses aggregated across this exam batch.
            Each number is how many students chose that option — not a single person.

    [ITEM DISTRIBUTION]
    {json.dumps(items_with_context, indent=2)}

    Return ONLY this JSON format:
    {{
        "summary": "2-3 sentences on overall class performance patterns: correct answer rates, distractor pull trends, areas of conceptual weakness.",
        "analysis": {{
            "QUESTION_ID": "1-2 sentence psychometric diagnostic framed around the GROUP of students.",
            "QUESTION_ID": "1-2 sentence psychometric diagnostic framed around the GROUP of students."
        }}
    }}

    Rules:
    - Keys in 'analysis' must be the exact numeric question_id values from the input.
    - Every question_id in the input must appear in 'analysis'.
    - Never say 'the respondent' — always refer to 'students', 'examinees', or 'the class'.
    - Base diagnostics on the distribution numbers and the correct_answer field.
    - Do not use A/B/C/D as keys in 'analysis'. Use the numeric question IDs only.
    """
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
        if not raw_text:
            print(
                f"Ollama returned empty response for item analysis exam {examination_id}."
            )
            return None
        return json.loads(raw_text)
    except json.JSONDecodeError as je:
        print(f"JSON decode error for item analysis: {je} | Raw: {raw_text}")
        return None
    except Exception as e:
        print(f"Ollama call error for item analysis: {e}")
        return None


def analyze_overall_examination_ollama(
    overall_accuracy: float,
    worst_topics: list,
    full_breakdown: list,
) -> dict:

    system_instruction: str = (
        "You are an expert Criminology Department Head advising a course instructor. "
        "Analyze the overall board exam review results for this class of criminology students. "
        "\n\nGUIDELINES:\n"
        "- Tone: Professional, direct, and highly practical for a Criminology instructor.\n"
        "- Do not simply repeat the numbers back. Explain what the data means for the class's board exam passing rate.\n"
        "- Focus your teaching strategy strictly on the 'Worst Performing Areas' in the Criminology curriculum.\n"
        "- Give concrete teaching strategies (e.g., 'Introduce scenario-based case studies for Criminal Law', 'Conduct a focused drill session on Questioned Documents').\n"
        "\nTASK:\n"
        "Return a JSON object with a brief 'summary' evaluating the class's readiness and exactly 3 teaching 'recommendations' for the instructor."
    )

    prompt: str = f"""
    [CLASS EXAM DATA]
    Overall Latest Examination Accuracy: {overall_accuracy}%

    [WORST PERFORMING AREAS (PRIORITY)]
    {json.dumps(worst_topics, indent=2)}

    [FULL TOPIC BREAKDOWN]
    {json.dumps(full_breakdown, indent=2)}

    Result Format MUST be exact JSON:
    {{
        "summary": "Your 2-3 sentence summary evaluating the class's overall readiness for the board exam...",
        "recommendations": [
            "Practical teaching recommendation 1...",
            "Practical teaching recommendation 2...",
            "Practical teaching recommendation 3..."
        ]
    }}
    """

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

        if not raw_text:
            print(
                "!!! WARNING: Ollama returned an empty response string for cohort analysis."
            )
            return None

        # Return the parsed JSON dictionary
        return json.loads(raw_text)

    except json.JSONDecodeError as je:
        print(f"!!! JSON DECODE ERROR: {je}")
        print(f"Attempted to decode: {raw_text}")
        return None
    except Exception as e:
        print(f"!!! OLLAMA CALL ERROR: {e}")
        return None


def analyze_item_ollama(
    question: str,
    choices: dict,
    correct_answer: str,
    source_context: str,
    slot_name: str,
) -> dict:

    system_instruction: str = (
        f"You are an expert Criminology Professor specializing in {slot_name}. "
        "Analyze the MCQ provided using the provided source material segments. "
        "CRITICAL: The source material may contain 'noise' (headers, page numbers, or OCR artifacts); "
        "ignore the noise and focus only on the technical substance. "
        f"If context is missing, use standard principles of {slot_name} and RA 9514. "
        "\n\nGUIDELINES FOR COLLEGE STUDENTS:\n"
        "- Keep explanations concise, clear, and direct. Avoid overly dense technical jargon.\n"
        "- Focus on WHY a choice is correct or WHY it is a common distractor/wrong.\n"
        "- Use a helpful 'Reviewer Tone' that simplifies complex concepts for easier memorization.\n"
        "\nTASK:\n"
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


def analyze_attempt_ollama(
    exam_name: str, overall_accuracy: float, topic_breakdown: list
) -> dict:

    system_instruction: str = (
        "You are an expert Criminology Professor and Board Exam Tutor. "
        "Analyze the criminology student's exam scorecard and provide constructive, practical feedback. "
        "\n\nGUIDELINES:\n"
        "- Tone: Professional, encouraging, and highly specific to Criminology board exam preparation.\n"
        "- Do not just repeat the numbers. Interpret what the scores mean for their board exam readiness.\n"
        "- Focus the recommendations on the student's weakest Criminology subjects (lowest percentages).\n"
        "- Keep the recommendations concise and actionable (e.g., 'Review the elements of Criminal Jurisprudence', 'Practice more questions on Forensic Ballistics').\n"
        "\nTASK:\n"
        "Return a JSON object with a brief 'summary' and exactly 3 'recommendations'."
    )

    prompt: str = f"""
    [EXAM DATA]
    Exam Name: {exam_name}
    Overall Accuracy: {overall_accuracy}%

    [TOPIC BREAKDOWN]
    {json.dumps(topic_breakdown, indent=2)}

    Result Format: 
    {{
        "summary": "A 2-3 sentence evaluation of their overall readiness and performance...",
        "recommendations": [
            "Specific action 1...",
            "Specific action 2...",
            "Specific action 3..."
        ]
    }}
    """

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

        if not raw_text:
            print(
                "!!! WARNING: Ollama returned an empty response string for attempt analysis."
            )
            return None

        # Return the parsed JSON dictionary
        return json.loads(raw_text)

    except json.JSONDecodeError as je:
        print(f"!!! JSON DECODE ERROR: {je}")
        print(f"Attempted to decode: {raw_text}")
        return None
    except Exception as e:
        print(f"!!! OLLAMA CALL ERROR: {e}")
        return None
