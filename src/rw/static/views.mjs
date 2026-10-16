import { el, icon, button, panel, details, hash } from "./dom.mjs";
import { PASS_SCOPE, disposition, preferredCheck, checkSummary, checks, recordedAnswers,
  replayCandidates, usedReplays } from "./model.mjs";
import { badge, releaseLabel, sourcesView, witnessPanel, matrixPanel, gapsPanel, receiptInspector } from "./evidence.mjs";
import { formatText, flagText, flagChip, explainButton, explanationContent } from "./explanations.mjs";

export const currentAttempt = s => s.inv?.attempts[s.attemptIndex] || null;
export const contextFor = s => s.contexts.find(c => c.snapshot_id === (s.inv?.snapshot_id || `snapshot:${s.form.snapshot}`));
const field = (title, id, input, help) => el("div", { class: "form-field" }, el("label", { for: id }, title), input,
  help ? el("p", { class: "field-help" }, help) : null);

export function runLabel(s) {
  const attempt = currentAttempt(s);
  if (!attempt) return s.form.mode === "live" ? "Live mode" : "Replay · not live";
  if (attempt.is_live_provider) return "Live run";
  return attempt.grounding.model.startsWith("replay:") ? "Replay · not live" : "Test proposal";
}

export function sidebar(s, a) {
  return [el("a", { class: "brand", href: "#", onclick: e => { e.preventDefault(); window.scrollTo(0, 0); } },
    el("span", { class: "brand-mark" }, icon("rollback")), "RollbackWitness"),
    el("div", { class: "new-review" }, button("New investigation", a.newInvestigation,
      { id: "new-investigation", variant: "secondary", symbol: "plus", disabled: !!s.busy })),
    s.history.length ? el("nav", { class: "recent-list", "aria-label": "Recent investigations" },
      el("div", { class: "nav-label" }, "Recent reviews"), s.history.slice(0, 8).map(h =>
        el("button", { type: "button", class: `recent${h.id === s.inv?.id ? " active" : ""}`, disabled: !!s.busy,
          onclick: () => a.openInvestigation(h.id), title: h.request_text.split("\n")[0], "aria-current": h.id === s.inv?.id ? "page" : null },
          el("span", { class: `dot ${h.latest_disposition || ""}` }), el("span", { class: "recent-text" }, h.request_text.split("\n")[0])))) : null];
}

export function topbar(s, a) {
  return [el("div", { class: "row" },
    button(icon("menu"), a.toggleSidebar, { variant: "icon-only mobile-menu", "aria-label": "Toggle navigation" }),
    s.canGoBack ? button("Back", a.back, { id: "back-button", variant: "ghost", symbol: "back", disabled: !!s.busy,
      "aria-label": "Back to previous view" }) : null,
    el("strong", { class: "topbar-title" }, "Rollback review")),
    el("div", { class: "topbar-actions" }, el("span", { class: "context-tag" }, "Synthetic fixture"),
      el("span", { class: "mode-label" }, el("span", { class: `dot ${s.inv ? currentAttempt(s)?.is_live_provider ? "live" : "replay" : ""}` }), runLabel(s), explainButton(a, "mode")),
      !s.inv ? button(icon("sliders"), () => a.openOverlay("settings"),
        { id: "settings-trigger", variant: "icon-only", "aria-label": "Demo setup", title: "Demo setup", disabled: !!s.busy }) : null)];
}

function currentFleet(s, a) {
  const c = contextFor(s);
  if (!c) return panel("Running services", null, el("div", { class: "panel-body small muted" }, s.contextError || "Loading snapshot…"));
  const complete = c.stores.every(store => store.coverage === "COMPLETE");
  return panel("Running services", "Installed versions before this change.", el("div", { class: "panel-body" },
    el("dl", { class: "compact-fleet" }, c.deployments.map(d => [el("dt", {}, d.service), el("dd", {}, `Version ${d.version}`,
      Object.entries(d.flags).map(([name, value]) => flagChip(a, d.service, name, value)))])),
    el("div", { class: "inventory-line" }, el("span", { class: "label-with-help" }, "Data coverage", explainButton(a, "coverage")),
      badge(complete ? "COMPLETE" : "PARTIAL", complete ? "Complete" : "Partial"))), explainButton(a, "versions"));
}

