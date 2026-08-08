"""llm_assistant.py — OpenAI-powered function-calling assistant for AgriFlow.

Same pattern as Task360: question -> model picks a function (via OpenAI's
native tool-calling) -> we run it against the DB -> model turns the result
into a natural-language answer.

Requires:
    OPENAI_API_KEY   (set in .env locally, and in Render's environment settings)

Usage from api.py:
    from llm_assistant import answer_question
    result = answer_question(payload.question, load_all_districts=..., ...)
"""

import json
import os

from openai import OpenAI

MODEL_ID = "gpt-4o-mini"  # cheap + fast; swap for gpt-4.1-mini or similar if you prefer

_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

SYSTEM_PROMPT = (
    "You are AgriFlow's assistant, a biomass supply-chain tool. Use the "
    "provided functions to look up real data before answering — never guess "
    "numbers. Quantities are dimensionless dataset biomass units, not "
    "tonnes. Keep answers to 1-3 plain sentences."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_district_supply",
            "description": "Get predicted supply, confidence, and residue type for one named district.",
            "parameters": {
                "type": "object",
                "properties": {
                    "district": {"type": "string", "description": "District name, e.g. 'Amreli'"}
                },
                "required": ["district"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_underused_plants",
            "description": "List all plants ranked by utilization percentage, lowest first.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_unmatched_districts",
            "description": "List districts whose supply hasn't been matched to any plant yet.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_supply_districts",
            "description": "Get the N districts with the highest predicted supply.",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "How many districts to return (default 5)"}
                },
            },
        },
    },
]


# ---------------------------------------------------------------------------
# The functions the model is allowed to call. Each returns JSON-safe data
# pulled straight from the same loaders api.py already uses, so answers
# always match what's on screen — no separate/stale data path.
# ---------------------------------------------------------------------------
def _get_district_supply(args, load_all_districts, **_):
    district = args.get("district", "")
    for d in load_all_districts():
        if d["district"].lower() == district.lower():
            return d
    return {"error": f"No district named '{district}' found."}


def _get_underused_plants(_args, get_plant_utilization, **_):
    plants = get_plant_utilization()
    return {"plants_by_utilization_ascending": sorted(plants, key=lambda p: p["utilization_pct"])}


def _get_unmatched_districts(_args, load_all_districts, get_matches, **_):
    matched_names = {m["district"] for m in get_matches()}
    districts = load_all_districts()
    return {"unmatched_districts": [d["district"] for d in districts if d["district"] not in matched_names]}


def _get_top_supply_districts(args, load_all_districts, **_):
    n = int(args.get("n", 5))
    districts = sorted(load_all_districts(), key=lambda d: -d["predicted_supply_2018"])
    return {"top_districts": districts[:n]}


DISPATCH = {
    "get_district_supply": _get_district_supply,
    "get_underused_plants": _get_underused_plants,
    "get_unmatched_districts": _get_unmatched_districts,
    "get_top_supply_districts": _get_top_supply_districts,
}


def answer_question(question: str, *, load_all_districts, get_plant_utilization, get_matches) -> dict:
    """Main entry point. Data-loading functions are passed in from api.py
    so this module never talks to the DB directly — one source of truth."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    first = _client.chat.completions.create(
        model=MODEL_ID,
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
    )
    choice = first.choices[0]

    tool_calls = choice.message.tool_calls
    if not tool_calls:
        # Model answered directly without needing a function — pass it through.
        return {"answer": choice.message.content.strip(), "supporting_data": {}}

    call = tool_calls[0]
    fn_name = call.function.name
    try:
        args = json.loads(call.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}

    handler = DISPATCH.get(fn_name)
    result = (
        handler(args, load_all_districts=load_all_districts,
                 get_plant_utilization=get_plant_utilization, get_matches=get_matches)
        if handler else {"error": f"Unknown function '{fn_name}'"}
    )

    # Second call: give the model the function result, ask it to phrase the answer.
    messages.append(choice.message)
    messages.append({
        "role": "tool",
        "tool_call_id": call.id,
        "content": json.dumps(result),
    })
    second = _client.chat.completions.create(model=MODEL_ID, messages=messages)
    answer_text = second.choices[0].message.content.strip()

    return {"answer": answer_text, "supporting_data": {"function_called": fn_name, "result": result}}