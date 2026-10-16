import { api, ApiError } from "./api.mjs";

export function investigationFromSearch(search) {
  const id = new URLSearchParams(search).get("investigation");
  if (id === null) return null;
  if (!/^[0-9a-f]{32}$/.test(id)) throw new ApiError(422, "Invalid investigation link. Start a new investigation below.");
  return id;
}

export async function loadInvestigation(id) {
  if (!/^[0-9a-f]{32}$/.test(id)) throw new ApiError(422, "Invalid investigation ID.");
  try { return await api("GET", `/api/investigations/${id}`); }
  catch (error) {
    if (error.status === 404) throw new ApiError(404, "This investigation is unknown or was lost when the API restarted. Start a new investigation below.");
    throw error;
  }
}

export function adoptInvestigation(state, inv) {
  state.inv = inv; state.attemptIndex = inv.attempts.length - 1; state.selected = null; state.overlay = null;
  state.form.request = inv.original_request_text || inv.request_text.split("\n\nAgent asked:")[0];
  state.form.mode = inv.mode; state.form.snapshot = inv.snapshot_id.replace(/^snapshot:/, "");
  state.form.replay = inv.transcript?.split(/[/\\]/).pop() || "";
  if (inv.mode === "live") state.liveRequest = state.form.request;
}
