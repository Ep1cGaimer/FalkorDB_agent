"""Step-wise local API. Only server-held evidence can authorize simulation."""
from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .contracts import (Approval, CandidatePlan, Disposition, FleetEntry,
                        GroundingClarification, GroundingResult, MAX_PLANS_PER_SESSION,
                        ScopeConfirmation, VerificationResult)
from .simulation import DEFAULT_FORBIDDEN_IDENTITIES, SimulationRefused

ROOT = Path(__file__).resolve().parents[2]
GROUNDING_DIR = ROOT / "artifacts/grounding"

EVIDENCE_DRIFT_REASON = "evidence changed since verification; re-verify and re-approve"


class EvidenceDrift(SimulationRefused):
    """The bytes behind a stored verification no longer hold, so approval/simulation must stop.

    ``drift`` names exactly what changed. The verification itself is never replaced: the operator has
    to re-verify and approve the fresh evidence.
    """

    def __init__(self, drift: list[str]):
        self.drift = list(drift)
        super().__init__(EVIDENCE_DRIFT_REASON)


class RequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvestigationRequest(RequestBody):
    request_text: str = Field(min_length=1, max_length=20000)
    mode: Literal["live", "replay"] = "live"
    replay_path: str | None = None


class ScopeRequest(RequestBody):
    confirmed_by: str = Field(min_length=1, max_length=200)


class ApprovalRequest(RequestBody):
    approved_by: str = Field(min_length=1, max_length=200)


class AlternativeRequest(RequestBody):
    replay_path: str | None = None


@dataclass
class Attempt:
    grounding: GroundingResult
    transcript: str | None
    plan: CandidatePlan | None
    errors: list[str]
    report: dict | None = None
    approval: Approval | None = None
    simulation: dict | None = None

    def public(self):
        citations = [c.model_dump(mode="json") for c in self.grounding.result.citations]
        plan = self.plan.model_dump(mode="json") if self.plan else None
        if plan is not None:
            plan["citations"] = citations
        return {"grounding": self.grounding.model_dump(mode="json"),
                "transcript": self.transcript, "plan": plan,
                "plan_hash": self.plan.plan_hash() if self.plan else None,
                "citations": citations, "validation_errors": self.errors,
                "clarification": self.grounding.result.model_dump(mode="json")
                    if isinstance(self.grounding.result, GroundingClarification) else None,
                "report": deepcopy(self.report),
                "approval": self.approval.model_dump(mode="json") if self.approval else None,
                "simulation": self.simulation}


@dataclass
class Investigation:
    id: str
    request: InvestigationRequest
    session: Any
    attempts: list[Attempt] = field(default_factory=list)
    lock: Any = field(default_factory=RLock)

    def public(self):
        from . import graph

        attempts = [attempt.public() for attempt in self.attempts]
        current_rows, current_log = graph.current_fleet(self.session.g, self.session.snapshot_id)
        if current_log["truncated"]:
            raise SimulationRefused("current fleet query is truncated")
        current = {row["service"]: row for row in current_rows}
        release_ids = {row["release_id"] for row in current_rows}

        def collect(value):
            if isinstance(value, dict):
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
            elif isinstance(value, str) and value.startswith("release:"):
                release_ids.add(value)

        collect(attempts)
        services = set(current)
        services.update(r.split(":", 2)[1] for r in release_ids if r.count(":") >= 2)
        releases = {}
        for service in sorted(services):
            rows, log = graph.releases_for_service(self.session.g, service)
            if log["truncated"]:
                raise SimulationRefused("release labels query is truncated")
            for row in rows:
                releases[row["release_id"]] = (service, row["version"])
        labels = {rid: f"{releases[rid][0]} {releases[rid][1]}"
                  for rid in sorted(release_ids) if rid in releases}

        def enrich_plan(plan):
            if plan is None:
                return
            plan["release_labels"] = labels
            for entry in plan["fleet"]:
                baseline = current.get(entry["service"], {})
                entry["current_release_id"] = baseline.get("release_id")
                current_release = releases.get(baseline.get("release_id"))
                proposed_release = releases.get(entry["release_id"])
                entry["current_version"] = current_release[1] if current_release else None
                entry["proposed_version"] = proposed_release[1] if proposed_release else None

        for attempt in attempts:
            attempt["release_labels"] = labels
            enrich_plan(attempt["plan"])
            if attempt["report"] is not None:
                attempt["report"]["release_labels"] = labels
                enrich_plan(attempt["report"]["plan"])
        return {"id": self.id, "investigation_id": self.id,
                "request_text": self.request.request_text, "mode": self.request.mode,
                "snapshot_id": self.session.snapshot_id,
                "snapshot_manifest_hash": self.session.manifest_hash,
                "attempts": attempts, "release_labels": labels,
                **(attempts[-1] if attempts else {})}


