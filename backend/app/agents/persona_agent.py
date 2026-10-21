import json
from ollama import chat


def generate_persona(
    product_description,
    target_market,
    research_objective
):
    prompt = f"""
Generate ONE realistic synthetic user persona for product research.

Product: {product_description}
Target Market: {target_market}
Research Objective: {research_objective}

Return one valid JSON object with exactly these fields:

{{
  "name": "A fictional name",
  "age": 22,
  "occupation": "College student",
  "income": 15000,
  "personality": "Personality description",
  "goals": "User goals",
  "preferences": "Product preferences",
  "pain_points": "User problems",
  "behavior_scores": {{
    "expense_tracking": 3,
    "saving_habit": 4,
    "shopping_frequency": 2,
    "impulse_buying": 3,
    "budget_awareness": 4,
    "technology_usage": 5
  }}
}}

Rules:
- Return valid JSON only. No Markdown or extra text.
- Use Indian rupees for monthly income.
- Age and income must be numeric.
- Every behavior score must be an integer from 1 to 5.
- All text fields must be non-empty.
- Create a fictional person.
- Keep descriptions short to avoid incomplete JSON.
"""

    response = chat(
        model="qwen3:1.7b",
        format="json",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        options={
            "temperature": 0.1,
            "num_predict": 800
        }
    )

    raw_response = response.message.content.strip()

    # Convert the model response into a Python dictionary
    try:
        persona = json.loads(raw_response)
    except json.JSONDecodeError as error:
        print("Invalid JSON returned by Qwen3:")
        print(raw_response)
        raise ValueError(
            f"Qwen3 returned incomplete JSON: {error}"
        ) from error

    # Check required fields
    required_fields = [
        "name",
        "age",
        "occupation",
        "income",
        "personality",
        "goals",
        "preferences",
        "pain_points",
        "behavior_scores"
    ]

    for field in required_fields:
        if field not in persona:
            raise ValueError(f"Missing persona field: {field}")

    # Validate behavior scores
    if not isinstance(persona["behavior_scores"], dict):
        raise ValueError("Behavior scores must be a JSON object")

    score_fields = [
        "expense_tracking",
        "saving_habit",
        "shopping_frequency",
        "impulse_buying",
        "budget_awareness",
        "technology_usage"
    ]

    for field in score_fields:
        score = persona["behavior_scores"].get(field)

        if type(score) is not int or not 1 <= score <= 5:
            raise ValueError(
                f"Invalid behavior score for {field}: {score}"
            )

    # Validate age
    if type(persona["age"]) is not int or persona["age"] < 1:
        raise ValueError("Age must be a positive integer")

    # Validate income
    if (
        type(persona["income"]) not in (int, float)
        or persona["income"] < 0
    ):
        raise ValueError("Income must be a non-negative number")

    # Validate text fields
    text_fields = [
        "name",
        "occupation",
        "personality",
        "goals",
        "preferences",
        "pain_points"
    ]

    for field in text_fields:
        value = persona.get(field)

        if isinstance(value, list):
            persona[field] = ", ".join(
                str(item).strip()
                for item in value
                if str(item).strip()
            )

        value = persona.get(field)

        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"Invalid text field: {field}, value={value!r}"
            )

    return persona