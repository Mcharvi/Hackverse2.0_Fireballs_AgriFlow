"""matching.py — AgriFlow supply–demand matching + route ordering.

Person B's operational layer: given predicted district supply and plant
capacities, assign each district's supply to plants, splitting oversupply
across plants and recording what can't be absorbed.

Design choices (documented so we can answer "why this algorithm?" honestly):
  - DEFAULT SOLVER IS EXACT, NOT GREEDY. This is a classic transportation
    problem (20 districts × 6 plants = 120 continuous allocation variables),
    and it's solved to proven optimality with a hand-written min-cost
    max-flow (successive shortest paths, ~60 lines, no solver dependency).
    Greedy nearest-plant matching is NOT optimal for total haul cost: it
    commits each district to its nearest plant in isolation, so a big
    district can fill a plant that a distant district needs more, inflating
    total ton-km. The flow solver considers every district–plant pair
    jointly and minimizes total ton-km (equivalently haul cost, since the
    per-ton-km rate is a constant scale factor).
  - Absorption is capacity-capped, not routing-capped: with total plant
    capacity below total supply, the objective is "which units go to which
    plant at minimum cost", not "absorb more". The flow maximizes absorbed
    units first (all absorbable supply ships — we assume the cost of
    unabsorbed residue burning exceeds any transport cost; the knob for
    "don't ship uneconomically far units" would be a leftover-penalty edge
    in the flow network), then minimizes cost among those flows.
  - The greedy is kept as `--solver greedy` / `--compare` so the optimal
    answer can be shown against the old heuristic with real numbers
    (ton-km / haul cost before vs after).
  - `min_alloc` is the economic lot threshold: allocations below it are
    skipped so we don't dispatch pickups for fragments, and that capacity
    sits idle instead. In optimal mode it's enforced by a refinement loop
    (drop fragments, then re-solve leftover supply against freed capacity
    until nothing economically viable remains); in greedy mode it's the
    original mid-assignment skip. Either way it's the answer to "why is a
    plant under 100% utilized?"
  - Route ordering is nearest-first per plant (a simple, honest heuristic,
    not a full VRP — true vehicle routing is out of scope for the demo).
  - Unabsorbed supply is NOT stored in `matches` — it is the difference
    between total predicted supply and matched quantity, visible to the
    frontend and the LLM assistant as "leftover that would otherwise burn".

Cost model:
  - COST_PER_TON_KM is a flat ₹/tonne-km road-freight ballpark (typical
    Indian trucking ₹2–3/t-km; demo default 2.0). The allocation optimum
    does not depend on the rate (constant scale factor), so the rate only
    shows up in the reported ₹ haul cost.

Usage:
    python matching.py                     # exact min-cost-flow matches into agriflow.db
    python matching.py --dry-run           # print the plan without writing anything
    python matching.py --solver greedy     # old greedy heuristic, for comparison
    python matching.py --compare           # run both, print cost comparison, write optimal
    python matching.py --min-alloc 1000    # tune the economic lot threshold
"""

import argparse
import math
import sqlite3
from collections import deque
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "agriflow.db"
EARTH_RADIUS_KM = 6371.0
COST_PER_TON_KM = 2.0  # ₹ per tonne-km, flat road-freight ballpark (demo default)
_EPS = 1e-9


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in km."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def district_supply(d: dict) -> float:
    """Latest available forecast for a district — 2026 primary, with the 2024
    and 2018 forecasts as fallbacks for older data layers.

    Uses `is not None` (not truthiness) so a district with a genuine zero
    supply value isn't silently promoted to an older, non-zero forecast.
    """
    for key in ("predicted_supply_2026", "predicted_supply_2024", "predicted_supply_2018"):
        value = d.get(key)
        if value is not None:
            return float(value)
    return 0.0


