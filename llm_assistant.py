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
    "numbers. You can look up: a district's predicted supply, a plant's "
    "capacity/utilization, the nearest plant to a district (with distance "
    "in km), unmatched districts, and top-supply districts. Quantities are "
    "dimensionless dataset biomass units, not tonnes. Keep answers to "
    "1-3 plain sentences."
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
    {
        "type": "function",
        "function": {
            "name": "get_nearest_plant",
            "description": "Find the nearest plant to a named district, by straight-line distance in km, including that plant's capacity. Use this for any 'how far' or 'nearest plant' question.",
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
            "name": "get_plant_details",
            "description": "Get a plant's capacity, location, current utilization, and status by plant name or plant_id (e.g. 'P1' or 'AgriFlow Plant 1').",
            "parameters": {
                "type": "object",
                "properties": {
                    "plant": {"type": "string", "description": "Plant name or plant_id"}
                },
                "required": ["plant"],
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


def _get_nearest_plant(args, load_all_districts, load_all_plants, **_):
    from matching import haversine_km  # reuse the one distance implementation, no duplicate math

    district_name = args.get("district", "")
    districts = load_all_districts()
    d = next((x for x in districts if x["district"].lower() == district_name.lower()), None)
    if not d:
        return {"error": f"No district named '{district_name}' found."}

    plants = load_all_plants()
    ranked = sorted(
        plants,
        key=lambda p: haversine_km(d["latitude"], d["longitude"], p["latitude"], p["longitude"]),
    )
    nearest = ranked[0]
    distance = haversine_km(d["latitude"], d["longitude"], nearest["latitude"], nearest["longitude"])
    return {
        "district": d["district"],
        "nearest_plant_name": nearest["plant_name"],
        "nearest_plant_id": nearest["plant_id"],
        "distance_km": round(distance, 1),
        "plant_annual_capacity": nearest["annual_capacity"],
    }


def _get_plant_details(args, get_plant_utilization, **_):
    query = args.get("plant", "").lower()
    for p in get_plant_utilization():
        if p["plant_id"].lower() == query or p["plant_name"].lower() == query:
            return p
    return {"error": f"No plant matching '{args.get('plant', '')}' found."}


DISPATCH = {
    "get_district_supply": _get_district_supply,
    "get_underused_plants": _get_underused_plants,
    "get_unmatched_districts": _get_unmatched_districts,
    "get_top_supply_districts": _get_top_supply_districts,
    "get_nearest_plant": _get_nearest_plant,
    "get_plant_details": _get_plant_details,
}


def answer_question(question: str, *, load_all_districts, load_all_plants, get_plant_utilization, get_matches) -> dict:
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
        handler(args, load_all_districts=load_all_districts, load_all_plants=load_all_plants,
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