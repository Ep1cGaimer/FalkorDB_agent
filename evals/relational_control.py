"""Relational (in-memory SQLite) control for RollbackWitness reader/record obligations.

Honest, equal-information control: it receives exactly the raw facts the FalkorDB importer
receives -- ``fixtures/shop/releases/*/release.json`` plus ``fixtures/shop/snapshots/*/manifest.json``
-- loads them into plain tables and derives reader/record obligations with one SQL join instead of
Cypher. Nulls are preserved verbatim (unknown writer / unknown format stay NULL, never invented).
A tie with the graph is an acceptable, reportable outcome; neither side is handicapped.

Nothing under ``src/rw/`` is imported except ``REPO_ROOT`` (a path constant) and, in ``main`` only,
the FalkorDB session used to display the side-by-side comparison. The obligations/gaps/rollback
functions below never touch the graph.

Run ``.venv\\Scripts\\python.exe evals\\relational_control.py`` (needs the live server) for the
markdown comparison table.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rw.verification import REPO_ROOT  # noqa: E402  (path set above)

FIXTURE_ROOT = REPO_ROOT / "fixtures" / "shop"
ORACLE_PATH = REPO_ROOT / "evals" / "expected" / "dispositions.json"

SCHEMA = """
CREATE TABLE releases (
    service         TEXT NOT NULL,
    version         TEXT NOT NULL,
    previous_version TEXT,            -- NULL for the first build
    bundle_id       TEXT,             -- NULL when the release is not part of a rollout bundle
    PRIMARY KEY (service, version)
);
CREATE TABLE routes (
    service     TEXT NOT NULL,
    version     TEXT NOT NULL,
    route_name  TEXT NOT NULL,
    store       TEXT,                 -- `reads_from`; NULL/absent means no READS_FROM store
    read_domain TEXT,                 -- ALL_KEYS | UNKNOWN
    entry       TEXT NOT NULL,
    PRIMARY KEY (service, version, route_name)
);
CREATE TABLE deployments (
    snapshot TEXT NOT NULL,
    service  TEXT NOT NULL,
    version  TEXT NOT NULL,
    PRIMARY KEY (snapshot, service)
);
CREATE TABLE records (
    snapshot       TEXT NOT NULL,
    store          TEXT NOT NULL,
    record_id      TEXT NOT NULL,
    payload_hash   TEXT,
    writer_service TEXT,              -- NULL when the manifest writer is unknown
    writer_version TEXT,              -- NULL when the manifest writer is unknown
    format         TEXT,              -- NULL when the manifest format is unknown
    PRIMARY KEY (snapshot, store, record_id)
);
CREATE TABLE coverage (
    snapshot TEXT NOT NULL,
    store    TEXT NOT NULL,
    status   TEXT,                    -- COMPLETE | PARTIAL | UNKNOWN (NULL when absent)
    PRIMARY KEY (snapshot, store)
);
CREATE TEMP TABLE fleet (
    service TEXT PRIMARY KEY,
    version TEXT NOT NULL
);
"""

OBLIGATION_SQL = """
SELECT f.service      AS service,
       f.version      AS version,
       r.route_name   AS route_name,
       r.store        AS store,
       rec.record_id  AS record_id,
       rec.writer_version AS writer_version
