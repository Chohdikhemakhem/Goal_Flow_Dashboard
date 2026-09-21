const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  `${window.location.protocol}//${window.location.hostname}:8000/api/v1`;

let refreshInFlight = null;

function cleanParams(params) {
  if (!params || typeof params !== "object") return "";
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    if (typeof value === "string" && value.trim() === "") continue;
    if (typeof value === "number" && !Number.isFinite(value)) continue;
    usp.append(key, String(value));
  }
  return usp.toString();
}

function parseDownloadFilename(response, fallbackName) {
  const disposition = response.headers.get("Content-Disposition") || response.headers.get("content-disposition") || "";
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    return decodeURIComponent(utf8Match[1]);
  }
  const simpleMatch = disposition.match(/filename="?([^"]+)"?/i);
  if (simpleMatch?.[1]) {
    return simpleMatch[1];
  }
  return fallbackName;
}

async function downloadBinary(path, fallbackErrorMessage, fallbackName) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      credentials: "include",
    });
  } catch {
    throw new Error("Impossible de contacter le serveur de rapports (connexion/API).");
  }
  if (response.status === 401) {
    const refreshResponse = await tryRefresh().catch(() => null);
    if (refreshResponse?.ok) {
      response = await fetch(`${API_BASE_URL}${path}`, {
        credentials: "include",
      });
    }
  }
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error?.detail?.message || fallbackErrorMessage);
  }
  return {
    blob: await response.blob(),
    filename: parseDownloadFilename(response, fallbackName),
  };
}