def load_districts(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [
        dict(r)
        for r in conn.execute(
            "SELECT district, latitude, longitude, predicted_supply_2018, "
            "predicted_supply_2024, predicted_supply_2026 FROM districts"
        )
    ]


def load_plants(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [
        dict(r)
        for r in conn.execute(
            "SELECT plant_id, latitude, longitude, annual_capacity FROM plants"
        )
    ]


# ---------------------------------------------------------------------------
# Min-cost max-flow (successive shortest paths) — exact transportation solver
# ---------------------------------------------------------------------------
def _min_cost_max_flow(
    num_nodes: int, edges: list[tuple[int, int, float, float]], source: int, sink: int
) -> list[float]:
    """Push max flow from `source` to `sink` at minimum total cost.

    `edges` is a list of (u, v, capacity, cost_per_unit); capacities and
    costs may be floats. Returns the shipped quantity per edge, in the same
    order as `edges`. Deterministic FIFO-SPFA shortest paths; correct for
    this network (non-negative forward costs, no negative-cost cycles).
    Tiny graphs here (≤ ~130 edges) — runs in microseconds.
    """
    graph: list[list[list]] = [[] for _ in range(num_nodes)]
    forward: list[list] = []  # mutable refs to the forward edge of each input edge

    def _add(u: int, v: int, cap: float, cost: float) -> list:
        fwd = [v, cap, cost, len(graph[v])]
        graph[u].append(fwd)
        graph[v].append([u, 0.0, -cost, len(graph[u]) - 1])
        return fwd

    for u, v, cap, cost in edges:
        forward.append(_add(u, v, cap, cost))

    while True:
        dist = [float("inf")] * num_nodes
        prev_v = [-1] * num_nodes
        prev_e = [-1] * num_nodes
        in_queue = [False] * num_nodes
        dist[source] = 0.0
        queue = deque([source])
        in_queue[source] = True
        while queue:
            u = queue.popleft()
            in_queue[u] = False
            du = dist[u]
            for ei, (v, cap, cost, _rev) in enumerate(graph[u]):
                if cap > _EPS and du + cost < dist[v] - _EPS:
                    dist[v] = du + cost
                    prev_v[v] = u
                    prev_e[v] = ei
                    if not in_queue[v]:
                        queue.append(v)
                        in_queue[v] = True
        if dist[sink] == float("inf"):
            break
        # Bottleneck along the shortest path.
        add = float("inf")
        v = sink
        while v != source:
            u = prev_v[v]
            add = min(add, graph[u][prev_e[v]][1])
            v = u
        # Augment.
        v = sink
        while v != source:
            u = prev_v[v]
            edge = graph[u][prev_e[v]]
            edge[1] -= add
            graph[v][edge[3]][1] += add
            v = u

    # Flow on each forward edge = residual on its reverse edge (exact even
    # for infinite-capacity edges, where inf - inf would be NaN).
    return [graph[fwd[0]][fwd[3]][1] for fwd in forward]


def _optimal_matches(
    districts: list[dict],
    plants: list[dict],
    min_alloc: float,
    cost_per_ton_km: float,
) -> list[dict]:
    """Exact min-cost transportation with an economic-lot refinement loop.

    Stage 1: one min-cost max-flow over every district–plant pair — total
    ton-km minimized among all flows that absorb every unit the plants can
    take (this is the globally optimal routing; it's what dominates cost).
    Stage 2: allocations below `min_alloc` are dropped as fragments, then
    leftover supply is re-solved against the freed capacity and the loop
    repeats until no economically-viable allocation remains. This recovers
    absorption the plain post-filter would strand (e.g. a plant whose only
    free capacity came from one dropped fragment), while still never
    dispatching a pickup smaller than the lot threshold.
    """

    def _solve_once(
        ds: list[dict], ps: list[dict], capacities: dict[str, float], supplies: dict[str, float]
    ) -> list[tuple[str, str, float]]:
        """One min-cost max-flow over active districts × active plants.
        Returns only allocations >= min_alloc."""
        d_nodes = {d["district"]: i + 1 for i, d in enumerate(ds)}
        p_nodes = {p["plant_id"]: 1 + len(ds) + i for i, p in enumerate(ps)}
        source = 0
        sink = 1 + len(ds) + len(ps)
        edges: list[tuple[int, int, float, float]] = []
        for d in ds:
            supply = supplies[d["district"]]
            if supply > _EPS:
                edges.append((source, d_nodes[d["district"]], supply, 0.0))
        for d in ds:
            for p in ps:
                cost = (
                    haversine_km(d["latitude"], d["longitude"], p["latitude"], p["longitude"])
                    * cost_per_ton_km
                )
                edges.append((d_nodes[d["district"]], p_nodes[p["plant_id"]], float("inf"), cost))
        for p in ps:
            edges.append((p_nodes[p["plant_id"]], sink, capacities[p["plant_id"]], 0.0))

        shipped = _min_cost_max_flow(len(ds) + len(ps) + 2, edges, source, sink)
        # shipped[] aligns with `edges`; skip the source→district edges to
        # reach the district→plant block.
        flow_idx = sum(1 for e in edges if e[0] == source)
        out: list[tuple[str, str, float]] = []
        for d in ds:
            for p in ps:
                qty = shipped[flow_idx]
                flow_idx += 1
                if qty > _EPS and qty >= min_alloc - _EPS:
                    out.append((d["district"], p["plant_id"], qty))
        return out

    remaining = {d["district"]: district_supply(d) for d in districts}
    freed = {p["plant_id"]: float(p["annual_capacity"] or 0.0) for p in plants}
    accepted: list[tuple[str, str, float]] = []

    while True:
        # A district can't be served a pickup below the lot threshold, and a
        # plant with less than a lot of free capacity can't take one either.
        ds = [d for d in districts if remaining[d["district"]] >= min_alloc - _EPS]
        ps = [p for p in plants if freed[p["plant_id"]] >= min_alloc - _EPS]
        if not ds or not ps:
            break
        new = _solve_once(ds, ps, freed, remaining)
        if not new:
            break
        for district, plant_id, qty in new:
            accepted.append((district, plant_id, qty))
            remaining[district] -= qty
            freed[plant_id] -= qty

    # Merge per (district, plant) so the output has one row per pair, then
    # build the match rows (same shape as the greedy solver's).
    merged: dict[tuple[str, str], float] = {}
    for district, plant_id, qty in accepted:
        merged[(district, plant_id)] = merged.get((district, plant_id), 0.0) + qty
    matches: list[dict] = []
    for (district, plant_id), qty in sorted(merged.items()):
        d = next(x for x in districts if x["district"] == district)
        p = next(x for x in plants if x["plant_id"] == plant_id)
        matches.append(
            {
                "district": district,
                "plant_id": plant_id,
                "allocated_quantity": round(qty, 1),
                "distance_km": round(
                    haversine_km(d["latitude"], d["longitude"], p["latitude"], p["longitude"]),
                    1,
                ),
                "pickup_order": None,
                "status": "matched",
            }
        )
    return matches


def _greedy_matches(districts: list[dict], plants: list[dict], min_alloc: float) -> list[dict]:
    """The original greedy heuristic, kept for comparison: districts processed
    largest-supply first, each drawing from its nearest plant with remaining
    capacity, splitting across plants when one can't take the whole supply.
    Locally sensible, globally NOT optimal (see module docstring)."""
    remaining = {p["plant_id"]: float(p["annual_capacity"]) for p in plants}
    matches: list[dict] = []

    for district in sorted(
        districts,
        key=lambda d: (-district_supply(d), d["district"]),
    ):
        supply = district_supply(district)
        to_assign = supply

        # Nearest plants first (distance tie-break by plant id).
        candidates = sorted(
            plants,
            key=lambda p: (
                haversine_km(
                    district["latitude"], district["longitude"],
                    p["latitude"], p["longitude"],
                ),
                p["plant_id"],
            ),
        )
        for plant in candidates:
            if to_assign <= _EPS:
                break
            capacity_left = remaining[plant["plant_id"]]
            if capacity_left <= _EPS:
                continue
            qty = min(to_assign, capacity_left)
            if qty < min_alloc:
                # Below the economic threshold — leave this capacity idle
                # rather than dispatch a pickup for a fragment.
                continue
            matches.append(
                {
                    "district": district["district"],
                    "plant_id": plant["plant_id"],
                    "allocated_quantity": round(qty, 1),
                    "distance_km": round(
                        haversine_km(
                            district["latitude"], district["longitude"],
                            plant["latitude"], plant["longitude"],
                        ),
                        1,
                    ),
                    "pickup_order": None,
                    "status": "matched",
                }
            )
            remaining[plant["plant_id"]] -= qty
            to_assign -= qty
        # to_assign > 0 means unabsorbed supply — intentionally not stored;
        # it shows up as the gap between total supply and matched quantity.
    return matches


def _assign_pickup_orders(matches: list[dict]) -> None:
    """Nearest-first pickup order per plant (simple route heuristic, not VRP)."""
    by_plant: dict[str, list[dict]] = {}
    for m in matches:
        by_plant.setdefault(m["plant_id"], []).append(m)
    for rows in by_plant.values():
        for order, m in enumerate(sorted(rows, key=lambda r: r["distance_km"]), start=1):
            m["pickup_order"] = order


def compute_matches(
    districts: list[dict],
    plants: list[dict],
    min_alloc: float = 2000.0,
    solver: str = "optimal",
    cost_per_ton_km: float = COST_PER_TON_KM,
) -> list[dict]:
    """Supply–demand matching. Returns a list of match rows.

    Default `solver="optimal"` is the exact min-cost-flow transportation
    solution; `solver="greedy"` reproduces the old heuristic. `min_alloc`
    is the economic lot threshold: allocations below it are skipped so we
    don't dispatch pickups for fragments.
    """
    if solver == "greedy":
        matches = _greedy_matches(districts, plants, min_alloc)
    else:
        matches = _optimal_matches(districts, plants, min_alloc, cost_per_ton_km)
    _assign_pickup_orders(matches)
    return matches


def summarize(
    matches: list[dict],
    districts: list[dict],
    plants: list[dict],
    cost_per_ton_km: float = COST_PER_TON_KM,
) -> dict:
    total_supply = sum(district_supply(d) for d in districts)
    matched = sum(m["allocated_quantity"] for m in matches)
    ton_km = sum(m["allocated_quantity"] * m["distance_km"] for m in matches)
    utilization = {}
    for p in plants:
        allocated = sum(
            m["allocated_quantity"] for m in matches if m["plant_id"] == p["plant_id"]
        )
        capacity = p["annual_capacity"] or 0
        utilization[p["plant_id"]] = (
            round(100 * allocated / capacity, 1) if capacity else 0.0
        )
    return {
        "total_supply": round(total_supply, 1),
        "matched": round(matched, 1),
        "leftover": round(total_supply - matched, 1),
        "absorbed_pct": round(100 * matched / total_supply, 1) if total_supply else 0.0,
        "utilization": utilization,
        "match_count": len(matches),
        "total_ton_km": round(ton_km, 1),
        "haul_cost": round(ton_km * cost_per_ton_km, 1),
        "avg_haul_km_per_unit": round(ton_km / matched, 1) if matched else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute AgriFlow supply-demand matches.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the plan without writing anything to the database.",
    )
    parser.add_argument(
        "--min-alloc", type=float, default=2000.0,
        help="Skip allocations below this many units (economic lot threshold).",
    )
    parser.add_argument(
        "--solver", choices=["optimal", "greedy"], default="optimal",
        help="Matching algorithm (default: exact min-cost flow; greedy = old heuristic).",
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="Run both solvers and print an absorption/cost comparison.",
    )
    parser.add_argument(
        "--cost-per-ton-km", type=float, default=COST_PER_TON_KM,
        help="Flat road-freight rate used for the reported haul cost (₹/tonne-km).",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    try:
        districts = load_districts(conn)
        plants = load_plants(conn)

        if args.compare:
            for name in ("greedy", "optimal"):
                s = summarize(
                    compute_matches(districts, plants, args.min_alloc, solver=name,
                                    cost_per_ton_km=args.cost_per_ton_km),
                    districts, plants, cost_per_ton_km=args.cost_per_ton_km,
                )
                print(
                    f"{name:8s}: matched {s['matched']:>11,.1f} units  "
                    f"ton-km {s['total_ton_km']:>12,.1f}  "
                    f"haul INR {s['haul_cost']:>13,.1f}  "
                    f"avg {s['avg_haul_km_per_unit']:>6.1f} km/unit  "
                    f"({s['match_count']} rows)"
                )
            print()  # blank line before the full optimal plan below

        matches = compute_matches(districts, plants, args.min_alloc, solver=args.solver,
                                  cost_per_ton_km=args.cost_per_ton_km)
        summary = summarize(matches, districts, plants, cost_per_ton_km=args.cost_per_ton_km)

        if not args.dry_run:
            conn.execute("DELETE FROM matches")
            conn.executemany(
                """INSERT INTO matches
                   (district, plant_id, allocated_quantity, distance_km,
                    pickup_order, status)
                   VALUES (:district, :plant_id, :allocated_quantity,
                           :distance_km, :pickup_order, :status)""",
                matches,
            )
            conn.commit()

        print(f"total supply : {summary['total_supply']:>11,.1f} units")
        print(f"matched      : {summary['matched']:>11,.1f} units  ({summary['match_count']} match rows)")
        print(f"leftover     : {summary['leftover']:>11,.1f} units  ({100 - summary['absorbed_pct']:.1f}% unabsorbed)")
        print(f"haul         : {summary['total_ton_km']:>11,.1f} ton-km  "
              f"~ INR {summary['haul_cost']:>11,.1f}  "
              f"({summary['avg_haul_km_per_unit']:.1f} km/unit avg)")
        print("\nutilization per plant:")
        for pid, pct in summary["utilization"].items():
            print(f"  {pid}: {pct:>5.1f}%")
        print("\nsample matches (top 6 by allocated quantity):")
        for m in sorted(matches, key=lambda r: -r["allocated_quantity"])[:6]:
            print(
                f"  {m['district']:15s} -> {m['plant_id']}  "
                f"{m['allocated_quantity']:>9,.1f} units  "
                f"{m['distance_km']:>6.1f} km  pickup #{m['pickup_order']}"
            )
        print("\n" + ("DRY RUN — database not modified" if args.dry_run else
                      f"wrote {len(matches)} rows to the matches table "
                      f"(solver={args.solver})"))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
