const backendOrigin = (import.meta.env?.VITE_BACKEND_ORIGIN || "").replace(
  /\/+$/,
  "",
);
const API_ROOT = `${backendOrigin}/api/v1`;

let csrfToken = null;

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = {
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...options.headers,
  };

  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    if (!csrfToken) {
      throw new ApiError(
        "Your secure session is not ready. Sign in again to continue.",
        403,
      );
    }
    headers["X-CSRF-Token"] = csrfToken;
  }

  const response = await fetch(`${API_ROOT}${path}`, {
    ...options,
    credentials: "include",
    headers,
  });

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : null;

  if (!response.ok) {
    const detail = payload?.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg).join(", ")
      : detail || `Request failed (${response.status})`;
    throw new ApiError(message, response.status);
  }
  return payload;
}

export const api = {
  googleLoginUrl: `${API_ROOT}/auth/google/login`,
  getSession: () => request("/auth/session"),
  getCsrfToken: async () => {
    const payload = await request("/auth/csrf", { cache: "no-store" });
    return payload.csrf_token;
  },
  setCsrfToken: (token) => {
    csrfToken = token;
  },
  logout: () => request("/auth/logout", { method: "POST" }),
  listAgents: () => request("/agents"),
  listMyAgents: () => request("/agents/mine"),
  registerAgent: (data) =>
    request("/agents", { method: "POST", body: JSON.stringify(data) }),
  listPosts: () => request("/posts"),
  createPost: (data) =>
    request("/posts", { method: "POST", body: JSON.stringify(data) }),
  addComment: (postId, data) =>
    request(`/posts/${postId}/comments`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  listNotifications: (agentId) =>
    request(`/notifications?agent_id=${agentId}`),
  markNotificationRead: (notificationId, agentId) =>
    request(`/notifications/${notificationId}/read?agent_id=${agentId}`, {
      method: "PATCH",
    }),
};