function retainedPanel(s, a) {
  const c = contextFor(s);
  const records = c?.stores.flatMap(store => store.records.map(r => ({ ...r, store: store.name }))) || [];
  const rows = records.map(r => el("tr", {},
    el("td", {}, el("span", { class: "table-primary" }, r.record_id)),
    el("td", {}, r.format ? el("span", { class: "badge data-format" }, formatText(r.format)) : badge("UNKNOWN", "Unknown format")),
    el("td", { class: "small subtle" }, r.writer ? `${r.writer.service} ${r.writer.version}` : badge("UNKNOWN", "Unknown writer"))));
  return panel("Saved shopping carts", "Rolling back the software does not remove these saved carts.", records.length
    ? el("div", { class: "table-scroll" }, el("table", {},
        el("thead", {}, el("tr", {}, el("th", { scope: "col" }, "Saved cart"),
          el("th", { scope: "col" }, el("span", { class: "label-with-help" }, "Data format", explainButton(a, "format"))),
          el("th", { scope: "col" }, "Saved by version"))), el("tbody", {}, rows)))
    : el("div", { class: "panel-body small muted" }, s.contextError || "Loading retained records…"));
}

function transcriptSelect(s, key, items, onChange) {
  if (!items.length) return el("p", { class: "field-help" }, "No matching recording is available.");
  if (!items.some(t => t.replay_path === s.form[key])) s.form[key] = items[0].replay_path;
  const select = el("select", { id: key, disabled: !!s.busy, onchange: e => { s.form[key] = e.target.value; onChange?.(e.target.value); } },
    items.map(t => el("option", { value: t.replay_path }, t.answer || `${t.outcome === "question" ? "Clarification" : "Fleet proposal"} · ${new Date(t.mtime).toLocaleString()}`)));
  select.value = s.form[key];
  return select;
}

function requestPanel(s, a) {
  const textarea = el("textarea", { id: "request", class: "request-input", value: s.form.request, readonly: s.form.mode === "replay",
    maxlength: "20000", disabled: !!s.busy, oninput: e => { s.form.request = e.target.value; a.syncButtons(); },
    placeholder: "Describe what to undo and what must be kept…" });
  return panel("What should the rollback do?", "Review the proposed versions first, then check whether they can read the saved data.", el("div", { class: "panel-body" },
    el("label", { for: "request", class: "sr-only" }, "Rollback request"), textarea,
    el("div", { class: "request-toolbar" },
      button("Investigate rollback", a.start, { id: "start-button", "data-action": "start", symbol: "arrow", disabled: !a.canStart() }))));
}

function fleetPanel(s, a, attempt) {
  const rows = attempt.plan.fleet.map(f => el("tr", {},
    el("td", {}, el("span", { class: "table-primary" }, f.service)),
    el("td", {}, el("div", { class: "version-diff" }, el("span", { class: "old" }, f.current_version || "?"), icon("chevron"),
      el("span", {}, f.proposed_version || "?")),
      Object.entries(f.flags).map(([key, value]) => flagChip(a, f.service, key, value))),
    el("td", {}, badge(f.changed ? "change" : null, f.changed ? "Change" : "Keep"))));
  const table = el("div", { class: "table-scroll" }, el("table", {},
    el("thead", {}, el("tr", {}, ...["Service", "Version", ""].map(x => el("th", {}, x)))), el("tbody", {}, rows)));
  const rationale = !attempt.report && attempt.grounding.result.rationale
    ? el("p", { class: "fleet-rationale" }, attempt.grounding.result.rationale) : null;
  return panel("Proposed changes", "Installed version → proposed version. Feature settings can change without installing an older version.", [table, rationale,
    el("div", { class: "panel-footer" }, button("Cited sources", () => a.openOverlay("sources"), { variant: "link", symbol: "file" }),
      !attempt.report ? button("Confirm & run checks", () => a.confirm(attempt),
        { id: "confirm-button", "data-action": "confirm", disabled: !!s.busy, symbol: "shield" }) : null)], explainButton(a, "versions"));
}

