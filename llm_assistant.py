"""llm_assistant.py — OpenAI-powered function-calling assistant for AgriFlow.

Question -> model may call one or more functions (looping until it has
enough to answer) -> each function hits the real DB via loaders passed in
from api.py -> model phrases a grounded natural-language answer.

Three things layered on top of the basic version:
  1. Multi-turn memory: pass prior chat turns in `history` so follow-up
     questions ("how far is that from Amreli?") resolve correctly.
  2. Grounding + fuzzy matching: the model is told never to state a number
     that isn't in a function result, and district/plant name lookups
     tolerate typos/misspellings instead of hard-failing on exact match.
  3. Multi-step agent loop: the model can chain several function calls
     (e.g. "top 3 districts" -> then "nearest plant" for each) before
     producing a final answer, instead of being limited to one call.

NEW: generate_insights() — proactive, unprompted insight bullets for the
dashboard on load. Deliberately does NOT reuse the tool-calling loop above:
that loop lets the model decide what to look up, which is right for open-
ended Q&A but wrong here, where we want a fixed, cheap, predictable set of
real numbers handed to the model in one shot, with no risk of it wandering
into extra tool calls (extra cost, extra latency) or narrating unrelated
things. Same grounding rule applies: only phrase what's in the payload.

Requires:
    OPENAI_API_KEY   (set in .env locally, and in Render's environment settings)
"""

import difflib
import json
import os

from openai import OpenAI

MODEL_ID = "gpt-4o-mini"
MAX_TOOL_ITERATIONS = 5  # hard cap so a confused loop can't run away on cost

# UI language codes -> English name for the system prompt. The assistant
# always answers in the language the user picked in the dropdown, regardless
# of which language the question itself was asked in (a Gujarati speaker may
# type or voice a question in English/Hindi and still get a Gujarati answer).
LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "gu": "Gujarati"}


def _language_instruction(language: str) -> str:
    name = LANGUAGE_NAMES.get(language or "en", "English")
    return (
        f"Answer in {name}. The user may ask the question in any language "
        f"(e.g. English, Hindi, Gujarati, or mixed Hinglish) — always reply "
        f"in {name} unless the user explicitly asks for a different language. "
        "Keep the same content rules as the main prompt: 1-3 plain sentences, "
        "only numbers present in function results, and call the functions when "
        "you need data."
    )

_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