def _now():
    return datetime.now(timezone.utc).isoformat()


def create_app(*, session_factory: Callable | None = None,
               ground_function: Callable | None = None, replay_function: Callable | None = None,
               db_path: Path = ROOT / "artifacts/sim.sqlite",
               transcript_dir: Path = GROUNDING_DIR) -> FastAPI:
    """Inject only grounding for integration tests; the real Session still verifies."""
    app = FastAPI(title="RollbackWitness", description="Synthetic fixture; local simulation only")
    investigations: dict[str, Investigation] = {}
    app.state.investigations = investigations
    registry_lock = RLock()
    initialized = False
    transcript_root = Path(transcript_dir).resolve()

    def replay_file(value):
        try:
            path = Path(value)
            if not path.is_absolute():
                # Accept a picker filename or a repo-relative artifacts/grounding path.
                path = transcript_root / path if len(path.parts) == 1 else ROOT / path
            path = path.resolve()
            if (path.parent != transcript_root or path.suffix.lower() != ".json"
                    or not path.is_file()):
                raise ValueError("outside transcript directory or not a saved JSON file")
            return path
        except (OSError, ValueError, RuntimeError) as exc:
            raise HTTPException(422, "replay_path must select a saved JSON file in artifacts/grounding") from exc

    @app.exception_handler(SimulationRefused)
    async def refused_handler(request, exc):
        content = {"detail": exc.reason, "reason": exc.reason}
        if isinstance(exc, EvidenceDrift):
            # structured detail (reason + the drift lines); the string reason stays for the UI
            content["detail"] = {"reason": exc.reason, "drift": exc.drift}
        return JSONResponse(status_code=409, content=content)

    def get_investigation(identifier):
        with registry_lock:
            inv = investigations.get(identifier)
        if inv is None:
            raise HTTPException(404, "investigation not found")
        return inv

    def get_attempt(inv, plan_hash):
        for attempt in inv.attempts:
            if attempt.plan and attempt.plan.plan_hash() == plan_hash:
                return attempt
        raise HTTPException(404, "plan not found in this investigation")

    def human(inv, name):
        forbidden = set(DEFAULT_FORBIDDEN_IDENTITIES)
        forbidden.update(attempt.grounding.model for attempt in inv.attempts)
        if not name.strip() or name.strip().casefold() in {s.casefold() for s in forbidden}:
            raise SimulationRefused("a human identity is required")
        return forbidden

    def ground_attempt(inv, context=None, replay_path=None):
        from . import grounding

        transcript = None
        if inv.request.mode == "replay":
            path = replay_path or inv.request.replay_path
            if not path:
                raise HTTPException(422, "replay_path is required in replay mode")
            path = replay_file(path)
            try:
                result = (replay_function or grounding.replay)(Path(path))
            except (OSError, ValueError, KeyError, grounding.GroundingError) as exc:
                raise HTTPException(422, f"replay unavailable: {exc}") from exc
            result = result.model_copy(update={"live": False, "model": f"replay:{Path(path).name}"})
            transcript = str(path)
        else:
            tools = grounding.GroundingTools(inv.session.g, inv.session.snapshot_id)
            try:
                result, transcript = (ground_function or grounding.ground)(
                    inv.request.request_text, tools, alternative_context=context)
            except grounding.GroundingError as exc:
                raise HTTPException(502, f"grounding unavailable: {exc}") from exc
        if result.request_text != inv.request.request_text:
            raise SimulationRefused("grounding request does not match this investigation")
        errors = list(result.validation_errors)
        plan = None
        if not isinstance(result.result, GroundingClarification):
            proposed, validation = inv.session.plan_from_proposal(
                result.result, inv.request.request_text, origin="agent",
                label=f"candidate {len(inv.attempts) + 1}")
            errors.extend(validation)
            if not errors:
                plan = proposed
            if plan and any(a.plan and a.plan.plan_hash() == plan.plan_hash() for a in inv.attempts):
                raise SimulationRefused("alternative must be a different plan")
        inv.attempts.append(Attempt(result, str(transcript) if transcript else None, plan, errors))

    @app.post("/api/investigations")
    def create_investigation(body: InvestigationRequest):
        nonlocal initialized
        if not body.request_text.strip():
            raise HTTPException(422, "request_text cannot be blank")
        if body.mode == "replay" and not body.replay_path:
            raise HTTPException(422, "replay_path is required in replay mode")
        if body.mode == "live" and body.replay_path:
            raise HTTPException(422, "replay_path requires replay mode")
        if body.mode == "replay":
            replay_file(body.replay_path)
        with registry_lock:
            if session_factory:
                session = session_factory()
            else:
                from .pipeline import Session
                # Initialize the shared fixture graph once, preserving other investigations.
                session = Session(snapshot="snap-001", reimport=not initialized)
                initialized = True
        inv = Investigation(uuid4().hex, body, session)
        ground_attempt(inv)
        with registry_lock:
            investigations[inv.id] = inv
        return inv.public()

    @app.get("/api/transcripts")
    def list_transcripts():
        transcripts = []
        for candidate in transcript_root.glob("*.json"):
            try:
                path = replay_file(candidate)
                data = json.loads(path.read_text(encoding="utf-8"))
                result = data.get("result", {})
                if not isinstance(result, dict):
                    continue
                request_text = data.get("request_text", result.get("request_text"))
                model = result.get("model", data.get("model"))
                live = result.get("live", data.get("live"))
                if not isinstance(request_text, str) or not isinstance(model, str) or not isinstance(live, bool):
                    continue
                transcripts.append({"file_name": path.name, "replay_path": path.name,
                    "request_text": request_text, "model": model, "live": live,
                    "mtime": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()})
            except (OSError, ValueError, AttributeError, HTTPException):
                continue
        return sorted(transcripts, key=lambda row: (row["mtime"], row["file_name"]), reverse=True)

    @app.get("/api/investigations")
    def list_investigations():
        with registry_lock:
            entries = list(investigations.values())
        rows = []
        for inv in entries:
            with inv.lock:
                report = inv.attempts[-1].report if inv.attempts else None
                rows.append({"id": inv.id, "investigation_id": inv.id,
                    "request_text": inv.request.request_text, "mode": inv.request.mode,
                    "latest_disposition": report["verification"]["disposition"] if report else None})
        return rows

    @app.get("/api/investigations/{identifier}")
    def get_state(identifier: str):
        inv = get_investigation(identifier)
        with inv.lock:
            return inv.public()

    @app.post("/api/investigations/{identifier}/plans/{plan_hash}/confirm-scope")
    def confirm_scope(identifier: str, plan_hash: str, body: ScopeRequest):
        inv = get_investigation(identifier)
        with inv.lock:
            attempt = get_attempt(inv, plan_hash)
            human(inv, body.confirmed_by)
            if attempt.report is None:
                confirmation = ScopeConfirmation(plan_hash=plan_hash,
                    confirmed_by=body.confirmed_by.strip(), confirmed_at=_now())
                attempt.report = inv.session.verify(attempt.plan, confirmation)
            public = inv.public()
            return next(a["report"] for a in public["attempts"] if a["plan_hash"] == plan_hash)

    @app.post("/api/investigations/{identifier}/alternative")
    def alternative(identifier: str, body: AlternativeRequest | None = None):
        from .pipeline import summarize_for_agent
        inv = get_investigation(identifier)
        with inv.lock:
            if len(inv.attempts) >= MAX_PLANS_PER_SESSION:
                raise SimulationRefused("plan limit reached")
            latest = inv.attempts[-1]
            if not latest.report or latest.report["verification"]["disposition"] not in {
                    Disposition.BLOCKED.value, Disposition.NEEDS_EVIDENCE.value}:
                raise SimulationRefused("alternative requires a BLOCKED or NEEDS_EVIDENCE verification")
            replay_path = body.replay_path if body else None
            if inv.request.mode == "replay" and not replay_path:
                raise SimulationRefused("a separate replay_path is required for the alternative")
            if inv.request.mode == "live" and replay_path:
                raise HTTPException(422, "replay_path requires replay mode")
            ground_attempt(inv, summarize_for_agent(latest.report), replay_path)
            return inv.public()

    def verified(attempt):
        if not attempt.report:
            raise SimulationRefused("plan scope has not been confirmed and verified")
        verification = VerificationResult.model_validate(attempt.report["verification"])
        if verification.disposition != Disposition.BOUNDED_PASS:
            raise SimulationRefused("verification is not BOUNDED_PASS")
        return verification

    def revalidated(inv, verification):
        """Refuse to act when the stored verification's bytes have drifted since it was taken.

        The session's own fixture root is authoritative (obligation paths may be absolute for a
        session built on a copy), and the stored verification is only checked, never replaced.
        """
        from . import probes
        from .verification import revalidate

        drift = revalidate(verification, inv.session.fixture_root,
                           probes.environment_hash, probes.probe_spec_hash)
        if drift:
            raise EvidenceDrift(drift)
        return verification

    @app.post("/api/investigations/{identifier}/plans/{plan_hash}/approve")
    def approve(identifier: str, plan_hash: str, body: ApprovalRequest):
        from .simulation import record_approval
        inv = get_investigation(identifier)
        with inv.lock:
            attempt = get_attempt(inv, plan_hash)
            verification = verified(attempt)
            revalidated(inv, verification)
            forbidden = human(inv, body.approved_by)
            approval = Approval(plan_hash=attempt.plan.plan_hash(),
                verification_hash=verification.verification_hash(),
                snapshot_manifest_hash=verification.snapshot_manifest_hash,
                approved_by=body.approved_by.strip(), approved_at=_now())
            record_approval(db_path, approval, verification, forbidden_identities=forbidden)
            attempt.approval = approval
            return approval

    @app.post("/api/investigations/{identifier}/plans/{plan_hash}/simulate")
    def simulate_plan(identifier: str, plan_hash: str):
        from . import graph, simulation, verification
        inv = get_investigation(identifier)
        with inv.lock:
            attempt = get_attempt(inv, plan_hash)
            result = verified(attempt)
            if attempt.approval is None:
                raise SimulationRefused("human approval required")
            revalidated(inv, result)
            try:
                _, manifest_hash = verification.load_manifest(inv.session.fixture_root, inv.session.snapshot)
            except (OSError, ValueError) as exc:
                raise SimulationRefused("current manifest is unavailable") from exc
            rows, log = graph.current_fleet(inv.session.g, inv.session.snapshot_id)
            if log["truncated"]:
                raise SimulationRefused("current fleet query is truncated")
            fleet = [FleetEntry(service=r["service"], release_id=r["release_id"], flags=r["flags"]) for r in rows]
            receipt = simulation.simulate(db_path, attempt.approval, result, manifest_hash, fleet, attempt.plan)
            attempt.simulation = receipt.model_dump(mode="json")
            return receipt

    @app.get("/")
    def index():
        path = Path(__file__).resolve().parent / "static/index.html"
        if path.is_file():
            return FileResponse(path)
        return {"product": "RollbackWitness", "api": "/docs",
                "investigations": "/api/investigations", "note": "LOCAL SIMULATION ONLY"}

    return app


app = create_app()