function verdictPanel(s, a, attempt) {
  const v = attempt.report.verification, d = v.disposition, counts = checkSummary(v);
  const selected = preferredCheck(v, null), failed = checks(v).find(r => r.result === "FAIL");
  const service = failed?.obligation.tuple.service || selected?.obligation.tuple.service;
  const sc = attempt.report.startup_checks?.[service];
  const serviceChecks = checks(v).filter(r => r.obligation.tuple.service === service);
  const readStatus = serviceChecks.some(r => r.result === "FAIL") ? "FAIL"
    : serviceChecks.length && serviceChecks.every(r => r.result === "PASS") ? "PASS" : "UNKNOWN";
  const title = d === "BLOCKED" ? "This rollback is blocked" : d === "NEEDS_EVIDENCE" ? "More evidence is needed" : "Saved-data checks passed";
  const description = d === "BLOCKED" && failed
    ? `${releaseLabel(s.inv, failed.obligation.tuple.release_id)} cannot read ${failed.obligation.tuple.record_id}, written by ${releaseLabel(s.inv, failed.obligation.writer_release_id)}.`
    : d === "NEEDS_EVIDENCE" ? "No read failure was established, but the evidence is incomplete."
    : `${counts.passed}/${counts.total} required read checks passed, with no evidence gaps.`;
  return el("section", { class: "panel verdict-panel", "aria-label": "Verification result" },
    el("div", { class: "verdict-top" }, el("h2", { class: `verdict-title ${d}` }, title),
      el("span", { class: "label-with-help" }, badge(d), explainButton(a, d))),
    el("p", { class: "verdict-description" }, description),
    sc ? el("div", { class: "startup-pair" },
      el("div", { class: "startup-item" }, el("div", { class: "row" }, el("span", { class: "label" }, "Startup check"),
        badge(sc.result === "GREEN" ? "PASS" : sc.result === "RED" ? "FAIL" : "UNKNOWN")),
        el("p", { class: "small" }, "Can this version start? · ", releaseLabel(s.inv, sc.release_id))),
      el("div", { class: "startup-item" }, el("div", { class: "row" }, el("span", { class: "label" }, "Saved-data check"), badge(readStatus)),
        el("p", { class: "small check-question" }, "Can it open existing saved carts?"),
        el("p", { class: "small" }, failed ? `${failed.obligation.tuple.record_id} · ${failed.obligation.tuple.format_id}` : `${serviceChecks.length} records checked`))) : null,
    d === "BOUNDED_PASS" ? el("p", { class: "verdict-note" }, PASS_SCOPE) : null);
}

function nextPanel(s, a, attempt) {
  if (!attempt.report) return null;
  const d = disposition(attempt);
  if (d === "BOUNDED_PASS") {
    if (attempt.simulation) return panel("Simulation complete", null, el("div", { class: "next-step" },
      el("p", { class: "simulation-result" }, attempt.simulation.applied ? "Local simulation recorded. No deployment occurred."
        : "Already simulated. This repeat request changed nothing."),
      details("Simulation receipt", el("dl", { class: "receipt-kv" }, el("dt", {}, "Idempotency key"),
        el("dd", {}, hash(attempt.simulation.idempotency_key))),
        button("Repeat simulation", () => a.simulate(attempt), { variant: "secondary", disabled: !!s.busy }))));
    return panel(attempt.approval ? "Ready to simulate" : "Local simulation", null, el("div", { class: "next-step" },
      el("p", {}, "Approve this exact configuration, then record it in the local simulator. No software is deployed."),
      attempt.approval ? button("Run local simulation", () => a.simulate(attempt), { id: "simulate-button", disabled: !!s.busy, class: "button primary full", symbol: "play" })
        : button("Approve local simulation", () => a.approve(attempt), { id: "approve-button", "data-action": "approve", disabled: !!s.busy, class: "button primary full", symbol: "check" })));
  }
  const canAlt = attempt === s.inv.attempts.at(-1) && s.inv.attempts.filter(x => x.plan).length < 2;
  if (!canAlt) return null;
  return panel("Next step", null, el("div", { class: "next-step" },
    el("p", {}, d === "BLOCKED" ? "Use this failure to propose a different combination of versions and settings." : "Check whether a different configuration changes the outcome."),
    s.inv.mode === "replay" ? field("Recorded alternative", "altReplay",
      transcriptSelect(s, "altReplay", replayCandidates(s.transcripts, s.inv.request_text, usedReplays(s.inv)), () => a.syncButtons())) : null,
    button("Find an alternative", a.alternative, { id: "alternative-button", "data-action": "alternative", disabled: !a.canAlternative(), class: "button secondary full", symbol: "rollback" })));
}