SYSTEM_PROMPT = (
    "You are AgriFlow's assistant, a biomass supply-chain tool. Use the "
    "provided functions to look up real data before answering — never state "
    "a number that isn't present in a function's result. If a function "
    "result contains an 'error' field, say plainly that you don't have that "
    "data — do not guess or make something up. If a result contains a "
    "'note' field (a fuzzy name match), mention which name you interpreted "
    "the question as before answering. You may call functions more than "
    "once, or call several different functions, if the question needs "
    "several pieces of data (e.g. comparing multiple districts). Quantities "
    "are dimensionless dataset biomass units, not tonnes. Keep answers to "
    "1-3 plain sentences unless the question genuinely needs a list."
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
            "description": "Get a plant's capacity, location, current utilization, and status by plant name or plant_id (e.g. 'P1' or 'Biofics Bio-CNG Plant').",
            "parameters": {
                "type": "object",
                "properties": {
                    "plant": {"type": "string", "description": "Plant name or plant_id"}
                },
                "required": ["plant"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_route_economics",
            "description": "Get the biomass sale-profit vs transport-cost analysis for the current match plan: totals (revenue, transport cost, profit, margin), breakeven distance, and the least/most profitable district-to-plant routes. Money values use demo rates (see parameters in the result).",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "How many worst/best routes to include (default 5)"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_plant_profitability",
            "description": "Rank plants by total profit from their matched routes (revenue minus transport cost), highest profit first, including margin and routes served. Money values use demo rates.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# ---------------------------------------------------------------------------
# Fuzzy matching helper — tolerates typos/misspellings on district & plant
# names instead of hard-failing on anything that isn't an exact match.
# ---------------------------------------------------------------------------
def _resolve_name(query: str, candidates: list[str], cutoff: float = 0.6) -> tuple[str | None, bool]:
    """Returns (matched_name, was_fuzzy). matched_name is None if nothing close enough."""
    q = query.strip().lower()
    for c in candidates:
        if c.lower() == q:
            return c, False
    close = difflib.get_close_matches(q, [c.lower() for c in candidates], n=1, cutoff=cutoff)
    if close:
        matched = next(c for c in candidates if c.lower() == close[0])
        return matched, True
    return None, False


# ---------------------------------------------------------------------------
# The functions the model is allowed to call. Each returns JSON-safe data
# pulled straight from the same loaders api.py already uses, so answers
# always match what's on screen — no separate/stale data path.
# ---------------------------------------------------------------------------
def _get_district_supply(args, load_all_districts, **_):
    query = args.get("district", "")
    districts = load_all_districts()
    names = [d["district"] for d in districts]
    matched, was_fuzzy = _resolve_name(query, names)
    if not matched:
        return {"error": f"No district matching '{query}' found."}
    d = next(x for x in districts if x["district"] == matched)
    return {**d, "note": f"Interpreted '{query}' as '{matched}'."} if was_fuzzy else d


def _get_underused_plants(_args, get_plant_utilization, **_):
    plants = get_plant_utilization()
    return {"plants_by_utilization_ascending": sorted(plants, key=lambda p: p["utilization_pct"])}


def _get_unmatched_districts(_args, load_all_districts, get_matches, **_):
    matched_names = {m["district"] for m in get_matches()}
    districts = load_all_districts()
    return {"unmatched_districts": [d["district"] for d in districts if d["district"] not in matched_names]}


def _latest_supply(d: dict) -> float:
    """Latest available forecast — 2026 primary, 2024/2018 fallbacks."""
    for key in ("predicted_supply_2026", "predicted_supply_2024", "predicted_supply_2018"):
        value = d.get(key)
        if value:
            return float(value)
    return 0.0


def _get_top_supply_districts(args, load_all_districts, **_):
    n = int(args.get("n", 5))
    districts = sorted(load_all_districts(), key=lambda d: -_latest_supply(d))
    return {"top_districts": districts[:n]}


def _get_nearest_plant(args, load_all_districts, load_all_plants, **_):
    from matching import haversine_km  # reuse the one distance implementation, no duplicate math

    query = args.get("district", "")
    districts = load_all_districts()
    names = [d["district"] for d in districts]
    matched, was_fuzzy = _resolve_name(query, names)
    if not matched:
        return {"error": f"No district matching '{query}' found."}
    d = next(x for x in districts if x["district"] == matched)

    plants = load_all_plants()
    ranked = sorted(
        plants,
        key=lambda p: haversine_km(d["latitude"], d["longitude"], p["latitude"], p["longitude"]),
    )
    nearest = ranked[0]
    distance = haversine_km(d["latitude"], d["longitude"], nearest["latitude"], nearest["longitude"])
    result = {
        "district": d["district"],
        "nearest_plant_name": nearest["plant_name"],
        "nearest_plant_id": nearest["plant_id"],
        "distance_km": round(distance, 1),
        "plant_annual_capacity": nearest["annual_capacity"],
    }
    if was_fuzzy:
        result["note"] = f"Interpreted '{query}' as '{matched}'."
    return result


def _get_route_economics(args, get_economics, **_):
    n = max(1, int(args.get("n", 5)))
    result = get_economics(top_n=n)
    return {
        "summary": result["summary"],
        "breakeven_distance_km": result["breakeven_distance_km"],
        "parameters": result["parameters"],
        "worst_routes": result["worst_routes"],
        "best_routes": result["best_routes"],
    }


def _get_plant_profitability(_args, get_economics, **_):
    result = get_economics()
    by_plant = result["by_plant"]
    ranked = sorted(
        ({"plant_id": pid, **agg} for pid, agg in by_plant.items()),
        key=lambda p: -p["profit"],
    )
    return {
        "plants_ranked_by_profit": ranked,
        "parameters": result["parameters"],
    }


def _get_plant_details(args, get_plant_utilization, **_):
    query = args.get("plant", "")
    plants = get_plant_utilization()
    # Match against both plant_id and plant_name.
    id_names = [p["plant_id"] for p in plants]
    matched_id, was_fuzzy = _resolve_name(query, id_names)
    if not matched_id:
        full_names = [p["plant_name"] for p in plants]
        matched_name, was_fuzzy = _resolve_name(query, full_names)
        if not matched_name:
            return {"error": f"No plant matching '{query}' found."}
        p = next(x for x in plants if x["plant_name"] == matched_name)
    else:
        p = next(x for x in plants if x["plant_id"] == matched_id)
    return {**p, "note": f"Interpreted '{query}' as '{p['plant_name']}'."} if was_fuzzy else p


DISPATCH = {
    "get_district_supply": _get_district_supply,
    "get_underused_plants": _get_underused_plants,
    "get_unmatched_districts": _get_unmatched_districts,
    "get_top_supply_districts": _get_top_supply_districts,
    "get_nearest_plant": _get_nearest_plant,
    "get_plant_details": _get_plant_details,
    "get_route_economics": _get_route_economics,
    "get_plant_profitability": _get_plant_profitability,
}


def answer_question(
    question: str,
    *,
    load_all_districts,
    load_all_plants,
    get_plant_utilization,
    get_matches,
    get_economics=None,
    get_impact=None,
    language: str = "en",
    history: list[dict] | None = None,
) -> dict:
    """Main entry point.

    `history` is prior turns as [{"role": "user"/"assistant", "content": str}, ...]
    from oldest to newest, NOT including the current `question`.
    `language` is the UI language code (en/hi/gu) — the answer is phrased in it.

    Data-loading functions are passed in from api.py so this module never
    talks to the DB directly — one source of truth.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": _language_instruction(language)},
    ]
    messages.extend(history or [])
    messages.append({"role": "user", "content": question})

    functions_called = []

    for _ in range(MAX_TOOL_ITERATIONS):
        response = _client.chat.completions.create(
            model=MODEL_ID,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        choice = response.choices[0]

        if not choice.message.tool_calls:
            return {
                "answer": choice.message.content.strip(),
                "supporting_data": {"functions_called": functions_called},
            }

        messages.append(choice.message)
        for call in choice.message.tool_calls:
            fn_name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            handler = DISPATCH.get(fn_name)
            if handler and fn_name in ("get_route_economics", "get_plant_profitability") and get_economics is None:
                result = {"error": "Economics data is not available in this context."}
            else:
                result = (
                    handler(
                        args,
                        load_all_districts=load_all_districts,
                        load_all_plants=load_all_plants,
                        get_plant_utilization=get_plant_utilization,
                        get_matches=get_matches,
                        get_economics=get_economics,
                    )
                    if handler else {"error": f"Unknown function '{fn_name}'"}
                )
            functions_called.append({"function": fn_name, "args": args})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)})

    # Hit the iteration cap — force a final answer without offering more tools.
    final = _client.chat.completions.create(model=MODEL_ID, messages=messages)
    return {
        "answer": final.choices[0].message.content.strip(),
        "supporting_data": {"functions_called": functions_called, "note": "hit max tool iterations"},
    }


# ---------------------------------------------------------------------------
# Proactive insights — dashboard-load bullets, not user-triggered Q&A.
# ---------------------------------------------------------------------------
INSIGHTS_SYSTEM_PROMPT = (
    "You write short, punchy insight bullets for a biomass supply-chain "
    "dashboard. You will be given a JSON payload of real, already-computed "
    "numbers — top-supply districts, plant utilization, unmatched supply, "
    "and totals. Pick the 2 or 3 most interesting, non-obvious facts and "
    "phrase each as a single plain-English sentence, under 20 words. "
    "Only state numbers and names that appear in the payload — never "
    "invent, round dramatically, or infer anything not present. Quantities "
    "are dimensionless dataset biomass units, not tonnes; do not call them "
    "tonnes or kg. Do not use the word 'confidence' unless a confidence "
    "field is in the payload. Respond with ONLY a JSON object of the shape "
    '{"insights": ["...", "...", "..."]} — no other text, no markdown.'
)


def generate_insights(
    *,
    load_all_districts,
    load_all_plants,
    get_plant_utilization,
    get_matches,
    get_economics=None,
    get_impact=None,
) -> dict:
    """Generate 2-3 proactive insight bullets for dashboard load.

    Deliberately skips the tool-calling loop in answer_question(): the data
    needed here is fixed and small, so we gather it directly with the same
    loaders api.py already uses (one source of truth, no drift from what's
    on screen) and make a single LLM call to phrase it. No agent loop, no
    risk of extra tool calls or wandering off-topic — cheap and predictable,
    which matters since this runs unprompted on every page load.
    """
    districts = load_all_districts()
    plants = get_plant_utilization()
    matches = get_matches()

    matched_names = {m["district"] for m in matches}
    unmatched = [d["district"] for d in districts if d["district"] not in matched_names]

    # Route economics (best effort — demo rates, see economics.py). If the
    # loader isn't wired in, the payload just omits it and the LLM/fallback
    # never mentions it.
    economics = get_economics() if get_economics is not None else None
    impact = get_impact() if get_impact is not None else None

    top_districts = sorted(districts, key=lambda d: -_latest_supply(d))[:5]
    plants_by_util = sorted(plants, key=lambda p: p["utilization_pct"])

    total_supply = sum(_latest_supply(d) for d in districts)
    total_matched = sum(m["matched_supply"] for m in matches)
    leftover = total_supply - total_matched

    data_payload = {
        "top_supply_districts": [
            {"district": d["district"], "predicted_supply": _latest_supply(d)}
            for d in top_districts
        ],
        "unmatched_districts": unmatched,
        "plant_utilization_ascending": [
            {"plant_name": p["plant_name"], "utilization_pct": p["utilization_pct"]}
            for p in plants_by_util
        ],
        "total_predicted_supply_units": round(total_supply, 1),
        "total_matched_units": round(total_matched, 1),
        "leftover_unmatched_units": round(leftover, 1),
    }
    if economics:
        data_payload["economics"] = {
            "total_profit": economics["summary"]["profit"],
            "total_revenue": economics["summary"]["revenue"],
            "total_transport_cost": economics["summary"]["transport_cost"],
            "overall_margin_pct": economics["summary"]["margin_pct"],
            "unprofitable_routes": economics["summary"]["unprofitable_routes"],
            "worst_route": (economics["worst_routes"] or [None])[0],
            "note": "Money values use demo rates (sale price, cost/km/unit, round-trip factor) — see /economics.",
        }
    if impact:
        data_payload["impact"] = {
            "leftover_tonnes": impact["leftover_tonnes"],
            "co2_avoided_tonnes": impact["co2_avoided_tonnes"],
            "equivalent_cars_off_road_for_a_year": impact["equivalent_cars_off_road_for_a_year"],
            "note": "CO2 figures use impact.py assumptions (1 unit = 1 tonne; Ni et al. 2015 emission factor).",
        }

    try:
        response = _client.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {"role": "system", "content": INSIGHTS_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(data_payload)},
            ],
            response_format={"type": "json_object"},
        )
        parsed = json.loads(response.choices[0].message.content)
        insights = parsed.get("insights", [])
        if not isinstance(insights, list) or not insights:
            raise ValueError("model returned no insights")
        # Keep it to at most 3, and make sure every entry is a plain string.
        insights = [str(x) for x in insights][:3]
    except Exception as e:
        # Fail soft: the dashboard shouldn't break because a phrasing call
        # failed. Fall back to a couple of insights built directly from the
        # data with no LLM involved.
        insights = _fallback_insights(data_payload)
        return {"insights": insights, "source": "fallback", "error": str(e)}

    return {"insights": insights, "source": "llm", "supporting_data": data_payload}


def _fallback_insights(data_payload: dict) -> list[str]:
    """Deterministic, LLM-free insights used if the OpenAI call fails —
    dashboard load should never show nothing just because an API hiccuped."""
    out = []
    top = data_payload.get("top_supply_districts") or []
    if top:
        d = top[0]
        out.append(
            f"{d['district']} has the highest predicted supply at "
            f"{d['predicted_supply']:.0f} units."
        )
    leftover = data_payload.get("leftover_unmatched_units")
    total = data_payload.get("total_predicted_supply_units")
    if leftover and total:
        pct = 100 * leftover / total if total else 0
        out.append(f"{leftover:.0f} units ({pct:.0f}% of total supply) remain unmatched today.")
    unmatched = data_payload.get("unmatched_districts") or []
    if unmatched:
        out.append(f"{len(unmatched)} district(s) have no matched plant yet.")
    economics = data_payload.get("economics") or {}
    worst = economics.get("worst_route")
    if worst:
        out.append(
            f"{worst['district']} is the least profitable matched route "
            f"at {worst['margin_pct']}% margin under demo rates."
        )
    elif economics.get("unprofitable_routes") == 0 and economics.get("total_profit") is not None:
        out.append("All matched routes are profitable under the current demo rates.")
    return out[:3] or ["No insights available right now."]