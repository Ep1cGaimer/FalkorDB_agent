export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(method, path, body, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      method, headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body), ...options,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError(0, "The local server did not answer. Check that it is running and try again.");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    let detail = data?.detail ?? data?.reason;
    if (Array.isArray(detail)) detail = detail.map(x => `${(x.loc || []).slice(1).join(".")}: ${x.msg}`).join("\n");
    else if (detail && typeof detail === "object") detail = [detail.message || detail.reason, ...(detail.drift || [])].filter(Boolean).join("\n");
    throw new ApiError(response.status, detail || response.statusText);
  }
  return data;
}
