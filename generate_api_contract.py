"""generate_api_contract.py — serialize the live API into api-contract.json.

Produces a json-server-compatible contract file from the actual API
responses, so the frontend can run a working fake API without the backend:

    npx json-server api-contract.json --port 3001

Resource routes work out of the box because every record carries an `id`
(so GET /districts/Amreli and GET /plants/P1 resolve). /health and
/assistant/query can't be faked by json-server (it has no POST handlers),
so their example payloads live under `_health` / `_assistant_query_example`
for reference.

Re-run this after the data or the endpoints change to refresh the contract.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from main import app

OUT = Path(__file__).resolve().parent / "api-contract.json"


def main() -> None:
    client = TestClient(app)

    districts = client.get("/districts").json()
    plants = client.get("/plants").json()
    predictions = client.get("/predictions").json()
    matches = client.get("/matches").json()
    health = client.get("/health").json()
    assistant = client.post(
        "/assistant/query", json={"question": "Which district has the highest biomass?"}
    ).json()

    for record in districts:
        record["id"] = record["district"]
    for record in plants:
        record["id"] = record["plant_id"]
    for record in predictions:
        record["id"] = f"{record['district']}-{record['year']}"
    for index, record in enumerate(matches, start=1):
        record["id"] = index

    contract = {
        "_health": [health],
        "_assistant_query_example": [assistant],
        "districts": districts,
        "plants": plants,
        "predictions": predictions,
        "matches": matches,
    }

    OUT.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    print(
        f"wrote {OUT} ({len(districts)} districts, {len(plants)} plants, "
        f"{len(predictions)} predictions, {len(matches)} matches)"
    )


if __name__ == "__main__":
    main()
