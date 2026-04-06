import { reactive } from "vue";
import { api } from "./api";

function cloneData(value) {
  return JSON.parse(JSON.stringify(value ?? {}));
}

const state = reactive({
  servers: [],
  users: [],
  overview: null,
  defaultConfig: {},
  loading: false,
  lastError: "",
  lastUpdatedAt: 0,
});

let timerId = null;

async function loadMeta() {
  const data = await api.getMeta();
  state.servers = data.servers || [];
}

async function refreshOverview() {
  const data = await api.getOverview();
  state.overview = data.overview || {};
}

async function refreshUsers() {
  const data = await api.listUsers();
  state.users = data.users || [];
}

async function refreshDefaultConfig() {
  const data = await api.getDefaultConfig();
  state.defaultConfig = cloneData(data.config || {});
}

async function refreshAll() {
  try {
    state.loading = true;
    state.lastError = "";
    await Promise.all([refreshUsers(), refreshOverview(), refreshDefaultConfig()]);
    state.lastUpdatedAt = Date.now();
  } catch (err) {
    state.lastError = err?.message || String(err);
    throw err;
  } finally {
    state.loading = false;
  }
}

async function init() {
  await loadMeta();
  await refreshAll();
}

function startPolling(interval = 5000) {
  if (timerId) {
    clearInterval(timerId);
  }
  timerId = setInterval(async () => {
    try {
      await Promise.all([refreshUsers(), refreshOverview()]);
      state.lastUpdatedAt = Date.now();
    } catch (err) {
      state.lastError = err?.message || String(err);
    }
  }, interval);
}

function stopPolling() {
  if (timerId) {
    clearInterval(timerId);
    timerId = null;
  }
}

async function createUser(name, server) {
  await api.createUser({ name, server });
  await Promise.all([refreshUsers(), refreshOverview()]);
}

async function deleteUser(userId) {
  await api.deleteUser(userId);
  await Promise.all([refreshUsers(), refreshOverview()]);
}

async function updateProfile(userId, payload) {
  await api.updateProfile(userId, payload);
  await Promise.all([refreshUsers(), refreshOverview()]);
}

async function updateSchedule(userId, schedule) {
  await api.updateSchedule(userId, schedule);
  await Promise.all([refreshUsers(), refreshOverview()]);
}

async function setSession(userId, sessionid) {
  await api.setSession(userId, sessionid);
  await Promise.all([refreshUsers(), refreshOverview()]);
}

async function startMonitor(userId) {
  await api.startMonitor(userId);
  await Promise.all([refreshUsers(), refreshOverview()]);
}

async function stopMonitor(userId) {
  await api.stopMonitor(userId);
  await Promise.all([refreshUsers(), refreshOverview()]);
}

async function updateDefaultConfig(config) {
  await api.updateDefaultConfig(config);
  await Promise.all([refreshDefaultConfig(), refreshUsers(), refreshOverview()]);
}

async function updateUserConfig(userId, config) {
  await api.updateUserConfig(userId, config);
  await Promise.all([refreshUsers(), refreshOverview()]);
}

async function updateUserConfigMode(userId, payload) {
  await api.updateUserConfigMode(userId, payload);
  await Promise.all([refreshUsers(), refreshOverview()]);
}

export function useAppStore() {
  return {
    state,
    api,
    cloneData,
    init,
    loadMeta,
    refreshAll,
    refreshUsers,
    refreshOverview,
    refreshDefaultConfig,
    startPolling,
    stopPolling,
    createUser,
    deleteUser,
    updateProfile,
    updateSchedule,
    setSession,
    startMonitor,
    stopMonitor,
    updateDefaultConfig,
    updateUserConfig,
    updateUserConfigMode,
  };
}
