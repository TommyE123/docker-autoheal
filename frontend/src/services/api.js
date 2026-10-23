import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_URL || "/api";

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
    "Cache-Control": "no-cache, no-store, must-revalidate",
    Pragma: "no-cache",
    Expires: "0",
  },
});

// Optional API-key authentication. The server key is never in the bundle: the user
// enters it when the API answers 401, and it lives only in this tab's sessionStorage.
const API_KEY_STORAGE = "autoheal_api_key";
const API_KEY_HEADER = "X-API-Key";

// The key as set or cleared during this page load, which wins over sessionStorage so a
// write that storage rejects (blocked, full) cannot leave an older stored key in use.
// undefined: not touched this page load, so read storage. null: cleared.
let memoryApiKey;

export const getApiKey = () => {
  if (memoryApiKey !== undefined) return memoryApiKey;
  try {
    return sessionStorage.getItem(API_KEY_STORAGE);
  } catch {
    return null;
  }
};
// Returns true when the key was persisted and so survives a reload.
export const setApiKey = (key) => {
  memoryApiKey = key;
  try {
    sessionStorage.setItem(API_KEY_STORAGE, key);
    return true;
  } catch {
    return false;
  }
};
// Returns true when storage no longer holds the key, so a reload will not bring it back.
export const clearApiKey = () => {
  memoryApiKey = null;
  try {
    sessionStorage.removeItem(API_KEY_STORAGE);
    return true;
  } catch {
    return false;
  }
};

let unauthorizedHandler = null;
export const onUnauthorized = (handler) => {
  unauthorizedHandler = handler;
  return () => {
    if (unauthorizedHandler === handler) unauthorizedHandler = null;
  };
};

export const attachApiKey = (config) => {
  const key = getApiKey();
  if (key) config.headers[API_KEY_HEADER] = key;
  return config;
};
export const notifyUnauthorized = (error) => {
  if (error?.response?.status === 401 && unauthorizedHandler) {
    unauthorizedHandler();
  }
  return Promise.reject(error);
};

api.interceptors.request.use(attachApiKey);
api.interceptors.response.use((response) => response, notifyUnauthorized);

// System Status
export const getSystemStatus = () => api.get("/status");
export const getHealth = () => axios.get("/health");

// Containers
export const getContainers = (includeStopped = false) =>
  api.get("/containers", { params: { include_stopped: includeStopped } });

export const getContainerDetails = (containerId) =>
  api.get(`/containers/${containerId}`);

export const updateContainerSelection = (containerIds, enabled) =>
  api.post("/containers/select", { container_ids: containerIds, enabled });

export const restartContainer = (containerId) =>
  api.post(`/containers/${containerId}/restart`);

export const unquarantineContainer = (containerId) =>
  api.post(`/containers/${containerId}/unquarantine`);

// Configuration
export const getConfig = () => api.get("/config");
export const updateConfig = (config) => api.put("/config", config);
export const updateMonitorConfig = (config) =>
  api.put("/config/monitor", config);
export const updateRestartConfig = (config) =>
  api.put("/config/restart", config);
export const exportConfig = () => api.get("/config/export");
export const importConfig = (file) => {
  const formData = new FormData();
  formData.append("file", file);
  return api.post("/config/import", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

// Observability
export const updateObservabilityConfig = (observabilityConfig) =>
  api.put("/config/observability", observabilityConfig);

// Health Checks
export const getHealthChecks = () => api.get("/healthchecks");
export const getHealthCheck = (containerId) =>
  api.get(`/healthchecks/${containerId}`);
export const addHealthCheck = (healthCheck) =>
  api.post("/healthchecks", healthCheck);
export const deleteHealthCheck = (containerId) =>
  api.delete(`/healthchecks/${containerId}`);

// Events
export const getEvents = (limit = 50, { eventType, container } = {}) => {
  const params = { limit };
  if (eventType) params.event_type = eventType;
  if (container) params.container = container;
  return api.get("/events", { params });
};
export const clearEvents = () => api.delete("/events");

// Maintenance Mode
export const enableMaintenanceMode = () => api.post("/maintenance/enable");
export const disableMaintenanceMode = () => api.post("/maintenance/disable");
export const getMaintenanceStatus = () => api.get("/maintenance/status");

// Notifications
export const getNotificationsConfig = () => api.get("/notifications/config");
export const updateNotificationsConfig = (config) =>
  api.put("/notifications/config", config);
export const addNotificationService = (service) =>
  api.post("/notifications/services", service);
export const updateNotificationService = (serviceName, service) =>
  api.put(`/notifications/services/${serviceName}`, service);
export const deleteNotificationService = (serviceName) =>
  api.delete(`/notifications/services/${serviceName}`);
export const testNotificationService = (serviceName) =>
  api.post(`/notifications/test/${serviceName}`);
export const testUnsavedNotificationService = (service) =>
  api.post("/notifications/test", service);

export default api;