async function tryRefresh() {
  if (!refreshInFlight) {
    refreshInFlight = fetch(`${API_BASE_URL}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    }).finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

async function request(path, options = {}, retry = true) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    credentials: "include",
    headers,
  });

  if (response.status === 401 && retry && !path.startsWith("/auth/")) {
    const refreshResponse = await tryRefresh().catch(() => null);
    if (refreshResponse?.ok) {
      return request(path, options, false);
    }
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: { message: response.statusText } }));
    const validationMessage = Array.isArray(error.detail)
      ? error.detail.map((item) => item?.msg).filter(Boolean).join(" | ")
      : null;
    const err = new Error(error.detail?.message || validationMessage || "Request failed");
    err.status = response.status;
    err.code = error.detail?.code || "request_failed";
    err.detail = error.detail || null;
    throw err;
  }
  if (response.status === 204) return null;
  try {
    return await response.json();
  } catch {
    const err = new Error("Reponse inattendue du serveur.");
    err.status = response.status;
    err.code = "invalid_json_response";
    err.detail = null;
    throw err;
  }
}

export const api = {
  login: (email, password) => request("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request("/auth/logout", { method: "POST" }),
  me: () => request("/auth/me"),
  changePassword: (currentPassword, newPassword) => request("/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  }),
  metrics: (params) => request(`/metrics/daily?${cleanParams(params)}`),
  currentCredits: (params) => request(`/metrics/current-credits?${cleanParams(params)}`),
  metricsSummary: (params) => request(`/metrics/summary?${cleanParams(params)}`),
  metricsCharts: (params) => request(`/metrics/charts?${cleanParams(params)}`),
  snapshots: (params = {}) => request(`/metrics/snapshots?${cleanParams(params)}`),
  potentialRadiationSnapshots: (params = {}) => request(`/reports/potential-radiation/snapshots?${cleanParams(params)}`),
  closedMonths: () => request("/metrics/closed-months"),
  deleteSnapshots: (batchIds) => request("/imports/snapshots/delete", {
    method: "POST",
    body: JSON.stringify({ batch_ids: batchIds }),
  }),
  activeSnapshot: () => request("/metrics/active-snapshot"),
  portfolioPerformance: () => request("/metrics/portfolio-performance"),
  parReduction: (params = {}) => request(`/metrics/par-reduction?${cleanParams(params)}`),
  parReductionEvolution: (params = {}) => request(`/metrics/par-reduction/evolution?${cleanParams(params)}`),
  agencies: () => request("/lookups/agencies?limit=500"),
   agents: (agencyId) => request(`/lookups/agents?limit=500${agencyId ? `&agency_id=${agencyId}` : ""}`),
   sectors: () => request("/lookups/sectors"),
  features: () => request("/lookups/features"),
  uploadLoans: (file) => {
    const body = new FormData();
    body.append("file", file);
    return request("/imports/loans", { method: "POST", body });
  },
  importBatches: () => request("/imports/batches"),
  deleteImportBatch: (id) => request(`/imports/batches/${id}`, { method: "DELETE" }),
  uploadCurrentState: (file) => {
    const body = new FormData();
    body.append("file", file);
    return request("/imports/current-state", { method: "POST", body });
  },
  uploadHistoricalMonth: (file, period, replaceExisting = false) => {
    const body = new FormData();
    body.append("file", file);
    body.append("period", period);
    body.append("replace_existing", String(Boolean(replaceExisting)));
    return request("/imports/historical", { method: "POST", body });
  },
  restructuredImportLogs: (params = {}) => request(`/imports/restructured-logs?${cleanParams(params)}`),
  restructuredImportLog: (id) => request(`/imports/restructured-logs/${id}`),
  previewRestructuredContracts: (file) => {
    const body = new FormData();
    body.append("file", file);
    return request("/imports/restructured-contracts/preview", {
      method: "POST",
      body,
    });
  },
  uploadRestructuredContracts: (file) => {
    const body = new FormData();
    body.append("file", file);
    return request("/imports/restructured-contracts", {
      method: "POST",
      body,
    });
  },
  uploadRestructuredSchedule: (file) => {
    const body = new FormData();
    body.append("file", file);
    return request("/imports/restructured-schedule", {
      method: "POST",
      body,
    });
  },
  restructuredPendingContracts: (params = {}) =>
    request(`/imports/restructured-pending?${cleanParams(params)}`),
  updateRestructuredPendingContract: (id, payload) =>
    request(`/imports/restructured-pending/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  validateRestructuredPendingContract: (id) =>
    request(`/imports/restructured-pending/${id}/validate`, {
      method: "POST",
    }),
  validateAllRestructuredPendingContracts: () =>
    request("/imports/restructured-pending/validate-all", {
      method: "POST",
    }),
  resyncRestructuredPendingContracts: () =>
    request("/imports/restructured-pending/resync", { method: "POST" }),
  getRestructuredPendingContractsDiagnostics: () =>
    request("/imports/restructured-pending/diagnostics"),
  targets: (params = {}) => request(`/targets?${cleanParams(params)}`),
  createTarget: (payload) => request("/targets", { method: "POST", body: JSON.stringify(payload) }),
  updateTarget: (id, payload) => request(`/targets/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteTarget: (id) => request(`/targets/${id}`, { method: "DELETE" }),
  previewObjectivesExcel: (file, period = {}) => {
    const body = new FormData();
    body.append("file", file);
    if (period.month) body.append("month", String(period.month));
    if (period.year) body.append("year", String(period.year));
    return request("/targets/import/preview", { method: "POST", body });
  },
  confirmObjectivesExcel: (file, mode, period = {}) => {
    const body = new FormData();
    body.append("file", file);
    body.append("mode", mode);
    if (period.month) body.append("month", String(period.month));
    if (period.year) body.append("year", String(period.year));
    return request("/targets/import/confirm", { method: "POST", body });
  },
  parReductionTargets: (params = {}) => request(`/par-reduction-targets?${cleanParams(params)}`),
  parReductionAgencySummary: (params = {}) => request(`/par-reduction-targets/agency-summary?${cleanParams(params)}`),
  createParReductionTarget: (payload) => request("/par-reduction-targets", { method: "POST", body: JSON.stringify(payload) }),
  updateParReductionTarget: (id, payload) => request(`/par-reduction-targets/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteParReductionTarget: (id) => request(`/par-reduction-targets/${id}`, { method: "DELETE" }),
  users: () => request("/users?limit=500"),
  usersPage: (params = {}) => request(`/users?${cleanParams(params)}`),
  gpMcrAudit: () => request("/users/gp-mcr-audit"),
  deleteMissingGpMcrAccounts: (accountIds) =>
    request("/users/gp-mcr-audit/missing-accounts", {
      method: "DELETE",
      body: JSON.stringify({ account_ids: accountIds }),
    }),
  acmLimits: () => request("/users/acm-limits"),
  updateAcmLimits: (payload) => request("/users/acm-limits", { method: "PUT", body: JSON.stringify(payload) }),
  loginAudit: (params = {}) => request(`/users/login-audit?${cleanParams(params)}`),
  taegPeriods: () => request("/taeg/periods"),
  taegDashboard: (params = {}) => request(`/taeg/dashboard?${cleanParams(params)}`),
  taegDetails: (params = {}) => request(`/taeg/details?${cleanParams(params)}`),
  taegMonthlyHistoryPeriods: () => request("/taeg/monthly-history/periods"),
  taegMonthlyHistory: (params = {}) => request(`/taeg/monthly-history?${cleanParams(params)}`),
  taegSectors: () => request("/taeg/sectors"),
  taegAcmRateVersions: () => request("/taeg/acm-rate-versions"),
  taegAcmRateVersion: (versionId) => request(`/taeg/acm-rate-versions/${versionId}`),
  createTaegAcmRateVersion: (payload) => request("/taeg/acm-rate-versions", { method: "POST", body: JSON.stringify(payload) }),
  updateTaegAcmRateVersion: (versionId, payload) => request(`/taeg/acm-rate-versions/${versionId}`, { method: "PUT", body: JSON.stringify(payload) }),
  createTaegSector: (payload) => request("/taeg/sectors", { method: "POST", body: JSON.stringify(payload) }),
  updateTaegSector: (id, payload) => request(`/taeg/sectors/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteTaegSector: (id) => request(`/taeg/sectors/${id}`, { method: "DELETE" }),
  taegCategoryMappings: () => request("/taeg/category-mappings"),
  upsertTaegCategoryMapping: (payload) => request("/taeg/category-mappings", { method: "PUT", body: JSON.stringify(payload) }),
  deleteTaegCategoryMapping: (id) => request(`/taeg/category-mappings/${id}`, { method: "DELETE" }),
  createUser: (payload) => request("/users", { method: "POST", body: JSON.stringify(payload) }),
  updateUser: (id, payload) => request(`/users/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteUser: (id) => request(`/users/${id}`, { method: "DELETE" }),
  setUserStatus: (id, isActive) => request(`/users/${id}/status`, { method: "PATCH", body: JSON.stringify({ is_active: isActive }) }),
  resetUserPassword: (id, temporaryPassword = "") => request(`/users/${id}/reset-password`, {
    method: "POST",
    body: JSON.stringify(temporaryPassword ? { temporary_password: temporaryPassword } : {}),
  }),
  autoCreateAgentUsers: () => request("/users/auto-create-agents", { method: "POST" }),
  provisionGpAccount: (agentName) => request("/users/gp-mcr-audit/provision-account", {
    method: "POST",
    body: JSON.stringify({ agent_name: agentName }),
  }),
  batchProvisionGpAccounts: (agentNames) => request("/users/gp-mcr-audit/provision-accounts", {
    method: "POST",
    body: JSON.stringify({ agent_names: agentNames }),
  }),
  bonusRules: () => request("/bonus/rules"),
  createBonusRule: (payload) => request("/bonus/rules", { method: "POST", body: JSON.stringify(payload) }),
  formulaHelp: () => request("/bonus/formula-help"),
  calculateBonus: (payload) => request("/bonus/calculate", { method: "POST", body: JSON.stringify(payload) }),
  downloadReport: async (type, params) => (
    downloadBinary(
      `/reports/metrics.${type}?${cleanParams(params)}`,
      "Echec du telechargement du rapport.",
      `microcred_metrics.${type}`,
    ).then((result) => result.blob)
  ),
  downloadLoginAudit: async (format, params = {}) => (
    downloadBinary(
      `/users/login-audit.${format}?${cleanParams(params)}`,
      "Echec du telechargement du rapport d'audit.",
      `login_audit.${format}`,
    ).then((result) => result.blob)
  ),
  downloadPortfolioReport: async (format, params) => (
    downloadBinary(
      `/reports/portfolio.${format}?${cleanParams(params)}`,
      "Portfolio report export failed",
      `microcred_portfolio.${format}`,
    ).then((result) => result.blob)
  ),
  restructuredKpis: (params = {}) =>
    request(`/credits-restructures/kpis?${cleanParams(params)}`),
  restructuredQualityChart: (params = {}) =>
    request(`/credits-restructures/charts/quality-by-agency?${cleanParams(params)}`),
  restructuredConsecutiveChart: (params = {}) =>
    request(`/credits-restructures/charts/repartition-consecutives?${cleanParams(params)}`),
  restructuredContracts: (params = {}) =>
    request(`/credits-restructures/contrats?${cleanParams(params)}`),
  restructuredMissingContracts: (params = {}) =>
    request(`/credits-restructures/absents-mcr?${cleanParams(params)}`),
  deleteMissingMcrContracts: (contractNos) =>
    request("/credits-restructures/absents-mcr/contracts", {
      method: "DELETE",
      body: JSON.stringify({ contract_nos: contractNos }),
    }),
  downloadRestructuredContractsExport: (params = {}) => downloadBinary(
    `/credits-restructures/contrats/export.xlsx?${cleanParams(params)}`,
    "Echec du telechargement du rapport restructure.",
    "detail_contrats_restructures.xlsx",
  ),
  downloadRestructuredMissingContractsExport: (params = {}) => downloadBinary(
    `/credits-restructures/absents-mcr/export.xlsx?${cleanParams(params)}`,
    "Echec du telechargement de la liste des contrats absents du MCR.",
    "contrats_absents_mcr.xlsx",
  ),
  downloadTaegReport: (params = {}) => downloadBinary(
    `/taeg/export.xlsx?${cleanParams(params)}`,
    "Echec du telechargement du rapport TAEG.",
    "TAEG_export.xlsx",
  ),
};