function clarificationPanel(s, a, attempt) {
  const c = attempt.clarification;
  if (s.inv.answered) return panel("Clarified scope", null, el("div", { class: "panel-body" },
    el("p", { class: "question-text" }, c.question), el("p", { class: "small subtle" },
      s.inv.request_text.split("\nOperator answered: ").slice(1).join("\nOperator answered: ")),
    el("div", { class: "row", style: "justify-content:flex-end;margin-top:17px" },
      button("View proposal", () => a.selectAttempt(s.inv.attempts.length - 1), { symbol: "arrow", disabled: !!s.busy }))));
  let answer;
  if (s.inv.mode === "replay") {
    const choices = recordedAnswers(s.transcripts, s.inv.request_text, c.question);
    const selected = choices.find(t => t.replay_path === s.form.answerReplay) || choices[0];
    s.form.answerReplay = selected?.replay_path || ""; s.form.answer = selected?.answer || "";
    answer = field("Recorded answer", "answerReplay", transcriptSelect(s, "answerReplay", choices, a.setAnswerReplay));
  } else answer = field("Your answer", "clarification-answer", el("textarea", { id: "clarification-answer", value: s.form.answer,
    maxlength: "4000", disabled: !!s.busy, placeholder: "Clarify what should be kept…",
    oninput: e => { s.form.answer = e.target.value; a.syncButtons(); } }));
  return panel("One detail needs your decision", null, el("div", { class: "panel-body" },
    el("p", { class: "question-text" }, c.question), details("Why this question was asked", sourcesView(c.citations, s.inv)), answer,
    el("div", { class: "row", style: "justify-content:flex-end;margin-top:17px" }, button("Continue with this answer", a.answer,
      { id: "answer-button", "data-action": "answer", disabled: !a.canAnswer(), symbol: "arrow" }))));
}

function comparisonPanel(s, a) {
  const plans = s.inv.attempts.map((attempt, index) => ({ attempt, index })).filter(x => x.attempt.plan);
  if (plans.length < 2) return null;
  const choices = plans.map(({ attempt, index }, i) => {
    const counts = attempt.report ? checkSummary(attempt.report.verification) : null;
    return el("button", { type: "button", class: `candidate-choice${s.attemptIndex === index ? " selected" : ""}`,
      "data-candidate": index, "aria-pressed": String(s.attemptIndex === index), disabled: !!s.busy, onclick: () => a.selectAttempt(index) },
      el("div", { class: "row between" }, el("strong", {}, `Candidate ${i + 1}`), badge(disposition(attempt))),
      el("div", { class: "candidate-fleet" }, attempt.plan.fleet.map(f => el("div", {}, `${f.service} ${f.proposed_version || "?"}`,
        Object.entries(f.flags).map(([key, value]) => ` · ${flagText(f.service, key, value)}`)))),
      counts ? el("span", { class: "tiny muted" }, `${counts.passed}/${counts.total} reads passed${counts.gaps ? ` · ${counts.gaps} evidence gaps` : ""}`)
        : el("span", { class: "tiny muted" }, "Awaiting checks"));
  });
  return panel("Compare candidates", "Each candidate is a proposed configuration checked separately.", el("div", { class: "panel-body candidate-list" }, choices));
}

function activeReview(s, a) {
  const attempt = currentAttempt(s), main = el("div", { class: "stack" });
  const request = el("div", { class: "request-summary" }, icon("rollback"),
    el("div", {}, s.inv.original_request_text || s.inv.request_text.split("\n\nAgent asked:")[0],
      s.inv.answered ? details("Clarified scope", el("p", { class: "small subtle" },
        s.inv.request_text.split("\nOperator answered: ").slice(1).join("\nOperator answered: "))) : null));
  if (attempt.clarification) main.append(clarificationPanel(s, a, attempt));
  else if (attempt.validation_errors.length || !attempt.plan) main.append(panel("Proposal could not be accepted", "Nothing was checked.",
    el("div", { class: "panel-body" }, attempt.validation_errors.map(error => el("p", { class: "small subtle" }, error)))));
  else {
    if (attempt.report) main.append(verdictPanel(s, a, attempt));
    main.append(fleetPanel(s, a, attempt));
    if (attempt.report) for (const part of [gapsPanel(attempt.report.verification), witnessPanel(s.inv, attempt, s.selected, a),
      matrixPanel(s.inv, attempt, s.selected, a)]) if (part) main.append(part);
  }
  const aside = el("aside", { class: "stack review-aside", "aria-label": "Available action and candidate comparison" },
    nextPanel(s, a, attempt), comparisonPanel(s, a));
  return [request, el("div", { class: `review-grid${!aside.childElementCount ? " no-aside" : ""}` }, main, aside.childElementCount ? aside : null)];
}

