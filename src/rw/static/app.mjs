import { api, ApiError } from "./api.mjs";
import { disposition, preferredCheck, replayMatches, recordedAnswers, replayCandidates, usedReplays, workspaceTitle } from "./model.mjs";
import { currentAttempt, contextFor, sidebar, topbar, investigationView, overlay } from "./views.mjs";
import { investigationFromSearch, loadInvestigation, adoptInvestigation } from "./handoff.mjs";

// Local UI audit origin, not an authenticated person's identity. Explicit clicks still
// confirm scope and approve simulation; the server retains every evidence/approval gate.
const LOCAL_UI_IDENTITY = "local-ui-user";

const state = {
  inv: null, attemptIndex: 0, busy: null, error: null,
  selected: null, focusRecord: null, overlay: null, returnFocus: null, contexts: [], contextError: null,
  transcripts: [], history: [], liveRequest: "", retainedExpanded: false,
  form: { request: "", snapshot: "", mode: "live", replay: "", answerReplay: "", altReplay: "", answer: "" },
};

const NAVIGATION_VERSION = "rollback-review-v1";
let navigationReady = false;
let restoringNavigation = false;
let restorationVersion = 0;
let pendingNavigation = null;

function viewSnapshot() {
  return {
    investigationId: state.inv?.id || null, attemptIndex: state.attemptIndex,
    selected: state.selected, focusRecord: state.focusRecord, overlay: state.overlay,
    returnFocus: state.returnFocus, form: { ...state.form }, liveRequest: state.liveRequest,
    retainedExpanded: state.retainedExpanded,
    scroll: [window.scrollX, window.scrollY],
  };
}

const viewAddress = view => view.investigationId ? `#investigation/${view.investigationId}` : "#investigations";
const ownsEntry = entry => entry?.application === NAVIGATION_VERSION && entry.view && Number.isInteger(entry.index);

function rememberView() {
  if (!navigationReady || restoringNavigation || pendingNavigation) return;
  const view = viewSnapshot(), index = ownsEntry(history.state) ? history.state.index : 0;
  history.replaceState({ application: NAVIGATION_VERSION, index, view }, "", viewAddress(view));
}

function navigate(change) {
  if (pendingNavigation || restoringNavigation) return;
  rememberView();
  const index = ownsEntry(history.state) ? history.state.index + 1 : 1;
  change();
  const view = viewSnapshot();
  history.pushState({ application: NAVIGATION_VERSION, index, view }, "", viewAddress(view));
  render();
}