FROM fleet AS f
JOIN routes  AS r   ON r.service = f.service AND r.version = f.version
JOIN records AS rec ON rec.store = r.store AND rec.snapshot = :snapshot
ORDER BY f.service, r.route_name, r.store, rec.record_id
"""


# --------------------------------------------------------------------------- load raw facts

def load_facts(fixture_root: Path | None = None) -> sqlite3.Connection:
    """Load the raw fixture facts into an in-memory database. Returns the connection."""
    root = Path(fixture_root) if fixture_root else FIXTURE_ROOT
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)

    for path in sorted((root / "releases").glob("*/release.json")):
        rel = json.loads(path.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO releases (service, version, previous_version, bundle_id) VALUES (?, ?, ?, ?)",
            (rel["service"], rel["version"], rel.get("previous_version"), rel.get("bundle_id")),
        )
        for route in rel.get("routes") or []:
            conn.execute(
                "INSERT INTO routes (service, version, route_name, store, read_domain, entry) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (rel["service"], rel["version"], route["name"], route.get("reads_from"),
                 route.get("read_domain"), route["entry"]),
            )

    for path in sorted((root / "snapshots").glob("*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        snapshot = manifest["snapshot"]
        for dep in manifest.get("deployments") or []:
            conn.execute("INSERT INTO deployments (snapshot, service, version) VALUES (?, ?, ?)",
                         (snapshot, dep["service"], dep["version"]))
        for store in manifest.get("stores") or []:
            conn.execute("INSERT INTO coverage (snapshot, store, status) VALUES (?, ?, ?)",
                         (snapshot, store["name"], store.get("coverage")))
            for rec in store.get("records") or []:
                writer = rec.get("writer") or {}
                conn.execute(
                    "INSERT INTO records (snapshot, store, record_id, payload_hash, writer_service, "
                    "writer_version, format) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (snapshot, store["name"], rec["record_id"], rec.get("payload_hash"),
                     writer.get("service"), writer.get("version"), rec.get("format")),
                )
    conn.commit()
    return conn


# --------------------------------------------------------------------------- obligations

def obligations(conn: sqlite3.Connection, snapshot: str, fleet: dict[str, str]) -> list[tuple]:
    """Every (service, version, route_name, store, record_id, writer_version_or_None) pair.

    The candidate fleet is passed as a temp table and resolved by one SQL join:
    fleet -> routes (service, version) -> records (store, snapshot).
    """
    with conn:
        conn.execute("DELETE FROM fleet")
        conn.executemany("INSERT INTO fleet (service, version) VALUES (?, ?)", sorted(fleet.items()))
        rows = conn.execute(OBLIGATION_SQL, {"snapshot": snapshot}).fetchall()
    return sorted(tuple(row) for row in rows)


def gaps(conn: sqlite3.Connection, snapshot: str, fleet: dict[str, str]) -> list[dict]:
    """Unresolved evidence the relational control can see for this snapshot/fleet.

    - coverage != COMPLETE (or missing) for a store the fleet reads;
    - records read by the fleet whose manifest writer is null;
    - records read by the fleet whose manifest format is null.

    Subjects use the oracle's ``snapshot/store[/record]`` form. Gap rows are per store or per
    store/record, not repeated per affected reader.
    """
    with conn:
        conn.execute("DELETE FROM fleet")
        conn.executemany("INSERT INTO fleet (service, version) VALUES (?, ?)", sorted(fleet.items()))
        read_stores = [row["store"] for row in conn.execute(
            "SELECT DISTINCT r.store AS store FROM fleet AS f "
            "JOIN routes AS r ON r.service = f.service AND r.version = f.version "
            "WHERE r.store IS NOT NULL ORDER BY r.store"
        )]
        out: list[dict] = []
        for store in read_stores:
            cov = conn.execute("SELECT status FROM coverage WHERE snapshot = ? AND store = ?",
                               (snapshot, store)).fetchone()
            if cov is None:
                out.append({"kind": "COVERAGE_INCOMPLETE", "subject": f"{snapshot}/{store}",
                            "detail": "no coverage row for this snapshot/store"})
            elif cov["status"] != "COMPLETE":
                out.append({"kind": "COVERAGE_INCOMPLETE", "subject": f"{snapshot}/{store}",
                            "detail": f"manifest coverage={cov['status']!r}"})
            unknown = conn.execute(
                "SELECT DISTINCT rec.record_id AS record_id, rec.writer_version AS writer_version, "
                "rec.format AS format "
                "FROM fleet AS f "
                "JOIN routes AS r ON r.service = f.service AND r.version = f.version "
                "JOIN records AS rec ON rec.store = r.store AND rec.snapshot = :snapshot "
                "WHERE r.store = :store ORDER BY rec.record_id",
                {"snapshot": snapshot, "store": store},
            ).fetchall()
            seen: set[tuple[str, str]] = set()
            for rec in unknown:
                subject = f"{snapshot}/{store}/{rec['record_id']}"
                if rec["writer_version"] is None and (subject, "WRITER_UNKNOWN") not in seen:
                    seen.add((subject, "WRITER_UNKNOWN"))
                    out.append({"kind": "WRITER_UNKNOWN", "subject": subject,
                                "detail": "manifest writer is null; provenance stays unknown"})
                if rec["format"] is None and (subject, "FORMAT_UNKNOWN") not in seen:
                    seen.add((subject, "FORMAT_UNKNOWN"))
                    out.append({"kind": "FORMAT_UNKNOWN", "subject": subject,
                                "detail": "manifest format is null; binding keeps literal UNKNOWN"})
    return sorted(out, key=lambda g: (g["kind"], g["subject"]))


# --------------------------------------------------------------------------- naive release selector

def bundle_rollback(conn: sqlite3.Connection, snapshot: str, bundle_id: str) -> dict[str, str | None]:
    """Model the plain release tool: every service whose current release is in ``bundle_id``
    goes back to that release's declared ``previous_version`` (None when there is none).

    This is the baseline the graph-grounded investigation is compared against: it consults release
    metadata only and never looks at routes or retained records.
    """
    rows = conn.execute(
        "SELECT d.service AS service, rel.previous_version AS previous_version "
        "FROM deployments AS d "
        "JOIN releases AS rel ON rel.service = d.service AND rel.version = d.version "
        "WHERE d.snapshot = ? AND rel.bundle_id = ? ORDER BY d.service",
        (snapshot, bundle_id),
    ).fetchall()
    return {row["service"]: row["previous_version"] for row in rows}


# --------------------------------------------------------------------------- comparison table (live graph)

def _release_id(session, service: str, version: str) -> str:
    from rw import graph as G

    rows, _ = G.releases_for_service(session.g, service)
    match = [r["release_id"] for r in rows if r["version"] == version]
    if len(match) != 1:
        raise RuntimeError(f"cannot resolve one release for {service} {version}: {rows}")
    return match[0]


def graph_obligations(session, fleet: dict[str, str], flags_by_service: dict | None = None):
    """FalkorDB obligations for the same fleet, via the shipped pipeline (Session.verify)."""
    from rw.contracts import FleetEntry, GroundingProposal, ScopeConfirmation

    flags_by_service = flags_by_service or {}
    changes = [FleetEntry(service=service, release_id=_release_id(session, service, version),
                          flags=flags_by_service.get(service) or {})
               for service, version in sorted(fleet.items())]
    plan, errors = session.plan_from_proposal(
        GroundingProposal(changes=changes, citations=[], rationale="relational control"),
        "relational control case", origin="fixture", label="relational-control")
    if errors or plan is None:
        raise RuntimeError(f"plan rejected: {errors}")
    report = session.verify(plan, ScopeConfirmation(plan_hash=plan.plan_hash(),
                                                    confirmed_by="relational-control",
                                                    confirmed_at="2026-10-15T00:00:00Z"))
    return report["verification"]


def main() -> int:
    from rw import graph as G
    from rw.pipeline import Session

    conn = load_facts()
    oracle = json.loads(ORACLE_PATH.read_text(encoding="utf-8"))
    graph_name = f"rw_control_{uuid.uuid4().hex[:8]}"
    imported = False
    rows: list[tuple[str, int, int, str, str]] = []
    mismatches: list[str] = []
    oracle_mismatches: list[str] = []
    try:
        for case in oracle["cases"]:
            case_id = case["id"]
            snapshot = case["snapshot"].removeprefix("snapshot:")
            fleet = {service: spec["version"] for service, spec in case["fleet"].items()}
            flags = {service: (spec.get("flags") or {}) for service, spec in case["fleet"].items()}

            sql_tuples = obligations(conn, snapshot, fleet)
            sql_set = {(t[0], t[4]) for t in sql_tuples}
            sql_gaps = gaps(conn, snapshot, fleet)

            session = Session(snapshot=snapshot, graph_name=graph_name, reimport=not imported)
            imported = True
            verification = graph_obligations(session, fleet, flags)
            graph_set = {(o["tuple"]["service"], o["tuple"]["record_id"])
                         for o in verification["obligations"]}

            oracle_set = {(o["service"], o["record_id"]) for o in case["obligations"]}
            equal = sql_set == graph_set
            if not equal:
                mismatches.append(f"{case_id}: SQL-only={sorted(sql_set - graph_set)} "
                                  f"graph-only={sorted(graph_set - sql_set)}")
            if sql_set != oracle_set:
                oracle_mismatches.append(f"{case_id}: SQL-only={sorted(sql_set - oracle_set)} "
                                         f"oracle-only={sorted(oracle_set - sql_set)}")

            gap_cell = "none" if not sql_gaps else ", ".join(
                f"{kind}x{sum(1 for g in sql_gaps if g['kind'] == kind)}"
                for kind in sorted({g["kind"] for g in sql_gaps}))
            rows.append((case_id, len(sql_tuples), len(verification["obligations"]),
                         "yes" if equal else "NO", gap_cell))
    finally:
        try:
            G.connect().select_graph(graph_name).delete()
        except Exception as exc:  # pragma: no cover - teardown best effort
            print(f"(warning: could not delete {graph_name}: {exc})")

    print("| case | SQL obligations | FalkorDB obligations | sets equal | SQL gaps |")
    print("|---|---|---|---|---|")
    for case_id, sql_n, graph_n, equal, gap_cell in rows:
        print(f"| {case_id} | {sql_n} | {graph_n} | {equal} | {gap_cell} |")
    total = len(rows)
    print()
    print(f"SQL obligations == FalkorDB obligations: {sum(1 for r in rows if r[3] == 'yes')}/{total} cases")
    print(f"SQL obligations == independent oracle: "
          f"{total - len(oracle_mismatches)}/{total} cases")
    for line in mismatches:
        print(f"graph mismatch: {line}")
    for line in oracle_mismatches:
        print(f"oracle mismatch: {line}")
    print("Note: a tie is a valid outcome; obligation sets are compared as (service, record_id) pairs.")
    return 1 if (mismatches or oracle_mismatches) else 0


if __name__ == "__main__":
    raise SystemExit(main())