function messages(s, a) {
  return [s.busy ? el("div", { class: "status-message", role: "status", "aria-live": "polite" }, el("span", { class: "spinner" }), s.busy) : null,
    s.error ? el("div", { class: "error-message", role: "alert" }, el("strong", {}, s.error.status === 409 ? "Action refused" : "The request could not finish"),
      el("p", {}, s.error.message), el("div", { class: "row" },
        !s.inv && s.form.mode === "live" && [0, 502, 503].includes(s.error.status)
          ? button("Choose a saved replay", () => { a.setMode("replay"); a.openOverlay("settings"); }, { variant: "link" }) : null,
        button("Dismiss", a.dismissError, { variant: "link" }))) : null].filter(Boolean);
}

export function investigationView(s, a) {
  return [el("div", { class: "page-heading" }, el("div", {}, el("h1", {}, s.inv ? "Rollback investigation" : "Review a rollback"),
    !s.inv ? el("p", {}, "A rollback switches software to an older version. Check whether it can still read data saved by a newer one.") : null)),
    ...messages(s, a), s.inv ? activeReview(s, a) : el("div", { class: "review-grid" },
      el("div", { class: "stack" }, requestPanel(s, a), retainedPanel(s, a)),
      el("aside", { class: "stack review-aside", "aria-label": "Current fleet" }, currentFleet(s, a)))];
}

export function overlay(s, a) {
  if (!s.overlay) return null;
  const { kind } = s.overlay, attempt = currentAttempt(s);
  let title, body;
  if (kind === "settings") {
    title = "Demo setup";
    const snaps = el("select", { id: "snapshot-select", disabled: !!s.inv || !!s.busy, onchange: e => a.setSnapshot(e.target.value) },
      s.contexts.map(c => {
        const incomplete = c.stores.some(store => store.coverage !== "COMPLETE");
        const unknown = c.stores.some(store => store.records.some(r => !r.writer || !r.format));
        return el("option", { value: c.snapshot }, unknown ? "Unknown writer / format" : incomplete ? "Partial inventory" : "Complete inventory");
      }));
    snaps.value = s.form.snapshot;
    body = el("div", {},
      field("Run mode", "mode-live", el("div", { class: "segment", role: "group", "aria-label": "Run mode" },
        ...["live", "replay"].map(mode => el("button", { type: "button", id: `mode-${mode}`, "aria-pressed": String(s.form.mode === mode),
          disabled: !!s.inv || !!s.busy, onclick: () => a.setMode(mode) }, mode === "live" ? "Live model" : "Saved replay")))),
      s.form.mode === "replay" ? field("Recording", "replay", transcriptSelect(s, "replay",
        s.transcripts.filter(t => !t.request_text.includes("\n\nAgent asked:")), a.setReplay)) : null,
      field("Retained data", "snapshot-select", snaps, s.contextError || "Choose which saved-data snapshot the checks will use."));
  } else if (kind === "explanation") {
    const explanation = explanationContent(s.overlay.service);
    title = explanation.title; body = explanation.body;
  } else if (kind === "receipt") {
    title = "Read check details"; body = receiptInspector(s.inv, attempt, s.selected);
  } else {
    title = "Cited sources"; body = el("div", {},
      el("p", { class: "explanation-intro" }, "These release notes and code excerpts explain why the versions were proposed. Actual saved-data compatibility is checked separately by running the readers."),
      sourcesView(attempt?.citations, s.inv));
  }
  const dialog = el("dialog", { id: "workspace-dialog", "aria-labelledby": "dialog-title", oncancel: e => { e.preventDefault(); a.closeOverlay(); },
    onclick: e => { if (e.target !== dialog) return; const r = dialog.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) a.closeOverlay(); } },
    el("div", { class: "dialog-heading" }, el("h2", { id: "dialog-title" }, title), button(icon("close"), a.closeOverlay,
      { id: "close-dialog", variant: "icon-only", "aria-label": "Close dialog" })), el("div", { class: "dialog-body" }, body),
    el("div", { class: "dialog-footer" }, button("Done", a.closeOverlay, { variant: "secondary" })));
  return dialog;
}
