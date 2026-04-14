async function requestJson(url, options = {}) {
  const init = {
    headers: { "Content-Type": "application/json" },
    ...options,
  };
  const resp = await fetch(url, init);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.message || `请求失败: ${resp.status}`);
  }
  return data;
}

export const api = {
  requestJson,
  getMeta: () => requestJson("/api/meta"),
  getOverview: () => requestJson("/api/system/overview"),
  getSystemLogs: (query = {}) => {
    const params = new URLSearchParams();
    if (query.limit != null) {
      params.set("limit", String(query.limit));
    }
    if (query.keyword) {
      params.set("keyword", String(query.keyword));
    }
    if (query.events) {
      params.set("events", String(query.events));
    }
    const suffix = params.toString();
    return requestJson(`/api/system/logs${suffix ? `?${suffix}` : ""}`);
  },
  getDefaultConfig: () => requestJson("/api/config/default"),
  updateDefaultConfig: (config) =>
    requestJson("/api/config/default", {
      method: "PUT",
      body: JSON.stringify(config),
    }),
  listUsers: () => requestJson("/api/users"),
  getUserRuntime: (userId) => requestJson(`/api/users/${userId}/runtime`),
  getUserLogs: (userId, query = {}) => {
    const params = new URLSearchParams();
    if (query.limit != null) {
      params.set("limit", String(query.limit));
    }
    if (query.keyword) {
      params.set("keyword", String(query.keyword));
    }
    if (query.types) {
      params.set("types", String(query.types));
    }
    const suffix = params.toString();
    return requestJson(`/api/users/${userId}/logs${suffix ? `?${suffix}` : ""}`);
  },
  createUser: (payload) =>
    requestJson("/api/users", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteUser: (userId) => requestJson(`/api/users/${userId}`, { method: "DELETE" }),
  updateProfile: (userId, payload) =>
    requestJson(`/api/users/${userId}/profile`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  updateSchedule: (userId, schedule) =>
    requestJson(`/api/users/${userId}/schedule`, {
      method: "PUT",
      body: JSON.stringify({ schedule }),
    }),
  setSession: (userId, sessionid) =>
    requestJson(`/api/users/${userId}/session`, {
      method: "POST",
      body: JSON.stringify({ sessionid }),
    }),
  checkLogin: (userId) => requestJson(`/api/users/${userId}/check-login`),
  startMonitor: (userId) => requestJson(`/api/users/${userId}/start`, { method: "POST" }),
  stopMonitor: (userId) => requestJson(`/api/users/${userId}/stop`, { method: "POST" }),
  startLogin: (userId) => requestJson(`/api/users/${userId}/login/start`, { method: "POST" }),
  getLoginState: (userId) => requestJson(`/api/users/${userId}/login/state`),
  cancelLogin: (userId) => requestJson(`/api/users/${userId}/login/cancel`, { method: "POST" }),
  updateUserConfig: (userId, config) =>
    requestJson(`/api/users/${userId}/config`, {
      method: "PUT",
      body: JSON.stringify(config),
    }),
  updateUserConfigMode: (userId, payload) =>
    requestJson(`/api/users/${userId}/config/mode`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
};
