const LIVE_PREFIX = "/api/v1/live";

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function configuredOrigin() {
  const configured = import.meta.env.VITE_API_BASE_URL;
  if (configured) return configured.replace(/\/$/, "");
  if (typeof window !== "undefined") return window.location.origin;
  return "";
}

function apiUrl(path) {
  return `${configuredOrigin()}${path}`;
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(apiUrl(path), {
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
    });
  } catch (error) {
    throw new ApiError("The AURA-Med API could not be reached.", 0, { cause: error });
  }

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof payload === "object" ? payload.detail : payload;
    throw new ApiError(detail || `The API returned ${response.status}.`, response.status);
  }
  return payload;
}

export function listScenarios() {
  return request("/api/v1/scenarios");
}

export function createLiveSession(config) {
  return request(`${LIVE_PREFIX}/sessions`, {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export function getLiveSession(sessionId) {
  return request(`${LIVE_PREFIX}/sessions/${encodeURIComponent(sessionId)}`);
}

export function startLiveSession(sessionId) {
  return request(`${LIVE_PREFIX}/sessions/${encodeURIComponent(sessionId)}/start`, { method: "POST" });
}

export function stopLiveSession(sessionId) {
  return request(`${LIVE_PREFIX}/sessions/${encodeURIComponent(sessionId)}/stop`, { method: "POST" });
}

export function getLiveReport(sessionId) {
  return request(`${LIVE_PREFIX}/sessions/${encodeURIComponent(sessionId)}/report`);
}

export function getLiveFailures(sessionId) {
  return request(`${LIVE_PREFIX}/sessions/${encodeURIComponent(sessionId)}/failures`);
}

export function exportUrl(sessionId, file) {
  return apiUrl(`${LIVE_PREFIX}/sessions/${encodeURIComponent(sessionId)}/${file}`);
}

export function createLiveSocket(sessionId, { onEvent, onOpen, onError, onClose }) {
  const origin = configuredOrigin() || window.location.origin;
  const url = new URL(`${LIVE_PREFIX}/sessions/${encodeURIComponent(sessionId)}/events`, origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(url.toString());

  socket.addEventListener("open", () => onOpen?.());
  socket.addEventListener("message", (message) => {
    try {
      onEvent?.(JSON.parse(message.data));
    } catch {
      onError?.("The live stream sent an unreadable event.");
    }
  });
  socket.addEventListener("error", () => onError?.("The live stream connection could not be established."));
  socket.addEventListener("close", (event) => onClose?.(event));
  return socket;
}