async function restoreNavigation(target) {
  if (state.busy && !restoringNavigation) { pendingNavigation = target; return; }
  const version = ++restorationVersion;
  const match = target.hash.match(/^#investigation\/([a-f0-9]{32})$/);
  const owned = ownsEntry(target.entry) && viewAddress(target.entry.view) === target.hash;
  const view = owned ? target.entry.view : { ...viewSnapshot(), investigationId: match?.[1] || null,
    attemptIndex: null, selected: null, focusRecord: null, overlay: null, scroll: [0, 0] };
  // Closing a dialog keeps settings edits and the selected record, just like Done/Escape.
  const closingDialog = state.overlay && !view.overlay && state.inv?.id === (view.investigationId || undefined);
  const carry = closingDialog ? { form: { ...state.form }, liveRequest: state.liveRequest,
    selected: state.selected, returnFocus: state.returnFocus } : null;
  let inv = view.investigationId === state.inv?.id ? state.inv : null, error = null;
  restoringNavigation = true;
  state.overlay = null;
  state.busy = view.investigationId && !inv ? "Loading investigation…" : null;
  state.error = null;
  if (state.busy) render();
  if (view.investigationId && !inv) {
    try { inv = await loadInvestigation(view.investigationId); }
    catch (failure) { error = failure; }
  }
  if (version !== restorationVersion) return;
  state.inv = inv;
  state.attemptIndex = inv ? Math.max(0, Math.min(view.attemptIndex ?? inv.attempts.length - 1, inv.attempts.length - 1)) : 0;
  state.form = { ...state.form, ...view.form };
  state.liveRequest = view.liveRequest ?? "";
  state.retainedExpanded = !!view.retainedExpanded;
  state.selected = view.selected;
  state.focusRecord = view.focusRecord;
  state.returnFocus = view.returnFocus;
  state.overlay = view.overlay && (["settings", "explanation"].includes(view.overlay.kind) || inv) ? view.overlay : null;
  if (inv) {
    state.form.mode = inv.mode;
    state.form.snapshot = inv.snapshot_id.replace(/^snapshot:/, "");
    if (!owned) {
      adoptInvestigation(state, inv);
    }
  } else if (!state.contexts.some(c => c.snapshot === state.form.snapshot)) {
    state.form.snapshot = state.contexts[0]?.snapshot || "";
  }
  if (carry) Object.assign(state, carry);
  state.busy = null; state.error = error;
  restoringNavigation = false; navigationReady = true;
  history.replaceState({ application: NAVIGATION_VERSION, index: owned ? target.entry.index : 0,
    view: viewSnapshot() }, "", viewAddress(viewSnapshot()));
  render();
  document.getElementById("sidebar").classList.remove("open");
  if (carry) (document.getElementById(carry.returnFocus) || document.getElementById("workspace")).focus({ preventScroll: true });
  window.scrollTo(...(view.scroll || [0, 0]));
  rememberView();
}

function render() {
  document.title = workspaceTitle(contextFor(state), currentAttempt(state));
  const active = document.activeElement;
  const focusedId = active?.id;
  const selection = active && typeof active.selectionStart === "number" ? [active.selectionStart, active.selectionEnd] : null;
  const scroll = [window.scrollX, window.scrollY];
  const dialogScroll = document.getElementById("workspace-dialog")?.scrollTop || 0;
  state.canGoBack = !!state.inv || (ownsEntry(history.state) && history.state.index > 0);
  document.getElementById("sidebar").replaceChildren(...sidebar(state, actions).filter(Boolean));
  document.getElementById("topbar").replaceChildren(...topbar(state, actions).filter(Boolean));
  const main = document.getElementById("workspace");
  main.setAttribute("aria-busy", String(!!state.busy));
  main.replaceChildren(...investigationView(state, actions).flat(Infinity).filter(Boolean));
  const root = document.getElementById("overlay-root"), dialog = overlay(state, actions);
  root.replaceChildren(...(dialog ? [dialog] : []));
  if (dialog) { dialog.showModal(); dialog.scrollTop = dialogScroll; }
  if (focusedId) {
    const next = document.getElementById(focusedId);
    if (next && (!dialog || dialog.contains(next))) {
      next.focus({ preventScroll: true });
      if (selection && next.setSelectionRange) next.setSelectionRange(...selection);
    }
  }
  window.scrollTo(...scroll);
  syncButtons();
}

async function loadHistory() {
  try { state.history = (await api("GET", "/api/investigations")).reverse(); }
  catch { /* A history refresh cannot invalidate the current investigation. */ }
}

async function execute(label, fn) {
  if (state.busy) return;
  state.busy = label; state.error = null; render();
  try { await fn(); }
  catch (error) { state.error = error instanceof ApiError ? error : new ApiError(-1, error.message); }
  finally {
    await loadHistory(); state.busy = null;
    const target = pendingNavigation; pendingNavigation = null;
    if (target) await restoreNavigation(target);
    else { rememberView(); render(); }
  }
}

async function refresh() {
  state.inv = await loadInvestigation(state.inv.id);
}

function selectLatest(inv) {
  navigate(() => {
    adoptInvestigation(state, inv);
  });
}

function canStart() {
  return !state.busy && !state.inv && state.contexts.some(c => c.snapshot === state.form.snapshot) && !!state.form.request.trim()
    && (state.form.mode !== "replay" || state.transcripts.some(t => t.replay_path === state.form.replay && t.request_text === state.form.request));
}
function canAnswer() {
  const attempt = currentAttempt(state);
  return !state.busy && !!attempt?.clarification && !state.inv.answered && attempt === state.inv.attempts.at(-1)
    && !!state.form.answer.trim() && (state.inv.mode !== "replay" || replayMatches(state.transcripts, state.inv.request_text,
      attempt.clarification.question, state.form.answer).some(t => t.replay_path === state.form.answerReplay));
}
function canAlternative() {
  const attempt = currentAttempt(state);
  return !state.busy && !!attempt && attempt === state.inv.attempts.at(-1)
    && state.inv.attempts.filter(x => x.plan).length < 2
    && ["BLOCKED", "NEEDS_EVIDENCE"].includes(disposition(attempt))
    && (state.inv.mode !== "replay" || replayCandidates(state.transcripts, state.inv.request_text, usedReplays(state.inv)).some(t => t.replay_path === state.form.altReplay));
}
function syncButtons() {
  const attempt = currentAttempt(state);
  const enabled = { start: canStart(), answer: canAnswer(), alternative: canAlternative(),
    confirm: !state.busy && !!attempt?.plan && !attempt.report,
    approve: !state.busy && disposition(attempt) === "BOUNDED_PASS" && !attempt.approval };
  for (const node of document.querySelectorAll("button[data-action]")) node.disabled = !enabled[node.dataset.action];
  rememberView();
}

const actions = {
  canStart, canAnswer, canAlternative, syncButtons,
  start() {
    if (!canStart()) return;
    const f = state.form;
    execute(f.mode === "live" ? "Finding software versions for your request…" : "Reading the saved proposal…", async () => {
      const body = { request_text: f.request, snapshot: f.snapshot, mode: f.mode };
      if (f.mode === "replay") body.replay_path = f.replay;
      selectLatest(await api("POST", "/api/investigations", body));
    });
  },
  answer() {
    if (!canAnswer()) return;
    execute("Updating the proposal with your answer…", async () => {
      const body = { answer: state.form.answer.trim() };
      if (state.inv.mode === "replay") body.replay_path = state.form.answerReplay;
      selectLatest(await api("POST", `/api/investigations/${state.inv.id}/answer`, body));
    });
  },
  confirm(attempt) {
    if (!attempt.plan || state.busy || attempt.report) return;
    execute("Checking readers against retained records…", async () => {
      await api("POST", `/api/investigations/${state.inv.id}/plans/${attempt.plan_hash}/confirm-scope`, { confirmed_by: LOCAL_UI_IDENTITY });
      await refresh();
      const verification = currentAttempt(state).report.verification;
      const focused = verification.obligations.find(ob => ob.tuple.record_id === state.focusRecord?.record_id && ob.tuple.store_id === state.focusRecord?.store_id);
      state.selected = focused?.obligation_hash || null;
    });
  },
  alternative() {
    if (!canAlternative()) return;
    const prior = preferredCheck(currentAttempt(state).report.verification, state.selected);
    state.focusRecord = prior ? { record_id: prior.obligation.tuple.record_id, store_id: prior.obligation.tuple.store_id } : null;
    execute("Finding an alternative…", async () => {
      const body = state.inv.mode === "replay" ? { replay_path: state.form.altReplay } : {};
      selectLatest(await api("POST", `/api/investigations/${state.inv.id}/alternative`, body));
    });
  },
  approve(attempt) {
    if (disposition(attempt) !== "BOUNDED_PASS" || attempt.approval || state.busy) return;
    execute("Approving this local simulation…", async () => {
      await api("POST", `/api/investigations/${state.inv.id}/plans/${attempt.plan_hash}/approve`, { approved_by: LOCAL_UI_IDENTITY });
      await refresh();
    });
  },
  simulate(attempt) {
    if (!attempt.approval || disposition(attempt) !== "BOUNDED_PASS" || state.busy) return;
    execute("Running the local simulation…", async () => {
      await api("POST", `/api/investigations/${state.inv.id}/plans/${attempt.plan_hash}/simulate`);
      await refresh();
    });
  },
  openInvestigation(id) {
    execute("Loading investigation…", async () => {
      state.overlay = null; state.focusRecord = null;
      selectLatest(await loadInvestigation(id));
      document.getElementById("sidebar").classList.remove("open");
    });
  },
  refreshInvestigation() {
    execute("Refreshing stored evidence…", async () => { selectLatest(await loadInvestigation(state.inv.id)); });
  },
  newInvestigation() {
    if (state.busy) return;
    navigate(() => {
      state.inv = null; state.attemptIndex = 0; state.selected = null; state.focusRecord = null; state.error = null; state.overlay = null;
      state.form.answer = ""; state.form.answerReplay = ""; state.form.altReplay = "";
      if (state.form.mode === "live") state.form.request = state.liveRequest;
    });
    document.getElementById("sidebar").classList.remove("open");
    window.scrollTo(0, 0); document.getElementById("request")?.focus({ preventScroll: true });
  },
  back() {
    if (state.busy) return;
    rememberView();
    if (ownsEntry(history.state) && history.state.index > 0) history.back();
    else if (state.inv) actions.newInvestigation();
  },
  selectAttempt(index) {
    if (!state.busy && index !== state.attemptIndex) navigate(() => { state.attemptIndex = index; state.selected = null; });
  },
  inspect(selected) { state.selected = selected; actions.openOverlay("receipt"); },
  openOverlay(kind, service) {
    navigate(() => {
      state.returnFocus = document.activeElement?.id || null;
      state.overlay = { kind, service };
    });
  },
  closeOverlay() {
    rememberView();
    if (ownsEntry(history.state) && history.state.index > 0) history.back();
    else { state.overlay = null; rememberView(); render(); }
  },
  setMode(mode) {
    if (state.inv || state.busy) return;
    if (state.form.mode === "live") state.liveRequest = state.form.request;
    state.form.mode = mode;
    if (mode === "live") state.form.request = state.liveRequest;
    else {
      const first = state.transcripts.filter(t => !t.request_text.includes("\n\nAgent asked:"));
      const t = first.find(t => t.replay_path === state.form.replay) || first[0];
      if (t) { state.form.replay = t.replay_path; state.form.request = t.request_text; }
    }
    state.error = null; render();
  },
  setReplay(path) {
    const t = state.transcripts.find(t => t.replay_path === path);
    if (!state.inv && t) { state.form.replay = path; state.form.request = t.request_text; render(); }
  },
  setSnapshot(snapshot) { if (!state.inv && !state.busy) { state.form.snapshot = snapshot; state.retainedExpanded = false; render(); } },
  setRetainedExpanded(open) {
    // Rebuilding an already-open <details> emits toggle too; it must not rewrite
    // a history entry while Back is restoring a dialog's previous view.
    if (open === state.retainedExpanded) return;
    state.retainedExpanded = open; rememberView();
  },
  setAnswerReplay(path) {
    const question = currentAttempt(state)?.clarification?.question;
    const selected = recordedAnswers(state.transcripts, state.inv.request_text, question).find(t => t.replay_path === path);
    state.form.answerReplay = selected?.replay_path || ""; state.form.answer = selected?.answer || ""; render();
  },
  dismissError() { state.error = null; render(); },
  toggleSidebar() { document.getElementById("sidebar").classList.toggle("open"); },
};

async function boot() {
  history.scrollRestoration = "manual";
  const results = await Promise.allSettled([api("GET", "/api/snapshots"), api("GET", "/api/transcripts"), loadHistory()]);
  if (results[0].status === "fulfilled") {
    state.contexts = results[0].value;
    state.form.snapshot = state.contexts[0]?.snapshot || "";
  }
  else state.contextError = `Fixture inventory unavailable: ${results[0].reason.message}`;
  if (results[1].status === "fulfilled") state.transcripts = results[1].value;
  else state.error = new ApiError(0, `Saved transcripts unavailable: ${results[1].reason.message}`);
  const handoff = location.hash ? null : investigationFromSearch(location.search);
  await restoreNavigation({ entry: handoff ? null : history.state, hash: handoff ? `#investigation/${handoff}` : location.hash });
}

window.addEventListener("popstate", event => restoreNavigation({ entry: event.state, hash: location.hash }));
window.addEventListener("beforeunload", rememberView);
let scrollTimer;
window.addEventListener("scroll", () => {
  clearTimeout(scrollTimer); scrollTimer = setTimeout(rememberView, 100);
}, { passive: true });

document.addEventListener("keydown", event => {
  if (event.key === "Escape") document.getElementById("sidebar").classList.remove("open");
});
boot().catch(error => { state.error = new ApiError(-1, error.message); render(); });
