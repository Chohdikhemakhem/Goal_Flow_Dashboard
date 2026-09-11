import React, { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  BarChart3,
  BriefcaseBusiness,
  Calculator,
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  FileDown,
  Filter,
  LogOut,
  Menu,
  Plus,
  Save,
  Search,
  Target,
  Trash2,
  TrendingDown,
  Upload,
  Users,
  Settings2,
  X,
  FileWarning,
} from "lucide-react";
import {
  Bar,
  BarChart,
  Brush,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "./api";
import * as XLSX from "xlsx";
import "./styles.css";

const DEFAULT_EXPRESSION =
  "250000 * (0.35 * min(disbursement_volume / target_disbursement, 1) + 0.25 * min(outstanding / target_outstanding, 1) + 0.25 * min(healthy_outstanding / target_healthy_outstanding, 1) + 0.15 * max(1 - par_30_rate / target_par, 0))";

const CHART_MODES = Object.freeze({
  GLOBAL_BY_AGENCY: "GLOBAL_BY_AGENCY",
  AGENCY_MONTHLY_TREND: "AGENCY_MONTHLY_TREND",
  AGENT_MONTHLY_TREND: "AGENT_MONTHLY_TREND",
  GLOBAL_QUALITY_TREND: "GLOBAL_QUALITY_TREND",
});
const RISK_STACK_SERIES = Object.freeze([
  { key: "par1_15Rate", label: "Cohorte 1-15", color: "#7aa7e8" },
  { key: "par16_30Rate", label: "Cohorte 16-30", color: "#a8c4ec" },
  { key: "par31_60Rate", label: "Cohorte 31-60", color: "#cfe0f7" },
  { key: "par61_90Rate", label: "Cohorte 61-90", color: "#c9c9c9" },
  { key: "par91_120Rate", label: "Cohorte 91-120", color: "#4a7fc7" },
  { key: "par120Rate", label: "PAR120", color: "#1d4f9a" },
]);
const PAR_REDUCTION_COLORS = Object.freeze({
  cohort_1_15: "#2563eb",
  cohort_16_30: "#0f766e",
  par30: "#dc2626",
});
const VOLUME_STACK_SERIES = Object.freeze([
  { key: "microDisbursement", countKey: "microDisbursementCount", label: "Crédit Micro", color: "#60a5fa" },
  { key: "tpmeDisbursement", countKey: "tpmeDisbursementCount", label: "Crédit TPME", color: "#2563eb" },
  { key: "afariDisbursement", countKey: "afariDisbursementCount", label: "Crédit ACV", color: "#0f766e" },
]);
const TAEG_HISTORY_LINE_COLORS = Object.freeze([
  "#2563eb",
  "#0f766e",
  "#7c3aed",
  "#dc2626",
  "#ea580c",
  "#0891b2",
  "#65a30d",
  "#be185d",
  "#4f46e5",
  "#0369a1",
]);
const TAEG_SECTOR_ORDER = [
  "commerce",
  "service",
  "production",
  "artisanat",
  "agriculture",
  "peche",
  "elevage",
  "amelioration du logement",
  "education",
  "autre acv",
];
function taegSectorSortIndex(sectorName) {
  const normalized = stripAccents(String(sectorName || "").trim()).toLocaleLowerCase("fr-FR");
  const index = TAEG_SECTOR_ORDER.findIndex((entry) => {
    const n = stripAccents(entry);
    return normalized === n || normalized.startsWith(n) || n.startsWith(normalized);
  });
  return index === -1 ? TAEG_SECTOR_ORDER.length : index;
}
function sortBySectorOrder(rows, getSectorName) {
  return [...rows].sort((left, right) => {
    const leftIdx = taegSectorSortIndex(getSectorName(left));
    const rightIdx = taegSectorSortIndex(getSectorName(right));
    if (leftIdx !== rightIdx) return leftIdx - rightIdx;
    return String(getSectorName(left) || "").localeCompare(String(getSectorName(right) || ""), "fr-FR", { sensitivity: "base" });
  });
}
const REGION_NORD_AGENCIES = Object.freeze([
  "AGENCE EZAHROUNI",
  "AGENCE ARIANA",
  "AGENCE BEN AROUS",
  "AGENCE JENDOUBA",
  "AGENCE KEF",
  "AGENCE BIZERTE",
  "AGENCE TCV",
  "AGENCE NABEUL",
  "AGENCE SILIANA",
  "AGENCE BEJA",
  "AGENCE FAHS",
]);
function isNordAgency(agencyLabel) {
  const normalized = stripAccents(String(agencyLabel || "").trim()).toUpperCase();
  return REGION_NORD_AGENCIES.some((name) => normalized === name || normalized.includes(stripAccents(name)));
}
const CREDIT_RISK_OPTIONS = Object.freeze([
  { value: "cohort_1_15", label: "Cohorte 1-15" },
  { value: "cohort_16_30", label: "Cohorte 16-30" },
  { value: "cohort_31_60", label: "Cohorte 31-60" },
  { value: "cohort_61_90", label: "Cohorte 61-90" },
  { value: "cohort_91_120", label: "Cohorte 91-120" },
  { value: "par_0", label: "PAR0" },
  { value: "par_30", label: "PAR30" },
  { value: "par_120", label: "PAR120" },
]);
const FORCE_LOGIN_ON_START =
  String(import.meta.env.VITE_FORCE_LOGIN_ON_START ?? "true").toLowerCase() !== "false";
const DEFAULT_FEATURE_FLAGS = Object.freeze({
  bonus_module_active: false,
});
const COMMITTEE_MONTH_STORAGE_KEY = "metrics-gp-mcr-committee-month";
const TABLE_FILTER_OPENED_EVENT = "metrics-gp-mcr-table-filter-opened";

function money(value) {
  return new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 }).format(Number(value || 0));
}

function formatNumber(value) {
  const numeric = Number(value ?? 0);
  return new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 }).format(Number.isFinite(numeric) ? numeric : 0);
}

function clampProgress(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? Math.max(0, Math.min(100, numeric)) : 0;
}

function interpolateColor(start, end, ratio) {
  const channel = (index) => Math.round(start[index] + (end[index] - start[index]) * ratio);
  return `rgb(${channel(0)}, ${channel(1)}, ${channel(2)})`;
}

function progressGradient(value) {
  const achievement = Number(value);
  if (!Number.isFinite(achievement) || achievement <= 0) {
    return "linear-gradient(90deg, #dc2626, #dc2626)";
  }
  if (achievement >= 100) {
    return "linear-gradient(90deg, #16a34a, #16a34a)";
  }
  const red = [220, 38, 38];
  const orange = [249, 115, 22];
  const green = [22, 163, 74];
  if (achievement <= 50) {
    const color = interpolateColor(red, orange, achievement / 50);
    return `linear-gradient(90deg, rgb(${red.join(",")}), ${color})`;
  }
  const color = interpolateColor(orange, green, (achievement - 50) / 50);
  return `linear-gradient(90deg, rgb(${orange.join(",")}), ${color})`;
}

function moneyDetailed(value) {
  if (value === null || value === undefined || value === "") return "-";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "-";
  return new Intl.NumberFormat("fr-FR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(numeric);
}

function formatMoney(value) {
  return moneyDetailed(value);
}

function percent(value) {
  return `${(Number(value || 0) * 100).toFixed(2)}%`;
}

function chartPercent(value) {
  return `${Number(value || 0).toFixed(2)}%`;
}

function chartPercentNullable(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `${Number(value).toFixed(2)}%`;
}

function taegStatusMeta(status) {
  if (status === "conforme") return { className: "success", label: "Conforme" };
  if (status === "non_couvert") return { className: "warning", label: "Non couvert ACM" };
  return { className: "danger", label: "Non Conforme" };
}

function shortDate(value) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleDateString("fr-FR");
}

function clean(params) {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== "" && value !== null && value !== undefined),
  );
}

function normalizeRestructuredImportPreview(result) {
  const safeResult = result && typeof result === "object" ? result : {};
  return {
    file_name: safeResult.file_name || "",
    rows_seen: Number.isFinite(Number(safeResult.rows_seen)) ? Number(safeResult.rows_seen) : 0,
    existing_contracts_count: Number.isFinite(Number(safeResult.existing_contracts_count)) ? Number(safeResult.existing_contracts_count) : 0,
    imported_list_count: Number.isFinite(Number(safeResult.imported_list_count)) ? Number(safeResult.imported_list_count) : 0,
    detected_in_mcr_count: Number.isFinite(Number(safeResult.detected_in_mcr_count)) ? Number(safeResult.detected_in_mcr_count) : 0,
    kept_count: Number.isFinite(Number(safeResult.kept_count)) ? Number(safeResult.kept_count) : 0,
    add_count: Number.isFinite(Number(safeResult.add_count)) ? Number(safeResult.add_count) : 0,
    update_count: Number.isFinite(Number(safeResult.update_count)) ? Number(safeResult.update_count) : 0,
    delete_count: Number.isFinite(Number(safeResult.delete_count)) ? Number(safeResult.delete_count) : 0,
    pending_cleanup_count: Number.isFinite(Number(safeResult.pending_cleanup_count)) ? Number(safeResult.pending_cleanup_count) : 0,
    deletions: Array.isArray(safeResult.deletions) ? safeResult.deletions : [],
    message: typeof safeResult.message === "string" ? safeResult.message : "Previsualisation terminee.",
  };
}

class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: "" };
  }

  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      message: error?.message || "Une erreur inattendue est survenue dans l'interface.",
    };
  }

  componentDidCatch(error, errorInfo) {
    console.error("React error boundary intercepted an error", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="app-shell-compact">
          <main className="content">
            <section className="panel">
              <h3>Une erreur d'affichage est survenue</h3>
              <p className="error">{this.state.message}</p>
              <p className="muted">Rechargez la page. Si le probleme persiste, verifiez le dernier import et les logs backend.</p>
            </section>
          </main>
        </div>
      );
    }
    return this.props.children;
  }
}

function riskAxisUpperBound(value) {
  const safeValue = Math.max(0, Number(value || 0));
  if (safeValue <= 6) return 6;
  if (safeValue <= 8) return 8;
  if (safeValue <= 10) return 10;
  if (safeValue <= 15) return 15;
  return Math.ceil((safeValue * 1.12) / 5) * 5;
}

function normalizeDateValue(value) {
  if (!value) return null;
  if (value instanceof Date) {
    const ts = value.getTime();
    return Number.isNaN(ts) ? null : ts;
  }
  const raw = String(value).trim();
  const isoDate = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (isoDate) {
    const [_, y, m, d] = isoDate;
    return Date.UTC(Number(y), Number(m) - 1, Number(d));
  }
  const frDate = raw.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (frDate) {
    const [__, d, m, y] = frDate;
    return Date.UTC(Number(y), Number(m) - 1, Number(d));
  }
  const parsed = new Date(raw).getTime();
  return Number.isNaN(parsed) ? null : parsed;
}

function normalizeNumberValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeTextValue(value) {
  if (value === null || value === undefined) return null;
  const normalized = String(value).trim().toLocaleLowerCase("fr-FR");
  return normalized || null;
}

function sortRows(rows, sortState, columns) {
  if (!sortState?.key || !sortState?.direction) return rows;
  const column = columns.find((item) => item.key === sortState.key);
  if (!column || !column.sortableType) return rows;
  const directionFactor = sortState.direction === "asc" ? 1 : -1;
  const decorated = rows.map((item, index) => ({ item, index }));
  decorated.sort((left, right) => {
    const leftRaw = column.sortAccessor ? column.sortAccessor(left.item) : left.item[column.key];
    const rightRaw = column.sortAccessor ? column.sortAccessor(right.item) : right.item[column.key];

    const leftValue = column.sortableType === "date"
      ? normalizeDateValue(leftRaw)
      : column.sortableType === "text"
        ? normalizeTextValue(leftRaw)
        : normalizeNumberValue(leftRaw);
    const rightValue = column.sortableType === "date"
      ? normalizeDateValue(rightRaw)
      : column.sortableType === "text"
        ? normalizeTextValue(rightRaw)
        : normalizeNumberValue(rightRaw);

    if (leftValue === null && rightValue === null) return left.index - right.index;
    if (leftValue === null) return 1;
    if (rightValue === null) return -1;
    if (leftValue === rightValue) return left.index - right.index;
    if (column.sortableType === "text") {
      return leftValue.localeCompare(rightValue, "fr-FR", { sensitivity: "base" }) * directionFactor;
    }

    return leftValue > rightValue ? directionFactor : -directionFactor;
  });
  return decorated.map((entry) => entry.item);
}

function stripAccents(value) {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

function normalizeFilterText(value) {
  return stripAccents(String(value ?? "").trim()).toLocaleLowerCase("fr-FR");
}

function getColumnFilterType(column) {
  if (column.filterType) return column.filterType;
  if (column.sortableType === "date") return "date";
  if (column.sortableType === "number") return "number";
  return "text";
}

function getColumnValue(column, row) {
  if (column.filterAccessor) return column.filterAccessor(row);
  if (column.sortAccessor) return column.sortAccessor(row);
  return row[column.key];
}

function buildColumnOptions(rows, column) {
  if (Array.isArray(column.filterOptions)) return column.filterOptions;
  const values = new Map();
  rows.forEach((row) => {
    const raw = getColumnValue(column, row);
    if (raw === null || raw === undefined || raw === "") return;
    const key = typeof raw === "boolean" ? String(raw) : String(raw).trim();
    if (!key) return;
    if (!values.has(key)) {
      values.set(key, {
        value: key,
        label: column.optionLabel ? column.optionLabel(raw) : key,
      });
    }
  });
  return Array.from(values.values()).sort((left, right) =>
    normalizeFilterText(left.label).localeCompare(normalizeFilterText(right.label), "fr-FR", { sensitivity: "base" })
  );
}

function isColumnFilterActive(filter, filterType) {
  if (!filter) return false;
  if (filterType === "enum" || filterType === "boolean") return (filter.selected || []).length > 0;
  if (filter.mode === "in") return (filter.selected || []).length > 0;
  if (filterType === "date" && filter.mode === "year") return Boolean(filter.value);
  if (filterType === "date" && ["today", "yesterday", "this_month", "previous_month"].includes(filter.mode)) return true;
  if (filter.mode === "between") return Boolean(filter.value || filter.valueTo);
  return Boolean(filter.value);
}

function countActiveColumnFilters(filters, columns) {
  return columns.reduce((count, column) => (
    isColumnFilterActive(filters[column.key], getColumnFilterType(column)) ? count + 1 : count
  ), 0);
}

function rowMatchesFilter(rawValue, filter, filterType) {
  if (!isColumnFilterActive(filter, filterType)) return true;
  if (filterType === "enum" || filterType === "boolean" || filter.mode === "in") {
    const selected = (filter.selected || []).map((item) => String(item));
    const raw = rawValue === null || rawValue === undefined ? "" : String(rawValue);
    return selected.includes(raw);
  }

  if (filterType === "number") {
    const rawNumber = normalizeNumberValue(rawValue);
    if (rawNumber === null) return false;
    const first = normalizeNumberValue(filter.value);
    const second = normalizeNumberValue(filter.valueTo);
    if (filter.mode === "neq") return first === null ? true : rawNumber !== first;
    if (filter.mode === "gt") return first === null ? true : rawNumber > first;
    if (filter.mode === "gte") return first === null ? true : rawNumber >= first;
    if (filter.mode === "lt") return first === null ? true : rawNumber < first;
    if (filter.mode === "lte") return first === null ? true : rawNumber <= first;
    if (filter.mode === "between") {
      if (first !== null && rawNumber < first) return false;
      if (second !== null && rawNumber > second) return false;
      return first !== null || second !== null;
    }
    return first === null ? true : rawNumber === first;
  }

  if (filterType === "date") {
    const rawDate = normalizeDateValue(rawValue);
    if (rawDate === null) return false;
    const dateValue = new Date(rawDate);
    const now = new Date();
    const currentMonth = now.getMonth();
    const currentYear = now.getFullYear();
    if (filter.mode === "today") {
      return dateValue.toDateString() === now.toDateString();
    }
    if (filter.mode === "yesterday") {
      const yesterday = new Date(now);
      yesterday.setDate(now.getDate() - 1);
      return dateValue.toDateString() === yesterday.toDateString();
    }
    if (filter.mode === "this_month") {
      return dateValue.getMonth() === currentMonth && dateValue.getFullYear() === currentYear;
    }
    if (filter.mode === "previous_month") {
      const ref = new Date(currentYear, currentMonth - 1, 1);
      return dateValue.getMonth() === ref.getMonth() && dateValue.getFullYear() === ref.getFullYear();
    }
    if (filter.mode === "year") {
      return String(dateValue.getFullYear()) === String(filter.value || "");
    }
    if (filter.mode === "before") {
      const beforeValue = normalizeDateValue(filter.value);
      return beforeValue === null ? true : rawDate < beforeValue;
    }
    if (filter.mode === "after") {
      const afterValue = normalizeDateValue(filter.value);
      return afterValue === null ? true : rawDate > afterValue;
    }
    const fromValue = normalizeDateValue(filter.value);
    const toValue = normalizeDateValue(filter.valueTo);
    if (fromValue !== null && rawDate < fromValue) return false;
    if (toValue !== null && rawDate > (toValue + (24 * 60 * 60 * 1000) - 1)) return false;
    return fromValue !== null || toValue !== null;
  }

  const text = normalizeFilterText(rawValue);
  const expected = normalizeFilterText(filter.value);
  if (!expected) return true;
  if (filter.mode === "not_contains") return !text.includes(expected);
  if (filter.mode === "starts_with") return text.startsWith(expected);
  if (filter.mode === "ends_with") return text.endsWith(expected);
  if (filter.mode === "equals") return text === expected;
  if (filter.mode === "not_equals") return text !== expected;
  return text.includes(expected);
}

function filterRows(rows, columns, filters) {
  if (!filters || Object.keys(filters).length === 0) return rows;
  return rows.filter((row) =>
    columns.every((column) => rowMatchesFilter(getColumnValue(column, row), filters[column.key], getColumnFilterType(column)))
  );
}

function getFilterTypeLabel(filterType) {
  if (filterType === "number") return "Filtre numerique";
  if (filterType === "date") return "Filtre date";
  if (filterType === "boolean") return "Filtre booleen";
  if (filterType === "enum") return "Filtre liste";
  return "Filtre texte";
}

function getFilterSummary(filter, filterType) {
  if (!isColumnFilterActive(filter, filterType)) return "Aucun filtre actif";
  if (filterType === "enum" || filterType === "boolean" || filter.mode === "in") {
    return `${(filter.selected || []).length} valeur(s) selectionnee(s)`;
  }
  if (filter.mode === "between") {
    return `${filter.value || "..."} -> ${filter.valueTo || "..."}`;
  }
  if (filterType === "date" && ["today", "yesterday", "this_month", "previous_month"].includes(filter.mode)) {
    return "Periode rapide active";
  }
  return filter.value ? `Condition active: ${filter.value}` : "Filtre actif";
}

function getFocusableElements(container) {
  if (!container) return [];
  return Array.from(
    container.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => !element.hasAttribute("disabled") && element.getAttribute("aria-hidden") !== "true");
}

function TableFilterPopover({
  popupId,
  anchorRect,
  column,
  rows,
  filter,
  sortState,
  onApply,
  onReset,
  onClose,
  onApplySort,
}) {
  const filterType = getColumnFilterType(column);
  const canSort = column.sortableType === "number";
  const options = useMemo(() => buildColumnOptions(rows, column), [rows, column]);
  const defaultFilter = {
    mode: filterType === "number" ? "eq" : filterType === "date" ? "between" : filterType === "enum" || filterType === "boolean" ? "in" : "contains",
    value: "",
    valueTo: "",
    selected: [],
  };
  const [draftFilter, setDraftFilter] = useState(filter || defaultFilter);
  const [position, setPosition] = useState({ top: -9999, left: -9999, width: 320, placement: "bottom", compact: false, ready: false });
  const popoverRef = useRef(null);
  const filterTypeLabel = getFilterTypeLabel(filterType);

  useEffect(() => {
    setDraftFilter(filter || defaultFilter);
  }, [filterType, filter, column.key]);

  useEffect(() => {
    if (!anchorRect) return;
    function updatePlacement() {
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;
      const compact = viewportWidth <= 900 && viewportHeight > viewportWidth;
      const node = popoverRef.current;
      const measuredWidth = node?.offsetWidth || Math.min(Math.max(anchorRect.width + 140, 320), 420);
      const measuredHeight = node?.offsetHeight || (filterType === "enum" || filterType === "boolean" ? 420 : 470);
      if (compact) {
        setPosition({
          top: Math.max(12, viewportHeight - Math.min(measuredHeight, viewportHeight - 24) - 12),
          left: Math.max(12, (viewportWidth - Math.min(measuredWidth, viewportWidth - 24)) / 2),
          width: Math.min(measuredWidth, viewportWidth - 24),
          placement: "sheet",
          compact: true,
          ready: true,
        });
        return;
      }
      const openAbove = viewportHeight - anchorRect.bottom < measuredHeight + 16 && anchorRect.top > measuredHeight + 16;
      let top = openAbove ? anchorRect.top - measuredHeight - 8 : anchorRect.bottom + 8;
      let left = anchorRect.right - measuredWidth;
      top = Math.max(12, Math.min(top, viewportHeight - measuredHeight - 12));
      left = Math.max(12, Math.min(left, viewportWidth - measuredWidth - 12));
      setPosition({
        top,
        left,
        width: measuredWidth,
        placement: openAbove ? "top" : "bottom",
        compact: false,
        ready: true,
      });
    }
    const frame = window.requestAnimationFrame(updatePlacement);
    return () => window.cancelAnimationFrame(frame);
  }, [anchorRect, filterType, options.length, draftFilter.mode]);

  const draftFilterRef = useRef(draftFilter);
  useEffect(() => {
    draftFilterRef.current = draftFilter;
  }, [draftFilter]);

  // Focus initial : uniquement au montage du popover, jamais a chaque frappe.
  useEffect(() => {
    const container = popoverRef.current;
    if (!container) return undefined;
    const focusables = getFocusableElements(container);
    focusables[0]?.focus();
  }, []);

  // Listener clavier : ne se recree que si onApply/onClose changent, jamais sur draftFilter.
  useEffect(() => {
    const container = popoverRef.current;
    if (!container) return undefined;

    function onKeyDown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key === "Enter" && !["TEXTAREA", "BUTTON"].includes(event.target.tagName)) {
        if (event.target.type !== "checkbox") {
          event.preventDefault();
          onApply(draftFilterRef.current);
          onClose();
        }
      }
      if (event.key !== "Tab") return;
      const ordered = getFocusableElements(container);
      if (ordered.length === 0) return;
      const first = ordered[0];
      const last = ordered[ordered.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    container.addEventListener("keydown", onKeyDown);
    return () => container.removeEventListener("keydown", onKeyDown);
  }, [onApply, onClose]);

  function patchDraft(patch) {
    setDraftFilter((current) => ({ ...current, ...patch }));
  }

  function toggleSelectedValue(optionValue) {
    const checked = (draftFilter.selected || []).includes(optionValue);
    patchDraft({
      selected: checked
        ? (draftFilter.selected || []).filter((item) => item !== optionValue)
        : [...(draftFilter.selected || []), optionValue],
    });
  }

  function applyFilter() {
    onApply(draftFilter);
    onClose();
  }

  function cancelFilter() {
    setDraftFilter(filter || defaultFilter);
    onClose();
  }

  function resetAndClose() {
    onReset();
    onClose();
  }

  if (!anchorRect) return null;

  const invalidBetween = draftFilter.mode === "between"
    && filterType !== "enum"
    && filterType !== "boolean"
    && !draftFilter.value
    && !draftFilter.valueTo;
  const noOptionList = (filterType === "enum" || filterType === "boolean" || draftFilter.mode === "in") && options.length === 0;
  const activeSummary = getFilterSummary(filter, filterType);

  return createPortal(
    <div
      ref={popoverRef}
      data-filter-popover={popupId}
      className={`column-filter-popover portal-${position.placement}${position.compact ? " compact-sheet" : ""}${position.ready ? " ready" : ""}`}
      style={{ top: `${position.top}px`, left: `${position.left}px`, width: `${position.width}px` }}
      role="dialog"
      aria-modal="false"
      aria-label={`Filtre avance pour ${column.label}`}
    >
      <div className="column-filter-header">
        <div>
          <div className="column-filter-title">{column.label}</div>
          <div className="column-filter-type">{filterTypeLabel}</div>
        </div>
        <button type="button" className="icon-button" onClick={cancelFilter} aria-label="Fermer le filtre">
          <X size={14} />
        </button>
      </div>

      {canSort && (
        <div className="column-filter-block">
          <div className="column-filter-label">Tri</div>
          <div className="column-filter-sort-actions">
            <button
              type="button"
              className={sortState?.key === column.key && sortState?.direction === "asc" ? "filter-chip active" : "filter-chip"}
              onClick={() => onApplySort(column.key, "asc")}
            >
              Trier du plus petit au plus grand
            </button>
            <button
              type="button"
              className={sortState?.key === column.key && sortState?.direction === "desc" ? "filter-chip active" : "filter-chip"}
              onClick={() => onApplySort(column.key, "desc")}
            >
              Trier du plus grand au plus petit
            </button>
            <button
              type="button"
              className={sortState?.key === column.key ? "filter-chip active" : "filter-chip"}
              onClick={() => onApplySort(column.key, null)}
            >
              Effacer le tri
            </button>
          </div>
        </div>
      )}

      <div className="column-filter-block column-filter-body">
        <div className="column-filter-summary">
          {activeSummary}
        </div>
        {filterType !== "enum" && filterType !== "boolean" && (
          <label className="column-filter-field">
            <span className="column-filter-label">Condition</span>
            <select
              value={draftFilter.mode}
              onChange={(event) => patchDraft({ mode: event.target.value, selected: [] })}
            >
              {filterType === "text" && (
                <>
                  <option value="contains">Contient</option>
                  <option value="not_contains">Ne contient pas</option>
                  <option value="starts_with">Commence par</option>
                  <option value="ends_with">Finit par</option>
                  <option value="equals">Egal a</option>
                  <option value="not_equals">Different de</option>
                  <option value="in">Liste de valeurs</option>
                </>
              )}
              {filterType === "number" && (
                <>
                  <option value="eq">Egal a</option>
                  <option value="neq">Different de</option>
                  <option value="gt">Superieur a</option>
                  <option value="gte">Superieur ou egal a</option>
                  <option value="lt">Inferieur a</option>
                  <option value="lte">Inferieur ou egal a</option>
                  <option value="between">Compris entre</option>
                  <option value="in">Liste de valeurs</option>
                </>
              )}
              {filterType === "date" && (
                <>
                  <option value="today">Aujourd&apos;hui</option>
                  <option value="yesterday">Hier</option>
                  <option value="this_month">Ce mois</option>
                  <option value="previous_month">Mois precedent</option>
                  <option value="year">Annee</option>
                  <option value="before">Avant</option>
                  <option value="after">Apres</option>
                  <option value="between">Entre deux dates</option>
                </>
              )}
            </select>
          </label>
        )}

        {filterType === "enum" || filterType === "boolean" || draftFilter.mode === "in" ? (
          <div className="column-filter-options">
            {options.map((option) => {
              const checked = (draftFilter.selected || []).includes(option.value);
              return (
                <label key={option.value} className="column-filter-option">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleSelectedValue(option.value)}
                  />
                  <span>{option.label}</span>
                </label>
              );
            })}
            {noOptionList && (
              <div className="column-filter-empty">Aucune valeur disponible pour cette colonne.</div>
            )}
          </div>
        ) : draftFilter.mode === "between" ? (
          <div className="column-filter-range">
            <input
              type={filterType === "date" ? "date" : "number"}
              step={filterType === "number" ? "any" : undefined}
              value={draftFilter.value || ""}
              onChange={(event) => patchDraft({ value: event.target.value })}
              placeholder={filterType === "date" ? "Date debut" : "Valeur min"}
            />
            <input
              type={filterType === "date" ? "date" : "number"}
              step={filterType === "number" ? "any" : undefined}
              value={draftFilter.valueTo || ""}
              onChange={(event) => patchDraft({ valueTo: event.target.value })}
              placeholder={filterType === "date" ? "Date fin" : "Valeur max"}
            />
          </div>
        ) : draftFilter.mode === "year" ? (
          <input
            type="number"
            min="2000"
            max="2100"
            value={draftFilter.value || ""}
            onChange={(event) => patchDraft({ value: event.target.value })}
            placeholder="Annee"
          />
        ) : ["today", "yesterday", "this_month", "previous_month"].includes(draftFilter.mode) ? null : (
          <input
            type={filterType === "number" ? "number" : filterType === "date" ? "date" : "text"}
            step={filterType === "number" ? "any" : undefined}
            value={draftFilter.value || ""}
            onChange={(event) => patchDraft({ value: event.target.value })}
            placeholder="Valeur"
          />
        )}
        {invalidBetween && (
          <div className="column-filter-error">Veuillez saisir au moins une borne pour ce filtre.</div>
        )}
      </div>

      <div className="column-filter-actions">
        <button type="button" className="primary fit" onClick={applyFilter} disabled={invalidBetween}>Appliquer</button>
        <button type="button" className="icon-button" onClick={resetAndClose}>Effacer</button>
        <button type="button" className="icon-button" onClick={cancelFilter}>Annuler</button>
      </div>
    </div>,
    document.body,
  );
}

function SortableHeader({
  label,
  columnKey,
  sortState,
  onToggle,
  rows = [],
  column = null,
  filterState = null,
  onFilterChange = null,
  onFilterReset = null,
}) {
  const [filterOpen, setFilterOpen] = useState(false);
  const rootRef = useRef(null);
  const popupId = useId();
  const filterType = column ? getColumnFilterType(column) : null;
  const filterActive = column ? isColumnFilterActive(filterState, filterType) : false;
  const [anchorRect, setAnchorRect] = useState(null);
  const canFilter = Boolean(column && onFilterChange && onFilterReset && column.key !== "actions" && column.filterable !== false);

  useEffect(() => {
    function handleExternalOpen(event) {
      if (event.detail?.popupId !== popupId) {
        setFilterOpen(false);
      }
    }
    window.addEventListener(TABLE_FILTER_OPENED_EVENT, handleExternalOpen);
    return () => window.removeEventListener(TABLE_FILTER_OPENED_EVENT, handleExternalOpen);
  }, [popupId]);

  useEffect(() => {
    if (!filterOpen) return undefined;
    function updatePosition() {
      const rect = rootRef.current?.getBoundingClientRect();
      if (!rect || rect.width === 0 || rect.height === 0) {
        setFilterOpen(false);
        return;
      }
      setAnchorRect({
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
        left: rect.left,
        width: rect.width,
        height: rect.height,
      });
    }
    function closeOnOutside(event) {
      const popover = document.querySelector(`[data-filter-popover="${popupId}"]`);
      if (!rootRef.current?.contains(event.target) && !popover?.contains(event.target)) {
        setFilterOpen(false);
      }
    }
    updatePosition();
    document.addEventListener("mousedown", closeOnOutside);
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      document.removeEventListener("mousedown", closeOnOutside);
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [filterOpen, popupId]);

  function openFilter() {
    if (!canFilter) return;
    const rect = rootRef.current?.getBoundingClientRect();
    if (!rect) return;
    setAnchorRect({
      top: rect.top,
      right: rect.right,
      bottom: rect.bottom,
      left: rect.left,
      width: rect.width,
      height: rect.height,
    });
    window.dispatchEvent(new CustomEvent(TABLE_FILTER_OPENED_EVENT, { detail: { popupId } }));
    setFilterOpen(true);
  }

  return (
    <th className="sortable-th" ref={rootRef}>
      <div className="th-actions">
        <span className="header-label">{label}</span>
        {canFilter && (
          <button
            type="button"
            className={filterActive ? "filter-button active" : "filter-button"}
            aria-label={`Filtrer ${label}`}
            onClick={() => {
              if (filterOpen) {
                setFilterOpen(false);
                return;
              }
              openFilter();
            }}
          >
            <Filter size={14} />
          </button>
        )}
      </div>
      {filterOpen && canFilter && (
        <TableFilterPopover
          popupId={popupId}
          anchorRect={anchorRect}
          column={column}
          rows={rows}
          filter={filterState}
          sortState={sortState}
          onApply={onFilterChange}
          onReset={() => {
            onFilterReset();
          }}
          onClose={() => setFilterOpen(false)}
          onApplySort={onToggle}
        />
      )}
    </th>
  );
}

function determineChartMode(filters) {
  if (filters?.agent_id) return CHART_MODES.AGENT_MONTHLY_TREND;
  if (filters?.agency_id) return CHART_MODES.AGENCY_MONTHLY_TREND;
  return CHART_MODES.GLOBAL_BY_AGENCY;
}

function applyRoleScopeToFilters(user, baseFilters) {
  if (!user) return { ...baseFilters };
  const scoped = { ...baseFilters };
  if (user.role === "agency_manager" && user.agency_id) {
    scoped.agency_id = String(user.agency_id);
  }
  if (user.role === "portfolio_manager") {
    // Keep GP metrics multi-agency: do not hard-lock agency filter for this role.
    scoped.agency_id = "";
    if (user.agent_id) scoped.agent_id = String(user.agent_id);
  }
  return scoped;
}

function canAccessTargets(user) {
  return (
    user?.role === "super_admin"
    || user?.role === "agency_manager"
    || user?.role === "portfolio_manager"
  );
}

function canAccessParReduction(user) {
  return ["super_admin", "admin", "agency_manager", "portfolio_manager"].includes(user?.role);
}

function canManageParReductionTargets(user) {
  return user?.role === "admin" || user?.role === "super_admin";
}

function canAccessTaeg(user) {
  return user?.role === "super_admin" || user?.role === "admin" || user?.role === "committee_member"|| user?.role === "agency_manager";
}

function canAccessConfiguration(user) {
  return user?.role === "super_admin";
}

function canAccessImport(user) {
  return user?.role === "super_admin" || user?.role === "support";
}

function canAccessUsers(user) {
  return user?.role === "super_admin" || user?.role === "support";
}

function displayRoleLabel(role) {
  if (role === "super_admin") return "Super Admin";
  if (role === "admin") return "Admin";
  if (role === "support") return "Support";
  if (role === "committee_member") return "Membre comité";
  if (role === "agency_manager") return "Chef d'agence";
  if (role === "portfolio_manager") return "Portfolio Manager";
  return role || "";
}

function defaultModuleForUser(user) {
  return user?.role === "support" ? "import" : "dashboard";
}

function useCompactViewport(maxWidth = 1024) {
  const getValue = () => {
    if (typeof window === "undefined") return false;
    return window.innerWidth <= maxWidth;
  };
  const [isCompact, setIsCompact] = useState(getValue);

  useEffect(() => {
    function onResize() {
      setIsCompact(getValue());
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [maxWidth]);

  return isCompact;
}

function selectedName(items, id, fallback) {
  const selectedIds = String(id || "")
    .split(",")
    .map((token) => token.trim())
    .filter(Boolean);
  if (selectedIds.length === 0) return fallback;
  const names = selectedIds
    .map((selectedId) => items.find((item) => String(item.id) === String(selectedId))?.name)
    .filter(Boolean);
  if (names.length === 0) return fallback;
  return names.join(" + ");
}

function selectedIds(value) {
  return String(value || "")
    .split(",")
    .map((token) => token.trim())
    .filter(Boolean);
}

function joinSelectedIds(values) {
  return Array.from(new Set((values || []).map((value) => String(value).trim()).filter(Boolean))).join(",");
}

function formatMonthLabel(label) {
  if (typeof label !== "string") return String(label || "");
  const match = label.match(/^(\d{4})-(\d{2})$/);
  if (!match) return label;
  return `${match[2]}/${match[1]}`;
}

function formatLongMonthLabel(value) {
  if (!value) return "";
  const parsed = new Date(`${String(value).slice(0, 10)}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return formatDateLabel(value);
  const label = parsed.toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function formatShortMonthOnlyLabel(value) {
  if (!value) return "";
  const parsed = new Date(`${String(value).slice(0, 10)}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return formatDateLabel(value);
  const label = parsed.toLocaleDateString("fr-FR", { month: "long" });
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function monthKeyFromDate(value) {
  if (!value) return "";
  return String(value).slice(0, 7);
}

function monthBoundsFromKey(monthKey) {
  const match = String(monthKey || "").match(/^(\d{4})-(\d{2})$/);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  if (!Number.isFinite(year) || !Number.isFinite(month) || month < 1 || month > 12) return null;
  const lastDay = new Date(year, month, 0).getDate();
  return {
    start: `${match[1]}-${match[2]}-01`,
    end: `${match[1]}-${match[2]}-${String(lastDay).padStart(2, "0")}`,
  };
}

function formatDateLabel(value) {
  if (!value) return "";
  if (typeof value === "string") {
    const isoMatch = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (isoMatch) return `${isoMatch[3]}/${isoMatch[2]}/${isoMatch[1]}`;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleDateString("fr-FR");
}

function formatTimeLabel(value) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

function formatDateTimeLabel(value) {
  const dateLabel = formatDateLabel(value);
  const timeLabel = formatTimeLabel(value);
  if (dateLabel && timeLabel) return `${dateLabel} ${timeLabel}`;
  return dateLabel || timeLabel || "";
}

function formatCurrentStateDateLabel(snapshotDate) {
  return formatDateLabel(snapshotDate) || "Etat actuel";
}

function formatAcmPeriodLabel(startDate, endDate) {
  const startLabel = formatDateLabel(startDate);
  const endLabel = formatDateLabel(endDate);
  if (startLabel && endLabel) return `${startLabel} -> ${endLabel}`;
  if (startLabel) return `${startLabel} -> Jusqu'a modification`;
  return "Periode non renseignee";
}

function formatFilteredPeriodLabel(dateFrom, dateTo) {
  const fromLabel = formatDateLabel(dateFrom);
  const toLabel = formatDateLabel(dateTo);
  if (fromLabel && toLabel) return `Periode filtree : ${fromLabel} -> ${toLabel}`;
  if (fromLabel) return `Periode filtree : depuis ${fromLabel}`;
  if (toLabel) return `Periode filtree : jusqu'au ${toLabel}`;
  return "Periode filtree : aucune";
}

function inferNoticeTone(message, requestedTone) {
  if (requestedTone) return requestedTone;
  const text = String(message || "")
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
  if (!text) return "info";
  const errorMarkers = [
    "aucune ",
    "choisir ",
    "saisir ",
    "format ",
    "la periode",
    "la date",
    "selectionnez ",
    "impossible",
    "echec",
    "erreur",
    "invalid",
    "unauthorized",
    "forbidden",
    "failed",
    "votre profil",
    "vous ne pouvez",
    "super admin:",
    "chef d'agence:",
    "un objectif existe",
    "le nouveau mot de passe",
  ];
  return errorMarkers.some((marker) => text.includes(marker)) ? "error" : "info";
}

function formatTrendPeriodLabel(label, currentStateSnapshotDate) {
  if (label === "CURRENT") return formatCurrentStateDateLabel(currentStateSnapshotDate);
  return formatMonthLabel(label);
}

function mapChartPoints(pack, mode, activeSnapshotDate) {
  return (pack?.points || []).map((point) => ({
    name:
      mode === CHART_MODES.GLOBAL_BY_AGENCY
        ? point.label
        : formatTrendPeriodLabel(point.label, activeSnapshotDate),
    disbursementCount: Number(point.disbursement_count || 0),
    disbursement: Number(point.disbursement_volume || 0),
    microDisbursement: Number(point.micro_disbursement_volume || 0),
    microDisbursementCount: Number(point.micro_disbursement_count || 0),
    tpmeDisbursement: Number(point.tpme_disbursement_volume || 0),
    tpmeDisbursementCount: Number(point.tpme_disbursement_count || 0),
    afariDisbursement: Number(point.afari_disbursement_volume || 0),
    afariDisbursementCount: Number(point.afari_disbursement_count || 0),
    healthyRate: Number(point.healthy_rate || 0) * 100,
    par0Rate: Number(point.par_0_rate || 0) * 100,
    par1_30Rate: Number(point.par_1_30_rate || 0) * 100,
    par1_15Rate: Number(point.par_1_15_rate || 0) * 100,
    par16_30Rate: Number(point.par_16_30_rate || 0) * 100,
    par31_60Rate: Number(point.par_31_60_rate || 0) * 100,
    par61_90Rate: Number(point.par_61_90_rate || 0) * 100,
    par91_120Rate: Number(point.par_91_120_rate || 0) * 100,
    par120Rate: Number(point.par_120_rate || 0) * 100,
    par30Rate: Number(point.par_30_rate || 0) * 100,
  }));
}

function buildChartTitles(mode, agencyName, agentName) {
  const agencyLabel = agencyName.includes(" + ") ? "Agences" : "Agence";
  if (mode === CHART_MODES.GLOBAL_QUALITY_TREND) {
    return {
      qualityTitle: "Repartition du portefeuille a risque MicroCred",
      volumeTitle: "Evolution volume decaisse MicroCred",
    };
  }
  if (mode === CHART_MODES.AGENT_MONTHLY_TREND) {
    return {
      qualityTitle: `Evolution qualite portefeuille - Agent ${agentName}`,
      volumeTitle: `Evolution volume decaisse - Agent ${agentName}`,
    };
  }
  if (mode === CHART_MODES.AGENCY_MONTHLY_TREND) {
    return {
      qualityTitle: `Evolution qualite portefeuille - ${agencyLabel} ${agencyName}`,
      volumeTitle: `Evolution volume decaisse - ${agencyLabel} ${agencyName}`,
    };
  }
  return {
    qualityTitle: "Qualite portefeuille par agence",
    volumeTitle: "Volume decaisse par agence",
  };
}

function passwordPolicyChecks(password) {
  return [
    { label: "Minimum 12 caracteres", valid: password.length >= 12 },
    { label: "Une majuscule et une minuscule", valid: /[A-Z]/.test(password) && /[a-z]/.test(password) },
    { label: "Au moins un chiffre", valid: /\d/.test(password) },
    { label: "Au moins un caractere special", valid: /[^A-Za-z0-9]/.test(password) },
  ];
}

function Login({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function submit(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    try {
      await api.login(email, password);
      onLogin();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-panel">
        <div>
          <p className="eyebrow">MicroCred</p>
          <h1>Performance Command Center</h1>
          <p className="muted">Snapshots journaliers, KPI, objectifs et bonus.</p>
        </div>
        <form onSubmit={submit} className="form-stack">
          <div>
            <h2>Connexion</h2>
            <p className="muted">
              Utilisez votre email et le mot de passe transmis par le Super Admin. Si c'est votre premiere connexion,
              l'application demandera immediatement un nouveau mot de passe.
            </p>
          </div>
          <label>Email<input value={email} onChange={(e) => setEmail(e.target.value)} /></label>
          <label>Mot de passe<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
          {notice && <p className="notice">{notice}</p>}
          {error && <p className="error">{error}</p>}
          <button className="primary">Connexion</button>
        </form>
      </section>
    </main>
  );
}

function ForcePasswordChangeModal({ user, onChanged, onLogout }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const checks = passwordPolicyChecks(newPassword);
  const policyValid = checks.every((item) => item.valid);
  const confirmationValid = Boolean(newPassword) && newPassword === confirmation;

  async function submit(event) {
    event.preventDefault();
    setError("");
    if (!policyValid) {
      setError("Le nouveau mot de passe ne respecte pas tous les criteres.");
      return;
    }
    if (!confirmationValid) {
      setError("La confirmation du nouveau mot de passe ne correspond pas.");
      return;
    }
    setSubmitting(true);
    try {
      const updatedUser = await api.changePassword(currentPassword, newPassword);
      onChanged(updatedUser);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="password-change-backdrop" role="presentation">
      <section
        className="password-change-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="password-change-title"
      >
        <div>
          <p className="eyebrow">Securite du compte</p>
          <h2 id="password-change-title">Modification obligatoire du mot de passe</h2>
          <p className="muted">
            Bonjour {user?.full_name}. Choisissez un nouveau mot de passe avant de continuer.
          </p>
        </div>
        <form className="password-change-form" onSubmit={submit}>
          <label>
            Mot de passe actuel
            <input
              autoComplete="current-password"
              type="password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              required
            />
          </label>
          <label>
            Nouveau mot de passe
            <input
              autoComplete="new-password"
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              required
            />
          </label>
          <label>
            Confirmer le nouveau mot de passe
            <input
              autoComplete="new-password"
              type="password"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              required
            />
          </label>
          <ul className="password-policy" aria-label="Politique du mot de passe">
            {checks.map((item) => (
              <li className={item.valid ? "valid" : ""} key={item.label}>
                {item.valid ? "OK" : "-"} {item.label}
              </li>
            ))}
          </ul>
          {error && <p className="form-error">{error}</p>}
          <div className="password-change-actions">
            <button className="ghost-button" type="button" onClick={onLogout}>
              <LogOut size={16} />
              Deconnexion
            </button>
            <button className="primary" disabled={submitting || !policyValid || !confirmationValid}>
              <Save size={16} />
              {submitting ? "Enregistrement..." : "Enregistrer"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

function Dashboard() {
  const isCompactViewport = useCompactViewport(1024);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [user, setUser] = useState(null);
  const [active, setActive] = useState("dashboard");
  const [metrics, setMetrics] = useState([]);
  const [metricsTotal, setMetricsTotal] = useState(0);
  const [credits, setCredits] = useState([]);
  const [creditsTotal, setCreditsTotal] = useState(0);
  const [summary, setSummary] = useState(null);
  const [chartPack, setChartPack] = useState({ mode: CHART_MODES.GLOBAL_BY_AGENCY, points: [] });
  const [volumeChartPack, setVolumeChartPack] = useState({ mode: CHART_MODES.GLOBAL_BY_AGENCY, points: [] });
  const [qualityScope, setQualityScope] = useState("agency");
  const [volumeScope, setVolumeScope] = useState("agency");
  const [agencies, setAgencies] = useState([]);
  const [agents, setAgents] = useState([]);
  const [sectors, setSectors] = useState([]);
  const [users, setUsers] = useState([]);
  const [formulaHelp, setFormulaHelp] = useState({ metrics: [], operators: [], functions: [] });
  const [featureFlags, setFeatureFlags] = useState(DEFAULT_FEATURE_FLAGS);
  const [acmLimits, setAcmLimits] = useState(null);
  const [filters, setFilters] = useState({ limit: 20, offset: 0, snapshot_batch_ids: "", q: "", sector_ids: "" });
  const [committeeClosedMonths, setCommitteeClosedMonths] = useState([]);
  const [committeeClosedMonthsLoading, setCommitteeClosedMonthsLoading] = useState(false);
  const [committeeClosedMonthsStatus, setCommitteeClosedMonthsStatus] = useState("idle");
  const [committeeMonthKey, setCommitteeMonthKey] = useState(() => {
    if (typeof window === "undefined") return "";
    return window.localStorage.getItem(COMMITTEE_MONTH_STORAGE_KEY) || "";
  });
  const [snapshotOptions, setSnapshotOptions] = useState([]);
  const [activeSnapshot, setActiveSnapshot] = useState(null);
  const [portfolioPerf, setPortfolioPerf] = useState(null);
  const [notice, setNotice] = useState("");
  const [noticeTone, setNoticeTone] = useState("info");
  const [noticeLeaving, setNoticeLeaving] = useState(false);
  const noticeFadeTimerRef = useRef(null);
  const noticeClearTimerRef = useRef(null);

  function clearNoticeTimers() {
    if (noticeFadeTimerRef.current) {
      clearTimeout(noticeFadeTimerRef.current);
      noticeFadeTimerRef.current = null;
    }
    if (noticeClearTimerRef.current) {
      clearTimeout(noticeClearTimerRef.current);
      noticeClearTimerRef.current = null;
    }
  }

  function showNotice(message, options = {}) {
    const autoHideMs = Number(options.autoHideMs || 0);
    clearNoticeTimers();
    setNoticeLeaving(false);
    setNoticeTone(inferNoticeTone(message, options.tone));
    setNotice(message || "");
    if (!message || autoHideMs <= 0) return;
    const fadeMs = 320;
    const fadeStartMs = Math.max(autoHideMs - fadeMs, 0);
    noticeFadeTimerRef.current = setTimeout(() => setNoticeLeaving(true), fadeStartMs);
    noticeClearTimerRef.current = setTimeout(() => {
      setNotice("");
      setNoticeTone("info");
      setNoticeLeaving(false);
      clearNoticeTimers();
    }, autoHideMs);
  }

  async function loadBase() {
    const me = await api.me();
    const isCommitteeMember = me.role === "committee_member";
    setUser(me);
    setActive((current) => {
      if (me.role === "support") {
        return current === "import" || current === "users" ? current : "import";
      }
      return current;
    });
    if (me.must_change_password) return;
    if (me.role === "support") {
      const usersPage = await api.users();
      setUsers(usersPage.items || []);
      setMetrics([]);
      setMetricsTotal(0);
      setCredits([]);
      setCreditsTotal(0);
      setSummary(null);
      setChartPack({ mode: CHART_MODES.GLOBAL_BY_AGENCY, points: [] });
      setVolumeChartPack({ mode: CHART_MODES.GLOBAL_BY_AGENCY, points: [] });
      setAgencies([]);
      setAgents([]);
      setSnapshotOptions([]);
      setActiveSnapshot(null);
      setPortfolioPerf(null);
      setFormulaHelp({ metrics: [], operators: [], functions: [] });
      setFeatureFlags(DEFAULT_FEATURE_FLAGS);
      setAcmLimits(null);
      setCommitteeClosedMonths([]);
      setCommitteeClosedMonthsLoading(false);
      setCommitteeClosedMonthsStatus("idle");
      return;
    }
    const scopedFilters = applyRoleScopeToFilters(me, filters);
    let effectiveFilters = scopedFilters;
    if (JSON.stringify(scopedFilters) !== JSON.stringify(filters)) {
      setFilters(scopedFilters);
    }
    if (isCommitteeMember) setCommitteeClosedMonthsLoading(true);
    try {
      if (isCommitteeMember) {
        setCommitteeClosedMonthsStatus("loading");
        try {
          const closedMonthsData = await api.closedMonths();
          const resolvedClosedMonths = Array.isArray(closedMonthsData) ? closedMonthsData : [];
          setCommitteeClosedMonths(resolvedClosedMonths);

          if (!resolvedClosedMonths.length) {
            setCommitteeMonthKey("");
            setCommitteeClosedMonthsStatus("empty");
            setMetrics([]);
            setMetricsTotal(0);
            setCredits([]);
            setCreditsTotal(0);
            setSummary(null);
            setChartPack({ mode: CHART_MODES.GLOBAL_BY_AGENCY, points: [] });
            setVolumeChartPack({ mode: CHART_MODES.GLOBAL_BY_AGENCY, points: [] });
            setAgencies([]);
            setAgents([]);
            setSnapshotOptions([]);
            setActiveSnapshot(null);
            setPortfolioPerf(null);
            setFeatureFlags(DEFAULT_FEATURE_FLAGS);
            setAcmLimits(null);
            return;
          }

          const allowedKeys = new Set(resolvedClosedMonths.map((item) => item.key));
          const resolvedMonthKey = allowedKeys.has(committeeMonthKey)
            ? committeeMonthKey
            : resolvedClosedMonths[0]?.key || "";
          if (resolvedMonthKey !== committeeMonthKey) {
            setCommitteeMonthKey(resolvedMonthKey);
          }
          const bounds = monthBoundsFromKey(resolvedMonthKey);
          if (bounds) {
            effectiveFilters = {
              ...scopedFilters,
              date_from: bounds.start,
              date_to: bounds.end,
              snapshot_batch_ids: "",
              offset: 0,
            };
            if (JSON.stringify(effectiveFilters) !== JSON.stringify(filters)) {
              setFilters((prev) => ({
                ...prev,
                ...effectiveFilters,
              }));
            }
          }
          setCommitteeClosedMonthsStatus("ready");
        } catch (err) {
          setCommitteeClosedMonths([]);
          setCommitteeMonthKey("");
          setCommitteeClosedMonthsStatus(err?.status === 403 ? "forbidden" : "error");
          setMetrics([]);
          setMetricsTotal(0);
          setCredits([]);
          setCreditsTotal(0);
          setSummary(null);
          setChartPack({ mode: CHART_MODES.GLOBAL_BY_AGENCY, points: [] });
          setVolumeChartPack({ mode: CHART_MODES.GLOBAL_BY_AGENCY, points: [] });
          setAgencies([]);
          setAgents([]);
          setSnapshotOptions([]);
          setActiveSnapshot(null);
          setPortfolioPerf(null);
          setFeatureFlags(DEFAULT_FEATURE_FLAGS);
          setAcmLimits(null);
          return;
        }
      } else {
        setCommitteeClosedMonths([]);
        setCommitteeClosedMonthsStatus("idle");
      }

      const effectiveQualityScope = me.role === "portfolio_manager" ? "agency" : (qualityScope === "region_nord" || qualityScope === "region_sud") ? "agency" : qualityScope;
      const chartFilters = clean({
        agency_id: effectiveFilters.agency_id,
        agent_id: effectiveFilters.agent_id,
        date_from: effectiveFilters.date_from,
        date_to: effectiveFilters.date_to,
        snapshot_batch_ids: effectiveFilters.snapshot_batch_ids || undefined,
        months: 6,
        quality_scope: effectiveQualityScope,
      });
      const [metricPage, creditPage, summaryData, chartsData, activeSnapshotData, featuresData, acmLimitsData] = await Promise.all([
        api.metrics(clean(effectiveFilters)),
        api.currentCredits(clean(effectiveFilters)),
        api.metricsSummary(clean(effectiveFilters)),
        api.metricsCharts(chartFilters),
        isCommitteeMember
          ? Promise.resolve({ snapshot_date: null, label: null })
          : api.activeSnapshot().catch(() => ({ snapshot_date: null, label: null })),
        api.features().catch(() => DEFAULT_FEATURE_FLAGS),
        api.acmLimits().catch(() => null),
      ]);
      setMetrics(metricPage.items);
      setMetricsTotal(metricPage.total);
      setCredits(creditPage.items);
      setCreditsTotal(creditPage.total);
      setSummary(summaryData);
      setChartPack(chartsData);
      setVolumeChartPack(chartsData);
      setActiveSnapshot(activeSnapshotData);
      setFeatureFlags(featuresData || DEFAULT_FEATURE_FLAGS);
      setAcmLimits(acmLimitsData || null);
      if (isCommitteeMember) {
        setAgencies([]);
        setAgents([]);
        setSnapshotOptions([]);
      } else {
        const agencyPage = await api.agencies();
        setAgencies(agencyPage.items);
        const agentPage = await api.agents(effectiveFilters.agency_id);
        setAgents(agentPage.items);
        api.sectors().then(setSectors).catch(() => setSectors([]));
        api.snapshots(clean({ agency_id: effectiveFilters.agency_id, agent_id: effectiveFilters.agent_id }))
          .then(setSnapshotOptions)
          .catch(() => setSnapshotOptions([]));
      }
      if (me.role === "super_admin") {
        api.users().then((page) => setUsers(page.items)).catch(() => {});
      }
      if (me.role === "portfolio_manager") {
        api.portfolioPerformance().then(setPortfolioPerf).catch(() => setPortfolioPerf(null));
      } else {
        setPortfolioPerf(null);
      }
      if (me.role === "super_admin" && (featuresData?.bonus_module_active ?? false)) {
        api.formulaHelp().then(setFormulaHelp).catch(() => {});
      } else {
        setFormulaHelp({ metrics: [], operators: [], functions: [] });
      }
    } finally {
      if (isCommitteeMember) setCommitteeClosedMonthsLoading(false);
    }
  }

  function dismissNotice() {
    clearNoticeTimers();
    setNoticeLeaving(false);
    setNoticeTone("info");
    setNotice("");
  }

  useEffect(() => {
    loadBase().catch((err) => showNotice(err.message));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!committeeMonthKey) {
      window.localStorage.removeItem(COMMITTEE_MONTH_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(COMMITTEE_MONTH_STORAGE_KEY, committeeMonthKey);
  }, [committeeMonthKey]);

  useEffect(() => {
    if (!user || user.role !== "committee_member") return;
    if (!committeeClosedMonths.length) return;

    const allowedKeys = new Set(committeeClosedMonths.map((item) => item.key));
    const resolvedMonthKey = allowedKeys.has(committeeMonthKey)
      ? committeeMonthKey
      : committeeClosedMonths[0]?.key || "";

    if (resolvedMonthKey && resolvedMonthKey !== committeeMonthKey) {
      setCommitteeMonthKey(resolvedMonthKey);
      return;
    }

    const bounds = monthBoundsFromKey(resolvedMonthKey);
    if (!bounds) return;
    if (
      filters.date_from !== bounds.start
      || filters.date_to !== bounds.end
      || String(filters.snapshot_batch_ids || "").trim() !== ""
    ) {
      setFilters((prev) => ({
        ...prev,
        date_from: bounds.start,
        date_to: bounds.end,
        snapshot_batch_ids: "",
        offset: 0,
      }));
    }
  }, [committeeClosedMonths, committeeMonthKey, filters.date_from, filters.date_to, filters.snapshot_batch_ids, user]);

  useEffect(() => {
    if (!user || user.must_change_password) return;
    if (user.role === "support") return;
    const isCommitteeMember = user.role === "committee_member";
    if (isCommitteeMember && committeeClosedMonthsStatus !== "ready") {
      setAgents([]);
      setSnapshotOptions([]);
      return;
    }
    const scopedFilters = applyRoleScopeToFilters(user, filters);
    if (JSON.stringify(scopedFilters) !== JSON.stringify(filters)) {
      setFilters(scopedFilters);
      return;
    }
    api.metrics(clean(scopedFilters)).then((page) => {
      setMetrics(page.items);
      setMetricsTotal(page.total);
    }).catch((err) => {
      setMetrics([]);
      setMetricsTotal(0);
      showNotice(err.message);
    });
    api.currentCredits(clean(scopedFilters)).then((page) => {
      setCredits(page.items);
      setCreditsTotal(page.total);
    }).catch(() => {
      setCredits([]);
      setCreditsTotal(0);
    });
    api.metricsSummary(clean(scopedFilters)).then(setSummary).catch(() => setSummary(null));
    const effectiveQualityScope = user.role === "portfolio_manager" ? "agency" : (qualityScope === "region_nord" || qualityScope === "region_sud") ? "agency" : qualityScope;
    api.metricsCharts(clean({
      agency_id: scopedFilters.agency_id,
      agent_id: scopedFilters.agent_id,
      sector_ids: scopedFilters.sector_ids,
      date_from: scopedFilters.date_from,
      date_to: scopedFilters.date_to,
      snapshot_batch_ids: scopedFilters.snapshot_batch_ids || undefined,
      months: 6,
      quality_scope: effectiveQualityScope,
    }))
      .then(setChartPack)
      .catch(() => setChartPack({ mode: effectiveQualityScope === "global" ? CHART_MODES.GLOBAL_QUALITY_TREND : determineChartMode(scopedFilters), points: [] }));
    const effectiveVolumeScope = user.role === "super_admin" ? volumeScope : "agency";
    api.metricsCharts(clean({
      agency_id: scopedFilters.agency_id,
      agent_id: scopedFilters.agent_id,
      sector_ids: scopedFilters.sector_ids,
      date_from: scopedFilters.date_from,
      date_to: scopedFilters.date_to,
      snapshot_batch_ids: scopedFilters.snapshot_batch_ids || undefined,
      months: 6,
      quality_scope: effectiveVolumeScope,
    }))
      .then(setVolumeChartPack)
      .catch(() => setVolumeChartPack({ mode: effectiveVolumeScope === "global" ? CHART_MODES.GLOBAL_QUALITY_TREND : determineChartMode(scopedFilters), points: [] }));
    if (isCommitteeMember) {
      setAgents([]);
      setSnapshotOptions([]);
    } else {
      api.agents(scopedFilters.agency_id).then((page) => setAgents(page.items)).catch(() => {});
      api.snapshots(clean({ agency_id: scopedFilters.agency_id, agent_id: scopedFilters.agent_id }))
        .then(setSnapshotOptions)
        .catch(() => setSnapshotOptions([]));
    }
    if (user.role === "portfolio_manager") {
      api.portfolioPerformance().then(setPortfolioPerf).catch(() => setPortfolioPerf(null));
    }
  }, [
    user,
    filters.agency_id,
    filters.agent_id,
    filters.sector_ids,
    filters.snapshot_batch_ids,
    filters.date_from,
    filters.date_to,
    filters.q,
    filters.risk_categories,
    filters.offset,
    filters.limit,
    qualityScope,
    volumeScope,
    committeeClosedMonthsStatus,
  ]);

  useEffect(() => {
    if (!user) return;
    const unauthorized =
      (active === "dashboard" && user.role === "support")
      || (active === "restructured" && user.role === "support")
      || 
      (active === "targets" && !canAccessTargets(user))
      || (active === "par-reduction" && !canAccessParReduction(user))
      || (active === "par-reduction-targets" && !canManageParReductionTargets(user))
      || (active === "taeg" && !canAccessTaeg(user))
      || (active === "configuration" && !canAccessConfiguration(user))
      || (active === "import" && !canAccessImport(user))
      || (active === "bonus" && user.role !== "super_admin")
      || (active === "users" && !canAccessUsers(user));
    if (unauthorized) setActive(defaultModuleForUser(user));
  }, [active, user]);

  useEffect(() => () => clearNoticeTimers(), []);

  useEffect(() => {
    setSidebarOpen(false);
  }, [isCompactViewport]);

  useEffect(() => {
    function closeDrawerAfterViewportChange() {
      setSidebarOpen(false);
    }

    window.addEventListener("orientationchange", closeDrawerAfterViewportChange);
    window.addEventListener("resize", closeDrawerAfterViewportChange);
    return () => {
      window.removeEventListener("orientationchange", closeDrawerAfterViewportChange);
      window.removeEventListener("resize", closeDrawerAfterViewportChange);
    };
  }, []);

  useEffect(() => {
    const selectedIds = String(filters.snapshot_batch_ids || "")
      .split(",")
      .map((token) => Number(token.trim()))
      .filter((value) => Number.isFinite(value) && value > 0);
    if (selectedIds.length === 0) return;
    const allowedIds = new Set(snapshotOptions.map((item) => Number(item.batch_id)));
    const cleanedIds = selectedIds.filter((id) => allowedIds.has(id));
    if (cleanedIds.length === selectedIds.length) return;
    setFilters((prev) => ({ ...prev, snapshot_batch_ids: cleanedIds.join(","), offset: 0 }));
  }, [snapshotOptions, filters.snapshot_batch_ids]);

  function logout() {
    api.logout()
      .catch(() => {})
      .finally(() => {
        window.location.reload();
      });
  }

  function passwordChanged(updatedUser) {
    setUser(updatedUser);
    showNotice("Mot de passe modifie avec succes.", { autoHideMs: 4000 });
    loadBase().catch((err) => showNotice(err.message));
  }

  async function applyCurrentMonthFilter() {
    try {
      let snapshotDate = activeSnapshot?.snapshot_date || null;
      if (!snapshotDate) {
        const fallback = await api.activeSnapshot();
        snapshotDate = fallback?.snapshot_date || null;
        setActiveSnapshot(fallback || null);
      }
      if (!snapshotDate) {
        showNotice("Aucune snapshot active disponible pour appliquer ce filtre.");
        return;
      }
      const now = new Date();
      const startDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
      const endDate = String(snapshotDate).slice(0, 10);
      setFilters((prev) => ({ ...prev, date_from: startDate, date_to: endDate, offset: 0 }));
      showNotice(`Filtre applique: ${startDate} -> ${endDate}`, { autoHideMs: 4000 });
    } catch (err) {
      showNotice(err.message);
    }
  }

  async function deleteSnapshots(batchIds) {
    try {
      const result = await api.deleteSnapshots(batchIds);
      setFilters((prev) => {
        const deletedIds = new Set((result.deleted_batch_ids || []).map(Number));
        const remainingIds = String(prev.snapshot_batch_ids || "")
          .split(",")
          .map((value) => Number(value.trim()))
          .filter((value) => Number.isFinite(value) && value > 0 && !deletedIds.has(value));
        return { ...prev, snapshot_batch_ids: remainingIds.join(","), offset: 0 };
      });
      showNotice(
        `${result.deleted_batch_ids.length} snapshot(s) supprimee(s), ${result.deleted_rows} ligne(s) retiree(s).`,
        { autoHideMs: 4000 },
      );
      await loadBase();
    } catch (err) {
      showNotice(err.message);
      throw err;
    }
  }

  if (user?.must_change_password) {
    return <ForcePasswordChangeModal user={user} onChanged={passwordChanged} onLogout={logout} />;
  }

  const navItems = [
    ...(user?.role === "support" ? [] : [{ key: "dashboard", label: "Dashboard", Icon: BarChart3 }]),
    ...(user?.role === "support" ? [] : [{ key: "restructured", label: "Suivi restructures/consolides", Icon: AlertTriangle }]),
    ...(canAccessTaeg(user) ? [{ key: "taeg", label: "TAEG", Icon: BriefcaseBusiness }] : []),
    ...(canAccessImport(user) ? [{ key: "import", label: "Importation", Icon: Upload }] : []),
    ...(canAccessTargets(user) ? [{ key: "targets", label: "Objectifs", Icon: Target }] : []),
    ...(canAccessParReduction(user) ? [{ key: "par-reduction", label: "Suivi baisse PAR", Icon: TrendingDown }] : []),
    ...(canManageParReductionTargets(user) ? [{ key: "par-reduction-targets", label: "Objectifs de baisse PAR", Icon: Target }] : []),
    ...(user?.role === "super_admin"
      ? [{
        key: "bonus",
        label: "Bonus",
        Icon: Calculator,
        inDevelopment: !featureFlags.bonus_module_active,
      }]
      : []),
    ...(canAccessUsers(user) ? [{ key: "users", label: "Utilisateurs", Icon: Users }] : []),
    ...(canAccessConfiguration(user) ? [{ key: "configuration", label: "Configuration", Icon: Settings2 }] : []),
  ];
  const activeSectionLabel = navItems.find((item) => item.key === active)?.label || (user?.role === "support" ? "Importation" : "Dashboard");
  const currentStateDateLabel = formatCurrentStateDateLabel(activeSnapshot?.snapshot_date);
  const hasCurrentStateDate = Boolean(activeSnapshot?.snapshot_date);
  const showCurrentStateMeta = user?.role !== "committee_member";

  return (
    <main className={`app-shell ${isCompactViewport ? "app-shell-compact" : ""}`}>
      {isCompactViewport && sidebarOpen && (
        <button
          type="button"
          className="sidebar-overlay"
          aria-label="Fermer le menu"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <aside
        className={`sidebar ${isCompactViewport ? "sidebar-drawer" : ""} ${isCompactViewport && sidebarOpen ? "open" : ""}`}
        aria-hidden={isCompactViewport ? !sidebarOpen : false}
      >
        <div className="sidebar-head">
          <div>
            <p className="eyebrow">MicroCred</p>
            <h2>Performance</h2>
          </div>
          {isCompactViewport && (
            <button
              type="button"
              className="icon-button sidebar-close"
              aria-label="Fermer le menu"
              onClick={() => setSidebarOpen(false)}
            >
              <X size={16} />
            </button>
          )}
        </div>
        <nav>
          {navItems.map(({ key, label, Icon, inDevelopment }) => (
            <button
              key={key}
              className={`${active === key ? "nav-active" : ""}${inDevelopment ? " nav-dev" : ""}`}
              onClick={() => {
                if (key === "bonus" && inDevelopment) {
                  showNotice("Module en developpement", { autoHideMs: 0 });
                  setActive(key);
                  if (isCompactViewport) setSidebarOpen(false);
                  return;
                }
                setActive(key);
                if (isCompactViewport) setSidebarOpen(false);
              }}
            >
              <Icon size={18} />
              <span>{label}</span>
              {inDevelopment && <span className="nav-badge">En dev</span>}
            </button>
          ))}
        </nav>
        <button className="ghost" onClick={logout}><LogOut size={16} />Deconnexion</button>
      </aside>

      <section className="content">
        <header className="topbar">
          <div className="topbar-main">
            {isCompactViewport && (
              <button
                type="button"
                className="icon-button mobile-nav-trigger"
                onClick={() => setSidebarOpen(true)}
                aria-label="Ouvrir le menu"
              >
                <Menu size={18} />
              </button>
            )}
            <div>
              <h1>{activeSectionLabel}</h1>
              <p className="muted">{user?.full_name} - {displayRoleLabel(user?.role)}</p>
              {showCurrentStateMeta && (
                <div className="topbar-meta">
                  <span className={hasCurrentStateDate ? "state-date-pill" : "state-date-pill muted-pill"}>
                    <CalendarDays size={14} />
                    Etat actuel MCR : {currentStateDateLabel}
                  </span>
                </div>
              )}
            </div>
          </div>
          {active === "dashboard" && (
            <div className="topbar-actions">
              <ReportButtons
                user={user}
                agencies={agencies}
                filters={filters}
                setNotice={showNotice}
                onAutoFilterCurrentMonth={applyCurrentMonthFilter}
                committeeClosedMonths={committeeClosedMonths}
                committeeClosedMonthsLoading={committeeClosedMonthsLoading}
                committeeClosedMonthsStatus={committeeClosedMonthsStatus}
                committeeSelectedMonth={committeeMonthKey}
                onCommitteeMonthChange={setCommitteeMonthKey}
              />
            </div>
          )}
        </header>

        {notice && (
          <div className={`notice notice-${noticeTone}${noticeLeaving ? " is-hiding" : ""}`}>
            <span>{notice}</span>
            <button type="button" className="notice-close" onClick={dismissNotice}>
              Fermer
            </button>
          </div>
        )}

        {active === "dashboard" && (
          <DashboardScreen
            user={user}
            metrics={metrics}
            metricsTotal={metricsTotal}
            credits={credits}
            creditsTotal={creditsTotal}
            summary={summary}
            chartPack={chartPack}
            volumeChartPack={volumeChartPack}
            agencies={agencies}
            agents={agents}
             sectors={sectors}
             snapshotOptions={snapshotOptions}
             activeSnapshotDate={activeSnapshot?.snapshot_date || null}
            qualityScope={qualityScope}
            setQualityScope={setQualityScope}
            volumeScope={volumeScope}
            setVolumeScope={setVolumeScope}
            filters={filters}
            setFilters={setFilters}
            setNotice={showNotice}
            portfolioPerf={portfolioPerf}
            isCompactLayout={isCompactViewport}
            featureFlags={featureFlags}
            acmLimits={acmLimits}
            onDeleteSnapshots={deleteSnapshots}
            committeeClosedMonths={committeeClosedMonths}
            committeeSelectedMonth={committeeMonthKey}
          />
        )}
        {active === "restructured" && user && (
          <RestructuredCreditsScreenV2
            user={user}
            agencies={agencies}
            setNotice={showNotice}
            isCompactLayout={isCompactViewport}
            committeeSelectedMonth={committeeMonthKey}
          />
        )}
          {active === "import" && canAccessImport(user) && (
            <ImportScreen user={user} reload={loadBase} setNotice={showNotice} />
          )}
        {active === "targets" && canAccessTargets(user) && (
          <TargetsScreen agencies={agencies} user={user} setNotice={showNotice} />
        )}
        {active === "par-reduction" && canAccessParReduction(user) && (
          <ParReductionScreen user={user} agencies={agencies} setNotice={showNotice} />
        )}
        {active === "par-reduction-targets" && canManageParReductionTargets(user) && (
          <ParReductionTargetsScreen user={user} agencies={agencies} setNotice={showNotice} />
        )}
        {active === "taeg" && canAccessTaeg(user) && (
          <TaegScreen
            user={user}
            agencies={agencies}
            agents={agents}
            setNotice={showNotice}
            committeeSelectedMonth={committeeMonthKey}
          />
        )}
        {active === "bonus" && user?.role === "super_admin" && (
          featureFlags.bonus_module_active
            ? <BonusScreen formulaHelp={formulaHelp} setNotice={showNotice} />
            : <BonusDisabledScreen />
        )}
          {active === "users" && canAccessUsers(user) && (
            <UsersScreen
              currentUser={user}
            agencies={agencies}
            agents={agents}
            sectors={sectors}
            users={users}
            reload={() => api.users().then((page) => setUsers(page.items))}
            setNotice={showNotice}
          />
        )}
        {active === "configuration" && canAccessConfiguration(user) && (
          <ConfigurationScreen
            setNotice={showNotice}
            onAcmLimitsUpdated={() => api.acmLimits().then(setAcmLimits).catch(() => setAcmLimits(null))}
          />
        )}
      </section>
    </main>
  );
}

function ReportButtons({
  user,
  agencies,
  filters,
  setNotice,
  onAutoFilterCurrentMonth,
  committeeClosedMonths = [],
  committeeClosedMonthsLoading = false,
  committeeClosedMonthsStatus = "idle",
  committeeSelectedMonth = "",
  onCommitteeMonthChange,
}) {
  const isCommitteeMember = user?.role === "committee_member";
  const isPortfolioExportRole = user?.role === "portfolio_manager" || user?.role === "agency_manager";
  const isAdminExportRole = user?.role === "admin" || user?.role === "super_admin";
  const canUsePotentialRadiation = ["admin", "super_admin", "agency_manager", "portfolio_manager"].includes(user?.role);
  const [reportType, setReportType] = useState("");
  const [futureDays, setFutureDays] = useState(3);
  const [exportAgencyId, setExportAgencyId] = useState("");
  const [snapshotOptions, setSnapshotOptions] = useState([]);
  const [snapshotBatchId, setSnapshotBatchId] = useState("");

  const portfolioReportOptions = [
    {
      value: "arrears_list",
      label: "Liste des impayees",
      description: "Credits en retard superieur a 2 jours (MCR actuel)",
    },
    {
      value: "renewal_candidates",
      label: "Liste possibilite de renouvellement",
      description: "Credits arrivant a echeance sous 3 mois et Classe 0/1",
    },
    {
      value: "future_schedules",
      label: "Liste des echeances futures",
      description: "NEXT_SCHEDULE_DATE > aujourd'hui + periode",
    },
    ...(canUsePotentialRadiation ? [{
      value: "potential_radiation",
      label: "Potentiel Radiation",
      description: "Credits des clients Potentielle Radiable sur le snapshot selectionne",
    }] : []),
  ];

  const selectedReportMeta = portfolioReportOptions.find((item) => item.value === reportType);
  const needsFutureDays = reportType === "future_schedules";
  const isPotentialRadiationReport = reportType === "potential_radiation";
  const isFutureDaysValid = Number.isFinite(Number(futureDays)) && Number(futureDays) >= 1 && Number(futureDays) <= 10;
  const requiresAgencySelection = isAdminExportRole;
  // Non-admin scoped roles have their scope enforced server-side; the UI sends
  // the currently selected filter (or empty for super_admin) and the backend
  // intersects it with the user's effective scope.
  const scopedUserAgencyId = user?.agency_id ? String(user.agency_id) : "";
  const resolvedPortfolioAgencyId = isAdminExportRole
    ? exportAgencyId
    : (isPortfolioExportRole && scopedUserAgencyId ? scopedUserAgencyId : (filters.agency_id || ""));
  const resolvedPortfolioAgentId = isAdminExportRole ? "" : filters.agent_id;
  const canDownloadPortfolioReport = Boolean(reportType)
    && (!needsFutureDays || isFutureDaysValid)
    && (!isPotentialRadiationReport || Boolean(snapshotBatchId))
    && (!requiresAgencySelection || Boolean(resolvedPortfolioAgencyId));
  useEffect(() => {
    if (!isPotentialRadiationReport) {
      setSnapshotOptions([]);
      setSnapshotBatchId("");
      return undefined;
    }
    // Snapshot list requires at least one selection gate:
    // - admin / super_admin: explicit agency selection
    // - agency_manager: implicit (their agency_id)
    // - portfolio_manager: implicit (portfolio identity, no agency filter)
    let snapshotAgencyFilter = "";
    if (isAdminExportRole) {
      if (!resolvedPortfolioAgencyId) {
        setSnapshotOptions([]);
        setSnapshotBatchId("");
        return undefined;
      }
      snapshotAgencyFilter = resolvedPortfolioAgencyId;
    } else if (user?.role === "agency_manager" && scopedUserAgencyId) {
      snapshotAgencyFilter = scopedUserAgencyId;
    }
    let cancelled = false;
    setSnapshotOptions([]);
    setSnapshotBatchId("");
    api.potentialRadiationSnapshots({ agency_ids: snapshotAgencyFilter })
      .then((items) => {
        if (!cancelled) setSnapshotOptions(Array.isArray(items) ? items : []);
      })
      .catch(() => {
        if (!cancelled) setSnapshotOptions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [isPotentialRadiationReport, resolvedPortfolioAgencyId, isAdminExportRole, scopedUserAgencyId, user?.role]);

  async function download(type) {
    try {
      const blob = await api.downloadReport(type, clean(filters));
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `microcred_metrics.${type}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function downloadPortfolio(format) {
    if (!canDownloadPortfolioReport) {
      setNotice(
        requiresAgencySelection && !resolvedPortfolioAgencyId
          ? "Selectionnez au moins une agence et un rapport valide avant telechargement."
          : "Selectionnez un type de rapport valide avant telechargement.",
      );
      return;
    }
    try {
      const selectedPortfolioAgencyIds = selectedIds(resolvedPortfolioAgencyId);
      const params = clean({
        report_type: reportType,
        future_days: needsFutureDays ? Number(futureDays) : undefined,
        snapshot_batch_id: isPotentialRadiationReport ? Number(snapshotBatchId) : undefined,
        agency_id: selectedPortfolioAgencyIds.length === 1 ? selectedPortfolioAgencyIds[0] : undefined,
        agency_ids: selectedPortfolioAgencyIds.length > 1 ? joinSelectedIds(selectedPortfolioAgencyIds) : undefined,
        agent_id: resolvedPortfolioAgentId || undefined,
        date_from: filters.date_from,
        date_to: filters.date_to,
      });
      const blob = await api.downloadPortfolioReport(format, params);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `microcred_${reportType}.${format}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setNotice(err.message);
    }
  }

  if (isPortfolioExportRole) {
    return (
      <div className="export-actions pm-actions">
        <button
          className="icon-button"
          type="button"
          title="Filtrer mois actuel jusqu'au dernier snapshot"
          onClick={onAutoFilterCurrentMonth}
        >
          <Filter size={16} />
          Mois actuel
        </button>
        <div className="portfolio-report-controls">
          <label className="portfolio-report-field" title="Choisir le rapport a telecharger">
            <span>Rapport</span>
            <select value={reportType} onChange={(e) => setReportType(e.target.value)}>
              <option value="">Selectionner un rapport...</option>
              {portfolioReportOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          {needsFutureDays && (
            <label className="portfolio-report-field small" title="Periode en jours (1 a 10)">
              <span>Periode (jours)</span>
              <input
                type="number"
                min={1}
                max={10}
                value={futureDays}
                onChange={(e) => setFutureDays(e.target.value)}
              />
            </label>
          )}
          {isPotentialRadiationReport && (
            <label className="portfolio-report-field" title="Choisir le snapshot de reference">
              <span>Snapshot de reference</span>
              <select
                value={snapshotBatchId}
                onChange={(event) => setSnapshotBatchId(event.target.value)}
                disabled={snapshotOptions.length === 0}
                required
              >
                <option value="">
                  {snapshotOptions.length === 0 ? "Aucun snapshot disponible" : "Selectionner un snapshot..."}
                </option>
                {snapshotOptions.map((item) => (
                  <option key={item.batch_id} value={item.batch_id}>{item.label}</option>
                ))}
              </select>
            </label>
          )}
          <div className="portfolio-report-actions">
            <button
              className="icon-button"
              type="button"
              disabled={!canDownloadPortfolioReport}
              onClick={() => downloadPortfolio("xlsx")}
            >
              <FileDown size={16} />
              Excel
            </button>
            {!isPotentialRadiationReport && (
              <button
                className="icon-button"
                type="button"
                disabled={!canDownloadPortfolioReport}
                onClick={() => downloadPortfolio("pdf")}
              >
                <FileDown size={16} />
                PDF
              </button>
            )}
          </div>
          <p className="portfolio-report-hint">
            {selectedReportMeta?.description || "Choisissez un rapport pour activer le telechargement."}
          </p>
        </div>
      </div>
    );
  }

  if (isAdminExportRole) {
  return (
    <div className="admin-export-stack">
      <div className="admin-export-row admin-export-row-top">
        <button
          className="icon-button"
          type="button"
          title="Filtrer mois actuel jusqu'au dernier snapshot"
          onClick={onAutoFilterCurrentMonth}
        >
          <Filter size={16} />
          Mois actuel
        </button>
      </div>

      <div className="portfolio-report-field admin-export-field admin-export-field-agency" title="Selectionner une ou plusieurs agences a exporter">
        <span>Agence</span>
        <AgencyMultiSelect
          options={agencies}
          selectedIds={selectedIds(exportAgencyId)}
          onChange={(nextAgencyIds) => setExportAgencyId(nextAgencyIds)}
          responsiveTags
          overflowLabel="agences"
          mode="reports"
          showQuickSelect
          compactSummary
          onQuickSelect={(ids) => setExportAgencyId(joinSelectedIds(ids))}
        />
      </div>

      <div className="admin-export-row admin-export-row-controls">
        <label className="portfolio-report-field admin-export-field admin-export-field-report" title="Choisir le rapport a telecharger">
          <span>Rapport</span>
          <select value={reportType} onChange={(e) => setReportType(e.target.value)}>
            <option value="">Selectionner un rapport...</option>
            {portfolioReportOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        {needsFutureDays && (
          <label className="portfolio-report-field small admin-export-field" title="Periode en jours (1 a 10)">
            <span>Periode (jours)</span>
            <input
              type="number"
              min={1}
              max={10}
              value={futureDays}
              onChange={(e) => setFutureDays(e.target.value)}
            />
          </label>
        )}
          {isPotentialRadiationReport && (
            <label className="portfolio-report-field admin-export-field admin-export-field-snapshot" title="Choisir le snapshot de reference">
              <span>Snapshot de reference</span>
              <select
                value={snapshotBatchId}
                onChange={(event) => setSnapshotBatchId(event.target.value)}
                disabled={snapshotOptions.length === 0}
                required
              >
                <option value="">
                  {snapshotOptions.length === 0 ? "Aucun snapshot disponible" : "Selectionner un snapshot..."}
                </option>
                {snapshotOptions.map((item) => (
                  <option key={item.batch_id} value={item.batch_id}>{item.label}</option>
                ))}
              </select>
            </label>
          )}

        <div className="portfolio-report-actions admin-export-actions">
          <button
            className="icon-button"
            type="button"
            disabled={!canDownloadPortfolioReport}
            onClick={() => downloadPortfolio("xlsx")}
          >
            <FileDown size={16} />
            Excel
          </button>
          {!isPotentialRadiationReport && (
            <button
              className="icon-button"
              type="button"
              disabled={!canDownloadPortfolioReport}
              onClick={() => downloadPortfolio("pdf")}
            >
              <FileDown size={16} />
              PDF
            </button>
          )}
        </div>
      </div>

      <p className="portfolio-report-hint">
        {selectedReportMeta?.description || "Choisissez un rapport pour activer le telechargement."}
        {!resolvedPortfolioAgencyId
          ? " Selectionnez une ou plusieurs agences pour exporter les donnees."
          : selectedIds(resolvedPortfolioAgencyId).length > 1
            ? " Plusieurs agences selectionnees : fichier consolide avec colonnes Agence et Agent."
            : ""}
      </p>
    </div>
  );
}

  if (isCommitteeMember) {
    const committeeMessage =
      committeeClosedMonthsStatus === "forbidden"
        ? "Vous n'avez pas l'autorisation d'acceder a cette ressource."
        : committeeClosedMonthsStatus === "error"
          ? "Impossible de charger les periodes historiques."
          : !committeeClosedMonthsLoading && committeeClosedMonths.length === 0
            ? "Aucun MCR historique disponible."
            : "";
    return (
      <div className="export-actions">
        <label className="portfolio-report-field" title="Selectionner un mois cloture">
          <span>Periode</span>
          <select
            value={committeeSelectedMonth || committeeClosedMonths[0]?.key || ""}
            onChange={(event) => onCommitteeMonthChange?.(event.target.value)}
            disabled={
              committeeClosedMonthsLoading
              || committeeClosedMonthsStatus === "forbidden"
              || committeeClosedMonthsStatus === "error"
              || committeeClosedMonths.length === 0
            }
          >
            {committeeClosedMonthsLoading && <option value="">Chargement des mois...</option>}
            {!committeeClosedMonthsLoading && committeeClosedMonthsStatus === "forbidden" && (
              <option value="">Acces non autorise</option>
            )}
            {!committeeClosedMonthsLoading && committeeClosedMonthsStatus === "error" && (
              <option value="">Erreur de chargement</option>
            )}
            {!committeeClosedMonthsLoading && committeeClosedMonthsStatus !== "forbidden" && committeeClosedMonthsStatus !== "error" && committeeClosedMonths.length === 0 && (
              <option value="">Aucun MCR historique disponible.</option>
            )}
            {committeeClosedMonths.map((item) => (
              <option key={item.key} value={item.key}>
                {formatLongMonthLabel(item.snapshot_date)}
              </option>
            ))}
          </select>
        </label>
        <button className="icon-button" onClick={() => download("xlsx")}><FileDown size={16} />Excel</button>
        <button className="icon-button" onClick={() => download("pdf")}><FileDown size={16} />PDF</button>
        {committeeMessage && (
          <p className="portfolio-report-hint">{committeeMessage}</p>
        )}
      </div>
    );
  }

  return (
    <div className="export-actions">
      {!isCommitteeMember && (
        <button
          className="icon-button"
          type="button"
          title="Filtrer mois actuel jusqu'au dernier snapshot"
          onClick={onAutoFilterCurrentMonth}
        >
          <Filter size={16} />
          Mois actuel
        </button>
      )}
      <button className="icon-button" onClick={() => download("xlsx")}><FileDown size={16} />Excel</button>
      <button className="icon-button" onClick={() => download("pdf")}><FileDown size={16} />PDF</button>
    </div>
  );
}

function DashboardScreen({
  user,
  metrics,
  metricsTotal,
  credits,
  creditsTotal,
  summary,
  chartPack,
  volumeChartPack,
  agencies = [],
  agents = [],
  sectors = [],
  snapshotOptions = [],
  activeSnapshotDate,
  qualityScope,
  setQualityScope,
  volumeScope,
  setVolumeScope,
  filters,
  setFilters,
  setNotice,
  portfolioPerf,
  isCompactLayout,
  featureFlags,
  acmLimits,
  onDeleteSnapshots,
  committeeClosedMonths,
  committeeSelectedMonth,
}) {
  const isCommitteeMember = user?.role === "committee_member";
  const totals = summary || {
    credits_count: 0,
    disbursement_count: 0,
    disbursements_count: 0,
    disbursement_volume: 0,
    nb_clients: 0,
    outstanding: 0,
    healthy_outstanding: 0,
    healthy_count: 0,
    healthy_client_count: 0,
    par_0: 0,
    par_0_count: 0,
    par_0_client_count: 0,
    par_1_15: 0,
    par_1_15_count: 0,
    par_1_15_client_count: 0,
    par_16_30: 0,
    par_16_30_count: 0,
    par_16_30_client_count: 0,
    par_1_30: 0,
    par_1_30_count: 0,
    par_1_30_client_count: 0,
    par_31_60: 0,
    par_31_60_count: 0,
    par_31_60_client_count: 0,
    par_61_90: 0,
    par_61_90_count: 0,
    par_61_90_client_count: 0,
    par_91_120: 0,
    par_91_120_count: 0,
    par_91_120_client_count: 0,
    par_120: 0,
    par_120_count: 0,
    par_120_client_count: 0,
    par_30: 0,
    par_30_count: 0,
    par_30_client_count: 0,
    potentially_radiable_volume: 0,
    potentially_radiable_rate: 0,
    potential_radiable_client_count: 0,
    potential_radiable_loan_count: 0,
    healthy_rate: 0,
    par_0_rate: 0,
    par_1_30_rate: 0,
    par_31_60_rate: 0,
    par_61_90_rate: 0,
    par_91_120_rate: 0,
    par_120_rate: 0,
    par_30_rate: 0,
  };
  const chartHeight = isCompactLayout ? 420 : 390;
  const qualityChartContainerRef = useRef(null);
  const volumeChartContainerRef = useRef(null);
  const chartMode = chartPack?.mode || determineChartMode(filters);
  const volumeMode = volumeChartPack?.mode || chartMode;
  const agencyName = selectedName(agencies, filters.agency_id, "selectionnee");
  const agentName = selectedName(agents, filters.agent_id, "selectionne");
  const { qualityTitle: qualityTitleBase } = buildChartTitles(chartMode, agencyName, agentName);
  const qualityTitle = qualityScope === "region_nord" && chartMode === CHART_MODES.GLOBAL_BY_AGENCY
    ? "Qualite portefeuille - Région Nord"
    : qualityScope === "region_sud" && chartMode === CHART_MODES.GLOBAL_BY_AGENCY
      ? "Qualite portefeuille - Région Sud"
      : qualityTitleBase;
  const { volumeTitle } = buildChartTitles(volumeMode, agencyName, agentName);
  const qualitySubtitle =
    isCommitteeMember
      ? (
        chartMode === CHART_MODES.GLOBAL_BY_AGENCY
          ? "Comparaison du portefeuille entre agences pour le mois cloture selectionne."
          : "Vue MicroCred consolidee sur le mois cloture selectionne."
      )
      : chartMode === CHART_MODES.GLOBAL_BY_AGENCY
        ? "Comparaison du portefeuille entre agences (% de l'encours)."
        : chartMode === CHART_MODES.GLOBAL_QUALITY_TREND
          ? "Vue MicroCred consolidee sur les periodes importees et snapshots selectionnees."
          : "Evolution selon les periodes importees (mois historiques + etat actuel).";
  const volumeSubtitle =
    isCommitteeMember
      ? (
        volumeMode === CHART_MODES.GLOBAL_BY_AGENCY
          ? "Comparaison du volume decaisse entre agences pour le mois cloture selectionne."
          : "Evolution du volume decaisse sur le mois cloture selectionne."
      )
      : volumeMode === CHART_MODES.GLOBAL_BY_AGENCY
        ? "Comparaison du volume decaisse entre agences."
        : "Evolution selon les periodes importees (mois historiques + etat actuel).";
  const selectedSnapshotIds = useMemo(
    () =>
      String(filters.snapshot_batch_ids || "")
        .split(",")
        .map((token) => Number(token.trim()))
        .filter((value) => Number.isFinite(value) && value > 0),
    [filters.snapshot_batch_ids],
  );
  const chartDataRaw = useMemo(
    () => mapChartPoints(chartPack, chartMode, activeSnapshotDate),
    [activeSnapshotDate, chartMode, chartPack],
  );
  const chartData = useMemo(() => {
    if (chartMode !== CHART_MODES.GLOBAL_BY_AGENCY) return chartDataRaw;
    if (qualityScope === "region_nord") return chartDataRaw.filter((point) => isNordAgency(point.name));
    if (qualityScope === "region_sud") return chartDataRaw.filter((point) => !isNordAgency(point.name));
    return chartDataRaw;
  }, [chartDataRaw, chartMode, qualityScope]);
  const volumeRawData = useMemo(
    () => mapChartPoints(volumeChartPack || chartPack, volumeMode, activeSnapshotDate),
    [activeSnapshotDate, chartPack, volumeChartPack, volumeMode],
  );
  const canSwitchVolumeScope = user?.role === "super_admin" && !filters.agency_id && !filters.agent_id;
  const volumeChartData = useMemo(() => {
    if (volumeMode === CHART_MODES.GLOBAL_BY_AGENCY) {
      return [...volumeRawData].sort(
        (left, right) => Number(right.disbursement || 0) - Number(left.disbursement || 0),
      );
    }
    return volumeRawData;
  }, [volumeMode, volumeRawData]);
  const acmConfigured = Boolean(acmLimits?.configured);
  const isAdminScopeUser = user?.role === "admin" || user?.role === "super_admin";
  const canSwitchQualityRegion = (user?.role === "admin" || user?.role === "super_admin") && chartMode === CHART_MODES.GLOBAL_BY_AGENCY && !filters.agency_id && !filters.agent_id;
  const showAcmOverlay = isAdminScopeUser && chartMode === CHART_MODES.GLOBAL_QUALITY_TREND && chartData.length > 0;
  const showAcmReferenceLine =
    showAcmOverlay && acmConfigured && Number.isFinite(Number(acmLimits?.par_0_limit || 0));
  const riskAxisMax = useMemo(() => {
    const maxRiskValue = chartData.reduce((maxValue, point) => {
      const stackedTotal = RISK_STACK_SERIES.reduce(
        (sum, serie) => sum + Number(point[serie.key] || 0),
        0,
      );
      return Math.max(
        maxValue,
        stackedTotal,
        Number(point.par0Rate || 0),
        showAcmReferenceLine ? Number(acmLimits?.par_0_limit || 0) : 0,
      );
    }, 0);
    return riskAxisUpperBound(maxRiskValue);
  }, [acmLimits?.par_0_limit, chartData, showAcmReferenceLine]);
  const isPortfolioManager = user?.role === "portfolio_manager";
  const isAgencyManager = user?.role === "agency_manager";
  const lockedAgencyId = isAgencyManager ? (user?.agency_id ? String(user.agency_id) : "") : "";
  const lockedAgentId = isPortfolioManager ? (user?.agent_id ? String(user.agent_id) : "") : "";
  const filteredAgencyList = lockedAgencyId
    ? agencies.filter((agency) => String(agency.id) === lockedAgencyId)
    : agencies;
  const filteredAgentList = lockedAgentId
    ? agents.filter((agent) => String(agent.id) === lockedAgentId)
    : agents;
  const filteredPeriodText = formatFilteredPeriodLabel(filters.date_from, filters.date_to);
  const committeeSelectedMonthMeta = useMemo(
    () => committeeClosedMonths.find((item) => item.key === committeeSelectedMonth) || null,
    [committeeClosedMonths, committeeSelectedMonth],
  );
  const qualitySubtitleBase =
    !isCommitteeMember && selectedSnapshotIds.length > 0 && chartMode !== CHART_MODES.GLOBAL_BY_AGENCY
      ? `${qualitySubtitle} + ${selectedSnapshotIds.length} snapshot(s) selectionnee(s).`
      : qualitySubtitle;
  const qualitySubtitleText = qualityScope === "region_nord" && chartMode === CHART_MODES.GLOBAL_BY_AGENCY
    ? "Agences de la Région Nord (Ezahrouni, Ariana, Ben Arous, Jendouba, Kef, Bizerte, TCV, Nabeul, Siliana, Beja, Fahs)."
    : qualityScope === "region_sud" && chartMode === CHART_MODES.GLOBAL_BY_AGENCY
      ? "Agences de la Région Sud (hors Région Nord)."
      : qualitySubtitleBase;
  const volumeSubtitleText =
    !isCommitteeMember && selectedSnapshotIds.length > 0 && volumeMode !== CHART_MODES.GLOBAL_BY_AGENCY
      ? `${volumeSubtitle} + ${selectedSnapshotIds.length} snapshot(s) selectionnee(s).`
      : volumeSubtitle;
  const effectiveVolumeTitle =
    canSwitchVolumeScope && volumeScope === "global" ? "Evolution volume decaisse MicroCred" : volumeTitle;
  const effectiveVolumeSubtitleText =
    canSwitchVolumeScope && volumeScope === "global"
      ? "Volume decaisse consolide sur toutes les agences MicroCred selon le filtre actif."
      : volumeSubtitleText;

  function resetDashboardFilters() {
    setFilters((prev) => ({
      ...prev,
      agency_id: lockedAgencyId || "",
      agent_id: lockedAgentId || "",
      date_from: "",
      date_to: "",
      snapshot_batch_ids: "",
      risk_categories: "",
      q: "",
      sector_ids: "",
      offset: 0,
    }));
    setNotice?.("Filtres reinitialises.", { autoHideMs: 3000 });
  }

  function updateDateFilter(field, value) {
    const next = { ...filters, [field]: value, offset: 0 };
    setFilters(next);
  }

  return (
    <>
      <section className="filter-row">
        {!isCommitteeMember && (
          <>
            <button
              type="button"
              className="icon-button filter-reset-trigger"
              title="Reinitialiser tous les filtres"
              aria-label="Reinitialiser tous les filtres"
              onClick={resetDashboardFilters}
            >
              <Filter size={18} />
            </button>
            <AgencyMultiSelect
              options={filteredAgencyList}
              selectedIds={selectedIds(isAgencyManager || isPortfolioManager ? lockedAgencyId : filters.agency_id)}
              disabled={isAgencyManager || isPortfolioManager}
              responsiveTags
              overflowLabel="agences"
              mode="dashboard"
              showQuickSelect
              compactSummary
              onQuickSelect={(ids) => setFilters({
                ...filters,
                agency_id: ids,
                agent_id: "",
                offset: 0,
              })}
              onChange={(nextAgencyIds) => setFilters({
                ...filters,
                agency_id: nextAgencyIds,
                agent_id: "",
                offset: 0,
              })}
            />
            <select
              value={isPortfolioManager ? lockedAgentId : (filters.agent_id || "")}
              disabled={isPortfolioManager}
              onChange={(e) => setFilters({ ...filters, agent_id: e.target.value, offset: 0 })}
            >
              <option value="">Tous les agents</option>
              {filteredAgentList.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
            </select>
            {!isCommitteeMember && (
              <label className="sector-select-label">
                <SectorMultiSelect
                  options={sectors}
                  selectedIds={selectedIds(filters.sector_ids)}
                  disabled={sectors.length === 0}
                  onChange={(nextIds) => setFilters({ ...filters, sector_ids: nextIds, offset: 0 })}
                />
              </label>
            )}
            <div className="period-filter-indicator" aria-live="polite">
              <CalendarDays size={14} />
              <span>{filteredPeriodText}</span>
            </div>
            <input
              type="date"
              value={filters.date_from || ""}
              onChange={(e) => updateDateFilter("date_from", e.target.value)}
            />
            <input
              type="date"
              value={filters.date_to || ""}
              onChange={(e) => updateDateFilter("date_to", e.target.value)}
            />
          </>
        )}
        {isCommitteeMember && (
          <div className="period-filter-indicator committee-period-indicator" aria-live="polite">
            <CalendarDays size={14} />
            <span>
              {committeeSelectedMonthMeta
                ? `Donnees arretees au : ${formatDateLabel(committeeSelectedMonthMeta.snapshot_date)}`
                : filteredPeriodText}
            </span>
          </div>
        )}
        {!isCommitteeMember && (
          <label className="snapshot-select">
            <span>Snapshots a comparer</span>
            <SnapshotMultiSelect
              options={snapshotOptions}
              selectedIds={selectedSnapshotIds}
              disabled={snapshotOptions.length === 0}
              onChange={(ids) => setFilters({ ...filters, snapshot_batch_ids: ids.join(","), offset: 0 })}
            />
          </label>
        )}
      </section>

      {user?.role === "super_admin" && (
        <SnapshotAdminPanel
          options={snapshotOptions}
          onDeleteSnapshots={onDeleteSnapshots}
        />
      )}

      <section className={`kpi-grid ${isPortfolioManager ? "portfolio-extended" : "expanded"}`}>
        <Metric label="Client Actif" value={money(totals.nb_clients)} count={totals.nb_clients} />
        <Metric label="Nombre de crédits" value={money(totals.disbursement_count)} count={totals.disbursements_count} />
        <Metric label="Volume decaisse" value={money(totals.disbursement_volume)} />
        <Metric label="Encours" value={money(totals.outstanding)} />
        <Metric label="Encours sain" value={money(totals.healthy_outstanding)} sub={percent(totals.healthy_rate)} count={totals.healthy_count} clientCount={totals.healthy_client_count} />
        <Metric label="PAR0" value={money(totals.par_0)} sub={percent(totals.par_0_rate)} tone="warn" count={totals.par_0_count} clientCount={totals.par_0_client_count} />
        <Metric label="PAR30" value={money(totals.par_30)} sub={percent(totals.par_30_rate)} tone="risk" count={totals.par_30_count} clientCount={totals.par_30_client_count} />
        <Metric label="Cohorte 1-15" value={money(totals.par_1_15)} sub={percent(totals.par_1_15_rate)} tone="warn" count={totals.par_1_15_count} clientCount={totals.par_1_15_client_count} />
        <Metric label="Cohorte 16-30" value={money(totals.par_16_30)} sub={percent(totals.par_16_30_rate)} tone="warn" count={totals.par_16_30_count} clientCount={totals.par_16_30_client_count} />
        <Metric label="Cohorte 31-60" value={money(totals.par_31_60)} sub={percent(totals.par_31_60_rate)} tone="risk" count={totals.par_31_60_count} clientCount={totals.par_31_60_client_count} />
        <Metric label="Cohorte 61-90" value={money(totals.par_61_90)} sub={percent(totals.par_61_90_rate)} tone="risk" count={totals.par_61_90_count} clientCount={totals.par_61_90_client_count} />
        <Metric label="Cohorte 91-120" value={money(totals.par_91_120)} sub={percent(totals.par_91_120_rate)} tone="risk" count={totals.par_91_120_count} clientCount={totals.par_91_120_client_count} />
        <Metric label="PAR120" value={money(totals.par_120)} sub={percent(totals.par_120_rate)} tone="risk" count={totals.par_120_count} clientCount={totals.par_120_client_count} />
        <Metric label="Potentielle Radiable" value={money(totals.potentially_radiable_volume)} sub={percent(totals.potentially_radiable_rate)} tone="risk" count={totals.potentially_radiable_loan_count} clientCount={totals.potential_radiable_client_count} />
        {isPortfolioManager && (
          <Metric
            label="Couverture objectifs"
            value={percent(portfolioPerf?.coverage_ratio || 0)}
            sub={portfolioPerf?.has_target ? "Objectifs agent courants" : "Aucun objectif defini"}
          />
        )}
        {isPortfolioManager && (
          <Metric
            label="Prime"
            value={featureFlags?.bonus_module_active ? money(portfolioPerf?.bonus_amount || 0) : "--"}
            sub={featureFlags?.bonus_module_active
              ? (portfolioPerf?.has_bonus_rule ? "Formule active admin" : "Aucune formule active")
              : "Module en developpement"}
            tone={featureFlags?.bonus_module_active ? "warn" : "inactive"}
            tooltip={!featureFlags?.bonus_module_active ? "Module en developpement" : undefined}
          />
        )}
      </section>
      {isPortfolioManager && portfolioPerf?.message && (
        <div className="notice">{portfolioPerf.message}</div>
      )}

      <section className="chart-grid">
        <div className="panel chart-panel">
          <div className="chart-panel-header">
            <div>
              <h3>{qualityTitle}</h3>
              <p className="chart-subtitle">{qualitySubtitleText}</p>
            </div>
            {!isPortfolioManager && (
              <div className="segment-control quality-scope chart-scope-toggle" role="tablist" aria-label="Scope qualite portefeuille">
                <button
                  type="button"
                  className={qualityScope === "agency" ? "segment-active" : ""}
                  onClick={() => setQualityScope("agency")}
                >
                  Par agence
                </button>
                <button
                  type="button"
                  className={qualityScope === "global" ? "segment-active" : ""}
                  onClick={() => setQualityScope("global")}
                >
                  Global
                </button>
                {canSwitchQualityRegion && (
                  <>
                    <button
                      type="button"
                      className={qualityScope === "region_nord" ? "segment-active" : ""}
                      onClick={() => setQualityScope("region_nord")}
                    >
                      Région Nord
                    </button>
                    <button
                      type="button"
                      className={qualityScope === "region_sud" ? "segment-active" : ""}
                      onClick={() => setQualityScope("region_sud")}
                    >
                      Région Sud
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
          {chartData.length === 0 ? (
            <div className="chart-empty">Aucune donnee disponible pour ce filtre.</div>
          ) : (
            <div ref={qualityChartContainerRef} className="chart-viewport with-acm-overlay chart-tooltip-shell">
              <ResponsiveContainer width="100%" height={chartHeight}>
                <ComposedChart
                  data={chartData}
                  margin={{ top: 16, right: showAcmOverlay ? 280 : 28, bottom: 8, left: 0 }}
                  reverseStackOrder={false}
                  barCategoryGap="18%"
                >
                  <CartesianGrid strokeDasharray="4 4" stroke="#d6e0ee" />
                  <XAxis
                    dataKey="name"
                    tick={{ fill: "#52617a", fontSize: 12 }}
                    interval="preserveStartEnd"
                    angle={chartMode === CHART_MODES.GLOBAL_BY_AGENCY ? -20 : -12}
                    textAnchor="end"
                    height={58}
                  />
                  <YAxis
                    domain={[0, riskAxisMax]}
                    allowDecimals={false}
                    tick={{ fill: "#52617a", fontSize: 12 }}
                    tickFormatter={(value) => `${Number(value).toFixed(0)}%`}
                  />
                  <Tooltip
                    content={<QualityPortfolioTooltip containerRef={qualityChartContainerRef} />}
                    allowEscapeViewBox={{ x: true, y: true }}
                    isAnimationActive={false}
                  />
                  <Legend />
                  {showAcmReferenceLine && (
                    <ReferenceLine
                      y={Number(acmLimits?.par_0_limit || 0)}
                      stroke="#ef4444"
                      strokeDasharray="6 4"
                      label={{ value: "Limite PAR0 ACM", fill: "#ef4444", fontSize: 11 }}
                    />
                  )}
                  {RISK_STACK_SERIES.map((serie, index) => (
                    <Bar
                      key={serie.key}
                      dataKey={serie.key}
                      stackId="risk"
                      name={serie.label}
                      fill={serie.color}
                      maxBarSize={56}
                      radius={index === RISK_STACK_SERIES.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]}
                    />
                  ))}
                  <Line type="monotone" dataKey="par0Rate" name="PAR0 (%)" stroke="#ff6b2c" strokeWidth={3} dot={{ r: 3 }} />
                </ComposedChart>
              </ResponsiveContainer>
              {showAcmOverlay && (
                <AcmBenchmarkCard acmLimits={acmLimits} />
              )}
            </div>
          )}
        </div>
        <div className="panel chart-panel">
          <div className="chart-panel-header">
            <div>
              <h3>{effectiveVolumeTitle}</h3>
              <p className="chart-subtitle">{effectiveVolumeSubtitleText}</p>
            </div>
            {canSwitchVolumeScope && (
              <div className="segment-control quality-scope chart-scope-toggle" role="tablist" aria-label="Scope volume decaisse">
                <button
                  type="button"
                  className={volumeScope === "agency" ? "segment-active" : ""}
                  onClick={() => setVolumeScope("agency")}
                >
                  Par agence
                </button>
                <button
                  type="button"
                  className={volumeScope === "global" ? "segment-active" : ""}
                  onClick={() => {
                      console.log("Global volume");
                      setVolumeScope("global");
                    }}
                >
                  Global
                </button>
              </div>
            )}
          </div>
          {volumeChartData.length === 0 ? (
            <div className="chart-empty">Aucune donnee disponible pour ce filtre.</div>
          ) : (
            <div ref={volumeChartContainerRef} className="chart-tooltip-shell">
              <ResponsiveContainer width="100%" height={chartHeight}>
                <BarChart data={volumeChartData} margin={{ top: 8, right: 20, bottom: 8, left: 0 }} barCategoryGap="18%">
                  <CartesianGrid strokeDasharray="4 4" stroke="#d6e0ee" />
                  <XAxis
                    dataKey="name"
                    tick={{ fill: "#52617a", fontSize: 12 }}
                    interval="preserveStartEnd"
                    angle={volumeMode === CHART_MODES.GLOBAL_BY_AGENCY ? -20 : -12}
                    textAnchor="end"
                    height={54}
                  />
                  <YAxis tick={{ fill: "#52617a", fontSize: 12 }} tickFormatter={(value) => money(value)} />
                  <Tooltip
                    content={<VolumeDisbursementTooltip containerRef={volumeChartContainerRef} />}
                    allowEscapeViewBox={{ x: true, y: true }}
                    isAnimationActive={false}
                  />
                  <Legend />
                  {VOLUME_STACK_SERIES.map((serie, index) => (
                    <Bar
                      key={serie.key}
                      dataKey={serie.key}
                      stackId="volume"
                      name={serie.label}
                      fill={serie.color}
                      radius={index === VOLUME_STACK_SERIES.length - 1 ? [6, 6, 0, 0] : [0, 0, 0, 0]}
                      maxBarSize={56}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </section>

      <MetricsPanelSwitch
        user={user}
        metrics={metrics}
        metricsTotal={metricsTotal}
        credits={credits}
        creditsTotal={creditsTotal}
        filters={filters}
        setFilters={setFilters}
      />
    </>
  );
}

function SnapshotAdminPanel({ options, onDeleteSnapshots }) {
  const [selectedIds, setSelectedIds] = useState([]);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const allowedIds = new Set(options.map((item) => Number(item.batch_id)));
    setSelectedIds((current) => current.filter((id) => allowedIds.has(id)));
  }, [options]);

  function toggle(id) {
    setSelectedIds((current) => (
      current.includes(id)
        ? current.filter((value) => value !== id)
        : [...current, id]
    ));
  }

  async function removeSelected() {
    setBusy(true);
    try {
      await onDeleteSnapshots(selectedIds);
      setSelectedIds([]);
      setConfirmOpen(false);
    } finally {
      setBusy(false);
    }
  }
/*{
  return (
    <>
      <section className="panel snapshot-admin-panel">
        <div>
          <h3>Gestion des snapshots</h3>
          <p className="muted">
            Supprimer uniquement les snapshots errones. L'etat actuel et les mois clotures restent proteges.
          </p>
        </div>
        {options.length === 0 ? (
          <p className="muted">Aucune snapshot disponible.</p>
        ) : (
          <div className="snapshot-admin-list">
            {options.map((item) => {
              const id = Number(item.batch_id);
              return (
                <label className="snapshot-admin-item" key={item.batch_id}>
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(id)}
                    onChange={() => toggle(id)}
                  />
                  <span>{item.label}</span>
                </label>
              );
            })}
          </div>
        )}
        <button
          type="button"
          className="danger-button fit"
          disabled={selectedIds.length === 0}
          onClick={() => setConfirmOpen(true)}
        >
          <Trash2 size={16} />
          Supprimer la selection
        </button>
      </section>

      {confirmOpen && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="snapshot-delete-title">
          <div className="modal-card">
            <div className="modal-title">
              <AlertTriangle size={18} />
              <h3 id="snapshot-delete-title">Supprimer les snapshots selectionnees ?</h3>
            </div>
            <p className="muted">
              Cette action supprime definitivement les donnees associees a {selectedIds.length} snapshot(s).
            </p>
            <div className="button-row">
              <button type="button" className="icon-button" onClick={() => setConfirmOpen(false)} disabled={busy}>
                Annuler
              </button>
              <button type="button" className="danger-button" onClick={removeSelected} disabled={busy}>
                <Trash2 size={16} />
                {busy ? "Suppression..." : "Confirmer la suppression"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}*/}

function RestructuredCreditsScreenV2({ user, agencies, setNotice, isCompactLayout, committeeSelectedMonth }) {
  const isCommitteeMember = user?.role === "committee_member";
  const [filters, setFilters] = useState(() => applyRoleScopeToFilters(user, {
    agency_id: "",
    agent_id: "",
    date_from: "",
    date_to: "",
    snapshot_batch_ids: "",
    q: "",
    closure_status: "",
    consecutive_bucket: "",
    anomaly: "",
    paid_last_four: "",
    offset: 0,
    limit: 20,
  }));
  const [agents, setAgents] = useState([]);
  const [snapshotOptions, setSnapshotOptions] = useState([]);
  const [familyTab, setFamilyTab] = useState("restructured");
  const [kpis, setKpis] = useState(null);
  const [qualityChart, setQualityChart] = useState({ mode: CHART_MODES.GLOBAL_BY_AGENCY, points: [] });
  const [consecutiveChart, setConsecutiveChart] = useState({ items: [] });
  const [contracts, setContracts] = useState([]);
  const [contractsTotal, setContractsTotal] = useState(0);
  const [contractsSortState, setContractsSortState] = useState({ key: null, direction: null });
  const restructuredQualityChartContainerRef = useRef(null);
  const restructuredConsecutiveChartContainerRef = useRef(null);

  const scopedFilters = useMemo(
    () => applyRoleScopeToFilters(user, filters),
    [user, filters],
  );
  const chartHeight = isCompactLayout ? 320 : 300;
  const isAgencyManager = user?.role === "agency_manager";
  const isPortfolioManager = user?.role === "portfolio_manager";
  const lockedAgencyId = (isAgencyManager || isPortfolioManager) && user?.agency_id ? String(user.agency_id) : "";
  const lockedAgentId = scopedFilters.agent_id || "";
  const filteredAgencyList = lockedAgencyId
    ? agencies.filter((agency) => String(agency.id) === String(lockedAgencyId))
    : agencies;
  const filteredAgentList = lockedAgentId
    ? agents.filter((agent) => String(agent.id) === String(lockedAgentId))
    : agents;
  const selectedSnapshotIds = useMemo(
    () =>
      String(scopedFilters.snapshot_batch_ids || "")
        .split(",")
        .map((token) => Number(token.trim()))
        .filter((value) => Number.isFinite(value) && value > 0),
    [scopedFilters.snapshot_batch_ids],
  );
  const qualityChartData = useMemo(
    () => mapChartPoints(qualityChart, CHART_MODES.GLOBAL_BY_AGENCY, null),
    [qualityChart],
  );
  const lastUpdateLabel = kpis?.last_schedule_import_at || kpis?.last_recalculated_at
    ? formatDateTimeLabel(kpis?.last_schedule_import_at || kpis?.last_recalculated_at)
    : "Aucune importation";
  const filteredPeriodText = formatFilteredPeriodLabel(scopedFilters.date_from, scopedFilters.date_to);
  const exportParams = clean({
    family: familyTab,
    agency_id: scopedFilters.agency_id,
    agent_id: scopedFilters.agent_id,
    date_from: scopedFilters.date_from,
    date_to: scopedFilters.date_to,
    snapshot_batch_ids: scopedFilters.snapshot_batch_ids,
    q: scopedFilters.q,
    closure_status: scopedFilters.closure_status,
    consecutive_bucket: scopedFilters.consecutive_bucket,
    anomaly: scopedFilters.anomaly,
    paid_last_four: scopedFilters.paid_last_four,
    sort_key: contractsSortState.key,
    sort_direction: contractsSortState.direction,
  });

  useEffect(() => {
    if (!user) return;
    const nextFilters = applyRoleScopeToFilters(user, filters);
    if (JSON.stringify(nextFilters) !== JSON.stringify(filters)) {
      setFilters(nextFilters);
    }
  }, [user]);

  useEffect(() => {
    api.agents(scopedFilters.agency_id)
      .then((page) => setAgents(page.items || []))
      .catch(() => setAgents([]));
    if (isCommitteeMember) {
      setSnapshotOptions([]);
      return;
    }
    api.snapshots(clean({ agency_id: scopedFilters.agency_id, agent_id: scopedFilters.agent_id }))
      .then((items) => setSnapshotOptions(items || []))
      .catch(() => setSnapshotOptions([]));
  }, [isCommitteeMember, scopedFilters.agency_id, scopedFilters.agent_id]);

  useEffect(() => {
    if (!isCommitteeMember) return;
    const bounds = monthBoundsFromKey(committeeSelectedMonth);
    if (!bounds) return;
    if (
      filters.date_from !== bounds.start
      || filters.date_to !== bounds.end
      || String(filters.snapshot_batch_ids || "").trim() !== ""
    ) {
      setFilters((prev) => ({
        ...prev,
        date_from: bounds.start,
        date_to: bounds.end,
        snapshot_batch_ids: "",
        offset: 0,
      }));
    }
  }, [committeeSelectedMonth, filters.date_from, filters.date_to, filters.snapshot_batch_ids, isCommitteeMember]);

  useEffect(() => {
    const baseParams = clean({
      family: familyTab,
      agency_id: scopedFilters.agency_id,
      agent_id: scopedFilters.agent_id,
      date_from: scopedFilters.date_from,
      date_to: scopedFilters.date_to,
      snapshot_batch_ids: scopedFilters.snapshot_batch_ids || undefined,
    });
    api.restructuredKpis(baseParams).then(setKpis).catch(() => setKpis(null));
    api.restructuredQualityChart(baseParams).then(setQualityChart).catch(() => setQualityChart({ mode: CHART_MODES.GLOBAL_BY_AGENCY, points: [] }));
    api.restructuredConsecutiveChart(baseParams).then(setConsecutiveChart).catch(() => setConsecutiveChart({ items: [] }));
    api.restructuredContracts(clean({
      ...baseParams,
      q: scopedFilters.q,
      closure_status: scopedFilters.closure_status,
      consecutive_bucket: scopedFilters.consecutive_bucket,
      anomaly: scopedFilters.anomaly,
      paid_last_four: scopedFilters.paid_last_four,
      sort_key: contractsSortState.key,
      sort_direction: contractsSortState.direction,
      limit: scopedFilters.limit,
      offset: scopedFilters.offset,
    }))
      .then((page) => {
        setContracts(page.items || []);
        setContractsTotal(page.total || 0);
      })
      .catch((err) => {
        setContracts([]);
        setContractsTotal(0);
        setNotice?.(err.message);
      });
  }, [
    familyTab,
    scopedFilters.agency_id,
    scopedFilters.agent_id,
    scopedFilters.date_from,
    scopedFilters.date_to,
    scopedFilters.snapshot_batch_ids,
    scopedFilters.q,
    scopedFilters.closure_status,
    scopedFilters.consecutive_bucket,
    scopedFilters.anomaly,
    scopedFilters.paid_last_four,
    contractsSortState.key,
    contractsSortState.direction,
    scopedFilters.offset,
    scopedFilters.limit,
  ]);

  function updateFilters(patch) {
    setFilters((prev) => ({ ...prev, ...patch }));
  }

  function updateDateFilter(field, value) {
    const next = { ...scopedFilters, [field]: value, offset: 0 };
    setFilters(next);
  }

  async function downloadContractsExport() {
    try {
      const { blob, filename } = await api.downloadRestructuredContractsExport(exportParams);
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = filename || (familyTab === "consolidated" ? "detail_contrats_consolides.xlsx" : "detail_contrats_restructures.xlsx");
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(href);
    } catch (err) {
      setNotice?.(err.message, { tone: "error", autoHideMs: 5000 });
    }
  }

  return (
    <>
      <section className="filter-row restructured-filter-row">
        <AgencyMultiSelect
          options={filteredAgencyList}
          selectedIds={selectedIds(isAgencyManager || isPortfolioManager ? lockedAgencyId : scopedFilters.agency_id)}
          disabled={isAgencyManager || isPortfolioManager}
          responsiveTags
          overflowLabel="agences"
          mode="reports"
          showQuickSelect
          compactSummary
          onQuickSelect={(ids) => updateFilters({ agency_id: ids, agent_id: "", offset: 0 })}
          onChange={(nextAgencyIds) => updateFilters({ agency_id: nextAgencyIds, agent_id: "", offset: 0 })}
        />
        <select
          value={isPortfolioManager ? lockedAgentId : (scopedFilters.agent_id || "")}
          disabled={isPortfolioManager}
          onChange={(e) => updateFilters({ agent_id: e.target.value, offset: 0 })}
        >
          <option value="">Tous les agents</option>
          {filteredAgentList.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
        </select>
        <div className="period-filter-indicator" aria-live="polite">
          <CalendarDays size={14} />
          <span>{filteredPeriodText}</span>
        </div>
        {!isCommitteeMember && (
          <>
            <input type="date" value={scopedFilters.date_from || ""} onChange={(e) => updateDateFilter("date_from", e.target.value)} />
            <input type="date" value={scopedFilters.date_to || ""} onChange={(e) => updateDateFilter("date_to", e.target.value)} />
             {/*<label className="snapshot-select">
              <span>Snapshots</span>
              <SnapshotMultiSelect
                options={snapshotOptions}
                selectedIds={selectedSnapshotIds}
                disabled={snapshotOptions.length === 0}
                onChange={(ids) => updateFilters({ snapshot_batch_ids: ids.join(","), offset: 0 })}
              />
            </label> */}
          </>
        )}
        <div className="state-date-pill">
          <CalendarDays size={14} />
          Derniere mise a jour : {lastUpdateLabel}
        </div>
      </section>

      <section className="panel table-panel">
        <div className="panel-header">
          <div>
            <h3>Suivi des credits restructures et consolides</h3>
            <p className="chart-subtitle">Le module affiche et analyse les donnees deja importees depuis la section Importation.</p>
          </div>
          <div className="segment-control table-mode">
            <button type="button" className={familyTab === "restructured" ? "segment-active" : ""} onClick={() => { setFamilyTab("restructured"); setFilters((prev) => ({ ...prev, offset: 0 })); }}>
              Credits restructures
            </button>
            <button type="button" className={familyTab === "consolidated" ? "segment-active" : ""} onClick={() => { setFamilyTab("consolidated"); setFilters((prev) => ({ ...prev, offset: 0 })); }}>
              Credits consolides
            </button>
          </div>
        </div>
      </section>

      <section className="kpi-grid expanded restructured-kpi-grid">
        <Metric label="Suppose cloture" value={money(kpis?.supposed_closed || 0)} />
        <Metric label="Paye 4 dernieres echeances" value={money(kpis?.paid_last_four_yes || 0)} />
        <Metric label="Nombre de credits" value={money(kpis?.disbursement_count || 0)} count={kpis?.disbursements_count || 0} />
        <Metric label="Encours" value={money(kpis?.outstanding || 0)} count={kpis?.credits_count || 0} />
        <Metric label="Encours sain" value={money(kpis?.healthy_outstanding || 0)} sub={percent(kpis?.healthy_rate || 0)} count={kpis?.healthy_count || 0} clientCount={kpis?.healthy_client_count || 0} />
        <Metric label="PAR0" value={money(kpis?.par_0 || 0)} sub={percent(kpis?.par_0_rate || 0)} tone="warn" count={kpis?.par_0_count || 0} clientCount={kpis?.par_0_client_count || 0} />
        <Metric label="PAR30" value={money(kpis?.par_30 || 0)} sub={percent(kpis?.par_30_rate || 0)} tone="risk" count={kpis?.par_30_count || 0} clientCount={kpis?.par_30_client_count || 0} />
        <Metric label="Cohorte 1-30" value={money(kpis?.par_1_30 || 0)} sub={percent(kpis?.par_1_30_rate || 0)} tone="warn" count={kpis?.par_1_30_count || 0} clientCount={kpis?.par_1_30_client_count || 0} />
        <Metric label="Cohorte 31-60" value={money(kpis?.par_31_60 || 0)} sub={percent(kpis?.par_31_60_rate || 0)} tone="risk" count={kpis?.par_31_60_count || 0} clientCount={kpis?.par_31_60_client_count || 0} />
        <Metric label="Cohorte 61-90" value={money(kpis?.par_61_90 || 0)} sub={percent(kpis?.par_61_90_rate || 0)} tone="risk" count={kpis?.par_61_90_count || 0} clientCount={kpis?.par_61_90_client_count || 0} />
        <Metric label="Cohorte 91-120" value={money(kpis?.par_91_120 || 0)} sub={percent(kpis?.par_91_120_rate || 0)} tone="risk" count={kpis?.par_91_120_count || 0} clientCount={kpis?.par_91_120_client_count || 0} />
        <Metric label="PAR120" value={money(kpis?.par_120 || 0)} sub={percent(kpis?.par_120_rate || 0)} tone="risk" count={kpis?.par_120_count || 0} clientCount={kpis?.par_120_client_count || 0} />
        <Metric label="Potentielle Radiable" value={money(kpis?.potentially_radiable_volume || 0)} sub={percent(kpis?.potentially_radiable_rate || 0)} tone="risk" count={kpis?.potential_radiable_loan_count || 0} clientCount={kpis?.potential_radiable_client_count || 0} />
      </section>

      <section className="restructured-chart-grid restructured-chart-grid-rich">
        <div className="panel chart-panel">
          <h3>Qualite portefeuille par agence</h3>
          <p className="chart-subtitle">Meme palette, memes cohortes et memes tooltips que le Dashboard principal.</p>
          {qualityChartData.length === 0 ? (
            <div className="chart-empty">Aucune donnee portefeuille disponible pour ce filtre.</div>
          ) : (
            <div ref={restructuredQualityChartContainerRef} className="chart-tooltip-shell">
              <ResponsiveContainer width="100%" height={chartHeight}>
                <ComposedChart
                  data={qualityChartData}
                  margin={{ top: 16, right: 28, bottom: 8, left: 0 }}
                  reverseStackOrder={false}
                  barCategoryGap="18%"
                >
                  <CartesianGrid strokeDasharray="4 4" stroke="#d6e0ee" />
                  <XAxis dataKey="name" tick={{ fill: "#52617a", fontSize: 12 }} angle={-20} textAnchor="end" height={58} />
                  <YAxis tick={{ fill: "#52617a", fontSize: 12 }} tickFormatter={(value) => `${Number(value).toFixed(0)}%`} />
                  <Tooltip
                    content={<QualityPortfolioTooltip containerRef={restructuredQualityChartContainerRef} />}
                    allowEscapeViewBox={{ x: true, y: true }}
                    isAnimationActive={false}
                  />
                  <Legend />
                  {RISK_STACK_SERIES.map((serie, index) => (
                    <Bar
                      key={serie.key}
                      dataKey={serie.key}
                      stackId="risk"
                      name={serie.label}
                      fill={serie.color}
                      maxBarSize={56}
                      radius={index === RISK_STACK_SERIES.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]}
                    />
                  ))}
                  <Line type="monotone" dataKey="par0Rate" name="PAR0 (%)" stroke="#ff6b2c" strokeWidth={3} dot={{ r: 3 }} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
        <div className="panel chart-panel">
          <h3>Repartition echeances consecutives</h3>
          <p className="chart-subtitle">0 / 1-2 / 3 / 4+ echeances payees en capital apres decalage.</p>
          <div ref={restructuredConsecutiveChartContainerRef} className="chart-tooltip-shell">
            <ResponsiveContainer width="100%" height={chartHeight}>
              <BarChart data={consecutiveChart.items} margin={{ top: 10, right: 16, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="4 4" stroke="#d6e0ee" />
                <XAxis dataKey="label" tick={{ fill: "#52617a", fontSize: 12 }} />
                <YAxis tick={{ fill: "#52617a", fontSize: 12 }} allowDecimals={false} />
                <Tooltip
                  content={<RestructuredBarsTooltip metricLabel="Contrats" containerRef={restructuredConsecutiveChartContainerRef} />}
                  isAnimationActive={false}
                />
                <Legend />
                <Bar dataKey="value" name="Contrats" radius={[6, 6, 0, 0]}>
                  {consecutiveChart.items.map((entry) => (
                    <Cell key={entry.label} fill={entry.color || "#2563eb"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>

      <section className="panel table-panel">
        <div className="panel-header">
          <h3>Detail des contrats {familyTab === "consolidated" ? "consolides" : "restructures"}</h3>
          <div className="table-tools">
            <button className="icon-button" type="button" onClick={downloadContractsExport}>
              <FileDown size={16} />
              Exporter Excel
            </button>
          </div>
        </div>

        <div className="restructured-tools-grid restructured-tools-grid-wide">
          <label className="search-box">
            <Search size={16} />
            <input
              placeholder="Recherche contrat, client, agence, GP, anomalie..."
              value={scopedFilters.q || ""}
              onChange={(e) => updateFilters({ q: e.target.value, offset: 0 })}
            />
          </label>
          <select value={scopedFilters.closure_status || ""} onChange={(e) => updateFilters({ closure_status: e.target.value, offset: 0 })}>
            <option value="">Tous les statuts cloture</option>
            <option value="Suppose cloture">Suppose cloture</option>
            <option value="En cours">En cours</option>
            <option value="N/A">N/A</option>
          </select>
          <select value={scopedFilters.consecutive_bucket || ""} onChange={(e) => updateFilters({ consecutive_bucket: e.target.value, offset: 0 })}>
            <option value="">Toutes les series</option>
            <option value="0">0</option>
            <option value="1-2">1-2</option>
            <option value="3">3</option>
            <option value="4+">4+</option>
          </select>
          <select value={scopedFilters.anomaly || ""} onChange={(e) => updateFilters({ anomaly: e.target.value, offset: 0 })}>
            <option value="">Anomalie : toutes</option>
            <option value="Oui">Oui</option>
            <option value="Non">Non</option>
          </select>
          <select value={scopedFilters.paid_last_four || ""} onChange={(e) => updateFilters({ paid_last_four: e.target.value, offset: 0 })}>
            <option value="">4 dernieres echeances : toutes</option>
            <option value="Oui">Oui</option>
            <option value="Non">Non</option>
            <option value="N/A">N/A</option>
          </select>
        </div>
        <div className="table-scroll">
          <RestructuredContractsTable rows={contracts} />
        </div>
        <Pager
          total={contractsTotal}
          limit={scopedFilters.limit}
          offset={scopedFilters.offset}
          onPage={(offset) => updateFilters({ offset })}
          onLimitChange={(limit) => updateFilters({ limit, offset: 0 })}
        />
      </section>
    </>
  );
}

function ResponsiveChartTooltip({
  active,
  coordinate,
  containerRef,
  className = "",
  children,
}) {
  const tooltipRef = useRef(null);
  const [position, setPosition] = useState({ left: -9999, top: -9999, placement: "right-bottom" });

  useLayoutEffect(() => {
    if (!active || !coordinate || !containerRef?.current || !tooltipRef.current) return undefined;

    const updatePosition = () => {
      const tooltipNode = tooltipRef.current;
      const containerNode = containerRef.current;
      if (!tooltipNode || !containerNode) return;

      const containerRect = containerNode.getBoundingClientRect();
      const tooltipWidth = tooltipNode.offsetWidth || 320;
      const tooltipHeight = tooltipNode.offsetHeight || 220;
      const anchorX = containerRect.left + Number(coordinate.x || 0);
      const anchorY = containerRect.top + Number(coordinate.y || 0);
      const gap = 16;
      const padding = 10;
      const viewportMargin = 16;
      const halfContainer = containerRect.left + (containerRect.width / 2);
      const prefersRight = anchorX <= halfContainer;
      const prefersBelow = (anchorY - containerRect.top) < (containerRect.height / 2);
      const minLeft = Math.max(viewportMargin, containerRect.left + padding);
      const maxLeft = Math.min(window.innerWidth - viewportMargin, containerRect.right - padding) - tooltipWidth;
      const minTop = Math.max(viewportMargin, containerRect.top + padding);
      const maxTop = Math.min(window.innerHeight - viewportMargin, containerRect.bottom - padding) - tooltipHeight;
      let left = prefersRight ? anchorX + gap : anchorX - tooltipWidth - gap;
      let top = prefersBelow ? anchorY + gap : anchorY - tooltipHeight - gap;

      if (top > maxTop) {
        top = anchorY - tooltipHeight - gap;
      }
      if (top < minTop) {
        top = anchorY + gap;
      }
      if (left > maxLeft) {
        left = anchorX - tooltipWidth - gap;
      }
      if (left < minLeft) {
        left = anchorX + gap;
      }

      left = Math.min(Math.max(minLeft, left), Math.max(minLeft, maxLeft));
      top = Math.min(Math.max(minTop, top), Math.max(minTop, maxTop));

      setPosition({
        left,
        top,
        placement: `${left >= anchorX ? "right" : "left"}-${top >= anchorY ? "bottom" : "top"}`,
      });
    };

    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [active, coordinate, containerRef, children]);

  if (!active || !children) return null;

  return createPortal(
    (
      <div
        ref={tooltipRef}
        className={`chart-tooltip-card chart-tooltip-floating ${className}`.trim()}
        style={{ left: `${position.left}px`, top: `${position.top}px` }}
      >
        {children}
      </div>
    ),
    document.body,
  );
}

function RestructuredBarsTooltip({ active, payload, label, metricLabel, coordinate, containerRef }) {
  if (!active || !payload?.length) return null;
  const value = payload[0]?.value || 0;
  return (
    <ResponsiveChartTooltip active={active} coordinate={coordinate} containerRef={containerRef}>
      <strong>{label}</strong>
      <div className="tooltip-row">
        <span>{metricLabel}</span>
        <b>{money(value)}</b>
      </div>
    </ResponsiveChartTooltip>
  );
}

function RestructuredContractsTable({ rows }) {
  const columns = useMemo(() => [
    { key: "contract_no", label: "N contrat", render: (item) => item.contract_no, sortableType: "text" },
    { key: "type_credit", label: "Type credit", render: (item) => item.type_credit || "-", sortableType: "text" },
    {
      key: "client_name",
      label: "Client",
      render: (item) => [item.client_name, item.client_first_name].filter(Boolean).join(" ") || "-",
      sortableType: "text",
      sortAccessor: (item) => `${item.client_name || ""} ${item.client_first_name || ""}`.trim(),
    },
    { key: "agency_name", label: "Agence", render: (item) => item.agency_name || "-", sortableType: "text" },
    { key: "agent_name", label: "GP", render: (item) => item.agent_name || "-", sortableType: "text" },
    {
      key: "dateeod",
      label: "DateEOD",
      render: (item) => shortDate(item.dateeod),
      sortableType: "date",
      sortAccessor: (item) => item.dateeod,
    },
    {
      key: "delay_date",
      label: "Date decalage",
      render: (item) => shortDate(item.delay_date),
      sortableType: "date",
      sortAccessor: (item) => item.delay_date,
    },
    {
      key: "total_due",
      label: "Total_Due",
      render: (item) => money(item.total_due),
      sortableType: "number",
      sortAccessor: (item) => item.total_due,
    },
    {
      key: "total_scheduled_amount",
      label: "Echeance",
      render: (item) => <span className="table-number-cell">{moneyDetailed(item.total_scheduled_amount)}</span>,
      sortableType: "number",
      sortAccessor: (item) => normalizeNumberValue(item.total_scheduled_amount),
    },
    {
      key: "loan_duration",
      label: "LOAN_DURATION",
      render: (item) => item.loan_duration ?? "-",
      sortableType: "number",
      sortAccessor: (item) => item.loan_duration,
    },
    {
      key: "encours",
      label: "Encours",
      render: (item) => money(item.encours),
      sortableType: "number",
      sortAccessor: (item) => item.encours,
    },
    {
      key: "healthy_outstanding",
      label: "Encours sain",
      render: (item) => money(item.healthy_outstanding),
      sortableType: "number",
      sortAccessor: (item) => item.healthy_outstanding,
    },
    {
      key: "days_overdue",
      label: "Jours retard",
      render: (item) => item.days_overdue ?? "-",
      sortableType: "number",
      sortAccessor: (item) => item.days_overdue,
    },
    { key: "cohort_label", label: "Cohorte", render: (item) => item.cohort_label || "-", sortableType: "text" },
    { key: "par_label", label: "PAR", render: (item) => item.par_label || "-", sortableType: "text" },
    {
      key: "consecutive_paid_count",
      label: "Serie max",
      render: (item) => {
        const bucket = item.consecutive_paid_count <= 0
          ? "0"
          : item.consecutive_paid_count <= 2
            ? "1-2"
            : item.consecutive_paid_count === 3
              ? "3"
              : "4+";
        return <span className={`streak-chip streak-${String(bucket).replace("+", "plus").replace("-", "_")}`}>{item.consecutive_paid_count}</span>;
      },
      sortableType: "number",
      sortAccessor: (item) => item.consecutive_paid_count,
    },
    { key: "max_series_installments", label: "N echeances", render: (item) => item.max_series_installments || "-", sortableType: "text" },
    { key: "max_series_dates", label: "Dates echeances", render: (item) => item.max_series_dates || "-", sortableType: "text" },
    {
      key: "anomaly_detected",
      label: "Anomalie",
      render: (item) => <span className={`status-chip ${item.anomaly_detected ? "status-chip-danger" : "status-chip-neutral"}`}>{item.anomaly_detected ? "Oui" : "Non"}</span>,
      sortableType: "number",
      sortAccessor: (item) => (item.anomaly_detected ? 1 : 0),
      filterType: "boolean",
      filterAccessor: (item) => String(Boolean(item.anomaly_detected)),
      filterOptions: [{ value: "true", label: "Oui" }, { value: "false", label: "Non" }],
    },
    { key: "anomaly_detail", label: "Detail anomalie", render: (item) => item.anomaly_detail || "-", sortableType: "text" },
    {
      key: "paid_last_four_status",
      label: "4 dernieres echeances",
      render: (item) => <span className={`status-chip ${statusChipClass(item.paid_last_four_status)}`}>{item.paid_last_four_status}</span>,
      sortableType: "text",
      sortAccessor: (item) => item.paid_last_four_status,
      filterType: "enum",
      filterAccessor: (item) => item.paid_last_four_status,
    },
    {
      key: "last_paid_installment_no",
      label: "Derniere echeance payee",
      render: (item) => item.last_paid_installment_no ?? "-",
      sortableType: "number",
      sortAccessor: (item) => item.last_paid_installment_no,
    },
    {
      key: "last_paid_due_date",
      label: "Date derniere echeance",
      render: (item) => shortDate(item.last_paid_due_date),
      sortableType: "date",
      sortAccessor: (item) => item.last_paid_due_date,
    },
    {
      key: "closure_status",
      label: "Statut cloture",
      render: (item) => <span className={`status-chip ${statusChipClass(item.closure_status)}`}>{item.closure_status}</span>,
      sortableType: "text",
      sortAccessor: (item) => item.closure_status,
      filterType: "enum",
      filterAccessor: (item) => item.closure_status,
    },
  ], []);
  const {
    sortState,
    sortedRows,
    columnFilters,
    activeFilterCount,
    applySort,
    updateFilter,
    resetFilter,
    resetAllFilters,
  } = useAdvancedTableState(rows, columns);

  return (
    <>
      {activeFilterCount > 0 && (
        <div className="table-filter-summary">
          <span>{activeFilterCount} filtre(s) actif(s)</span>
          <button type="button" className="icon-button" onClick={resetAllFilters}>Reinitialiser tous les filtres</button>
        </div>
      )}
      <table className="credits-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <SortableHeader
                key={column.key}
                label={column.label}
                columnKey={column.key}
                sortState={sortState}
                sortableType={column.sortableType}
                onToggle={applySort}
                rows={rows}
                column={column}
                filterState={columnFilters[column.key]}
                onFilterChange={(nextFilter) => updateFilter(column.key, nextFilter)}
                onFilterReset={() => resetFilter(column.key)}
              />
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((item) => (
            <tr key={item.contract_no}>
              {columns.map((column) => (
                <td key={`${item.contract_no}-${column.key}`}>{column.render(item)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function MissingMcrContractsTableSection({
  rows,
  total,
  loading,
  search,
  onSearchChange,
  sortState,
  onSortChange,
  columnFilters,
  onFilterChange,
  onFilterReset,
  onResetAllFilters,
  limit,
  offset,
  onPage,
  onLimitChange,
  onExport,
  canDeleteMissingMcr = false,
  onDeleteMissingMcr,
  deletingMissingMcr = false,
}) {
  const [selectedContractNos, setSelectedContractNos] = useState([]);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const allowed = new Set(rows.map((item) => item.contract_no));
    setSelectedContractNos((current) => current.filter((value) => allowed.has(value)));
  }, [rows]);

  function toggleContract(contractNo) {
    if (!contractNo) return;
    setSelectedContractNos((current) => (
      current.includes(contractNo)
        ? current.filter((value) => value !== contractNo)
        : [...current, contractNo]
    ));
  }

  function toggleSelectAll() {
    const allContractNos = rows.map((item) => item.contract_no).filter(Boolean);
    const allSelected = allContractNos.length > 0 && allContractNos.every((no) => selectedContractNos.includes(no));
    setSelectedContractNos(allSelected ? [] : allContractNos);
  }

  const visibleContractNos = useMemo(
    () => rows.map((item) => item.contract_no).filter(Boolean),
    [rows],
  );
  const allOnPageSelected = visibleContractNos.length > 0
    && visibleContractNos.every((no) => selectedContractNos.includes(no));
  const someOnPageSelected = visibleContractNos.some((no) => selectedContractNos.includes(no));
  const headerCheckboxRef = useRef(null);
  useEffect(() => {
    if (headerCheckboxRef.current) {
      headerCheckboxRef.current.indeterminate = !allOnPageSelected && someOnPageSelected;
    }
  }, [allOnPageSelected, someOnPageSelected]);

  async function confirmDelete() {
    if (!Array.isArray(selectedContractNos) || selectedContractNos.length === 0) {
      setConfirmOpen(false);
      return;
    }
    setBusy(true);
    try {
      if (onDeleteMissingMcr) {
        await onDeleteMissingMcr(selectedContractNos);
      }
      setSelectedContractNos([]);
      setConfirmOpen(false);
    } catch {
      // notice already surfaced by parent
    } finally {
      setBusy(false);
    }
  }

  const columns = useMemo(() => [
    { key: "contract_no", label: "Numero de contrat", render: (item) => item.contract_no, sortableType: "text" },
    {
      key: "type_credit",
      label: "Type de credit",
      render: (item) => item.type_credit || "-",
      sortableType: "text",
      filterType: "enum",
      filterAccessor: (item) => item.type_credit || "",
      filterOptions: [
        { value: "Credit restructure", label: "Credit restructure" },
        { value: "Credit consolide", label: "Credit consolide" },
      ],
    },
    { key: "category_desc", label: "CATEGORY_DESC", render: (item) => item.category_desc || "-", sortableType: "text", filterType: "text" },
    {
      key: "delay_date",
      label: "Date de decalage",
      render: (item) => shortDate(item.delay_date),
      sortableType: "date",
      sortAccessor: (item) => item.delay_date,
      filterType: "date",
    },
    {
      key: "total_due",
      label: "Total Due",
      render: (item) => <span className="table-number-cell">{moneyDetailed(item.total_due)}</span>,
      sortableType: "number",
      sortAccessor: (item) => item.total_due,
      filterType: "number",
    },
    {
      key: "loan_duration",
      label: "LOAN_DURATION",
      render: (item) => <span className="table-number-cell">{item.loan_duration ?? "-"}</span>,
      sortableType: "number",
      sortAccessor: (item) => item.loan_duration,
      filterType: "number",
    },
    {
      key: "source",
      label: "Source",
      render: (item) => item.source || "-",
      sortableType: "text",
      filterType: "text",
    },
    {
      key: "detected_at",
      label: "Date de detection",
      render: (item) => formatDateTimeLabel(item.detected_at) || "-",
      sortableType: "date",
      sortAccessor: (item) => item.detected_at,
      filterType: "date",
    },
  ], []);
  const activeFilterCount = useMemo(
    () => countActiveColumnFilters(columnFilters, columns),
    [columnFilters, columns],
  );

  return (
    <section className="panel table-panel">
      <div className="panel-header">
        <div>
          <h3>Contrats absents du MCR</h3>
          <p className="muted">
            Contrats presents dans la liste officielle mais absents du MCR actif apres normalisation.
          </p>
        </div>
        <div className="button-row wrap">
          <span className="count-badge">{money(total)}</span>
          {canDeleteMissingMcr && (
            <button
              type="button"
              className="danger-button fit"
              disabled={selectedContractNos.length === 0 || busy || deletingMissingMcr}
              onClick={() => setConfirmOpen(true)}
            >
              <Trash2 size={16} />
              Supprimer la selection ({selectedContractNos.length})
            </button>
          )}
          <button type="button" className="icon-button" onClick={onExport}>
            <FileDown size={16} />
            Exporter Excel
          </button>
        </div>
      </div>
      <div className="restructured-tools-grid restructured-tools-grid-wide">
        <label className="search-box">
          <Search size={16} />
          <input
            placeholder="Recherche par contrat, type, categorie ou source..."
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
          />
        </label>
      </div>
      {activeFilterCount > 0 && (
        <div className="table-filter-summary">
          <span>{activeFilterCount} filtre(s) actif(s)</span>
          <button type="button" className="icon-button" onClick={onResetAllFilters}>Reinitialiser tous les filtres</button>
        </div>
      )}
      <div className="table-scroll">
        <table className="credits-table">
          <thead>
            <tr>
              {canDeleteMissingMcr && (
                <th className="select-cell">
                  <input
                    ref={headerCheckboxRef}
                    type="checkbox"
                    aria-label="Selectionner tous les contrats affiches"
                    checked={allOnPageSelected}
                    onChange={toggleSelectAll}
                    disabled={visibleContractNos.length === 0}
                  />
                </th>
              )}
              {columns.map((column) => (
                <SortableHeader
                  key={column.key}
                  label={column.label}
                  columnKey={column.key}
                  sortState={sortState}
                  onToggle={onSortChange}
                  rows={rows}
                  column={column}
                  filterState={columnFilters[column.key]}
                  onFilterChange={(nextFilter) => onFilterChange(column.key, nextFilter)}
                  onFilterReset={() => onFilterReset(column.key)}
                />
              ))}
            </tr>
          </thead>
          <tbody>
            {!loading && rows.map((item) => {
              const isSelected = selectedContractNos.includes(item.contract_no);
              return (
                <tr key={`${item.contract_no}-${item.type_credit}-${item.detected_at || "na"}`}>
                  {canDeleteMissingMcr && (
                    <td className="select-cell">
                      <input
                        type="checkbox"
                        aria-label={`Selectionner le contrat ${item.contract_no}`}
                        checked={isSelected}
                        onChange={() => toggleContract(item.contract_no)}
                        disabled={!item.contract_no}
                      />
                    </td>
                  )}
                  {columns.map((column) => (
                    <td key={`${item.contract_no}-${column.key}`}>{column.render(item)}</td>
                  ))}
                </tr>
              );
            })}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={columns.length + (canDeleteMissingMcr ? 1 : 0)} className="muted">Aucun contrat absent du MCR actif.</td>
              </tr>
            )}
            {loading && (
              <tr>
                <td colSpan={columns.length + (canDeleteMissingMcr ? 1 : 0)} className="muted">Chargement des contrats absents du MCR...</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <Pager
        total={total}
        limit={limit}
        offset={offset}
        onPage={onPage}
        onLimitChange={onLimitChange}
      />
      {confirmOpen && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="missing-mcr-delete-title">
          <div className="modal-card">
            <div className="modal-title">
              <AlertTriangle size={18} />
              <h3 id="missing-mcr-delete-title">Supprimer les contrats selectionnes ?</h3>
            </div>
            <p className="muted">
              {selectedContractNos.length} contrat(s) seront supprimes de la base.
              Les contrats ne sont pas supprimes definitivement ; ils sont marques comme exclus de cette vue.
            </p>
            {selectedContractNos.length > 0 && (
              <ul className="modal-list-preview">
                {selectedContractNos.slice(0, 5).map((contractNo) => (
                  <li key={contractNo}>{contractNo}</li>
                ))}
                {selectedContractNos.length > 5 && <li>... et {selectedContractNos.length - 5} autre(s)</li>}
              </ul>
            )}
            <div className="button-row">
              <button type="button" className="icon-button" onClick={() => setConfirmOpen(false)} disabled={busy || deletingMissingMcr}>
                Annuler
              </button>
              <button
                type="button"
                className="danger-button"
                onClick={confirmDelete}
                disabled={busy || deletingMissingMcr || selectedContractNos.length === 0}
              >
                <Trash2 size={16} />
                {busy || deletingMissingMcr ? "Suppression..." : "Confirmer la suppression"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function statusChipClass(value) {
  if (value === "Oui" || value === "Supposé cloturé" || value === "Suppose cloture") return "status-chip-success";
  if (value === "Non") return "status-chip-danger";
  if (value === "En cours") return "status-chip-info";
  return "status-chip-neutral";
}

function SnapshotMultiSelect({ options, selectedIds, onChange, disabled }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);

  const selectedItems = useMemo(
    () => options.filter((item) => selectedIds.includes(Number(item.batch_id))),
    [options, selectedIds],
  );

  useEffect(() => {
    function handleOutside(event) {
      if (!rootRef.current?.contains(event.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("touchstart", handleOutside, { passive: true });
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("touchstart", handleOutside);
    };
  }, []);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  function setSelected(nextIds) {
    const normalized = Array.from(new Set(nextIds.filter((id) => Number.isFinite(id) && id > 0)));
    onChange(normalized);
  }

  function toggleSelection(id) {
    if (selectedIds.includes(id)) {
      setSelected(selectedIds.filter((currentId) => currentId !== id));
      return;
    }
    setSelected([...selectedIds, id]);
  }

  return (
    <div className="snapshot-combobox" ref={rootRef}>
      <button
        type="button"
        className="snapshot-combobox-trigger"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
      >
        <span className="snapshot-trigger-values">
          {selectedItems.length === 0 ? (
            <span className="snapshot-placeholder">
              {disabled ? "Aucune snapshot disponible" : "Selectionner des snapshots"}
            </span>
          ) : (
            selectedItems.map((item) => (
              <span key={item.batch_id} className="snapshot-inline-badge">
                {item.label}
                <button
                  type="button"
                  className="snapshot-inline-remove"
                  aria-label={`Retirer ${item.label}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    toggleSelection(Number(item.batch_id));
                  }}
                >
                  <X size={12} />
                </button>
              </span>
            ))
          )}
        </span>
        <ChevronDown size={16} />
      </button>

      {open && !disabled && (
        <div className="snapshot-combobox-menu" role="listbox" aria-multiselectable="true">
          {options.map((item) => {
            const optionId = Number(item.batch_id);
            const isSelected = selectedIds.includes(optionId);
            return (
              <button
                key={item.batch_id}
                type="button"
                role="option"
                aria-selected={isSelected}
                className={`snapshot-option ${isSelected ? "selected" : ""}`}
                onClick={() => toggleSelection(optionId)}
              >
                <span className={`snapshot-option-check ${isSelected ? "on" : ""}`} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function SectorMultiSelect({ options, selectedIds, onChange, disabled }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);

  const selectedItems = useMemo(
    () => options.filter((item) => selectedIds.includes(String(item.id))),
    [options, selectedIds],
  );

  const allSelected = useMemo(
    () => options.length > 0 && selectedItems.length === options.length,
    [options, selectedItems],
  );

  const summaryText = useMemo(() => {
    if (selectedItems.length === 0) return "Tous les secteurs";
    if (allSelected) return "Tous les secteurs";
    if (selectedItems.length === 1) return selectedItems[0].name;
    return `${selectedItems.length} secteurs selectionnes`;
  }, [selectedItems, allSelected]);

  useEffect(() => {
    function handleOutside(event) {
      if (!rootRef.current?.contains(event.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("touchstart", handleOutside, { passive: true });
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("touchstart", handleOutside);
    };
  }, []);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  function setSelected(nextIds) {
    const normalized = Array.from(new Set(nextIds.map((id) => String(id).trim()).filter(Boolean)));
    onChange(normalized.join(","));
  }

  function toggleSelection(id) {
    const idStr = String(id);
    const nextSelected = selectedIds.includes(idStr)
      ? selectedIds.filter((currentId) => currentId !== idStr)
      : [...selectedIds, idStr];
    setSelected(nextSelected);
  }

  return (
    <div className="snapshot-combobox" ref={rootRef}>
      <button
        type="button"
        className="snapshot-combobox-trigger snapshot-combobox-trigger-compact"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
      >
        <span className="snapshot-trigger-values-compact">
          <span className="snapshot-placeholder" title={summaryText}>
            {summaryText}
          </span>
        </span>
        <ChevronDown size={16} />
      </button>

      {open && !disabled && (
        <div className="snapshot-combobox-menu" role="listbox" aria-multiselectable="true">
          {options.map((item) => {
            const optionId = String(item.id);
            const isSelected = selectedIds.includes(optionId);
            return (
              <button
                key={item.id}
                type="button"
                role="option"
                aria-selected={isSelected}
                className={`snapshot-option ${isSelected ? "selected" : ""}`}
                onClick={() => toggleSelection(item.id)}
              >
                <span className={`snapshot-option-check ${isSelected ? "on" : ""}`} />
                <span>{item.name}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function AgencyMultiSelect({
  options,
  selectedIds: selectedAgencyIds,
  onChange,
  disabled,
  responsiveTags = false,
  overflowLabel = "agences",
  showQuickSelect = false,
  onQuickSelect,
  mode = "dashboard",
  compactSummary = false,
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const triggerRef = useRef(null);
  const measureRef = useRef(null);
  const [visibleCount, setVisibleCount] = useState(selectedAgencyIds.length);

  const selectedItems = useMemo(
    () => options.filter((item) => selectedAgencyIds.includes(String(item.id))),
    [options, selectedAgencyIds],
  );

  useEffect(() => {
    function handleOutside(event) {
      if (!rootRef.current?.contains(event.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("touchstart", handleOutside, { passive: true });
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("touchstart", handleOutside);
    };
  }, []);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  // Responsive mode: compute how many chips fit in the available trigger
  // width, then collapse the remaining selections into a "+N agences" badge.
  const selectionKey = selectedAgencyIds.join("|");
  useLayoutEffect(() => {
    if (!responsiveTags) return undefined;
    const trigger = triggerRef.current;
    const measure = measureRef.current;
    if (!trigger || !measure) return undefined;

    function recompute() {
      const chipNodes = Array.from(measure.querySelectorAll("[data-measure-chip]"));
      const total = chipNodes.length;
      if (!total) {
        setVisibleCount(0);
        return;
      }
      const triggerStyle = window.getComputedStyle(trigger);
      const horizontalPadding =
        (parseFloat(triggerStyle.paddingLeft) || 0) + (parseFloat(triggerStyle.paddingRight) || 0);
      const gap = 6;
      const chevronReserve = 28;
      const overflowBadgeReserve = 96;
      const available = Math.max(0, trigger.clientWidth - horizontalPadding - chevronReserve);
      let used = 0;
      let count = 0;
      for (let index = 0; index < total; index += 1) {
        const chipWidth = chipNodes[index].offsetWidth + gap;
        const remaining = total - (index + 1);
        const projected = used + chipWidth + (remaining > 0 ? overflowBadgeReserve : 0);
        if (projected <= available) {
          used += chipWidth;
          count += 1;
        } else {
          break;
        }
      }
      setVisibleCount(count);
    }

    recompute();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", recompute);
      return () => window.removeEventListener("resize", recompute);
    }
    const observer = new ResizeObserver(recompute);
    observer.observe(trigger);
    return () => observer.disconnect();
  }, [responsiveTags, selectionKey, options.length, disabled]);

  function setSelected(nextIds) {
    const normalized = Array.from(new Set(nextIds.map((id) => String(id).trim()).filter(Boolean)));
    onChange(joinSelectedIds(normalized));
  }

  function toggleSelection(id) {
    const nextSelected = selectedAgencyIds.includes(String(id))
      ? selectedAgencyIds.filter((currentId) => currentId !== String(id))
      : [...selectedAgencyIds, String(id)];
    setSelected(nextSelected);
  }

  const safeVisibleCount = Math.max(0, Math.min(visibleCount, selectedItems.length));
  const visibleItems = responsiveTags ? selectedItems.slice(0, safeVisibleCount) : selectedItems;
  const hiddenCount = selectedItems.length - visibleItems.length;
  const hiddenTitles = selectedItems.slice(visibleItems.length).map((item) => item.name).join(", ");

  const allOptionIds = useMemo(
    () => options.map((item) => String(item.id)),
    [options],
  );
  const nordOptionIds = useMemo(
    () => options
      .filter((item) => isNordAgency(item.name))
      .map((item) => String(item.id)),
    [options],
  );
  const sudOptionIds = useMemo(
    () => options
      .filter((item) => !isNordAgency(item.name))
      .map((item) => String(item.id)),
    [options],
  );

  const summaryLabel = useMemo(() => {
    if (selectedAgencyIds.length === 0) return null;
    if (allOptionIds.length > 0 && selectedAgencyIds.length === allOptionIds.length) {
      if (mode === "reports") return "Toutes les agences";
      return null;
    }
    if (nordOptionIds.length > 0 && selectedAgencyIds.length === nordOptionIds.length && nordOptionIds.every((id) => selectedAgencyIds.includes(id))) {
      return "Région Nord";
    }
    if (sudOptionIds.length > 0 && selectedAgencyIds.length === sudOptionIds.length && sudOptionIds.every((id) => selectedAgencyIds.includes(id))) {
      return "Région Sud";
    }
    return `${selectedAgencyIds.length} agence(s)`;
  }, [selectedAgencyIds, allOptionIds, nordOptionIds, sudOptionIds, mode]);

  function handleQuickSelect(kind) {
    if (!onQuickSelect) return;
    let ids;
    if (kind === "all") ids = allOptionIds;
    else if (kind === "nord") ids = nordOptionIds;
    else if (kind === "sud") ids = sudOptionIds;
    else return;
    onQuickSelect(ids);
  }

  return (
    <div className="snapshot-combobox" ref={rootRef}>
      <button
        type="button"
        ref={triggerRef}
        className={`snapshot-combobox-trigger${responsiveTags ? " snapshot-combobox-trigger-compact" : ""}`}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
      >
        <span className={`snapshot-trigger-values${responsiveTags || compactSummary ? " snapshot-trigger-values-compact" : ""}`}>
          {selectedItems.length === 0 ? (
            <span className="snapshot-placeholder">
              {disabled ? "Aucune agence disponible" : (mode === "reports" ? "Toutes les agences" : "Toutes les agences")}
            </span>
          ) : compactSummary ? (
            <span className="snapshot-summary-label">{summaryLabel || `${selectedItems.length} agence(s)`}</span>
          ) : (
            <>
              {visibleItems.map((item) => (
                <span key={item.id} className="snapshot-inline-badge">
                  {item.name}
                  <button
                    type="button"
                    className="snapshot-inline-remove"
                    aria-label={`Retirer ${item.name}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      toggleSelection(item.id);
                    }}
                  >
                    <X size={12} />
                  </button>
                </span>
              ))}
              {hiddenCount > 0 && (
                <button
                  type="button"
                  className="snapshot-overflow-badge"
                  title={hiddenTitles}
                  onClick={(event) => {
                    event.stopPropagation();
                    setOpen(true);
                  }}
                >
                  +{hiddenCount} {overflowLabel}
                </button>
              )}
            </>
          )}
        </span>
        <ChevronDown size={16} />
      </button>

      {responsiveTags && !compactSummary && selectedItems.length > 0 && (
        <span className="snapshot-measure" aria-hidden="true" ref={measureRef}>
          {selectedItems.map((item) => (
            <span key={item.id} className="snapshot-inline-badge" data-measure-chip="true">
              {item.name}
              <span className="snapshot-inline-remove">
                <X size={12} />
              </span>
            </span>
          ))}
        </span>
      )}

      {open && !disabled && (
        <div className="snapshot-combobox-menu" role="listbox" aria-multiselectable="true">
          {showQuickSelect && (
            <>
              {mode === "reports" && (
                <button
                  type="button"
                  className="snapshot-option snapshot-quick-select"
                  role="option"
                  aria-selected={allOptionIds.length > 0 && allOptionIds.every((id) => selectedAgencyIds.includes(id))}
                  onClick={() => handleQuickSelect("all")}
                >
                  <span className="snapshot-option-check" />
                  Toutes les agences ({allOptionIds.length})
                </button>
              )}
              <button
                type="button"
                className="snapshot-option snapshot-quick-select"
                role="option"
                aria-selected={nordOptionIds.length > 0 && nordOptionIds.every((id) => selectedAgencyIds.includes(id))}
                onClick={() => handleQuickSelect("nord")}
              >
                <span className="snapshot-option-check" />
                Région Nord ({nordOptionIds.length})
              </button>
              <button
                type="button"
                className="snapshot-option snapshot-quick-select"
                role="option"
                aria-selected={sudOptionIds.length > 0 && sudOptionIds.every((id) => selectedAgencyIds.includes(id))}
                onClick={() => handleQuickSelect("sud")}
              >
                <span className="snapshot-option-check" />
                Région Sud ({sudOptionIds.length})
              </button>
              <div className="snapshot-divider" />
            </>
          )}
          {options.map((item) => {
            const optionId = String(item.id);
            const isSelected = selectedAgencyIds.includes(optionId);
            return (
              <button
                key={item.id}
                type="button"
                role="option"
                aria-selected={isSelected}
                className={`snapshot-option ${isSelected ? "selected" : ""}`}
                onClick={() => toggleSelection(optionId)}
              >
                <span className={`snapshot-option-check ${isSelected ? "on" : ""}`} />
                <span>{item.name}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function RiskCategoryMultiSelect({ options, selectedValues, onChange }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);

  const selectedItems = useMemo(
    () => options.filter((item) => selectedValues.includes(item.value)),
    [options, selectedValues],
  );

  useEffect(() => {
    function handleOutside(event) {
      if (!rootRef.current?.contains(event.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("touchstart", handleOutside, { passive: true });
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("touchstart", handleOutside);
    };
  }, []);

  function setSelected(nextValues) {
    const allowedValues = new Set(options.map((item) => item.value));
    const normalized = Array.from(new Set(nextValues.filter((value) => allowedValues.has(value))));
    onChange(normalized);
  }

  function toggleSelection(value) {
    if (selectedValues.includes(value)) {
      setSelected(selectedValues.filter((currentValue) => currentValue !== value));
      return;
    }
    setSelected([...selectedValues, value]);
  }

  return (
    <div className="snapshot-combobox" ref={rootRef}>
      <button
        type="button"
        className="snapshot-combobox-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
      >
        <span className="snapshot-trigger-values">
          {selectedItems.length === 0 ? (
            <span className="snapshot-placeholder">Toutes les categories</span>
          ) : (
            selectedItems.map((item) => (
              <span key={item.value} className="snapshot-inline-badge">
                {item.label}
                <button
                  type="button"
                  className="snapshot-inline-remove"
                  aria-label={`Retirer ${item.label}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    toggleSelection(item.value);
                  }}
                >
                  <X size={12} />
                </button>
              </span>
            ))
          )}
        </span>
        <ChevronDown size={16} />
      </button>

      {open && (
        <div className="snapshot-combobox-menu" role="listbox" aria-multiselectable="true">
          {options.map((item) => {
            const optionId = String(item.value);
            const isSelected = selectedValues.includes(optionId);
            return (
              <button
                key={item.value}
                type="button"
                role="option"
                aria-selected={isSelected}
                className={`snapshot-option ${isSelected ? "selected" : ""}`}
                onClick={() => toggleSelection(optionId)}
              >
                <span className={`snapshot-option-check ${isSelected ? "on" : ""}`} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function MetricsPanelSwitch({ user, metrics, metricsTotal, credits, creditsTotal, filters, setFilters }) {
  const [mode, setMode] = useState("METRICS");
  const [query, setQuery] = useState(filters.q || "");
  const isCredits = mode === "CREDITS";
  const activeRows = isCredits ? credits : metrics;
  const activeTotal = isCredits ? creditsTotal : metricsTotal;
  const selectedRiskCategories = useMemo(
    () => String(filters.risk_categories || "")
      .split(",")
      .map((token) => token.trim())
      .filter(Boolean),
    [filters.risk_categories],
  );

  useEffect(() => {
    setQuery(filters.q || "");
  }, [filters.q]);

  useEffect(() => {
    const timer = setTimeout(() => {
      const normalizedQuery = query.trim();
      const nextQ = normalizedQuery || "";
      if ((filters.q || "") === nextQ) return;
      setFilters((prev) => ({ ...prev, q: nextQ, offset: 0 }));
    }, 250);
    return () => clearTimeout(timer);
  }, [query, filters.q, setFilters]);

  function updateRiskCategories(values) {
    setFilters((prev) => ({ ...prev, risk_categories: values.join(","), offset: 0 }));
  }

  return (
    <section className="panel table-panel">
      <div className="panel-header">
        <h3>{isCredits ? "Credits existants (MCR actuel)" : "Metrics journaliers"}</h3>
        <div className="table-tools">
          <div className="segment-control table-mode">
            <button
              className={!isCredits ? "segment-active" : ""}
              type="button"
              onClick={() => setMode("METRICS")}
            >
              Metrics GP
            </button>
            <button
              className={isCredits ? "segment-active" : ""}
              type="button"
              onClick={() => setMode("CREDITS")}
            >
              Credits existants
            </button>
          </div>
          <label className="search-box">
            <Search size={16} />
            <input
              placeholder={
                isCredits
                  ? user?.role === "super_admin"
                    ? "Recherche globale: contrat, client, CIN, agence, agent..."
                    : "Recherche globale: contrat, client, agence, agent..."
                  : "Recherche globale: agence, agent, date..."
              }
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          {isCredits && (
            <label className="snapshot-select credit-risk-select">
              <span>Filtre risque</span>
              <RiskCategoryMultiSelect
                options={CREDIT_RISK_OPTIONS}
                selectedValues={selectedRiskCategories}
                onChange={updateRiskCategories}
              />
            </label>
          )}
        </div>
      </div>
      <p className="table-search-hint">La recherche s'applique a toutes les donnees, pas seulement a la page visible.</p>
      <div className="table-scroll">
        {isCredits ? <CreditsTable rows={activeRows} role={user?.role} /> : <MetricsTable rows={activeRows} role={user?.role} />}
      </div>
      <Pager
        total={activeTotal}
        limit={filters.limit}
        offset={filters.offset}
        onPage={(offset) => setFilters({ ...filters, offset })}
        onLimitChange={(limit) => setFilters({ ...filters, limit, offset: 0 })}
      />
    </section>
  );
}

function buildMetricsColumns(role) {
  const identityByRole = {
    admin: ["date", "agency", "agent", "client", "outstanding"],
    agency_manager: ["agent", "client", "outstanding"],
    portfolio_manager: ["client", "outstanding"],
  };

  const baseColumns = {
    date: {
      key: "date",
      label: "Date",
      render: (item) => item.date ?? "-",
      sortableType: "date",
      sortAccessor: (item) => item.date,
    },
    agency: {
      key: "agency",
      label: "Agence",
      render: (item) => item.agency?.name ?? "-",
      sortableType: "text",
      sortAccessor: (item) => item.agency?.name,
    },
    agent: {
      key: "agent",
      label: "Agent",
      render: (item) => item.agent?.name ?? "-",
      sortableType: "text",
      sortAccessor: (item) => item.agent?.name,
    },
    client: {
      key: "client",
      label: "Client",
      render: (item) => money(item.nb_clients),
      sortableType: "number",
      sortAccessor: (item) => item.nb_clients,
    },
    outstanding: {
      key: "outstanding",
      label: "Encours",
      render: (item) => money(item.outstanding),
      sortableType: "number",
      sortAccessor: (item) => item.outstanding,
    },
    disbursement_count: {
      key: "disbursement_count",
      label: "Nb decaissements",
      render: (item) => item.disbursement_count ?? 0,
      sortableType: "number",
      sortAccessor: (item) => item.disbursement_count,
    },
    disbursement_volume: {
      key: "disbursement_volume",
      label: "Volume",
      render: (item) => money(item.disbursement_volume),
      sortableType: "number",
      sortAccessor: (item) => item.disbursement_volume,
    },
    healthy_outstanding: {
      key: "healthy_outstanding",
      label: "Sain",
      render: (item) => money(item.healthy_outstanding),
      sortableType: "number",
      sortAccessor: (item) => item.healthy_outstanding,
    },
    healthy_rate: {
      key: "healthy_rate",
      label: "Sain %",
      render: (item) => percent(item.healthy_rate),
      sortableType: "number",
      sortAccessor: (item) => item.healthy_rate,
    },
    par_0: {
      key: "par_0",
      label: "PAR0",
      render: (item) => money(item.par_0),
      sortableType: "number",
      sortAccessor: (item) => item.par_0,
    },
    par_0_rate: {
      key: "par_0_rate",
      label: "PAR0 %",
      render: (item) => percent(item.par_0_rate),
      sortableType: "number",
      sortAccessor: (item) => item.par_0_rate,
    },
    par_1_30: {
      key: "par_1_30",
      label: "1-30",
      render: (item) => money(item.par_1_30),
      sortableType: "number",
      sortAccessor: (item) => item.par_1_30,
    },
    par_1_30_rate: {
      key: "par_1_30_rate",
      label: "1-30 %",
      render: (item) => percent(item.par_1_30_rate),
      sortableType: "number",
      sortAccessor: (item) => item.par_1_30_rate,
    },
    par_31_60: {
      key: "par_31_60",
      label: "31-60",
      render: (item) => money(item.par_31_60),
      sortableType: "number",
      sortAccessor: (item) => item.par_31_60,
    },
    par_31_60_rate: {
      key: "par_31_60_rate",
      label: "31-60 %",
      render: (item) => percent(item.par_31_60_rate),
      sortableType: "number",
      sortAccessor: (item) => item.par_31_60_rate,
    },
    par_61_90: {
      key: "par_61_90",
      label: "61-90",
      render: (item) => money(item.par_61_90),
      sortableType: "number",
      sortAccessor: (item) => item.par_61_90,
    },
    par_61_90_rate: {
      key: "par_61_90_rate",
      label: "61-90 %",
      render: (item) => percent(item.par_61_90_rate),
      sortableType: "number",
      sortAccessor: (item) => item.par_61_90_rate,
    },
    par_91_120: {
      key: "par_91_120",
      label: "91-120",
      render: (item) => money(item.par_91_120),
      sortableType: "number",
      sortAccessor: (item) => item.par_91_120,
    },
    par_91_120_rate: {
      key: "par_91_120_rate",
      label: "91-120 %",
      render: (item) => percent(item.par_91_120_rate),
      sortableType: "number",
      sortAccessor: (item) => item.par_91_120_rate,
    },
    par_120: {
      key: "par_120",
      label: "PAR120",
      render: (item) => money(item.par_120),
      sortableType: "number",
      sortAccessor: (item) => item.par_120,
    },
    par_120_rate: {
      key: "par_120_rate",
      label: "PAR120 %",
      render: (item) => percent(item.par_120_rate),
      sortableType: "number",
      sortAccessor: (item) => item.par_120_rate,
    },
    par_30: {
      key: "par_30",
      label: "PAR30",
      render: (item) => money(item.par_30),
      sortableType: "number",
      sortAccessor: (item) => item.par_30,
    },
    par_30_rate: {
      key: "par_30_rate",
      label: "PAR30 %",
      render: (item) => percent(item.par_30_rate),
      sortableType: "number",
      sortAccessor: (item) => item.par_30_rate,
    },
  };

  const identity = identityByRole[role] || identityByRole.admin;
  const remaining = [
    "disbursement_count",
    "disbursement_volume",
    "healthy_outstanding",
    "healthy_rate",
    "par_0",
    "par_0_rate",
    "par_1_30",
    "par_1_30_rate",
    "par_31_60",
    "par_31_60_rate",
    "par_61_90",
    "par_61_90_rate",
    "par_91_120",
    "par_91_120_rate",
    "par_120",
    "par_120_rate",
    "par_30",
    "par_30_rate",
  ];
  return [...identity, ...remaining].map((columnKey) => baseColumns[columnKey]);
}

function MetricsTable({ rows, role }) {
  const columns = useMemo(() => buildMetricsColumns(role), [role]);
  const {
    sortState,
    sortedRows,
    columnFilters,
    activeFilterCount,
    applySort,
    updateFilter,
    resetFilter,
    resetAllFilters,
  } = useAdvancedTableState(rows, columns);

  return (
    <>
      {activeFilterCount > 0 && (
        <div className="table-filter-summary">
          <span>{activeFilterCount} filtre(s) actif(s)</span>
          <button type="button" className="icon-button" onClick={resetAllFilters}>Reinitialiser tous les filtres</button>
        </div>
      )}
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <SortableHeader
                key={column.key}
                label={column.label}
                columnKey={column.key}
                sortState={sortState}
                sortableType={column.sortableType}
                onToggle={applySort}
                rows={rows}
                column={column}
                filterState={columnFilters[column.key]}
                onFilterChange={(nextFilter) => updateFilter(column.key, nextFilter)}
                onFilterReset={() => resetFilter(column.key)}
              />
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((item) => (
            <tr key={item.id}>
              {columns.map((column) => (
                <td key={`${item.id}-${column.key}`}>{column.render(item)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function CreditsTable({ rows, role }) {
  const showClientNcni = role === "super_admin";
  const columns = useMemo(
    () => [
      { key: "contract_no", label: "CONTRACT_NO", render: (item) => item.contract_no, sortableType: "text" },
      { key: "client_name", label: "CLIENT_NAME", render: (item) => item.client_name || "-", sortableType: "text" },
      { key: "client_first_name", label: "CLIENT_FIRST_NAME", render: (item) => item.client_first_name || "-", sortableType: "text" },
      { key: "client_id", label: "CLIENT_NO", render: (item) => item.client_id, sortableType: "text" },
      ...(showClientNcni ? [{ key: "client_ncni", label: "CLIENT_NCNI", render: (item) => item.client_ncni || "-", sortableType: "text" }] : []),
      { key: "agency_name", label: "BRANCH", render: (item) => item.agency_name, sortableType: "text" },
      { key: "agent_name", label: "DAO_NAME", render: (item) => item.agent_name, sortableType: "text" },
      { key: "client_rating", label: "CLIENT_RATING", render: (item) => item.client_rating || "-", sortableType: "text" },
      {
        key: "disbursement_date",
        label: "DISBURSEMENT_DATE",
        render: (item) => shortDate(item.disbursement_date),
        sortableType: "date",
        sortAccessor: (item) => item.disbursement_date,
      },
      {
        key: "maturity_date",
        label: "MATURITY_DATE",
        render: (item) => shortDate(item.maturity_date),
        sortableType: "date",
        sortAccessor: (item) => item.maturity_date,
      },
      {
        key: "disbursement_amount",
        label: "DISBURSEMENT_AMOUNT",
        render: (item) => money(item.disbursement_amount),
        sortableType: "number",
        sortAccessor: (item) => item.disbursement_amount,
      },
      {
        key: "days_overdue",
        label: "JOURS EN RETARD",
        render: (item) => item.days_overdue ?? 0,
        sortableType: "number",
        sortAccessor: (item) => item.days_overdue,
      },
      {
        key: "total_scheduled_amount",
        label: "TOTAL_SCHEDULED_AMOUNT",
        render: (item) => money(item.total_scheduled_amount),
        sortableType: "number",
        sortAccessor: (item) => item.total_scheduled_amount,
      },
      {
        key: "encours",
        label: "ENCOURS",
        render: (item) => money(item.encours),
        sortableType: "number",
        sortAccessor: (item) => item.encours,
      },
    ],
    [showClientNcni],
  );
  const {
    sortState,
    sortedRows,
    columnFilters,
    activeFilterCount,
    applySort,
    updateFilter,
    resetFilter,
    resetAllFilters,
  } = useAdvancedTableState(rows, columns);

  return (
    <>
      {activeFilterCount > 0 && (
        <div className="table-filter-summary">
          <span>{activeFilterCount} filtre(s) actif(s)</span>
          <button type="button" className="icon-button" onClick={resetAllFilters}>Reinitialiser tous les filtres</button>
        </div>
      )}
      <table className="credits-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <SortableHeader
                key={column.key}
                label={column.label}
                columnKey={column.key}
                sortState={sortState}
                sortableType={column.sortableType}
                onToggle={applySort}
                rows={rows}
                column={column}
                filterState={columnFilters[column.key]}
                onFilterChange={(nextFilter) => updateFilter(column.key, nextFilter)}
                onFilterReset={() => resetFilter(column.key)}
              />
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((item) => (
            <tr key={item.contract_no}>
              {columns.map((column) => (
                <td key={`${item.contract_no}-${column.key}`}>{column.render(item)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function Pager({ total, limit, offset, onPage, onLimitChange }) {
  const safeLimit = Math.max(1, Number(limit || 1));
  const page = Math.floor(offset / safeLimit) + 1;
  const pages = Math.max(1, Math.ceil(total / safeLimit));
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + safeLimit, total);
  const [inputPage, setInputPage] = useState(String(page));

  useEffect(() => {
    setInputPage(String(page));
  }, [page, pages]);

  function goToPage(nextPage) {
    const clamped = Math.min(pages, Math.max(1, nextPage));
    onPage((clamped - 1) * safeLimit);
  }

  function commitInputPage() {
    const parsed = Number(inputPage);
    if (!Number.isFinite(parsed)) {
      setInputPage(String(page));
      return;
    }
    goToPage(parsed);
  }

  return (
    <div className="pager">
      <div className="pager-range">
        <span>{start} - {end} of {total}</span>
        {onLimitChange ? (
          <label className="pager-size-select">
            <span>Lignes</span>
            <select
              value={safeLimit}
              onChange={(event) => onLimitChange(Number(event.target.value))}
              aria-label="Nombre de lignes par page"
            >
              {[10, 20, 40, 50, 100].map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </select>
          </label>
        ) : (
          <ChevronDown size={14} />
        )}
      </div>
      <div className="pager-controls">
        <button className="pager-nav" disabled={page <= 1} onClick={() => goToPage(1)} aria-label="Premiere page">
          <ChevronsLeft size={16} />
        </button>
        <button className="pager-nav" disabled={page <= 1} onClick={() => goToPage(page - 1)} aria-label="Page precedente">
          <ChevronLeft size={16} />
        </button>
        <input
          className="pager-input"
          value={inputPage}
          onChange={(e) => setInputPage(e.target.value.replace(/[^\d]/g, ""))}
          onBlur={commitInputPage}
          onKeyDown={(e) => {
            if (e.key === "Enter") commitInputPage();
          }}
        />
        <span className="pager-total">of {pages}</span>
        <button className="pager-nav" disabled={page >= pages} onClick={() => goToPage(page + 1)} aria-label="Page suivante">
          <ChevronRight size={16} />
        </button>
        <button className="pager-nav" disabled={page >= pages} onClick={() => goToPage(pages)} aria-label="Derniere page">
          <ChevronsRight size={16} />
        </button>
      </div>
    </div>
  );
}

function useClientPagination(items, pageSize = 10) {
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(items.length / pageSize));
  useEffect(() => {
    const maxPage = Math.max(0, pages - 1);
    if (page > maxPage) setPage(maxPage);
  }, [page, pages]);
  const offset = page * pageSize;
  const visible = items.slice(offset, offset + pageSize);
  const pager = (
    <Pager
      total={items.length}
      limit={pageSize}
      offset={offset}
      onPage={(nextOffset) => setPage(Math.floor(nextOffset / pageSize))}
    />
  );
  return { visible, pager };
}

function useAdvancedTableState(rows, columns) {
  const [sortState, setSortState] = useState({ key: null, direction: null });
  const [columnFilters, setColumnFilters] = useState({});
  const filteredRows = useMemo(() => filterRows(rows, columns, columnFilters), [rows, columns, columnFilters]);
  const sortedRows = useMemo(() => sortRows(filteredRows, sortState, columns), [filteredRows, sortState, columns]);
  const activeFilterCount = useMemo(() => countActiveColumnFilters(columnFilters, columns), [columnFilters, columns]);

  function applySort(columnKey, direction) {
    setSortState(direction ? { key: columnKey, direction } : { key: null, direction: null });
  }

  function updateFilter(columnKey, nextValue) {
    setColumnFilters((current) => ({ ...current, [columnKey]: nextValue }));
  }

  function resetFilter(columnKey) {
    setColumnFilters((current) => {
      if (!(columnKey in current)) return current;
      const next = { ...current };
      delete next[columnKey];
      return next;
    });
  }

  function resetAllFilters() {
    setColumnFilters({});
  }

  return {
    sortState,
    sortedRows,
    columnFilters,
    activeFilterCount,
    applySort,
    updateFilter,
    resetFilter,
    resetAllFilters,
  };
}

function ImportScreen({ user, reload, setNotice }) {
  const [currentFile, setCurrentFile] = useState(null);
  const [historyFile, setHistoryFile] = useState(null);
  const [historyPeriod, setHistoryPeriod] = useState("");
  const [restructuredContractsFile, setRestructuredContractsFile] = useState(null);
  const [restructuredScheduleFile, setRestructuredScheduleFile] = useState(null);
  const [pendingContracts, setPendingContracts] = useState([]);
  const [pendingTotal, setPendingTotal] = useState(0);
  const [pendingLimit, setPendingLimit] = useState(10);
  const [pendingOffset, setPendingOffset] = useState(0);
  const [pendingSearch, setPendingSearch] = useState("");
  const [pendingStatus, setPendingStatus] = useState("");
  const [missingMcrContracts, setMissingMcrContracts] = useState([]);
  const [missingMcrTotal, setMissingMcrTotal] = useState(0);
  const [missingMcrLimit, setMissingMcrLimit] = useState(10);
  const [missingMcrOffset, setMissingMcrOffset] = useState(0);
  const [missingMcrSearch, setMissingMcrSearch] = useState("");
  const [missingMcrSortState, setMissingMcrSortState] = useState({ key: null, direction: null });
  const [missingMcrDeleting, setMissingMcrDeleting] = useState(false);
  const [missingMcrColumnFilters, setMissingMcrColumnFilters] = useState({});
  const [missingMcrLoading, setMissingMcrLoading] = useState(false);
  const [pendingEditModal, setPendingEditModal] = useState(null);
  const [pendingForm, setPendingForm] = useState({
    shift_date: "",
    total_due: "",
    loan_duration: "",
  });
  const [pendingSaving, setPendingSaving] = useState(false);
  const [replaceDialog, setReplaceDialog] = useState(null);
  const [restructuredImportPreview, setRestructuredImportPreview] = useState(null);
  const [restructuredImportPreviewLoading, setRestructuredImportPreviewLoading] = useState(false);
  const [restructuredImportApplying, setRestructuredImportApplying] = useState(false);
  const [restructuredPreviewShowAllDeletions, setRestructuredPreviewShowAllDeletions] = useState(false);
  const [pendingResyncing, setPendingResyncing] = useState(false);
  const [pendingDiagnostics, setPendingDiagnostics] = useState(null);
  const [pendingDiagnosticsOpen, setPendingDiagnosticsOpen] = useState(false);
  const [batches, setBatches] = useState([]);
  const [restructuredLogs, setRestructuredLogs] = useState([]);
  const [activeScheduleJob, setActiveScheduleJob] = useState(null);
  const restructuredPreviewModalRef = useRef(null);
  const canUpload = user?.role === "super_admin" || user?.role === "support";
  const canDeleteImports = user?.role === "super_admin";
  const missingMcrFilterCount = useMemo(
    () => countActiveColumnFilters(missingMcrColumnFilters, [
      { key: "contract_no", sortableType: "text" },
      { key: "type_credit", filterType: "enum" },
      { key: "category_desc", sortableType: "text" },
      { key: "delay_date", sortableType: "date" },
      { key: "total_due", sortableType: "number" },
      { key: "loan_duration", sortableType: "number" },
      { key: "source", sortableType: "text" },
      { key: "detected_at", sortableType: "date" },
    ]),
    [missingMcrColumnFilters],
  );
  const serializedMissingMcrFilters = useMemo(
    () => JSON.stringify(missingMcrColumnFilters || {}),
    [missingMcrColumnFilters],
  );

  async function refreshBatches() {
    setMissingMcrLoading(canUpload);
    try {
      const [items, logs, pendingPage, missingPage] = await Promise.all([
        api.importBatches(),
        api.restructuredImportLogs({ limit: 12 }).catch(() => []),
        canUpload
          ? api.restructuredPendingContracts({
            limit: pendingLimit,
            offset: pendingOffset,
            q: pendingSearch || undefined,
            status: pendingStatus || undefined,
          }).catch(() => ({ items: [], total: 0, limit: pendingLimit, offset: pendingOffset }))
          : Promise.resolve({ items: [], total: 0, limit: pendingLimit, offset: pendingOffset }),
        canUpload
          ? api.restructuredMissingContracts(clean({
            family: "all",
            q: missingMcrSearch || undefined,
            table_filters: missingMcrFilterCount > 0 ? serializedMissingMcrFilters : undefined,
            sort_key: missingMcrSortState.key || undefined,
            sort_direction: missingMcrSortState.direction || undefined,
            limit: missingMcrLimit,
            offset: missingMcrOffset,
          })).catch(() => ({ items: [], total: 0, limit: missingMcrLimit, offset: missingMcrOffset }))
          : Promise.resolve({ items: [], total: 0, limit: missingMcrLimit, offset: missingMcrOffset }),
      ]);
      setBatches(items || []);
      setRestructuredLogs(logs || []);
      setPendingContracts(pendingPage?.items || []);
      setPendingTotal(pendingPage?.total || 0);
      setMissingMcrContracts(missingPage?.items || []);
      setMissingMcrTotal(missingPage?.total || 0);
    } catch {
      setBatches([]);
      setRestructuredLogs([]);
      setPendingContracts([]);
      setPendingTotal(0);
      setMissingMcrContracts([]);
      setMissingMcrTotal(0);
    } finally {
      setMissingMcrLoading(false);
    }
  }

  useEffect(() => {
    refreshBatches();
  }, [
    pendingLimit,
    pendingOffset,
    pendingSearch,
    pendingStatus,
    missingMcrLimit,
    missingMcrOffset,
    missingMcrSearch,
    missingMcrSortState.key,
    missingMcrSortState.direction,
    serializedMissingMcrFilters,
    missingMcrFilterCount,
  ]);

  useEffect(() => {
    if (!restructuredImportPreview) return undefined;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const modalNode = restructuredPreviewModalRef.current;
    if (modalNode) {
      modalNode.focus();
    }

    const handleKeyDown = (event) => {
      if (!restructuredImportPreview) return;
      if (event.key === "Escape") {
        event.preventDefault();
        closeRestructuredImportPreview();
        return;
      }
      if (event.key !== "Tab" || !modalNode) return;
      const focusableNodes = Array.from(
        modalNode.querySelectorAll(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (!focusableNodes.length) return;
      const firstNode = focusableNodes[0];
      const lastNode = focusableNodes[focusableNodes.length - 1];
      if (event.shiftKey && document.activeElement === firstNode) {
        event.preventDefault();
        lastNode.focus();
      } else if (!event.shiftKey && document.activeElement === lastNode) {
        event.preventDefault();
        firstNode.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [restructuredImportPreview, restructuredImportApplying]);

  function isValidPeriod(period) {
    return /^(\d{1,2}\/\d{4}|\d{4}-\d{1,2})$/.test(period.trim());
  }

  function displayPeriod(period) {
    const normalized = period.trim();
    if (/^\d{2}\/\d{4}$/.test(normalized)) return normalized;
    return formatMonthLabel(normalized);
  }

  function formatImportMessage(prefix, result) {
    const periodLabel = result?.import_batch?.period ? `periode ${formatMonthLabel(result.import_batch.period)}` : "etat actuel";
    return `${prefix}: ${result.rows_seen} lignes, ${result.inserted} inserees, ${result.updated} mises a jour, ${result.duplicates} doublons, ${periodLabel}, snapshot ${result.snapshot_date}.`;
  }

  async function uploadCurrentState() {
    if (!currentFile) return setNotice("Choisir un fichier Excel pour l'etat actuel.");
    setNotice("Importation de l'etat actuel en cours...");
    try {
      const result = await api.uploadCurrentState(currentFile);
      setNotice(formatImportMessage("Etat actuel importe", result));
      setCurrentFile(null);
      await refreshBatches();
      await reload();
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function uploadHistorical(replaceExisting = false, payload = null) {
    const file = payload?.file || historyFile;
    const period = (payload?.period || historyPeriod || "").trim();
    if (!file) return setNotice("Choisir un fichier Excel historique.");
    if (!period) return setNotice("Saisir la periode du fichier historique (MM/YYYY).");
    if (!isValidPeriod(period)) {
      return setNotice("Format periode invalide. Utiliser MM/YYYY (ex: 02/2026).");
    }

    setNotice(replaceExisting ? "Remplacement du fichier historique en cours..." : "Importation historique en cours...");
    try {
      const result = await api.uploadHistoricalMonth(file, period, replaceExisting);
      setNotice(formatImportMessage("Mois historique importe", result));
      setHistoryFile(null);
      setHistoryPeriod("");
      setReplaceDialog(null);
      await refreshBatches();
      await reload();
    } catch (err) {
      if (err.code === "historical_period_exists" && !replaceExisting) {
        setReplaceDialog({
          file,
          period,
          existingBatch: err.detail?.existing_batch || null,
        });
        return;
      }
      setNotice(err.message);
    }
  }

  async function deleteBatch(batch) {
    const label = batch.period ? formatMonthLabel(batch.period) : shortDate(batch.snapshot_date);
    const confirmed = window.confirm(
      `Supprimer definitivement l'import ${batch.batch_type} (${label}) et toutes ses donnees MCR ?`,
    );
    if (!confirmed) return;
    try {
      const result = await api.deleteImportBatch(batch.id);
      setNotice(result?.message || "Import supprime.");
      await refreshBatches();
      await reload();
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function uploadRestructuredContractsFile() {
    if (!restructuredContractsFile) {
      return setNotice("Choisir le fichier liste_restructure_all.xlsx.");
    }
    setRestructuredImportPreviewLoading(true);
    setNotice("Analyse de la synchronisation restructuree/consolidee en cours...");
    try {
      console.info("Restructured contracts import preview started", {
        fileName: restructuredContractsFile?.name || "",
        fileSize: restructuredContractsFile?.size || 0,
        fileType: restructuredContractsFile?.type || "",
        endpoint: "/api/v1/imports/restructured-contracts/preview",
      });
      const result = await api.previewRestructuredContracts(restructuredContractsFile);
      const normalizedResult = normalizeRestructuredImportPreview(result);
      console.info("Restructured contracts import preview success", normalizedResult);
      setRestructuredPreviewShowAllDeletions(false);
      setRestructuredImportPreview(normalizedResult);
      setNotice(normalizedResult.message);
    } catch (err) {
      console.error("Restructured contracts import preview failed", err);
      setRestructuredImportPreview(null);
      setNotice(err?.message || "Echec de l'import : reponse inattendue du serveur.");
    } finally {
      setRestructuredImportPreviewLoading(false);
    }
  }

  async function confirmRestructuredContractsImport() {
    if (!restructuredContractsFile || !restructuredImportPreview) {
      return setNotice("La previsualisation a expire. Rechargez le fichier avant de confirmer.");
    }
    setRestructuredImportApplying(true);
    setNotice("Application de la synchronisation restructuree/consolidee en cours...");
    try {
      console.info("Restructured contracts import apply started", {
        fileName: restructuredContractsFile?.name || "",
        fileSize: restructuredContractsFile?.size || 0,
        fileType: restructuredContractsFile?.type || "",
        endpoint: "/api/v1/imports/restructured-contracts",
      });
      const result = await api.uploadRestructuredContracts(restructuredContractsFile);
      console.info("Restructured contracts import apply success", result);
      setRestructuredImportPreview(null);
      setRestructuredPreviewShowAllDeletions(false);
      setRestructuredContractsFile(null);
      setNotice(
        `${result?.message || "Import termine."} ${result?.inserted ?? 0} ajoute(s), ${result?.updated ?? 0} mis a jour, ${result?.deleted ?? 0} supprime(s), ${result?.recalculated_contracts ?? 0} contrat(s) recalcules.`,
      );
      await refreshBatches();
      await reload();
    } catch (err) {
      console.error("Restructured contracts import apply failed", err);
      setNotice(err?.message || "Echec de l'import : erreur serveur.");
    } finally {
      setRestructuredImportApplying(false);
    }
  }

  function closeRestructuredImportPreview() {
    if (restructuredImportApplying) return;
    setRestructuredImportPreview(null);
    setRestructuredPreviewShowAllDeletions(false);
  }

  async function uploadRestructuredScheduleFile() {
    if (!restructuredScheduleFile) {
      return setNotice("Choisir le fichier SCHEDULE a importer.");
    }
    setNotice("Import SCHEDULE demarre en tache de fond...");
    try {
      const job = await api.uploadRestructuredSchedule(restructuredScheduleFile);
      setRestructuredScheduleFile(null);
      setActiveScheduleJob(job);
      await refreshBatches();
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function downloadMissingMcrContractsExport() {
    try {
      const { blob, filename } = await api.downloadRestructuredMissingContractsExport(clean({
        family: "all",
        q: missingMcrSearch || undefined,
        table_filters: missingMcrFilterCount > 0 ? serializedMissingMcrFilters : undefined,
        sort_key: missingMcrSortState.key || undefined,
        sort_direction: missingMcrSortState.direction || undefined,
      }));
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = filename || "contrats_absents_mcr.xlsx";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(href);
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function deleteMissingMcrContracts(contractNos) {
    if (!Array.isArray(contractNos) || contractNos.length === 0) {
      return { deleted_count: 0, skipped_count: 0, deleted_contract_nos: [], skipped_contract_nos: [] };
    }
    setMissingMcrDeleting(true);
    try {
      const result = await api.deleteMissingMcrContracts(contractNos);
      const deleted = result?.deleted_count ?? contractNos.length;
      const skipped = result?.skipped_count ?? 0;
      const deletedList = result?.deleted_contract_nos || [];
      const skippedList = result?.skipped_contract_nos || [];
      const parts = [`${deleted} contrat(s) supprime(s) de la base.`];
      if (skipped > 0) {
        parts.push(`${skipped} ignore(s) : ${skippedList.slice(0, 3).join(", ")}${skippedList.length > 3 ? "..." : ""}`);
      }
      setNotice(parts.join(" "));
      await refreshBatches();
      return result;
    } catch (err) {
      setNotice(err?.message || "Echec de la suppression des contrats absents du MCR.");
      throw err;
    } finally {
      setMissingMcrDeleting(false);
    }
  }

  function pendingStatusLabel(status) {
    return status === "ready" ? "Pret a enregistrer" : "A completer";
  }

  function pendingStatusClass(status) {
    return status === "ready" ? "success" : "warning";
  }

  function openPendingEditModal(item) {
    setPendingEditModal(item);
    setPendingForm({
      shift_date: item?.shift_date || "",
      total_due: item?.total_due != null ? String(item.total_due) : "",
      loan_duration: item?.loan_duration != null ? String(item.loan_duration) : "",
    });
  }

  function closePendingEditModal() {
    setPendingEditModal(null);
    setPendingForm({
      shift_date: "",
      total_due: "",
      loan_duration: "",
    });
    setPendingSaving(false);
  }

  async function savePendingContract() {
    if (!pendingEditModal?.id) return;
    setPendingSaving(true);
    try {
      await api.updateRestructuredPendingContract(pendingEditModal.id, {
        shift_date: pendingForm.shift_date || null,
        total_due: pendingForm.total_due === "" ? null : Number(pendingForm.total_due),
        loan_duration: pendingForm.loan_duration === "" ? null : Number(pendingForm.loan_duration),
      });
      setNotice("Contrat a completer mis a jour.");
      closePendingEditModal();
      await refreshBatches();
    } catch (err) {
      setNotice(err.message);
      setPendingSaving(false);
    }
  }

  async function validatePendingContract(item) {
    if (!item?.id) return;
    setNotice(`Validation du contrat ${item.contract_no} en cours...`);
    try {
      const result = await api.validateRestructuredPendingContract(item.id);
      setNotice(result?.message || "Contrat enregistre.");
      await refreshBatches();
      await reload();
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function validateAllPendingContracts() {
    setNotice("Enregistrement de tous les contrats valides en cours...");
    try {
      const result = await api.validateAllRestructuredPendingContracts();
      setNotice(result?.message || "Contrats enregistres.");
      await refreshBatches();
      await reload();
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function resyncPendingContracts() {
    setPendingResyncing(true);
    setNotice("Reanalyse de tout le MCR pour reconstruire la liste des contrats a completer...");
    try {
      const summary = await api.resyncRestructuredPendingContracts();
      const parts = [
        `${summary?.new_detected ?? 0} contrat(s) ajoute(s)`,
        `${summary?.updated_existing ?? 0} mis a jour`,
        `${summary?.skipped_invalid ?? 0} ignore(s) (categorie non eligible)`,
        `${summary?.already_present ?? 0} deja dans la liste officielle`,
      ];
      if (summary?.loans_scanned !== undefined) {
        parts.unshift(`${summary.loans_scanned} ligne(s) MCR analysee(s)`);
      }
      setNotice(`Resynchronisation terminee. ${parts.join(" | ")}.`);
      await refreshBatches();
    } catch (err) {
      setNotice(err?.message || "Echec de la resynchronisation des contrats a completer.");
    } finally {
      setPendingResyncing(false);
    }
  }

  async function loadPendingDiagnostics() {
    try {
      const data = await api.getRestructuredPendingContractsDiagnostics();
      setPendingDiagnostics(data);
      setPendingDiagnosticsOpen(true);
    } catch (err) {
      setNotice(err?.message || "Impossible de charger le diagnostic.");
    }
  }

  useEffect(() => {
    if (!activeScheduleJob?.id) return undefined;
    const status = String(activeScheduleJob.status || "").toLowerCase();
    if (!["queued", "running"].includes(status)) return undefined;
    const timer = setInterval(async () => {
      try {
        const job = await api.restructuredImportLog(activeScheduleJob.id);
        setActiveScheduleJob(job);
        setRestructuredLogs((current) => {
          const others = current.filter((item) => item.id !== job.id);
          return [job, ...others].slice(0, 12);
        });
        if (!["queued", "running"].includes(String(job.status || "").toLowerCase())) {
          setNotice(job.message || "Import SCHEDULE termine.");
          await refreshBatches();
        }
      } catch {
        // keep last known state silently
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [activeScheduleJob?.id, activeScheduleJob?.status]);

  return (
    <>
      {canUpload && (
        <>
          <section className="import-grid">
            <div className="panel">
              <h3>Importer l'etat actuel</h3>
              <p className="muted">
                Ce fichier represente la situation actuelle du portefeuille. Les indicateurs principaux utilisent cette reference.
              </p>
              <input
                type="file"
                accept=".xlsx,.xls"
                onChange={(e) => setCurrentFile(e.target.files?.[0] || null)}
              />
              <button className="primary fit" onClick={uploadCurrentState}>
                <Upload size={16} />
                Importer l'etat actuel
              </button>
            </div>

            <div className="panel">
              <h3>Importer un mois passe</h3>
              <p className="muted">
                Associer le fichier a une periode explicite (MM/YYYY). Cette periode sera utilisee dans les chartes mensuelles.
              </p>
              <label>
                Periode du fichier (MM/YYYY)
                <input
                  placeholder="02/2026"
                  value={historyPeriod}
                  onChange={(e) => setHistoryPeriod(e.target.value)}
                />
              </label>
              <input
                type="file"
                accept=".xlsx,.xls"
                onChange={(e) => setHistoryFile(e.target.files?.[0] || null)}
              />
              <button className="primary fit" onClick={() => uploadHistorical(false)}>
                <Upload size={16} />
                Importer le mois passe
              </button>
            </div>
          </section>

          <section className="import-grid import-grid-secondary">
            <div className="panel">
              <h3>Importer la liste des credits restructures et consolides</h3>
              <p className="muted">
                Import manuel reserve aux roles autorises. Le systeme fait un upsert sur le numero de contrat et recalcule l'analyse.
              </p>
              <input
                type="file"
                accept=".xlsx,.xls"
                onChange={(e) => {
                  setRestructuredImportPreview(null);
                  setRestructuredContractsFile(e.target.files?.[0] || null);
                }}
              />
              <button
                className="primary fit"
                onClick={uploadRestructuredContractsFile}
                disabled={restructuredImportPreviewLoading || restructuredImportApplying}
              >
                <Upload size={16} />
                {restructuredImportPreviewLoading ? "Analyse..." : "Importer la liste restructuree"}
              </button>
            </div>

            <div className="panel">
              <h3>Importer le fichier SCHEDULE</h3>
              <p className="muted">
                Import en tache de fond avec progression, upsert performant et recalcul automatique apres validation.
              </p>
              <input
                type="file"
                accept=".xlsx,.xls,.csv"
                onChange={(e) => setRestructuredScheduleFile(e.target.files?.[0] || null)}
              />
              <button className="primary fit" onClick={uploadRestructuredScheduleFile}>
                <Upload size={16} />
                Importer le fichier SCHEDULE
              </button>
              {activeScheduleJob && (
                <div className="import-job-status">
                  <strong>{activeScheduleJob.file_name || "SCHEDULE"}</strong>
                  <span>{activeScheduleJob.status || "-"}</span>
                  <span>{activeScheduleJob.phase || "-"}</span>
                  <span>{activeScheduleJob.progress_percent ?? 0}%</span>
                  <span>{(activeScheduleJob.source_rows_seen ?? 0)} ligne(s) lues</span>
                  <span>{(activeScheduleJob.row_count ?? 0)} utile(s)</span>
                  <span>{(activeScheduleJob.ignored_rows_count ?? 0)} ignoree(s)</span>
                  <span>{Number(activeScheduleJob.rows_per_second || 0).toFixed(2)} l/s</span>
                  <span>
                    ETA {activeScheduleJob.eta_seconds != null ? `${Number(activeScheduleJob.eta_seconds).toFixed(0)}s` : "-"}
                  </span>
                  <span>
                    Derniere activite {activeScheduleJob.last_activity_at ? formatDateTimeLabel(activeScheduleJob.last_activity_at) : "-"}
                  </span>
                </div>
              )}
            </div>
          </section>
        </>
      )}

      {canUpload && (
        <section className="panel">
          <div className="panel-header">
            <div>
              <h3>Contrats restructures et consolides a completer</h3>
              <p className="muted">
                Les contrats detectes dans le MCR mais absents de la liste officielle restent ici jusqu&apos;a validation complete.
              </p>
            </div>
            <div className="button-row wrap">
              <span className="count-badge">{pendingTotal}</span>
              <button
                className="icon-button"
                type="button"
                onClick={loadPendingDiagnostics}
                title="Afficher les compteurs par etape pour diagnostiquer pourquoi la liste peut etre vide"
              >
                Diagnostic
              </button>
              <button
                className="icon-button"
                type="button"
                onClick={resyncPendingContracts}
                disabled={pendingResyncing}
                title="Reanalyser tout le MCR pour reconstruire la liste des contrats a completer"
              >
                {pendingResyncing ? "Reanalyse..." : "Resynchroniser"}
              </button>
              <button className="primary fit" type="button" onClick={validateAllPendingContracts}>
                <Save size={16} />
                Enregistrer tous les contrats valides
              </button>
            </div>
          </div>
          {pendingDiagnosticsOpen && pendingDiagnostics && (
            <div className="diagnostic-panel" role="region" aria-label="Diagnostic des contrats a completer">
              <div className="diagnostic-header">
                <strong>Diagnostic de la detection</strong>
                <button className="icon-button" type="button" onClick={() => setPendingDiagnosticsOpen(false)}>
                  Fermer
                </button>
              </div>
              <ul className="diagnostic-list">
                <li>
                  <span>A. Lignes MCR (loans_raw) au total :</span>
                  <strong>{pendingDiagnostics.loans_total ?? 0}</strong>
                </li>
                <li>
                  <span>B. Lignes avec CATEGORY_DESC non vide :</span>
                  <strong>{pendingDiagnostics.loans_with_category_desc ?? 0}</strong>
                </li>
                <li>
                  <span>C. Contrats distincts categorie "Restructures" :</span>
                  <strong>{pendingDiagnostics.loans_restructured_distinct ?? 0}</strong>
                </li>
                <li>
                  <span>C. Contrats distincts categorie "Consolides" :</span>
                  <strong>{pendingDiagnostics.loans_consolidated_distinct ?? 0}</strong>
                </li>
                <li>
                  <span>D. Contrats deja dans la liste officielle :</span>
                  <strong>{pendingDiagnostics.official_restructured_contracts ?? 0}</strong>
                </li>
                <li>
                  <span>E. Contrats actuellement a completer :</span>
                  <strong>{pendingDiagnostics.pending_restructured_contracts ?? 0}</strong>
                </li>
              </ul>
              <p className="muted small">
                Si A &gt; 0 mais B = 0, votre MCR n&apos;a pas de colonne CATEGORY_DESC. Si B &gt; 0 mais
                C = 0, les valeurs de CATEGORY_DESC ne correspondent pas a la nomenclature reconnue
                (utilisez le bouton &quot;Resynchroniser&quot; apres verification).
              </p>
            </div>
          )}
          <div className="filters-row">
            <label className="search-inline">
              <Search size={16} />
              <input
                placeholder="Rechercher un contrat, client, agence ou agent"
                value={pendingSearch}
                onChange={(event) => {
                  setPendingOffset(0);
                  setPendingSearch(event.target.value);
                }}
              />
            </label>
            <label>
              Statut
              <select
                value={pendingStatus}
                onChange={(event) => {
                  setPendingOffset(0);
                  setPendingStatus(event.target.value);
                }}
              >
                <option value="">Tous</option>
                <option value="pending">A completer</option>
                <option value="ready">Pret a enregistrer</option>
              </select>
            </label>
            <button
              className="icon-button"
              type="button"
              onClick={() => {
                setPendingOffset(0);
                setPendingSearch("");
                setPendingStatus("");
              }}
            >
              Reinitialiser
            </button>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Numero de contrat</th>
                  <th>Type</th>
                  <th>CATEGORY_DESC</th>
                  <th>Client</th>
                  <th>Agence</th>
                  <th>Agent</th>
                  <th>Date de decaissement</th>
                  <th>Montant decaisse</th>
                  <th>Date de decalage</th>
                  <th>Total Due</th>
                  <th>LOAN_DURATION</th>
                  <th>Champs manquants</th>
                  <th>Statut</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {pendingContracts.map((item) => (
                  <tr key={item.id}>
                    <td>{item.contract_no}</td>
                    <td>{item.type_credit}</td>
                    <td>{item.category_desc || "-"}</td>
                    <td>{[item.client_name, item.client_first_name].filter(Boolean).join(" ") || "-"}</td>
                    <td>{item.agency_name || "-"}</td>
                    <td>{item.agent_name || "-"}</td>
                    <td>{shortDate(item.disbursement_date)}</td>
                    <td>{formatMoney(item.disbursement_amount)}</td>
                    <td>{shortDate(item.shift_date)}</td>
                    <td>{formatMoney(item.total_due)}</td>
                    <td>{item.loan_duration ?? "-"}</td>
                    <td>{item.missing_fields?.length ? item.missing_fields.join(", ") : "Aucun"}</td>
                    <td>
                      <span className={`status-pill ${pendingStatusClass(item.status)}`}>
                        {pendingStatusLabel(item.status)}
                      </span>
                    </td>
                    <td>
                      <div className="button-row wrap">
                        <button className="icon-button" type="button" onClick={() => openPendingEditModal(item)}>
                          Modifier
                        </button>
                        <button
                          className="primary fit"
                          type="button"
                          disabled={item.status !== "ready"}
                          onClick={() => validatePendingContract(item)}
                        >
                          Enregistrer
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {pendingContracts.length === 0 && (
                  <tr>
                    <td colSpan="14">Aucun contrat a completer pour les filtres selectionnes.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pager
            total={pendingTotal}
            limit={pendingLimit}
            offset={pendingOffset}
            onPage={setPendingOffset}
            onLimitChange={(nextLimit) => {
              setPendingLimit(nextLimit);
              setPendingOffset(0);
            }}
          />
        </section>
      )}

      {canUpload && (
        <MissingMcrContractsTableSection
          rows={missingMcrContracts}
          total={missingMcrTotal}
          loading={missingMcrLoading}
          search={missingMcrSearch}
          onSearchChange={(value) => {
            setMissingMcrOffset(0);
            setMissingMcrSearch(value);
          }}
          sortState={missingMcrSortState}
          onSortChange={(columnKey, direction) => {
            setMissingMcrSortState(direction ? { key: columnKey, direction } : { key: null, direction: null });
            setMissingMcrOffset(0);
          }}
          columnFilters={missingMcrColumnFilters}
          onFilterChange={(columnKey, nextFilter) => {
            setMissingMcrColumnFilters((current) => ({ ...current, [columnKey]: nextFilter }));
            setMissingMcrOffset(0);
          }}
          onFilterReset={(columnKey) => {
            setMissingMcrColumnFilters((current) => {
              if (!(columnKey in current)) return current;
              const next = { ...current };
              delete next[columnKey];
              return next;
            });
            setMissingMcrOffset(0);
          }}
          onResetAllFilters={() => {
            setMissingMcrColumnFilters({});
            setMissingMcrSortState({ key: null, direction: null });
            setMissingMcrSearch("");
            setMissingMcrOffset(0);
          }}
          limit={missingMcrLimit}
          offset={missingMcrOffset}
          onPage={setMissingMcrOffset}
          onLimitChange={(nextLimit) => {
            setMissingMcrLimit(nextLimit);
            setMissingMcrOffset(0);
          }}
          onExport={downloadMissingMcrContractsExport}
          canDeleteMissingMcr={canUpload}
          onDeleteMissingMcr={deleteMissingMcrContracts}
          deletingMissingMcr={missingMcrDeleting}
        />
      )}

      <section className="panel">
        <div className="panel-header">
          <div>
            <h3>Imports et snapshots</h3>
            <p className="muted">Supprimer uniquement les snapshots ou mois passes importes par erreur.</p>
          </div>
          <button className="icon-button" onClick={refreshBatches}>Actualiser</button>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Type</th>
                <th>Periode</th>
                <th>DateEOD</th>
                <th>Fichier</th>
                <th>Importe le</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {batches.map((batch) => {
                const deletable = canDeleteImports && ["SNAPSHOT", "HISTORICAL_MONTH"].includes(batch.batch_type);
                return (
                  <tr key={batch.id}>
                    <td>{batch.batch_type}</td>
                    <td>{batch.period ? formatMonthLabel(batch.period) : "-"}</td>
                    <td>{shortDate(batch.snapshot_date)}</td>
                    <td>{batch.file_name}</td>
                    <td>{shortDate(batch.imported_at)}</td>
                    <td>
                      <button className="danger-button fit" disabled={!deletable} onClick={() => deleteBatch(batch)}>
                        Supprimer
                      </button>
                    </td>
                  </tr>
                );
              })}
              {batches.length === 0 && (
                <tr>
                  <td colSpan="6">Aucun import disponible.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h3>Imports credits restructures et consolides</h3>
            <p className="muted">
              Historique des imports de la liste fixe et du fichier SCHEDULE, avec progression et details de recalcul.
            </p>
          </div>
          <button className="icon-button" onClick={refreshBatches}>Actualiser</button>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Type</th>
                <th>Fichier</th>
                <th>Demarre le</th>
                <th>Statut</th>
                <th>Progression</th>
                <th>Lignes</th>
                <th>Ajoutes</th>
                <th>MAJ</th>
                <th>Supprimes</th>
                <th>Recalcules</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              {restructuredLogs.map((log) => (
                <tr key={log.id}>
                  <td>{log.import_type}</td>
                  <td>{log.file_name || "-"}</td>
                  <td>{formatDateTimeLabel(log.started_at)}</td>
                  <td>{log.status || "-"}</td>
                  <td>{log.progress_percent ?? 0}%</td>
                  <td>{log.row_count ?? "-"}</td>
                  <td>{log.inserted_count ?? "-"}</td>
                  <td>{log.updated_count ?? "-"}</td>
                  <td>{log.deleted_count ?? "-"}</td>
                  <td>{log.recalculated_contracts ?? "-"}</td>
                  <td>
                    <div>{log.message || "-"}</div>
                    {log.phase_details && <div className="muted small">{log.phase_details}</div>}
                    {(log.source_rows_seen != null || log.rows_per_second != null || log.last_activity_at) && (
                      <div className="muted small">
                        {`${log.source_rows_seen ?? 0} lues | ${log.row_count ?? 0} utiles | ${log.ignored_rows_count ?? 0} ignorees | ${Number(log.rows_per_second || 0).toFixed(2)} l/s | ETA ${log.eta_seconds != null ? `${Number(log.eta_seconds).toFixed(0)}s` : "-"} | Activite ${log.last_activity_at ? formatDateTimeLabel(log.last_activity_at) : "-"}`}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              {restructuredLogs.length === 0 && (
                <tr>
                  <td colSpan="11">Aucun import restructure/consolide disponible.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {pendingEditModal && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="pending-contract-title">
          <div className="modal-card">
            <div className="modal-title">
              <Save size={18} />
              <h3 id="pending-contract-title">Completer le contrat {pendingEditModal.contract_no}</h3>
            </div>
            <p className="muted">
              Les donnees du MCR sont pre-remplies. Completez les champs obligatoires pour integrer ce contrat dans la liste officielle.
            </p>
            <div className="detail-grid">
              <div>
                <strong>Type</strong>
                <div>{pendingEditModal.type_credit}</div>
              </div>
              <div>
                <strong>CATEGORY_DESC</strong>
                <div>{pendingEditModal.category_desc || "-"}</div>
              </div>
              <div>
                <strong>Client</strong>
                <div>{[pendingEditModal.client_name, pendingEditModal.client_first_name].filter(Boolean).join(" ") || "-"}</div>
              </div>
              <div>
                <strong>Agence</strong>
                <div>{pendingEditModal.agency_name || "-"}</div>
              </div>
              <div>
                <strong>Agent</strong>
                <div>{pendingEditModal.agent_name || "-"}</div>
              </div>
              <div>
                <strong>Date de decaissement</strong>
                <div>{shortDate(pendingEditModal.disbursement_date)}</div>
              </div>
              <div>
                <strong>Montant decaisse</strong>
                <div>{formatMoney(pendingEditModal.disbursement_amount)}</div>
              </div>
            </div>
            <div className="form-grid">
              <label>
                Date de decalage
                <input
                  type="date"
                  value={pendingForm.shift_date}
                  onChange={(event) => setPendingForm((current) => ({ ...current, shift_date: event.target.value }))}
                />
              </label>
              <label>
                Total Due
                <input
                  type="number"
                  min="0"
                  step="0.001"
                  value={pendingForm.total_due}
                  onChange={(event) => setPendingForm((current) => ({ ...current, total_due: event.target.value }))}
                />
              </label>
              <label>
                LOAN_DURATION
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={pendingForm.loan_duration}
                  onChange={(event) => setPendingForm((current) => ({ ...current, loan_duration: event.target.value }))}
                />
              </label>
            </div>
            <p className="muted small">
              Champs manquants actuels: {pendingEditModal.missing_fields?.length ? pendingEditModal.missing_fields.join(", ") : "Aucun"}
            </p>
            <div className="button-row">
              <button className="icon-button" type="button" onClick={closePendingEditModal}>
                Annuler
              </button>
              <button className="primary" type="button" disabled={pendingSaving} onClick={savePendingContract}>
                <Save size={16} />
                Enregistrer
              </button>
            </div>
          </div>
        </div>
      )}

      {restructuredImportPreview && (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby="restructured-sync-preview-title"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              closeRestructuredImportPreview();
            }
          }}
        >
          <div
            ref={restructuredPreviewModalRef}
            className="modal-card modal-card-xl import-preview-modal"
            tabIndex={-1}
          >
            <div className="import-preview-modal-header">
              <div className="modal-title modal-title-neutral import-preview-modal-title">
                <div>
                  <h3 id="restructured-sync-preview-title">Previsualisation de synchronisation</h3>
                  <p className="muted">
                    {restructuredImportPreview.file_name || "liste_restructures.xlsx"} - confirmation requise avant suppression definitive.
                  </p>
                </div>
              </div>
              <button
                className="icon-button import-preview-close"
                type="button"
                onClick={closeRestructuredImportPreview}
                disabled={restructuredImportApplying}
                aria-label="Fermer la previsualisation"
              >
                <X size={16} />
              </button>
            </div>

            <div className="import-preview-modal-body">
              <div className="panel subtle-panel import-preview-summary-panel">
                <div className="metrics-grid">
                  <Metric label="Base actuelle" value={formatNumber(restructuredImportPreview.existing_contracts_count)} />
                  <Metric label="Nouvelle liste" value={formatNumber(restructuredImportPreview.imported_list_count)} />
                  <Metric label="Detectes dans le MCR" value={formatNumber(restructuredImportPreview.detected_in_mcr_count)} />
                  <Metric label="Conserves" value={formatNumber(restructuredImportPreview.kept_count)} />
                  <Metric label="A ajouter" value={formatNumber(restructuredImportPreview.add_count)} />
                  <Metric label="A mettre a jour" value={formatNumber(restructuredImportPreview.update_count)} />
                  <Metric
                    label="A supprimer"
                    value={formatNumber(restructuredImportPreview.delete_count)}
                    tone={restructuredImportPreview.delete_count > 0 ? "danger" : undefined}
                  />
                  <Metric
                    label="Nettoyage attente"
                    value={formatNumber(restructuredImportPreview.pending_cleanup_count)}
                    tone={restructuredImportPreview.pending_cleanup_count > 0 ? "warning" : undefined}
                  />
                </div>
                <p className="muted import-preview-message">{restructuredImportPreview.message}</p>
              </div>

              <div className="panel subtle-panel import-preview-details-panel">
                <div className="panel-header">
                  <div>
                    <h3>Contrats qui seront supprimes</h3>
                    <p className="muted">Raison: absent de la nouvelle liste et absent du MCR actif.</p>
                  </div>
                  <span className="count-badge">{restructuredImportPreview.deletions?.length || 0}</span>
                </div>
                {(restructuredImportPreview.deletions || []).length > 20 && (
                  <div className="import-preview-toggle-row">
                    <span className="muted">
                      {restructuredPreviewShowAllDeletions
                        ? `Affichage des ${formatNumber((restructuredImportPreview.deletions || []).length)} lignes.`
                        : `Affichage initial des 20 premieres lignes sur ${formatNumber((restructuredImportPreview.deletions || []).length)}.`}
                    </span>
                    <button
                      type="button"
                      className="icon-button"
                      onClick={() => setRestructuredPreviewShowAllDeletions((current) => !current)}
                    >
                      {restructuredPreviewShowAllDeletions ? "Afficher moins" : "Voir toutes les suppressions"}
                    </button>
                  </div>
                )}
                <div className="table-scroll import-preview-table-wrap">
                  <table className="import-preview-table">
                    <thead>
                      <tr>
                        <th>Numero de contrat</th>
                        <th>Type actuel</th>
                        <th>Source actuelle</th>
                        <th>Derniere mise a jour</th>
                        <th>Raison de suppression</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(restructuredImportPreview.deletions || [])
                        .slice(0, restructuredPreviewShowAllDeletions ? undefined : 20)
                        .map((item) => (
                          <tr key={`${item.scope}-${item.contract_no}`}>
                            <td>{item.contract_no}</td>
                            <td>{item.type_credit || "-"}</td>
                            <td>{item.source || "-"}</td>
                            <td>{item.updated_at ? formatDateTimeLabel(item.updated_at) : "-"}</td>
                            <td>{item.reason}</td>
                          </tr>
                        ))}
                      {(restructuredImportPreview.deletions || []).length === 0 && (
                        <tr>
                          <td colSpan="5" className="muted">Aucun contrat a supprimer pour cette synchronisation.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <div className="import-preview-modal-footer button-row button-row-end">
              <button
                className="icon-button"
                type="button"
                onClick={closeRestructuredImportPreview}
                disabled={restructuredImportApplying}
              >
                Annuler
              </button>
              <button
                className="primary fit"
                type="button"
                onClick={confirmRestructuredContractsImport}
                disabled={restructuredImportApplying}
              >
                <Save size={16} />
                {restructuredImportApplying ? "Application..." : "Confirmer la synchronisation"}
              </button>
            </div>
          </div>
        </div>
      )}

      {replaceDialog && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="modal-card">
            <div className="modal-title">
              <AlertTriangle size={18} />
              <h3>Periode deja importee</h3>
            </div>
            <p className="muted">
              Un fichier existe deja pour {displayPeriod(replaceDialog.period)}.
              {replaceDialog.existingBatch?.file_name ? ` Fichier existant: ${replaceDialog.existingBatch.file_name}.` : ""}
            </p>
            <p className="muted">Choisir une action pour continuer.</p>
            <div className="button-row">
              <button className="icon-button" onClick={() => setReplaceDialog(null)}>
                Annuler
              </button>
              <button
                className="danger-button"
                onClick={() => uploadHistorical(true, replaceDialog)}
              >
                Remplacer le fichier
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function TargetsScreen({ agencies, user, setNotice }) {
  // ===== HELPER FUNCTIONS FOR EXCEL IMPORT =====
  // FIX 1: Normalize key (lowercase, remove accents, collapse spaces)
  function normalizeKey(s) {
    if (s == null) return '';
    return s
      .toString()
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/[^a-z0-9]+/g, ' ')
      .trim()
      .replace(/\s+/g, ' ');
  }

  // FIX 2: Distinguish 0 from missing/empty
  function getNumeric(cellValue) {
    if (cellValue === null || cellValue === undefined) return null;
    if (typeof cellValue === 'number') return cellValue;
    const str = String(cellValue).trim().replace(/\s/g, '').replace(',', '.');
    if (str === '' || str === '-') return null;
    const num = Number(str.replace(/[^\d.\-]/g, ''));
    return isNaN(num) ? null : num;
  }

  // FIX 3: Agency matching
  const AGENCY_PREFIX = /^agence\s+/i;
  function stripAgencyPrefix(name) {
    return normalizeKey(name).replace(AGENCY_PREFIX, '');
  }

  const AGENCY_ALIASES = {
    'ariana':       ['ariana'],
    'beja':         ['beja'],
    'ben arous':    ['ben arous', 'benarous'],
    'bizerte':      ['bizerte'],
    'djerba':       ['djerba', 'jerba'],
    'ezahrouni':    ['ezahrouni', 'ezzahrouni', 'ez zahrrouni', 'ezahraouni'],
    'fahs':         ['fahs', 'el fahs', 'elfahs'],
    'gabes':        ['gabes'],
    'gafsa':        ['gafsa'],
    'jendouba':     ['jendouba', 'jenduba'],
    'kasserine':    ['kasserine', 'casserine'],
    'kef':          ['kef', 'el kef', 'elkef'],
    'mahdia':       ['mahdia'],
    'nabeul':       ['nabeul'],
    'sfax':         ['sfax'],
    'sidi bouzid':  ['sidi bouzid', 'sidi-bouzid'],
    'siliana':      ['siliana'],
    'sousse':       ['sousse'],
    'tozeur':       ['tozeur', 'tozour'],
    'tcv':          ['tcv', 'tunis', 'tunis centre ville', 'tunis centre', 'tunis cv', 'tunis-centre'],
  };

  function levenshtein(a, b) {
    if (a === b) return 0;
    if (!a.length) return b.length;
    if (!b.length) return a.length;
    const dp = Array.from({length: a.length + 1}, () => new Array(b.length + 1).fill(0));
    for (let i = 0; i <= a.length; i++) dp[i][0] = i;
    for (let j = 0; j <= b.length; j++) dp[0][j] = j;
    for (let i = 1; i <= a.length; i++) {
      for (let j = 1; j <= b.length; j++) {
        const cost = a[i-1] === b[j-1] ? 0 : 1;
        dp[i][j] = Math.min(dp[i-1][j] + 1, dp[i][j-1] + 1, dp[i-1][j-1] + cost);
      }
    }
    return dp[a.length][b.length];
  }

  function similarity(a, b) {
    if (!a && !b) return 1;
    if (!a || !b) return 0;
    if (a === b) return 1;
    return 1 - levenshtein(a, b) / Math.max(a.length, b.length);
  }

  function matchAgency(excelName, referentialNames) {
    const nExcel = normalizeKey(excelName);
    if (!nExcel) return { matched: null, strategy: 'empty', score: 0 };

    // Skip TOTAL row
    if (nExcel === 'total' || nExcel.startsWith('total ')) {
      return { matched: null, strategy: 'skip-total', score: 1 };
    }

    // Build stripped referential map: {strippedName → originalName}
    const strippedMap = {};
    for (const ref of referentialNames) {
      const stripped = stripAgencyPrefix(ref);
      if (stripped) strippedMap[stripped] = ref;
    }

    // Strategy 1: direct normalized match
    if (strippedMap[nExcel]) {
      return { matched: strippedMap[nExcel], strategy: 'direct', score: 1 };
    }

    // Strategy 2: alias match
    for (const [canonicalRef, aliases] of Object.entries(AGENCY_ALIASES)) {
      const normalizedAliases = aliases.map(normalizeKey);
      if (normalizedAliases.includes(nExcel) || canonicalRef === nExcel) {
        for (const [stripped, original] of Object.entries(strippedMap)) {
          if (stripped === canonicalRef) {
            return { matched: original, strategy: 'alias', score: 1 };
          }
        }
      }
    }

    // Strategy 3: fuzzy match (Levenshtein >= 0.85)
    let bestMatch = null;
    let bestScore = 0;
    for (const stripped of Object.keys(strippedMap)) {
      const score = similarity(nExcel, stripped);
      if (score > bestScore) {
        bestScore = score;
        bestMatch = strippedMap[stripped];
      }
    }
    return bestScore >= 0.85
      ? { matched: bestMatch, strategy: 'fuzzy', score: bestScore }
      : { matched: null, strategy: 'no-match', score: bestScore };
  }

  const isSuperAdmin = user?.role === "super_admin";
  const isAgencyManager = user?.role === "agency_manager";
  const isPortfolioManager = user?.role === "portfolio_manager";
  const canWriteObjectives = isSuperAdmin || isAgencyManager;
  const userAgencyId = (isAgencyManager || isPortfolioManager) ? user?.agency_id : "";
  const userAgentId = isPortfolioManager ? user?.agent_id : "";
  const initialAgency = userAgencyId ? String(userAgencyId) : "";
  const defaultScopeType = isAgencyManager ? "AGENT" : "AGENCY";
  const [scopeType, setScopeType] = useState(defaultScopeType);
  const [formAgents, setFormAgents] = useState([]);
  const [filterAgents, setFilterAgents] = useState([]);
  const [filters, setFilters] = useState({
    target_type: isPortfolioManager ? "AGENT" : "ALL",
    agency_id: initialAgency,
    agent_id: userAgentId ? String(userAgentId) : "",
    month: "",
    year: "",
    limit: 10,
    offset: 0,
  });
  const [targetPage, setTargetPage] = useState({ items: [], total: 0, limit: 10, offset: 0 });
  const [editingId, setEditingId] = useState(null);
  const [agencyActivePeriod, setAgencyActivePeriod] = useState({
    active_from: "",
    active_until: "",
    loading: false,
  });
  const [target, setTarget] = useState({
    target_type: defaultScopeType,
    agency_id: initialAgency,
    agent_id: isAgencyManager ? "" : (userAgentId ? String(userAgentId) : ""),
    month: Number(new Date().getMonth() + 1),
    year: Number(new Date().getFullYear()),
    active_from: "",
    active_until: "",
    target_disbursement_count: 0,
    target_nb_clients: 0,
    target_disbursement: 0,
    target_outstanding: 0,
    target_par: 0.08,
    target_healthy_outstanding: 0,
    target_par_0: 0,
    target_par_1_30: 0,
    target_par_31_60: 0,
    target_par_30: 0,
  });

  // État pour l'import Excel
  const [excelImportFile, setExcelImportFile] = useState(null);
  const [excelImportLoading, setExcelImportLoading] = useState(false);
  const [excelImportPreview, setExcelImportPreview] = useState(null);
  const [excelImportApplying, setExcelImportApplying] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [excelImportStep, setExcelImportStep] = useState("file"); // "file" | "preview" | "report"
  const [excelImportDragActive, setExcelImportDragActive] = useState(false);
  const [excelImportReport, setExcelImportReport] = useState(null);

  // Utilitaire : calcule les 3 prochains jours ouvrés à partir d'aujourd'hui
  // et retourne { du, au } au format jj/mm/aaaa
  function getActivePeriod() {
    const days = [];
    const current = new Date();
    current.setHours(0, 0, 0, 0);
    while (days.length < 3) {
      const dow = current.getDay();
      if (dow >= 1 && dow <= 5) days.push(new Date(current));
      current.setDate(current.getDate() + 1);
    }
    const pad = (n) => String(n).padStart(2, "0");
    const fmt = (d) => `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;
    return { du: fmt(days[0]), au: fmt(days[2]) };
  }

  const filterAgencyId = filters.agency_id ? Number(filters.agency_id) : null;
  const filteredAgencyOptions = userAgencyId
    ? agencies.filter((agency) => Number(agency.id) === Number(userAgencyId))
    : agencies;

  useEffect(() => {
    const agencyId = target.agency_id ? Number(target.agency_id) : null;
    if (!agencyId) {
      setFormAgents([]);
      return;
    }
    api.agents(agencyId)
      .then((page) => setFormAgents(page.items))
      .catch(() => setFormAgents([]));
  }, [target.agency_id]);

  useEffect(() => {
    if (!isAgencyManager) return undefined;
    if (!target.agency_id || !target.month || !target.year) {
      setAgencyActivePeriod({ active_from: "", active_until: "", loading: false });
      return undefined;
    }
    let cancelled = false;
    setAgencyActivePeriod((prev) => ({ ...prev, loading: true }));
    api
      .targets(
        clean({
          target_type: "AGENCY",
          agency_id: target.agency_id,
          month: target.month,
          year: target.year,
          limit: 1,
          offset: 0,
        }),
      )
      .then((page) => {
        if (cancelled) return;
        const agencyTarget = page?.items?.[0];
        setAgencyActivePeriod({
          active_from: agencyTarget?.active_from || "",
          active_until: agencyTarget?.active_until || "",
          loading: false,
        });
      })
      .catch(() => {
        if (cancelled) return;
        setAgencyActivePeriod({ active_from: "", active_until: "", loading: false });
      });
    return () => {
      cancelled = true;
    };
  }, [isAgencyManager, target.agency_id, target.month, target.year]);

  useEffect(() => {
    const agencyId = filters.agency_id ? Number(filters.agency_id) : null;
    if (!agencyId) {
      setFilterAgents([]);
      return;
    }
    api.agents(agencyId)
      .then((page) => setFilterAgents(page.items))
      .catch(() => setFilterAgents([]));
  }, [filters.agency_id]);

  async function loadTargets() {
    try {
      const params = clean({
        limit: filters.limit,
        offset: filters.offset,
        target_type: filters.target_type !== "ALL" ? filters.target_type : undefined,
        agency_id: filters.agency_id || undefined,
        agent_id: filters.agent_id || undefined,
        month: filters.month || undefined,
        year: filters.year || undefined,
      });
      const page = await api.targets(params);
      setTargetPage(page);
    } catch (err) {
      setNotice(err.message);
    }
  }

  useEffect(() => {
    loadTargets();
  }, [filters.target_type, filters.agency_id, filters.agent_id, filters.month, filters.year, filters.offset, filters.limit]);

  useEffect(() => {
    if (isAgencyManager && scopeType !== "AGENT") {
      setScopeType("AGENT");
      setTarget((prev) => ({ ...prev, target_type: "AGENT", agency_id: initialAgency }));
      return;
    }
    if (isSuperAdmin && scopeType !== "AGENCY") {
      setScopeType("AGENCY");
      setTarget((prev) => ({ ...prev, target_type: "AGENCY", agent_id: "" }));
    }
  }, [isSuperAdmin, isAgencyManager, initialAgency, scopeType]);

  function resetForm(nextType = defaultScopeType) {
    setEditingId(null);
    setScopeType(nextType);
    setTarget({
      target_type: nextType,
      agency_id: initialAgency,
      agent_id: nextType === "AGENT" ? (userAgentId ? String(userAgentId) : "") : "",
      month: Number(new Date().getMonth() + 1),
      year: Number(new Date().getFullYear()),
      active_from: "",
      active_until: "",
      target_disbursement_count: 0,
      target_nb_clients: 0,
      target_disbursement: 0,
      target_outstanding: 0,
      target_par: 0.08,
      target_healthy_outstanding: 0,
      target_par_0: 0,
      target_par_1_30: 0,
      target_par_31_60: 0,
      target_par_30: 0,
    });
  }

  function onScopeChange(nextType) {
    if (isPortfolioManager) return;
    if (isAgencyManager && nextType !== "AGENT") {
      setNotice("Chef d'agence: creation/modification autorisee uniquement pour les objectifs GP.");
      return;
    }
    setScopeType(nextType);
    setTarget((prev) => ({
      ...prev,
      target_type: nextType,
      agency_id: (isAgencyManager || isPortfolioManager) ? initialAgency : prev.agency_id,
      agent_id: nextType === "AGENT" ? prev.agent_id : "",
    }));
  }

  function validateForm() {
    if (!canWriteObjectives) return "Votre profil est en lecture seule pour les objectifs.";
    if (!target.target_type) return "Le type d'objectif est obligatoire.";
    if (isSuperAdmin && target.target_type !== "AGENCY" && target.target_type !== "AGENT") {
      return "Super Admin: type d'objectif invalide.";
    }
    if (isAgencyManager && target.target_type !== "AGENT") {
      return "Chef d'agence: seuls les objectifs GP sont modifiables.";
    }
    if (!target.agency_id) return "L'agence est obligatoire.";
    if ((isAgencyManager || isPortfolioManager) && Number(target.agency_id) !== Number(userAgencyId)) {
      return "Vous ne pouvez utiliser que votre agence.";
    }
    if (target.target_type === "AGENT" && !target.agent_id) {
      return "L'agent est obligatoire pour un objectif agent.";
    }
    if (!target.month || !target.year) {
      return "Le mois et l'annee sont obligatoires.";
    }
    if (target.target_type === "AGENCY") {
      if (!target.active_from || !target.active_until) {
        return "La periode active (du/au) est obligatoire pour un objectif agence.";
      }
      const fromTs = new Date(target.active_from).getTime();
      const untilTs = new Date(target.active_until).getTime();
      if (Number.isNaN(fromTs) || Number.isNaN(untilTs)) {
        return "Format de periode active invalide.";
      }
      if (untilTs < fromTs) {
        return "La date de fin de periode active doit etre superieure ou egale a la date de debut.";
      }
    }
    return "";
  }

  function buildPayload() {
    return {
      ...target,
      agency_id: Number(target.agency_id),
      agent_id: target.target_type === "AGENT" ? Number(target.agent_id) : null,
      month: Number(target.month),
      year: Number(target.year),
      active_from: target.target_type === "AGENCY" ? (target.active_from || null) : null,
      active_until: target.target_type === "AGENCY" ? (target.active_until || null) : null,
      target_disbursement_count: Number(target.target_disbursement_count || 0),
      target_nb_clients: Number(target.target_nb_clients || 0),
      target_disbursement: Number(target.target_disbursement || 0),
      target_outstanding: Number(target.target_outstanding || 0),
      target_par: Number(target.target_par || 0),
      target_healthy_outstanding: Number(target.target_healthy_outstanding || 0),
      target_par_0: Number(target.target_par_0 || 0),
      target_par_1_30: Number(target.target_par_1_30 || 0),
      target_par_31_60: Number(target.target_par_31_60 || 0),
      target_par_30: Number(target.target_par_30 || 0),
    };
  }

  async function saveTarget() {
    if (!canWriteObjectives) {
      setNotice("Votre profil est en lecture seule pour les objectifs.");
      return;
    }
    const validationMessage = validateForm();
    if (validationMessage) {
      setNotice(validationMessage);
      return;
    }
    try {
      const payload = buildPayload();
      if (editingId) {
        await api.updateTarget(editingId, payload);
        setNotice("Objectif modifie avec succes.");
      } else {
        await api.createTarget(payload);
        setNotice("Objectif enregistre avec succes.");
      }
      resetForm(scopeType);
      await loadTargets();
    } catch (err) {
      if (err.code === "target_duplicate") {
        setNotice("Un objectif existe deja pour ce type, ce perimetre et cette periode.");
        return;
      }
      setNotice(err.message);
    }
  }

  function editTarget(item) {
    const canEditItem = (
      isSuperAdmin
      || (isAgencyManager && item.target_type === "AGENT" && Number(item.agency_id) === Number(userAgencyId))
    );
    if (!canEditItem) {
      setNotice("Vous ne pouvez pas modifier cet objectif.");
      return;
    }
    const nextType = item.target_type || "AGENCY";
    setEditingId(item.id);
    setScopeType(nextType);
    setTarget({
      target_type: nextType,
      agency_id: item.agency_id ? String(item.agency_id) : initialAgency,
      agent_id: item.agent_id ? String(item.agent_id) : "",
      month: Number(item.month),
      year: Number(item.year),
      active_from: item.active_from || "",
      active_until: item.active_until || "",
      target_disbursement_count: Number(item.target_disbursement_count || 0),
      target_nb_clients: Number(item.target_nb_clients || 0),
      target_disbursement: Number(item.target_disbursement || 0),
      target_outstanding: Number(item.target_outstanding || 0),
      target_par: Number(item.target_par || 0),
      target_healthy_outstanding: Number(item.target_healthy_outstanding || 0),
      target_par_0: Number(item.target_par_0 || 0),
      target_par_1_30: Number(item.target_par_1_30 || 0),
      target_par_31_60: Number(item.target_par_31_60 || 0),
      target_par_30: Number(item.target_par_30 || 0),
    });
  }

  async function removeTarget(id) {
    if (!canWriteObjectives) {
      setNotice("Votre profil est en lecture seule pour les objectifs.");
      return;
    }
    const confirmed = window.confirm("Etes-vous sur de vouloir supprimer cet objectif ?");
    if (!confirmed) return;
    try {
      await api.deleteTarget(id);
      setNotice("Objectif supprime.");
      await loadTargets();
    } catch (err) {
      setNotice(err.message);
    }
  }

  // Gestion de l'import Excel d'objectifs (client-side parsing avec xlsx)
  const handleExcelFileSelect = (e) => {
    const file = e.target.files[0];
    if (file) {
      setExcelImportFile(file);
      setExcelImportPreview(null);
      setExcelImportStep("file");
      setExcelImportReport(null);
    }
  };

  const resetExcelImport = () => {
    setExcelImportFile(null);
    setExcelImportPreview(null);
    setExcelImportReport(null);
    setExcelImportStep("file");
  };

  const parseExcelFile = async () => {
    if (!excelImportFile) return;
    setExcelImportLoading(true);
    setExcelImportPreview(null);
    try {
      const arrayBuffer = await excelImportFile.arrayBuffer();
      const workbook = XLSX.read(arrayBuffer, { type: "array" });
      const sheetName = workbook.SheetNames[0];
      const worksheet = workbook.Sheets[sheetName];

      // Lire la cellule A1 (titre)
      const cellA1 = worksheet["A1"];
      const title = cellA1?.v ? String(cellA1.v).trim() : "";

      // Extraire mois et année du titre (ex: "Objectif Septembre 2026")
      const monthYearMatch = title.match(/Objectif\s+([a-zA-Z]+)\s+(\d{4})/i);
      let detectedMonth = null;
      let detectedYear = null;
      const MONTH_MAP = {
        "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4,
        "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
        "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
      };
      if (monthYearMatch) {
        const monthName = monthYearMatch[1].toLowerCase();
        detectedMonth = MONTH_MAP[monthName] || null;
        detectedYear = parseInt(monthYearMatch[2], 10);
      }

      const month = detectedMonth || target.month;
      const year = detectedYear || target.year;

      // FIX 1: Lire les en-têtes de la ligne 2 avec normalisation
      const headerMap = {}; // normalizedKey -> original header
      const colMap = {};    // normalizedKey -> column index
      const range = XLSX.utils.decode_range(worksheet["!ref"] || "A1");
      for (let col = range.s.c; col <= range.e.c; col++) {
        const cellAddress = XLSX.utils.encode_cell({ r: 1, c: col }); // Ligne 2 (index 1)
        const cell = worksheet[cellAddress];
        if (cell && cell.v != null && String(cell.v).trim() !== '') {
          const originalHeader = String(cell.v).trim();
          const norm = normalizeKey(originalHeader);
          headerMap[norm] = originalHeader;
          colMap[norm] = col;
        }
      }

      // Recherche tolérante des colonnes requises
      function findColumn(targetNorm) {
        if (colMap[targetNorm]) return colMap[targetNorm];
        for (const key of Object.keys(colMap)) {
          if (key.includes(targetNorm)) return colMap[key];
        }
        return null;
      }

      const colTotalGeneral = findColumn('total general');
      const colEncoursSain  = findColumn('encours sain');
      const colPAR0         = findColumn('par 0');
      const colPAR30        = findColumn('par 30');
      const colTranches = {};
      const trancheKeys = [
        '[1-30]', '[31-60]', '[61-90]', '[91-120]',
        '[121-150]', '[151-180]', '[181-210]', '[211-240]',
        '[241-270]', '[271-300]', '[301-330]', '[331-360]'
      ];
      for (const t of trancheKeys) {
        const norm = normalizeKey(t); // e.g. "1 30", "31 60"
        colTranches[t] = findColumn(norm);
      }

      const errors = [];
      const missing = [];
      if (colTotalGeneral === null) missing.push('Total général');
      if (colEncoursSain === null) missing.push('Encours sain');
      if (colPAR0 === null) missing.push('PAR 0');
      if (colPAR30 === null) missing.push('PAR 30');
      if (missing.length > 0) {
        errors.push(`Colonnes manquantes dans l'Excel : ${missing.join(", ")}`);
      }

      // Lignes de données (à partir de la ligne 3, index 2)
      const rows = [];
      const agencyCol = 0;
      for (let rowIdx = 2; rowIdx <= range.e.r; rowIdx++) {
        const agencyCell = worksheet[XLSX.utils.encode_cell({ r: rowIdx, c: agencyCol })];
        if (!agencyCell || !agencyCell.v) continue;
        const agencyName = String(agencyCell.v).trim();
        if (agencyName.toUpperCase() === "TOTAL") continue;
        if (!agencyName) continue;

        const rowData = { agence: agencyName };

        // FIX 2: Utiliser getNumeric pour distinguer 0 de manquant
        const getVal = (colIdx) => {
          if (colIdx === null) return null;
          const cell = worksheet[XLSX.utils.encode_cell({ r: rowIdx, c: colIdx })];
          return getNumeric(cell?.v);
        };

        // PAR30 % field in framework multiplies by 100 internally for display
        // So we must NOT multiply in import - keep as decimal (0.0523)
        // But guard against malformed Excel with values > 1 (e.g., 5.23 instead of 0.0523)
        function normalizeDecimalPercentage(raw) {
          if (raw === null) return null;
          if (raw > 1) {
            console.warn(
              `Valeur PAR30 > 1 detectee (${raw}), conversion en decimal (${raw / 100}). ` +
              `Le fichier Excel devrait contenir 0.0523 pour 5.23%.`
            );
            return raw / 100;
          }
          return raw;
        }

        const valTotalGeneral = getVal(colTotalGeneral);
        const valEncoursSain = getVal(colEncoursSain);
        const valPAR0 = getVal(colPAR0);
        const valPAR30 = getVal(colPAR30);

        rowData['total general'] = valTotalGeneral ?? 0;
        rowData['encours sain'] = valEncoursSain ?? 0;
        // PAR0: simple number field, multiply by 100 (0.1365 → 13.65)
        rowData['par 0'] = valPAR0 !== null ? valPAR0 * 100 : 0;
        // PAR30%: percentage field in framework, keep as decimal (0.0523)
        rowData['par 30'] = normalizeDecimalPercentage(valPAR30) ?? 0;

        for (const t of trancheKeys) {
          const v = getVal(colTranches[t]);
          rowData[normalizeKey(t)] = v ?? 0;
        }

        rows.push(rowData);
      }

      // Mapper les données selon le mapping requis
      const mappedRows = [];
      for (const row of rows) {
        const par1_30 = row['1 30'] || 0;
        const par31_60 = row['31 60'] || 0;
        const encoursSain = row['encours sain'] || 0;
        const totalGeneral = row['total general'] || 0;
        const par0 = row['par 0'] || 0;
        const par30 = row['par 30'] || 0;

        // Calculer PAR30 montant = somme des tranches [31-60] à [331-360]
        let par30Montant = 0;
        const availableTranches = [];
        const missingTranches = [];
        for (const t of trancheKeys.slice(1)) { // skip [1-30]
          const colIdx = colTranches[t];
          if (colIdx !== null) {
            const v = row[normalizeKey(t)] || 0;
            par30Montant += v;
            availableTranches.push(t);
          } else {
            missingTranches.push(t);
          }
        }
        // Warning seulement si la colonne n'existe PAS dans l'en-tête
        if (missingTranches.length > 0) {
          errors.push(`Agence ${row.agence}: colonnes tranches absentes de l'en-tête: ${missingTranches.join(", ")}`);
        }

        // Calculer Objectif encours = Total general + Encours sain
        // Si Total general manquant (colonne absente), calculer = somme de toutes les tranches
        let objectifEncours = totalGeneral + encoursSain;
        if (colTotalGeneral === null) {
          let sumTranches = 0;
          for (const t of trancheKeys) {
            sumTranches += row[normalizeKey(t)] || 0;
          }
          objectifEncours = sumTranches + encoursSain;
          if (sumTranches > 0) {
            errors.push(`Agence ${row.agence}: "Total général" absent de l'en-tête, calculé comme somme des tranches`);
          }
        }

        mappedRows.push({
          agency_name: row.agence,
          target_par_1_30: par1_30,
          target_par_31_60: par31_60,
          target_par_30: par30Montant,
          target_outstanding: objectifEncours,
          target_healthy_outstanding: encoursSain,
          target_par_0: par0,
          target_par: par30,
        });
      }

      // FIX 3: Correspondre avec les agences en base via matchAgency
      const agencyPage = await api.agencies();
      const dbAgencies = agencyPage.items || [];
      const referentialNames = dbAgencies.map(a => a.name);

      const validRows = [];
      const matchedErrors = [];
      for (const row of mappedRows) {
        const { matched, strategy, score } = matchAgency(row.agency_name, referentialNames);
        if (!matched) {
          if (strategy === 'skip-total') continue;
          matchedErrors.push({
            agence: row.agency_name,
            raison: 'AGENCE_NON_MATCHED',
            meilleur_score: score.toFixed(2),
            strategie: strategy,
          });
          continue;
        }
        console.info(`Match agence: Excel="${row.agency_name}" → Référentiel="${matched}" (stratégie=${strategy}, score=${score.toFixed(2)})`);
        const agency = dbAgencies.find(a => a.name === matched);
        validRows.push({ ...row, agency_id: agency.id });
      }

      // Vérifier les doublons existants
      let existingCount = 0;
      const existingAgencies = [];
      for (const row of validRows) {
        const existing = await api.targets(
          clean({
            target_type: "AGENCY",
            agency_id: row.agency_id,
            month: month,
            year: year,
            limit: 1,
            offset: 0,
          })
        );
        if (existing.items && existing.items.length > 0) {
          existingCount++;
          existingAgencies.push(row.agency_name);
        }
      }

      const preview = {
        title,
        month,
        year,
        rows: validRows,
        detected_agencies: rows.length,
        valid_agencies: validRows.length,
        existing_count: existingCount,
        existing_agencies: existingAgencies,
        errors: [...errors, ...matchedErrors.map(e => `${e.agence}: ${e.raison} (score=${e.meilleur_score}, ${e.strategie})`)],
      };

      setExcelImportPreview(preview);
      setExcelImportStep("preview");
      if (preview.errors.length > 0) {
        setNotice(`${preview.errors.length} avertissement(s) lors de l'analyse.`);
      }
    } catch (err) {
      setNotice(err.message || "Erreur lors de l'analyse du fichier Excel.");
      setExcelImportPreview(null);
    } finally {
      setExcelImportLoading(false);
    }
  };

  const prefillCurrentForm = () => {
    if (!excelImportPreview || !excelImportPreview.rows?.length) return;
    const selectedAgencyId = target.agency_id;
    if (!selectedAgencyId) {
      setNotice("Veuillez d'abord selectionner une agence dans le formulaire.");
      return;
    }
    const selectedAgency = agencies.find(a => String(a.id) === String(selectedAgencyId));
    if (!selectedAgency) {
      setNotice("Agence selectionnee introuvable.");
      return;
    }
    const normalizedSelected = selectedAgency.name.trim().toUpperCase().replace(/\s+/g, " ");
    const matchedRow = excelImportPreview.rows.find(r => 
      r.agency_name.trim().toUpperCase().replace(/\s+/g, " ") === normalizedSelected
    );
    if (!matchedRow) {
      setNotice(`Agence "${selectedAgency.name}" introuvable dans le fichier Excel.`);
      return;
    }

    // Pre-remplir UNIQUEMENT les champs mappés depuis Excel
    // NE PAS toucher aux 3 champs non-Excel : target_disbursement_count, target_nb_clients, target_disbursement
    const { du, au } = getActivePeriod();
    setTarget(prev => ({
      ...prev,
      target_par_1_30: matchedRow.target_par_1_30,
      target_par_31_60: matchedRow.target_par_31_60,
      target_par_30: matchedRow.target_par_30,
      target_outstanding: matchedRow.target_outstanding,
      target_healthy_outstanding: matchedRow.target_healthy_outstanding,
      target_par_0: matchedRow.target_par_0,
      target_par: matchedRow.target_par,
      // Mettre à jour mois/année si détectés
      month: excelImportPreview.month || prev.month,
      year: excelImportPreview.year || prev.year,
      // Période active calculée automatiquement (3 jours ouvrés)
      active_from: du,
      active_until: au,
    }));
    setNotice("Formulaire pre-rempli depuis l'Excel (Mode B). Verifiez et cliquez sur Enregistrer.");
    setShowImportModal(false);
  };

  const handleImportConfirm = async (action) => {
    if (!excelImportPreview || !excelImportPreview.rows) return;
    setExcelImportApplying(true);
    try {
      const { du, au } = getActivePeriod();
      const payload = {
        month: excelImportPreview.month,
        year: excelImportPreview.year,
        rows: excelImportPreview.rows.map((r) => ({
          ...r,
          active_from: du,
          active_until: au,
        })),
        action: action,
      };
      const result = await api.confirmTargetsImport(payload);
      setNotice(result.message);
      
      // Rapport d'import
      setExcelImportReport({
        success: result.imported || 0,
        updated: result.updated || 0,
        skipped: result.skipped || 0,
        errors: [],
      });
      setExcelImportStep("report");
      
      await loadTargets();
    } catch (err) {
      setNotice(err.message || "Erreur lors de l'import.");
      setExcelImportReport({
        success: 0,
        updated: 0,
        skipped: 0,
        errors: [err.message || "Erreur inconnue"],
      });
      setExcelImportStep("report");
    } finally {
      setExcelImportApplying(false);
    }
  };

  const noAgenciesAvailable = filteredAgencyOptions.length === 0;
  const noAgentsAvailable = scopeType === "AGENT" && target.agency_id && formAgents.length === 0;

  const disabledAgency = isAgencyManager || isPortfolioManager;
  const canEditListedTarget = (item) => (
    isSuperAdmin
    || (isAgencyManager && item.target_type === "AGENT" && Number(item.agency_id) === Number(userAgencyId))
  );
  const targetColumns = useMemo(
    () => [
      { key: "target_type", label: "Type", render: (item) => (item.target_type === "AGENT" ? "Agent" : "Agence"), sortableType: "text", sortAccessor: (item) => item.target_type },
      { key: "agency", label: "Agence", render: (item) => item.agency?.name || "-", sortableType: "text", sortAccessor: (item) => item.agency?.name },
      { key: "agent", label: "Agent", render: (item) => item.agent?.name || "-", sortableType: "text", sortAccessor: (item) => item.agent?.name },
      {
        key: "month",
        label: "Mois",
        render: (item) => item.month,
        sortableType: "number",
        sortAccessor: (item) => item.month,
      },
      {
        key: "year",
        label: "Annee",
        render: (item) => item.year,
        sortableType: "number",
        sortAccessor: (item) => item.year,
      },
      {
        key: "active_period",
        label: "Periode active",
        render: (item) => {
          if (!item.active_from || !item.active_until) return "-";
          return `${shortDate(item.active_from)} -> ${shortDate(item.active_until)}`;
        },
        sortableType: "date",
        sortAccessor: (item) => item.active_from,
        filterType: "date",
        filterAccessor: (item) => item.active_from,
      },
      {
        key: "target_disbursement_count",
        label: "Nb decaissements",
        render: (item) => money(item.target_disbursement_count),
        sortableType: "number",
        sortAccessor: (item) => item.target_disbursement_count,
      },
      {
        key: "target_nb_clients",
        label: "Nb clients",
        render: (item) => money(item.target_nb_clients),
        sortableType: "number",
        sortAccessor: (item) => item.target_nb_clients,
      },
      {
        key: "target_disbursement",
        label: "Volume",
        render: (item) => money(item.target_disbursement),
        sortableType: "number",
        sortAccessor: (item) => item.target_disbursement,
      },
      {
        key: "target_outstanding",
        label: "Encours",
        render: (item) => money(item.target_outstanding),
        sortableType: "number",
        sortAccessor: (item) => item.target_outstanding,
      },
      {
        key: "target_par",
        label: "PAR30 %",
        render: (item) => percent(item.target_par),
        sortableType: "number",
        sortAccessor: (item) => item.target_par,
      },
      {
        key: "target_healthy_outstanding",
        label: "Encours sain",
        render: (item) => money(item.target_healthy_outstanding),
        sortableType: "number",
        sortAccessor: (item) => item.target_healthy_outstanding,
      },
      {
        key: "target_par_0",
        label: "PAR0",
        render: (item) => money(item.target_par_0),
        sortableType: "number",
        sortAccessor: (item) => item.target_par_0,
      },
      {
        key: "target_par_1_30",
        label: "PAR1-30",
        render: (item) => money(item.target_par_1_30),
        sortableType: "number",
        sortAccessor: (item) => item.target_par_1_30,
      },
      {
        key: "target_par_31_60",
        label: "PAR31-60",
        render: (item) => money(item.target_par_31_60),
        sortableType: "number",
        sortAccessor: (item) => item.target_par_31_60,
      },
      {
        key: "target_par_30",
        label: "PAR30",
        render: (item) => money(item.target_par_30),
        sortableType: "number",
        sortAccessor: (item) => item.target_par_30,
      },
      {
        key: "last_modified_by",
        label: "Enregistre / modifie par",
        render: (item) =>
          item.updated_by_user?.full_name || item.created_by_user?.full_name || "-",
        sortableType: "text",
        sortAccessor: (item) => item.updated_by_user?.full_name || item.created_by_user?.full_name || "",
      },
      {
        key: "last_action_date",
        label: "Date de l'action",
        render: (item) =>
          formatDateTimeLabel(item.updated_at || item.created_at) || "-",
        sortableType: "date",
        sortAccessor: (item) => item.updated_at || item.created_at,
      },
      { key: "actions", label: "Actions", render: () => null },
    ],
    [],
  );
  const {
    sortState: targetSortState,
    sortedRows: sortedTargetItems,
    columnFilters: targetFilters,
    activeFilterCount: targetFilterCount,
    applySort: applyTargetSort,
    updateFilter: updateTargetFilter,
    resetFilter: resetTargetFilter,
    resetAllFilters: resetAllTargetFilters,
  } = useAdvancedTableState(targetPage.items, targetColumns);

  return (
    <section className="targets-stack">
      <div className="panel">
        <h3>Objectifs mensuels</h3>
        <div className="segment-control" role="tablist" aria-label="Type objectif">
          <button
            role="tab"
            className={scopeType === "AGENCY" ? "segment-active" : ""}
            disabled={isAgencyManager || isPortfolioManager}
            onClick={() => onScopeChange("AGENCY")}
            type="button"
          >
            Agence
          </button>
          <button
            role="tab"
            className={scopeType === "AGENT" ? "segment-active" : ""}
             disabled={isPortfolioManager}
            onClick={() => onScopeChange("AGENT")}
            type="button"
          >
            Agent
          </button>
        </div>
        <p className="muted">
          {scopeType === "AGENCY"
            ? "Definir des objectifs globaux pour une agence."
            : "Definir des objectifs individuels pour un agent."}
        </p>
        {isSuperAdmin && (
          <p className="muted">Super Admin: gestion de tous les objectifs (agence et GP) de toutes les agences.</p>
        )}
        {isAgencyManager && (
          <p className="muted">Chef d'agence: gestion des objectifs GP de votre agence uniquement.</p>
        )}
        {isPortfolioManager && (
          <p className="muted">Mode lecture seule: vous voyez uniquement vos propres objectifs.</p>
        )}
        <div className="form-grid">
          <label>Agence
            <select
              disabled={disabledAgency || noAgenciesAvailable || isPortfolioManager}
              value={target.agency_id}
              onChange={(e) =>
                setTarget({
                  ...target,
                  agency_id: e.target.value,
                  agent_id: "",
                })
              }
            >
              <option value="">Choisir</option>
              {filteredAgencyOptions.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}
            </select>
          </label>
          <label>Type
            <input value={scopeType === "AGENCY" ? "Agence" : "Agent"} disabled />
          </label>
          <label>Mois<input disabled={!canWriteObjectives} type="number" min="1" max="12" value={target.month} onChange={(e) => setTarget({ ...target, month: Number(e.target.value) })} /></label>
          <label>Annee<input disabled={!canWriteObjectives} type="number" value={target.year} onChange={(e) => setTarget({ ...target, year: Number(e.target.value) })} /></label>
          {scopeType === "AGENCY" && (
            <>
              <label>Periode active du
                <input
                  type="date"
                  disabled={!isSuperAdmin}
                  value={target.active_from || ""}
                  onChange={(e) => setTarget({ ...target, active_from: e.target.value })}
                />
              </label>
              <label>Periode active au
                <input
                  type="date"
                  disabled={!isSuperAdmin}
                  value={target.active_until || ""}
                  onChange={(e) => setTarget({ ...target, active_until: e.target.value })}
                />
              </label>
            </>
          )}
          {(scopeType === "AGENT" || isAgencyManager || isPortfolioManager) && (
            <label>Agent
              <select
                disabled={isPortfolioManager || !target.agency_id || noAgentsAvailable}
                value={target.agent_id}
                onChange={(e) => setTarget({ ...target, agent_id: e.target.value })}
              >
                <option value="">
                  {isPortfolioManager
                    ? "Mon compte"
                    : (!target.agency_id
                    ? "Selectionner d'abord une agence"
                    : noAgentsAvailable
                      ? "Aucun agent disponible"
                      : "Choisir")}
                </option>
                {formAgents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
              </select>
            </label>
          )}
          {(scopeType === "AGENT" || isAgencyManager) && (
            <label>Periode active (objectif agence)
              <input
                value={
                  agencyActivePeriod.loading
                    ? "Chargement..."
                    : (agencyActivePeriod.active_from && agencyActivePeriod.active_until
                      ? `${shortDate(agencyActivePeriod.active_from)} -> ${shortDate(agencyActivePeriod.active_until)}`
                      : "Aucune periode agence definie")
                }
                disabled
              />
            </label>
          )}
          <NumberField label="Objectif nombre decaissements" field="target_disbursement_count" state={target} setState={setTarget} disabled={!canWriteObjectives} />
          <NumberField label="Objectif clients en encours" field="target_nb_clients" state={target} setState={setTarget} disabled={!canWriteObjectives} />
          <NumberField label="Objectif volume decaissement" field="target_disbursement" state={target} setState={setTarget} disabled={!canWriteObjectives} />
          <NumberField label="Objectif encours" field="target_outstanding" state={target} setState={setTarget} disabled={!canWriteObjectives} />
          <NumberField label="Objectif PAR30 %" field="target_par" state={target} setState={setTarget} step="0.0001" disabled={!canWriteObjectives} />
          <NumberField label="Objectif encours sain" field="target_healthy_outstanding" state={target} setState={setTarget} disabled={!canWriteObjectives} />
          <NumberField label="Objectif PAR0" field="target_par_0" state={target} setState={setTarget} disabled={!canWriteObjectives} />
          <NumberField label="Objectif PAR1-30" field="target_par_1_30" state={target} setState={setTarget} disabled={!canWriteObjectives} />
          <NumberField label="Objectif PAR31-60" field="target_par_31_60" state={target} setState={setTarget} disabled={!canWriteObjectives} />
          <NumberField label="Objectif PAR30 montant" field="target_par_30" state={target} setState={setTarget} disabled={!canWriteObjectives} />
        </div>
        {(noAgenciesAvailable || noAgentsAvailable) && (
          <p className="muted">
            {noAgenciesAvailable
              ? "Aucune agence disponible actuellement."
              : "Aucun agent n'est disponible pour l'agence selectionnee."}
          </p>
        )}
        <div className="button-row">
          <button className="primary fit" onClick={saveTarget} disabled={!canWriteObjectives}>
            <Save size={16} />
            {editingId ? "Enregistrer modifications" : "Enregistrer objectif"}
          </button>
          {canWriteObjectives && scopeType === "AGENCY" && (
            <button
              type="button"
              className="secondary"
              onClick={() => setShowImportModal(true)}
              disabled={excelImportLoading || excelImportApplying}
            >
              <Upload size={16} />
              Importer Excel
            </button>
          )}
          {editingId && (
            <button className="icon-button" type="button" onClick={() => resetForm(scopeType)}>
              Annuler edition
            </button>
          )}
        </div>
      </div>

      {/* Modal Import Excel - Objectifs mensuels */}
      {showImportModal && (
        <div
          className="modal-backdrop import-modal-backdrop"
          onClick={() => !excelImportLoading && !excelImportApplying && setShowImportModal(false)}
        >
          <div
            className="modal import-modal-new"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="import-modal-title"
          >
            <div className="import-modal-header">
              <div className="import-modal-title-row">
                <Upload size={24} className="import-modal-icon" />
                <div>
                  <h3 id="import-modal-title">Importer un fichier Excel d&rsquo;objectifs</h3>
                  <p className="import-modal-subtitle">Pré-remplit automatiquement les objectifs des agences</p>
                </div>
              </div>
              <button
                type="button"
                className="import-modal-close"
                onClick={() => !excelImportLoading && !excelImportApplying && setShowImportModal(false)}
                aria-label="Fermer"
                disabled={excelImportLoading || excelImportApplying}
              >
                <X size={20} />
              </button>
            </div>

            {excelImportStep === "loading" && (
              <div className="import-modal-loading">
                <span className="spinner-large" />
                <p>Import en cours…</p>
                <p className="import-modal-loading-subtitle">
                  Lecture du fichier, mapping des agences, sauvegarde des objectifs…
                </p>
              </div>
            )}

            {excelImportStep === "file" && (
              <div className="import-modal-body">
                <div
                  className={`import-dropzone ${excelImportDragActive ? 'drag-active' : ''}`}
                  onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setExcelImportDragActive(true); }}
                  onDragLeave={(e) => { e.preventDefault(); e.stopPropagation(); setExcelImportDragActive(false); }}
                  onDrop={(e) => {
                    e.preventDefault(); e.stopPropagation();
                    setExcelImportDragActive(false);
                    const file = e.dataTransfer.files[0];
                    if (file && (file.name.endsWith('.xlsx') || file.name.endsWith('.xls'))) {
                      handleExcelFileSelect({ target: { files: [file] } });
                    }
                  }}
                  onClick={() => !excelImportFile && document.getElementById('excel-file-input')?.click()}
                >
                  <input
                    id="excel-file-input"
                    type="file"
                    accept=".xlsx,.xls"
                    onChange={handleExcelFileSelect}
                    disabled={excelImportLoading || excelImportApplying}
                    style={{ display: 'none' }}
                  />
                  <Upload size={40} className="import-dropzone-icon" />
                  <p className="import-dropzone-title">Glissez votre fichier Excel ici</p>
                  <p className="import-dropzone-subtitle">ou cliquez pour parcourir</p>
                  <p className="import-dropzone-formats">Formats acceptés : .xlsx, .xls</p>
                  {excelImportFile && (
                    <div className="import-dropzone-selected">
                      <FileDown size={18} className="import-dropzone-file-icon" />
                      <span className="import-dropzone-file-name">{excelImportFile.name}</span>
                      <span className="import-dropzone-file-size">
                        {(excelImportFile.size / 1024).toFixed(1)} KB
                      </span>
                      <button
                        type="button"
                        className="import-dropzone-change"
                        onClick={(e) => { e.stopPropagation(); setExcelImportFile(null); }}
                      >
                        Changer
                      </button>
                    </div>
                  )}
                </div>

                <p className="import-template-hint">
                  Template requis : Feuille <strong>Feuil1</strong> | Cellule B1 : <strong>{"Objectif <Mois> <Année>"}</strong>
                  (ex: <code>Objectif Septembre 2026</code>)
                </p>

                <div className="import-modal-footer">
                  <button className="secondary" onClick={() => setShowImportModal(false)}>Annuler</button>
                  <button
                    className="primary"
                    onClick={parseExcelFile}
                    disabled={!excelImportFile || excelImportLoading || excelImportApplying}
                  >
                    {excelImportLoading ? <span className="spinner-small" /> : 'Analyser et pré-remplir'}
                  </button>
                </div>
              </div>
            )}

            {excelImportStep === "preview" && excelImportPreview && (
              <div className="import-modal-body">
                <div className="import-preview-summary">
                  <div className="import-preview-period">
                    <span className="label">Période détectée :</span>
                    <span className="value">{excelImportPreview.month} / {excelImportPreview.year}</span>
                  </div>
                  <div className="import-preview-stats">
                    <span><strong>{excelImportPreview.detected_agencies}</strong> agences détectées</span>
                    <span><strong>{excelImportPreview.valid_agencies}</strong> agences valides</span>
                    {excelImportPreview.existing_count > 0 && (
                      <span className="import-preview-existing">
                        <strong>{excelImportPreview.existing_count}</strong> objectif(s) existant(s)
                      </span>
                    )}
                  </div>
                </div>

                {excelImportPreview.errors && excelImportPreview.errors.length > 0 && (
                  <div className="import-preview-warnings">
                    <strong>⚠ Avertissements :</strong>
                    <ul>
                      {excelImportPreview.errors.map((err, idx) => (
                        <li key={idx}>{err}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {excelImportPreview.rows && excelImportPreview.rows.length > 0 && (
                  <div className="import-table-wrap">
                    <table className="styled-table">
                      <thead>
                        <tr>
                          <th>Agence</th>
                          <th>PAR1-30</th>
                          <th>PAR31-60</th>
                          <th>PAR30 montant</th>
                          <th>Encours</th>
                          <th>Encours sain</th>
                          <th>PAR0</th>
                          <th>PAR30 %</th>
                        </tr>
                      </thead>
                      <tbody>
                        {excelImportPreview.rows.map((row, idx) => (
                          <tr key={idx}>
                            <td>{row.agency_name}</td>
                            <td>{Number(row.target_par_1_30).toLocaleString("fr-FR")}</td>
                            <td>{Number(row.target_par_31_60).toLocaleString("fr-FR")}</td>
                            <td>{Number(row.target_par_30).toLocaleString("fr-FR")}</td>
                            <td>{Number(row.target_outstanding).toLocaleString("fr-FR")}</td>
                            <td>{Number(row.target_healthy_outstanding).toLocaleString("fr-FR")}</td>
                            <td>{Number(row.target_par_0).toLocaleString("fr-FR", {minimumFractionDigits: 2, maximumFractionDigits: 2})}%</td>
                            <td>{Number(row.target_par).toFixed(2)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                <div className="import-modal-footer">
                  <button className="secondary" onClick={() => setExcelImportStep("file")}>Retour</button>
                  <button className="icon-button" onClick={resetExcelImport} aria-label="Réinitialiser">
                    <X size={14} />
                  </button>
                  <button
                    className="secondary"
                    onClick={() => prefillCurrentForm()}
                    disabled={excelImportApplying || !excelImportPreview.rows?.length}
                  >
                    Pré-remplir le formulaire courant (Mode B)
                  </button>
                  <button
                    className="primary"
                    onClick={() => { setExcelImportStep("loading"); handleImportConfirm("update"); }}
                    disabled={excelImportApplying}
                  >
                    {excelImportApplying ? 'Importation...' : 'Importer en masse (Mode A)'}
                  </button>
                </div>
              </div>
            )}

            {excelImportStep === "report" && excelImportReport && (
              <div className="import-modal-body import-report-body">
                <div className="import-report-stats">
                  <div className="import-stat-card success">
                    <div className="import-stat-icon">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    </div>
                    <div className="import-stat-value">{excelImportReport.success || 0}</div>
                    <div className="import-stat-label">agences<br />importées</div>
                  </div>
                  <div className="import-stat-card warning">
                    <div className="import-stat-icon">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                        <line x1="12" y1="9" x2="12" y2="13" />
                        <line x1="12" y1="17" x2="12.01" y2="17" />
                      </svg>
                    </div>
                    <div className="import-stat-value">{excelImportReport.skipped || 0}</div>
                    <div className="import-stat-label">agences<br />ignorées</div>
                  </div>
                  <div className="import-stat-card error">
                    <div className="import-stat-icon">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                        <circle cx="12" cy="12" r="10" />
                        <line x1="15" y1="9" x2="9" y2="15" />
                        <line x1="9" y1="9" x2="15" y2="15" />
                      </svg>
                    </div>
                    <div className="import-stat-value">{excelImportReport.errors?.length || 0}</div>
                    <div className="import-stat-label">agences<br />en erreur</div>
                  </div>
                </div>

                {excelImportReport.errors && excelImportReport.errors.length > 0 && (
                  <div className="import-report-detail">
                    <h4>Détail du rapport</h4>
                    <div className="import-report-list" role="list">
                      {excelImportPreview?.rows?.map((row, idx) => {
                        const isError = excelImportReport.errors?.some(e => e.includes(row.agency_name));
                        const isSkipped = isError ? false : (excelImportReport.skipped || 0) > 0;
                        if (isError) {
                          return (
                            <div key={idx} className="import-report-item error" role="listitem">
                              <span className="import-report-icon error">✗</span>
                              <span className="import-report-agency">{row.agency_name}</span>
                              <span className="import-report-reason">
                                {excelImportReport.errors.find(e => e.includes(row.agency_name)) || 'Erreur inconnue'}
                              </span>
                            </div>
                          );
                        }
                        return (
                          <div key={idx} className="import-report-item success" role="listitem">
                            <span className="import-report-icon success">✓</span>
                            <span className="import-report-agency">{row.agency_name}</span>
                            <span className="import-report-reason">
                              Importée (PAR0: {Number(row.target_par_0).toFixed(2)}%, PAR30: {Number(row.target_par).toFixed(2)}%)
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                <div className="import-modal-footer">
                  {excelImportReport.errors && excelImportReport.errors.length > 0 && (
                    <button
                      className="secondary"
                      onClick={() => { setExcelImportStep("file"); resetExcelImport(); }}
                    >
                      Réessayer
                    </button>
                  )}
                  <button
                    className={excelImportReport.success > 0 ? 'primary' : 'secondary'}
                    onClick={() => { resetExcelImport(); setShowImportModal(false); }}
                  >
                    {excelImportReport.success > 0 ? 'Voir les objectifs' : 'Fermer'}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}


      <div className="panel table-panel">
        <div className="panel-header">
          <h3>Liste des objectifs</h3>
          <div className="button-row">
            <select
              value={filters.target_type}
              onChange={(e) =>
                setFilters({
                  ...filters,
                  target_type: e.target.value,
                  agent_id: e.target.value === "AGENT" ? filters.agent_id : "",
                  offset: 0,
                })
              }
            >
              <option value="ALL">Tous les types</option>
              <option value="AGENCY">Agence</option>
              <option value="AGENT">Agent</option>
            </select>
            <select
              value={filters.agency_id}
              disabled={isAgencyManager || isPortfolioManager}
              onChange={(e) =>
                setFilters({
                  ...filters,
                  agency_id: e.target.value,
                  agent_id: "",
                  offset: 0,
                })
              }
            >
              <option value="">Toutes les agences</option>
              {filteredAgencyOptions.map((agency) => (
                <option key={agency.id} value={agency.id}>{agency.name}</option>
              ))}
            </select>
            {!isSuperAdmin && (
              <select
                disabled={isPortfolioManager || !filterAgencyId}
                value={filters.agent_id}
                onChange={(e) => setFilters({ ...filters, agent_id: e.target.value, offset: 0 })}
              >
                <option value="">
                  {isPortfolioManager
                    ? "Mon compte"
                    : (!filterAgencyId ? "Agent (choisir agence)" : "Tous les agents")}
                </option>
                {filterAgents.map((agent) => (
                  <option key={agent.id} value={agent.id}>{agent.name}</option>
                ))}
              </select>
            )}
          </div>
        </div>
        <div className="table-scroll">
          {targetFilterCount > 0 && (
            <div className="table-filter-summary">
              <span>{targetFilterCount} filtre(s) actif(s)</span>
              <button type="button" className="icon-button" onClick={resetAllTargetFilters}>Reinitialiser tous les filtres</button>
            </div>
          )}
          <table>
            <thead>
              <tr>
                {targetColumns.map((column) => (
                  <SortableHeader
                    key={column.key}
                    label={column.label}
                    columnKey={column.key}
                    sortState={targetSortState}
                    sortableType={column.sortableType}
                    onToggle={applyTargetSort}
                    rows={targetPage.items}
                    column={column}
                    filterState={targetFilters[column.key]}
                    onFilterChange={(nextFilter) => updateTargetFilter(column.key, nextFilter)}
                    onFilterReset={() => resetTargetFilter(column.key)}
                  />
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedTargetItems.map((item) => (
                <tr key={item.id}>
                  {targetColumns.slice(0, -1).map((column) => (
                    <td key={`${item.id}-${column.key}`}>{column.render(item)}</td>
                  ))}
                  <td className="row-actions">
                    <button className="icon-button" type="button" onClick={() => editTarget(item)} disabled={!canEditListedTarget(item)}>
                      Modifier
                    </button>
                    <button className="danger-button" type="button" onClick={() => removeTarget(item.id)} disabled={!canEditListedTarget(item)}>
                      Supprimer
                    </button>
                  </td>
                </tr>
              ))}
              {targetPage.items.length === 0 && (
                <tr>
                  <td colSpan={targetColumns.length} className="muted">Aucun objectif trouve pour les filtres actuels.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <Pager
          total={targetPage.total}
          limit={targetPage.limit}
          offset={targetPage.offset}
          onPage={(nextOffset) => setFilters({ ...filters, offset: nextOffset })}
        />
      </div>
    </section>
  );
}

function ParReductionTargetsScreen({ agencies, setNotice }) {
  const now = new Date();
  const [filters, setFilters] = useState({ year: now.getFullYear(), month: now.getMonth() + 1, agency_id: "", agent_id: "" });
  const [formAgents, setFormAgents] = useState([]);
  const [filterAgents, setFilterAgents] = useState([]);
  const [rows, setRows] = useState([]);
  const [agencySummary, setAgencySummary] = useState([]);
  const [expandedAgencies, setExpandedAgencies] = useState(new Set());
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState({
    year: now.getFullYear(),
    month: now.getMonth() + 1,
    agency_id: "",
    agent_id: "",
    target_par30: 0,
    target_cohort_1_15: 0,
    target_cohort_16_30: 0,
  });

  useEffect(() => {
    if (!form.agency_id) {
      setFormAgents([]);
      return;
    }
    api.agents(form.agency_id).then((page) => setFormAgents(page.items || [])).catch(() => setFormAgents([]));
  }, [form.agency_id]);

  useEffect(() => {
    if (!filters.agency_id) {
      api.agents().then((page) => setFilterAgents(page.items || [])).catch(() => setFilterAgents([]));
      return;
    }
    api.agents(filters.agency_id).then((page) => setFilterAgents(page.items || [])).catch(() => setFilterAgents([]));
  }, [filters.agency_id]);

  async function loadTargets() {
    try {
      const page = await api.parReductionTargets(clean({ ...filters, limit: 500, offset: 0 }));
      setRows(page.items || []);
      const summary = await api.parReductionAgencySummary(clean({
        year: filters.year,
        month: filters.month,
        agency_id: filters.agency_id || undefined,
        agent_id: filters.agent_id || undefined,
      }));
      setAgencySummary(summary || []);
    } catch (error) {
      setNotice(error.message);
    }
  }

  useEffect(() => { loadTargets(); }, [filters.year, filters.month, filters.agency_id, filters.agent_id]);

  function resetForm() {
    setEditingId(null);
    setForm({
      year: filters.year,
      month: filters.month,
      agency_id: filters.agency_id,
      agent_id: filters.agent_id,
      target_par30: 0,
      target_cohort_1_15: 0,
      target_cohort_16_30: 0,
    });
  }

  function editTarget(row) {
    setEditingId(row.id);
    setForm({
      year: row.year,
      month: row.month,
      agency_id: String(row.agency_id),
      agent_id: String(row.agent_id),
      target_par30: Number(row.target_par30 || 0),
      target_cohort_1_15: Number(row.target_cohort_1_15 || 0),
      target_cohort_16_30: Number(row.target_cohort_16_30 || 0),
    });
  }

  async function saveTarget() {
    if (!form.agency_id || !form.agent_id) {
      setNotice("L'agence et le Portfolio Manager sont obligatoires.");
      return;
    }
    const payload = {
      ...form,
      agency_id: Number(form.agency_id),
      agent_id: Number(form.agent_id),
      month: Number(form.month),
      year: Number(form.year),
      target_par30: Number(form.target_par30 || 0),
      target_cohort_1_15: Number(form.target_cohort_1_15 || 0),
      target_cohort_16_30: Number(form.target_cohort_16_30 || 0),
    };
    try {
      if (editingId) {
        await api.updateParReductionTarget(editingId, payload);
        setNotice("Objectif a atteindre modifie.");
      } else {
        await api.createParReductionTarget(payload);
        setNotice("Objectif a atteindre enregistre.");
      }
      resetForm();
      await loadTargets();
    } catch (error) {
      setNotice(error.message);
    }
  }

  async function removeTarget(id) {
    try {
      await api.deleteParReductionTarget(id);
      setNotice("Objectif a atteindre supprime.");
      await loadTargets();
    } catch (error) {
      setNotice(error.message);
    }
  }

  const months = ["Janvier", "Fevrier", "Mars", "Avril", "Mai", "Juin", "Juillet", "Aout", "Septembre", "Octobre", "Novembre", "Decembre"];
  return (
    <div className="module-stack par-reduction-module">
      <section className="panel">
        <div className="section-heading"><div><p className="eyebrow">Gestion dediee</p><h2>Objectifs de baisse PAR</h2></div><span className="status-badge">Admin / Super Admin</span></div>
        <div className="filters-row">
          <label>Annee<select value={filters.year} onChange={(event) => setFilters((current) => ({ ...current, year: Number(event.target.value) }))}>{[now.getFullYear() - 1, now.getFullYear(), now.getFullYear() + 1].map((year) => <option key={year} value={year}>{year}</option>)}</select></label>
          <label>Mois<select value={filters.month} onChange={(event) => setFilters((current) => ({ ...current, month: Number(event.target.value) }))}>{months.map((month, index) => <option key={month} value={index + 1}>{month}</option>)}</select></label>
          <label>Agence<select value={filters.agency_id} onChange={(event) => setFilters((current) => ({ ...current, agency_id: event.target.value, agent_id: "" }))}><option value="">Toutes les agences</option>{agencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}</select></label>
          <label>Portfolio Manager<select value={filters.agent_id} onChange={(event) => setFilters((current) => ({ ...current, agent_id: event.target.value }))}><option value="">Tous les portefeuilles</option>{filterAgents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label>
        </div>
      </section>
      <section className="panel">
        <div className="section-heading"><h3>Suivi des objectifs par agence</h3><span className="muted">Les objectifs agence sont la somme des niveaux agents</span></div>
        <div className="table-wrap"><table><thead><tr><th>Agence</th><th>Nb agents</th><th>PAR30 a atteindre</th><th>C1-15 a atteindre</th><th>C16-30 a atteindre</th><th>Detail</th></tr></thead><tbody>{agencySummary.map((agency) => { const expanded = expandedAgencies.has(agency.agency_id); return (<React.Fragment key={agency.agency_id}><tr><td>{agency.agency_name}</td><td>{agency.agent_count}</td><td>{formatMoney(agency.target_par30)} TND</td><td>{formatMoney(agency.target_cohort_1_15)} TND</td><td>{formatMoney(agency.target_cohort_16_30)} TND</td><td><button className="icon-button" type="button" title={expanded ? "Masquer les agents" : "Afficher les agents"} onClick={() => setExpandedAgencies((current) => { const next = new Set(current); if (next.has(agency.agency_id)) next.delete(agency.agency_id); else next.add(agency.agency_id); return next; })}>{expanded ? "-" : "+"}</button></td></tr>{expanded && agency.agents.map((agentTarget) => <tr className="nested-row" key={agentTarget.id}><td>↳ {agentTarget.agent?.name || "-"}</td><td>-</td><td>{formatMoney(agentTarget.target_par30)} TND</td><td>{formatMoney(agentTarget.target_cohort_1_15)} TND</td><td>{formatMoney(agentTarget.target_cohort_16_30)} TND</td><td><button className="icon-button" type="button" onClick={() => editTarget(agentTarget)} title="Modifier"><Save size={15} /></button></td></tr>)}</React.Fragment>); })}</tbody></table></div>
      </section>
      <section className="panel">
        <div className="section-heading"><h3>{editingId ? "Modifier l'objectif PAR a atteindre" : "Nouvel objectif PAR a atteindre"}</h3><span className="muted">Niveaux de PAR en TND</span></div>
        <div className="form-grid">
          <label>Annee<input type="number" value={form.year} onChange={(event) => setForm((current) => ({ ...current, year: Number(event.target.value) }))} /></label>
          <label>Mois<select value={form.month} onChange={(event) => setForm((current) => ({ ...current, month: Number(event.target.value) }))}>{months.map((month, index) => <option key={month} value={index + 1}>{month}</option>)}</select></label>
          <label>Agence<select value={form.agency_id} onChange={(event) => setForm((current) => ({ ...current, agency_id: event.target.value, agent_id: "" }))}><option value="">Choisir</option>{agencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}</select></label>
          <label>Portfolio Manager<select value={form.agent_id} disabled={!form.agency_id} onChange={(event) => setForm((current) => ({ ...current, agent_id: event.target.value }))}><option value="">Choisir</option>{formAgents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label>
          <NumberField label="PAR30 a atteindre" field="target_par30" state={form} setState={setForm} />
          <NumberField label="Cohorte 1-15 a atteindre" field="target_cohort_1_15" state={form} setState={setForm} />
          <NumberField label="Cohorte 16-30 a atteindre" field="target_cohort_16_30" state={form} setState={setForm} />
        </div>
        <div className="button-row"><button className="primary fit" type="button" onClick={saveTarget}><Save size={16} />{editingId ? "Enregistrer modifications" : "Enregistrer"}</button>{editingId && <button className="ghost" type="button" onClick={resetForm}>Annuler</button>}</div>
      </section>
      <section className="panel">
        <div className="section-heading"><h3>Objectifs a atteindre enregistres</h3><span className="muted">{rows.length} resultat(s)</span></div>
        <div className="table-wrap"><table><thead><tr><th>Annee</th><th>Mois</th><th>Agence</th><th>Portfolio Manager</th><th>PAR30 a atteindre</th><th>C1-15 a atteindre</th><th>C16-30 a atteindre</th><th>Creation</th><th>Modification</th><th>Actions</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id}><td>{row.year}</td><td>{months[row.month - 1]}</td><td>{row.agency?.name || "-"}</td><td>{row.agent?.name || "-"}</td><td>{formatMoney(row.target_par30)} TND</td><td>{formatMoney(row.target_cohort_1_15)} TND</td><td>{formatMoney(row.target_cohort_16_30)} TND</td><td>{shortDate(row.created_at)}</td><td>{shortDate(row.updated_at)}</td><td><div className="button-row"><button className="icon-button" type="button" onClick={() => editTarget(row)} title="Modifier"><Save size={15} /></button><button className="icon-button" type="button" onClick={() => removeTarget(row.id)} title="Supprimer"><Trash2 size={15} /></button></div></td></tr>)}</tbody></table></div>
      </section>
    </div>
  );
}

function ParReductionScreen({ user, agencies, setNotice }) {
  const today = new Date();
  const scopedAgent = user?.role === "portfolio_manager" ? String(user.agent_id || "") : "";
  const scopedAgency = user?.role === "agency_manager" || user?.role === "portfolio_manager"
    ? String(user.agency_id || "")
    : "";
  const canFilter = user?.role === "admin" || user?.role === "super_admin" || user?.role === "agency_manager";
  const isAgencyManager = user?.role === "agency_manager";
  const [filters, setFilters] = useState({ month: today.getMonth() + 1, year: today.getFullYear(), agency_id: scopedAgency, agent_id: scopedAgent });
  const [agents, setAgents] = useState([]);
  const [data, setData] = useState(null);
  const [evolution, setEvolution] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!filters.agency_id) {
      if (canFilter) {
        api.agents().then((page) => setAgents(page.items || [])).catch(() => setAgents([]));
      } else {
        setAgents([]);
      }
      return;
    }
    api.agents(filters.agency_id).then((page) => setAgents(page.items || [])).catch(() => setAgents([]));
  }, [filters.agency_id]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const params = clean(filters);
    Promise.all([api.parReduction(params), api.parReductionEvolution(params)])
      .then(([summary, points]) => {
        if (cancelled) return;
        setData(summary);
        setEvolution(Array.isArray(points) ? points : []);
      })
      .catch((error) => {
        if (!cancelled) {
          setData(null);
          setEvolution([]);
          setNotice(error.message);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [filters, setNotice]);

  const metricDefinitions = [
    ["cohort_1_15", "Cohorte 1-15"],
    ["cohort_16_30", "Cohorte 16-30"],
    ["par30", "PAR30"],
  ];
  const chartData = evolution.map((point) => ({
    name: shortDate(point.snapshot_date),
    par30: Number(point.par30 || 0),
    cohort_1_15: Number(point.cohort_1_15 || 0),
    cohort_16_30: Number(point.cohort_16_30 || 0),
    required_par30: point.reduction_required_par30 == null ? null : Number(point.reduction_required_par30),
    required_cohort_1_15: point.reduction_required_cohort_1_15 == null ? null : Number(point.reduction_required_cohort_1_15),
    required_cohort_16_30: point.reduction_required_cohort_16_30 == null ? null : Number(point.reduction_required_cohort_16_30),
  }));
  const achievementClass = (value) => {
    if (value < 0) return "danger";
    if (value >= 100) return "success";
    if (value >= 80) return "warning";
    return "muted";
  };

  const comparisonRows = data?.portfolio_comparison || [];

  function comparisonMetric(row, key) {
    return row.metrics?.[key] || {};
  }

  const comparisonDisplayRows = !data
    ? []
    : comparisonRows.length > 0
      ? comparisonRows
      : [{ row_type: "global", agent_name: filters.agent_id ? (agents.find((agent) => String(agent.id) === String(filters.agent_id))?.name || "Portefeuille") : (data.scope?.type || "Global"), metrics: data.metrics }];

  const [comparisonSort, setComparisonSort] = useState({ key: null, dir: null });

  function toggleComparisonSort(key) {
    setComparisonSort((prev) => {
      if (prev.key !== key) return { key, dir: "asc" };
      if (prev.dir === "asc") return { key, dir: "desc" };
      return { key: null, dir: null };
    });
  }

  const sortedComparisonRows = useMemo(() => {
    if (!comparisonSort.key) return comparisonDisplayRows;
    const factor = comparisonSort.dir === "asc" ? 1 : -1;
    return [...comparisonDisplayRows].sort((a, b) => {
      let aVal, bVal;
      if (comparisonSort.key === "global") {
        const aRates = metricDefinitions.map(([k]) => Number(comparisonMetric(a, k).achievement_rate ?? 0));
        const bRates = metricDefinitions.map(([k]) => Number(comparisonMetric(b, k).achievement_rate ?? 0));
        aVal = a.row_type === "global" ? Number(data.global_achievement_rate || 0) : aRates.reduce((s, v) => s + v, 0) / aRates.length;
        bVal = b.row_type === "global" ? Number(data.global_achievement_rate || 0) : bRates.reduce((s, v) => s + v, 0) / bRates.length;
      } else {
        aVal = Number(comparisonMetric(a, comparisonSort.key).achievement_rate ?? null);
        bVal = Number(comparisonMetric(b, comparisonSort.key).achievement_rate ?? null);
        if (!Number.isFinite(aVal) && !Number.isFinite(bVal)) return 0;
        if (!Number.isFinite(aVal)) return 1;
        if (!Number.isFinite(bVal)) return -1;
      }
      return (aVal - bVal) * factor;
    });
  }, [comparisonDisplayRows, comparisonSort, data]);

  return (
    <div className="module-stack par-reduction-module">
      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Suivi de baisse PAR</p>
            <h2>{String(filters.month).padStart(2, "0")}/{filters.year}</h2>
          </div>
          <div className="filters-row">
            <label>Mois<select value={filters.month} onChange={(event) => setFilters((current) => ({ ...current, month: Number(event.target.value) }))}>{Array.from({ length: 12 }, (_, index) => <option key={index + 1} value={index + 1}>{String(index + 1).padStart(2, "0")}</option>)}</select></label>
            <label>Annee<input type="number" value={filters.year} onChange={(event) => setFilters((current) => ({ ...current, year: Number(event.target.value) }))} /></label>
            {canFilter && (
              <label>Agence
                <AgencyMultiSelect
                  options={agencies}
                  selectedIds={selectedIds(filters.agency_id)}
                  disabled={isAgencyManager}
                  responsiveTags
                  overflowLabel="agences"
                  onChange={(nextAgencyIds) => setFilters((current) => ({ ...current, agency_id: nextAgencyIds, agent_id: "" }))}
                />
              </label>
            )}
            {canFilter && <label>Portfolio Manager<select value={filters.agent_id} onChange={(event) => setFilters((current) => ({ ...current, agent_id: event.target.value }))}><option value="">Tous les portefeuilles</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label>}
          </div>
        </div>
      </section>
      {loading && <section className="panel"><p className="muted">Chargement du suivi...</p></section>}
      {!loading && data && (
        <>
          <section className="metrics-grid par-reduction-grid">
            {metricDefinitions.map(([key, label]) => {
              const metric = data.metrics?.[key] || {};
              const achievement = Number(metric.achievement_rate || 0);
              const progress = clampProgress(achievement);
              const color = PAR_REDUCTION_COLORS[key];
              const progressLabel = metric.valid_target === false
                ? "Objectif invalide"
                : achievement < 0
                  ? `Degradation : ${achievement.toFixed(1)}%`
                  : `${achievement.toFixed(1)}% atteint`;
              return (
                <article className={`panel reduction-card ${achievementClass(achievement)}`} style={{ "--reduction-accent": color }} key={key}>
                  <div className="section-heading"><h3>{label}</h3><span className="status-badge">{metric.message ? "Donnees incompletes" : achievement >= 100 ? "Atteint" : achievement < 0 ? "Degradation" : achievement >= 80 ? "Proche" : "En progression"}</span></div>
                  <div className="reduction-values">
                    <div><span>PAR initial</span><strong>{formatMoney(metric.initial)} TND</strong></div>
                    <div><span>PAR actuel</span><strong>{formatMoney(metric.current)} TND</strong></div>
                    <div><span>Objectif a atteindre</span><strong>{formatMoney(metric.target_to_reach)} TND</strong></div>
                    <div><span>Baisse realisee</span><strong>{formatMoney(metric.reduction_realized)} TND</strong></div>
                    <div><span>Baisse necessaire</span><strong>{formatMoney(metric.reduction_required)} TND</strong></div>
                    <div><span>Atteinte</span><strong>{achievement.toFixed(1)}%</strong></div>
                  </div>
                  {metric.message && <p className="reduction-card-message">{metric.message}</p>}
                  <div className="progress-summary">
                    <span>{progressLabel}</span>
                    {achievement > 100 && <strong>Objectif depasse</strong>}
                  </div>
                  <div
                    className="progress-track"
                    role="progressbar"
                    aria-label={`${achievement.toFixed(1)} % de l'objectif de baisse atteint pour ${label}`}
                    aria-valuenow={Number.isFinite(achievement) ? achievement : 0}
                    aria-valuemin="0"
                    aria-valuemax="100"
                  >
                    <span style={{ "--progress-width": `${progress}%`, width: `${progress}%`, background: progressGradient(achievement) }} />
                  </div>
                </article>
              );
            })}
          </section>
          <section className="panel">
            <div className="section-heading"><div><h3>Evolution de la baisse</h3><p className="muted">Initial : {shortDate(data.initial_snapshot_date)} | Actuel : {shortDate(data.current_snapshot_date)}</p></div><strong>{Number(data.global_achievement_rate || 0).toFixed(1)}% global</strong></div>
            <div className="chart-wrap reduction-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={chartData}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="name" /><YAxis /><Tooltip formatter={(value, name) => [`${formatMoney(value)} TND`, name]} /><Legend /><Line type="monotone" dataKey="cohort_1_15" name="C1-15 - Baisse realisee" stroke={PAR_REDUCTION_COLORS.cohort_1_15} strokeWidth={2} dot={false} /><Line type="monotone" dataKey="required_cohort_1_15" name="C1-15 - Baisse necessaire" stroke={PAR_REDUCTION_COLORS.cohort_1_15} strokeWidth={2} strokeDasharray="6 5" dot={false} connectNulls={false} /><Line type="monotone" dataKey="cohort_16_30" name="C16-30 - Baisse realisee" stroke={PAR_REDUCTION_COLORS.cohort_16_30} strokeWidth={2} dot={false} /><Line type="monotone" dataKey="required_cohort_16_30" name="C16-30 - Baisse necessaire" stroke={PAR_REDUCTION_COLORS.cohort_16_30} strokeWidth={2} strokeDasharray="6 5" dot={false} connectNulls={false} /><Line type="monotone" dataKey="par30" name="PAR30 - Baisse realisee" stroke={PAR_REDUCTION_COLORS.par30} strokeWidth={2} dot={false} /><Line type="monotone" dataKey="required_par30" name="PAR30 - Baisse necessaire" stroke={PAR_REDUCTION_COLORS.par30} strokeWidth={2} strokeDasharray="6 5" dot={false} connectNulls={false} /></LineChart></ResponsiveContainer></div>
          </section>
          <section className="panel">
            <h3>Comparaison des portefeuilles</h3>
            <div className="table-wrap portfolio-comparison-table">
              <table>
                <thead>
                  <tr>
                    <th>Portfolio Manager</th>
                    {[
                      { key: "cohort_1_15", label: "C1-15" },
                      { key: "cohort_16_30", label: "C16-30" },
                      { key: "par30", label: "PAR30" },
                      { key: "global", label: "Global" },
                    ].map(({ key, label }) => {
                      const active = comparisonSort.key === key;
                      const icon = active ? (comparisonSort.dir === "asc" ? " ▲" : " ▼") : " ⇅";
                      return (
                        <th
                          key={key}
                          onClick={() => toggleComparisonSort(key)}
                          style={{ cursor: "pointer", userSelect: "none", whiteSpace: "nowrap" }}
                          title={`Trier par ${label}`}
                        >
                          {label}
                          <span style={{ opacity: active ? 1 : 0.35, fontSize: "0.75em", marginLeft: 2 }}>{icon}</span>
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {sortedComparisonRows.map((row) => {
                    const isAgency = row.row_type === "agency";
                    const rates = metricDefinitions.map(([key]) => Number(comparisonMetric(row, key).achievement_rate ?? 0));
                    const globalRate = row.row_type === "global" ? Number(data.global_achievement_rate || 0) : rates.reduce((sum, value) => sum + value, 0) / rates.length;
                    return (
                      <tr className={isAgency ? "portfolio-comparison-agency" : ""} key={`${row.row_type}-${row.agent_id || row.agency_id || "global"}`}>
                        <td><strong>{isAgency ? row.agency_name : row.agent_name}</strong>{isAgency && <small>Agence - {row.agent_count} PM</small>}</td>
                        {metricDefinitions.map(([key]) => {
                          const metric = comparisonMetric(row, key);
                          return <td key={key}>{metric.achievement_rate == null ? "N/A" : `${Number(metric.achievement_rate).toFixed(1)}%`}</td>;
                        })}
                        <td>{globalRate.toFixed(1)}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
      {!loading && !data && <section className="panel"><p className="muted">Aucune donnee de suivi disponible pour cette periode.</p></section>}
    </div>
  );
}

function NumberField({ label, field, state, setState, step = "1", disabled = false }) {
  return (
    <label>{label}
      <input disabled={disabled} type="number" min="0" step={step} value={state[field]} onChange={(e) => setState({ ...state, [field]: Number(e.target.value) })} />
    </label>
  );
}

function BonusDisabledScreen() {
  return (
    <section className="bonus-disabled panel">
      <h3>Module Bonus</h3>
      <p className="muted">
        Module en developpement. Les calculs et actions Bonus sont desactives dans cet environnement de test.
      </p>
      <span className="nav-badge">En dev</span>
    </section>
  );
}

function BonusScreen({ formulaHelp, setNotice }) {
  const [rule, setRule] = useState({ name: "Regle bonus", expression: DEFAULT_EXPRESSION });
  const [period, setPeriod] = useState({ month: 5, year: 2026 });
  const [rules, setRules] = useState([]);

  useEffect(() => {
    api.bonusRules().then((page) => setRules(page.items)).catch(() => {});
  }, []);
  const rulePage = useClientPagination(rules, 8);

  async function saveRule() {
    try {
      const saved = await api.createBonusRule({ name: rule.name, formula: { expression: rule.expression }, is_active: true });
      setRules([saved, ...rules]);
      setNotice("Formule bonus enregistree.");
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function calculate(ruleId) {
    try {
      const result = await api.calculateBonus({ ...period, bonus_rule_id: Number(ruleId) });
      setNotice(`${result.length} bonus calcules.`);
    } catch (err) {
      setNotice(err.message);
    }
  }

  function insertToken(token) {
    setRule({ ...rule, expression: `${rule.expression} ${token}`.trim() });
  }

  return (
    <section className="bonus-grid">
      <div className="panel bonus-formula-panel">
        <h3>Constructeur de formule</h3>
        <label>Nom de la regle<input value={rule.name} onChange={(e) => setRule({ ...rule, name: e.target.value })} /></label>
        <label>Expression mathematique
          <textarea className="formula-box" value={rule.expression} onChange={(e) => setRule({ ...rule, expression: e.target.value })} />
        </label>
        <div className="token-zone">
          <strong>Metrics</strong>
          <div className="token-grid">
            {formulaHelp.metrics.map((item) => <button key={item} className="token" onClick={() => insertToken(item)}>{item}</button>)}
          </div>
          <strong>Operations</strong>
          <div className="token-grid">
            {[...formulaHelp.operators, ...formulaHelp.functions].map((item) => <button key={item} className="token" onClick={() => insertToken(item)}>{item}</button>)}
          </div>
        </div>
        <button className="primary fit" onClick={saveRule}><Save size={16} />Enregistrer formule</button>
      </div>

      <div className="panel table-panel bonus-calc-panel">
        <h3>Calcul bonus</h3>
        <div className="form-grid two">
          <label>Mois<input type="number" min="1" max="12" value={period.month} onChange={(e) => setPeriod({ ...period, month: Number(e.target.value) })} /></label>
          <label>Annee<input type="number" value={period.year} onChange={(e) => setPeriod({ ...period, year: Number(e.target.value) })} /></label>
        </div>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Regle</th><th>Action</th></tr></thead>
            <tbody>
              {rulePage.visible.map((item) => (
                <tr key={item.id}>
                  <td>{item.name}</td>
                  <td><button className="icon-button" onClick={() => calculate(item.id)}><Calculator size={16} />Calculer</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {rulePage.pager}
      </div>
    </section>
  );
}

function UsersScreen({ currentUser, agencies, users, reload, setNotice }) {
  const isSuperAdmin = currentUser?.role === "super_admin";
  const isSupport = currentUser?.role === "support";
  const isProtectedRoleForSupport = (role) => role === "super_admin" || role === "committee_member";
  const canManageUsers = isSuperAdmin || isSupport;
  const canOperateUsers = canManageUsers;
  const canSeeAdvancedAudits = isSuperAdmin || isSupport;
  const emptyForm = useMemo(
    () => ({
      email: "",
      full_name: "",
      role: "portfolio_manager",
      agency_id: "",
      agent_id: "",
      initial_password: "",
    }),
    [],
  );
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState(null);
  const [formAgents, setFormAgents] = useState([]);
  const [userQuery, setUserQuery] = useState("");
  const [temporaryCredentialInfo, setTemporaryCredentialInfo] = useState(null);
  const [gpAudit, setGpAudit] = useState(null);
  const [gpAuditLoading, setGpAuditLoading] = useState(false);
  const [gpMissingSelectedIds, setGpMissingSelectedIds] = useState([]);
  const [gpMissingConfirmOpen, setGpMissingConfirmOpen] = useState(false);
  const [gpMissingDeleting, setGpMissingDeleting] = useState(false);
  const [gpActionSelectedKeys, setGpActionSelectedKeys] = useState([]);
  const [gpActionProvisioning, setGpActionProvisioning] = useState(false);
  const [gpActionConfirmOpen, setGpActionConfirmOpen] = useState(false);
  const [usersTab, setUsersTab] = useState("gp-audit");
  const [loginAudit, setLoginAudit] = useState(null);
  const [loginAuditLoading, setLoginAuditLoading] = useState(false);
  const [loginAuditFilters, setLoginAuditFilters] = useState({ user_id: "", role: "", date_from: "", date_to: "" });


  async function loadLoginAudit() {
    if (!canSeeAdvancedAudits) return;
    setLoginAuditLoading(true);
    try {
      const params = clean(loginAuditFilters);
      const result = await api.loginAudit(params);
      setLoginAudit(result);
    } catch (err) {
      setLoginAudit(null);
      setNotice(err.message);
    } finally {
      setLoginAuditLoading(false);
    }
  }

  async function exportLoginAudit(format) {
    if (!canSeeAdvancedAudits) return;
    try {
      const blob = await api.downloadLoginAudit(format, clean(loginAuditFilters));
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = `login_audit.${format}`;
      anchor.click();
      URL.revokeObjectURL(href);
    } catch (err) {
      setNotice(err.message);
    }
  }


  async function loadGpAudit() {
    if (!canSeeAdvancedAudits) return;
    setGpAuditLoading(true);
    try {
      const result = await api.gpMcrAudit();
      setGpAudit(result);
      setGpMissingSelectedIds((current) => {
        const allowed = new Set((result?.existing_accounts_not_in_mcr || []).map((item) => item.user_id));
        return current.filter((id) => allowed.has(id));
      });
    } catch (err) {
      setGpAudit(null);
      setNotice(err.message);
    } finally {
      setGpAuditLoading(false);
    }
  }

  async function deleteMissingGpMcrAccounts(accountIds) {
    if (!Array.isArray(accountIds) || accountIds.length === 0) return;
    setGpMissingDeleting(true);
    try {
      const result = await api.deleteMissingGpMcrAccounts(accountIds);
      const deleted = result?.deleted_count ?? accountIds.length;
      const skipped = result?.skipped_count ?? 0;
      let msg = `${deleted} compte(s) GP supprime(s) de la base.`;
      if (skipped > 0) {
        msg += ` ${skipped} ignore(s).`;
      }
      setNotice(msg);
      await reload();
      await loadGpAudit();
    } catch (err) {
      setNotice(err?.message || "Echec de la suppression des comptes GP.");
      throw err;
    } finally {
      setGpMissingDeleting(false);
    }
  }

  useEffect(() => {
    if (canSeeAdvancedAudits) {
      loadGpAudit();
      loadLoginAudit();
    }
  }, [canSeeAdvancedAudits]);

  useEffect(() => {
    if (!canSeeAdvancedAudits) return;
    loadLoginAudit();
  }, [canSeeAdvancedAudits, loginAuditFilters.user_id, loginAuditFilters.role, loginAuditFilters.date_from, loginAuditFilters.date_to]);

  useEffect(() => {
    if (!form.agency_id || (form.role !== "portfolio_manager" && form.role !== "agency_manager")) {
      setFormAgents([]);
      return;
    }
    api.agents(form.agency_id)
      .then((page) => setFormAgents(page.items || []))
      .catch(() => setFormAgents([]));
  }, [form.agency_id, form.role]);

  const filteredUsers = useMemo(() => {
    const q = userQuery.trim().toLowerCase();
    if (!q) return users;
    return users.filter((item) =>
      `${item.full_name} ${item.email} ${item.role} ${item.agency_id || ""} ${item.agent_id || ""} ${item.is_active ? "actif" : "inactif"}`.toLowerCase().includes(q)
    );
  }, [users, userQuery]);

  const userColumns = useMemo(
    () => [
      { key: "full_name", label: "Nom", sortableType: "text" },
      { key: "email", label: "Email", sortableType: "text" },
      { key: "role", label: "Role", sortableType: "text" },
      {
        key: "agency_id",
        label: "Agence",
        sortableType: "number",
        sortAccessor: (item) => item.agency_id,
      },
      {
        key: "agent_id",
        label: "Agent",
        sortableType: "number",
        sortAccessor: (item) => item.agent_id,
      },
      {
        key: "is_active",
        label: "Statut",
        sortableType: "number",
        sortAccessor: (item) => (item.is_active ? 1 : 0),
        filterType: "boolean",
        filterAccessor: (item) => String(Boolean(item.is_active)),
        filterOptions: [{ value: "true", label: "Oui" }, { value: "false", label: "Non" }],
      },
      ...(isSuperAdmin ? [{ key: "temporary_password", label: "Mot de passe provisoire", sortableType: "text" }] : []),
      { key: "actions", label: "Actions" },
    ],
    [isSuperAdmin],
  );
  const {
    sortState: userSortState,
    sortedRows: sortedUsers,
    columnFilters: userColumnFilters,
    activeFilterCount: userFilterCount,
    applySort: applyUserSort,
    updateFilter: updateUserFilter,
    resetFilter: resetUserFilter,
    resetAllFilters: resetAllUserFilters,
  } = useAdvancedTableState(filteredUsers, userColumns);
  const userPage = useClientPagination(sortedUsers, 10);

  function roleLabel(role) {
    if (role === "super_admin") return "Super Admin";
    if (role === "admin") return "Admin";
    if (role === "support") return "Support";
    if (role === "committee_member") return "Membre comité";
    if (role === "agency_manager") return "Chef d'agence";
    if (role === "portfolio_manager") return "Portfolio Manager";
    return role;
  }

  function validateForm() {
    if (!form.full_name.trim()) return "Le nom complet est obligatoire.";
    if (!form.email.trim()) return "L'email est obligatoire.";
    if (!editingId && form.role !== "portfolio_manager" && !form.initial_password.trim()) {
      return "Le mot de passe initial est obligatoire pour ce profil.";
    }
    if (form.role === "agency_manager" && !form.agency_id) {
      return "L'agence est obligatoire pour un chef d'agence.";
    }
    if (form.role === "portfolio_manager") {
      if (!form.agency_id) return "L'agence est obligatoire pour un portfolio manager.";
      if (!form.agent_id) return "L'agent est obligatoire pour un portfolio manager.";
    }
    return "";
  }

  function buildPayload(includePassword) {
    const payload = {
      email: form.email.trim(),
      full_name: form.full_name.trim(),
      role: form.role,
      agency_id: null,
      agent_id: null,
    };
    if (includePassword && form.role !== "portfolio_manager") {
      payload.initial_password = form.initial_password;
    }

    if (form.role === "agency_manager") {
      payload.agency_id = Number(form.agency_id);
    }
    if (form.role === "portfolio_manager") {
      payload.agency_id = Number(form.agency_id);
      payload.agent_id = Number(form.agent_id);
    }
    return payload;
  }

  function resetForm() {
    setEditingId(null);
    setForm(emptyForm);
  }

  async function createUser() {
    if (!canManageUsers) return;
    const validationMessage = validateForm();
    if (validationMessage) {
      setNotice(validationMessage);
      return;
    }
    try {
      const result = await api.createUser(buildPayload(true));
      setTemporaryCredentialInfo(result?.temporary_password ? { type: "single", account: result } : null);
      setNotice(
        result?.temporary_password
          ? "Compte utilisateur cree. Communiquez le mot de passe temporaire a l'utilisateur."
          : "Compte utilisateur cree. Le mot de passe provisoire n'est pas affiche pour le profil Support."
      );
      resetForm();
      await reload();
      await loadGpAudit();
    } catch (err) {
      setNotice(err.message);
    }
  }

  function editUser(item) {
    if (!canManageUsers) return;
    setEditingId(item.id);
    setForm({
      email: item.email,
      full_name: item.full_name,
      role: item.role,
      agency_id: item.agency_id ? String(item.agency_id) : "",
      agent_id: item.agent_id ? String(item.agent_id) : "",
      initial_password: "",
    });
  }

  async function saveUser() {
    if (!canManageUsers) return;
    const validationMessage = validateForm();
    if (validationMessage) {
      setNotice(validationMessage);
      return;
    }
    try {
      await api.updateUser(editingId, buildPayload(false));
      setNotice("Utilisateur modifie.");
      resetForm();
      await reload();
      await loadGpAudit();
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function toggleUserStatus(item) {
    if (!canOperateUsers) return;
    try {
      await api.setUserStatus(item.id, !item.is_active);
      setNotice(item.is_active ? "Compte desactive." : "Compte reactive.");
      await reload();
      await loadGpAudit();
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function removeUser(item) {
    if (!canManageUsers) return;
    const confirmed = window.confirm(
      `Supprimer definitivement le compte ${item.email} ? Cette action supprimera aussi ses sessions et references liees.`,
    );
    if (!confirmed) return;
    try {
      await api.deleteUser(item.id);
      setNotice("Compte supprime definitivement.");
      await reload();
      await loadGpAudit();
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function resetPassword(item) {
    if (!canOperateUsers) return;
    try {
      const result = await api.resetUserPassword(item.id);
      if (result?.temporary_password) {
        setTemporaryCredentialInfo({ type: "single", account: result });
        setNotice("Mot de passe temporaire genere. L'utilisateur devra le modifier a la prochaine connexion.");
      } else {
        setTemporaryCredentialInfo(null);
        setNotice("Mot de passe reinitialise. L'utilisateur devra le modifier a la prochaine connexion.");
      }
      await reload();
      await loadGpAudit();
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function autoCreateAgents() {
    if (!canManageUsers) return;
    try {
      const result = await api.autoCreateAgentUsers();
      const visibleAccounts = (result.accounts || []).filter((account) => account.temporary_password);
      setTemporaryCredentialInfo(visibleAccounts.length > 0 ? { type: "bulk", accounts: visibleAccounts } : null);
      setNotice(`${result.provisioned_count || 0} compte(s) GP provisionne(s).`);
      await reload();
      await loadGpAudit();
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function provisionSingleGpAccount(row) {
    if (!canManageUsers) return;
    try {
      const agentName = row.agent_name;
      const result = await api.provisionGpAccount(agentName);
      if (result.account?.temporary_password) {
        setTemporaryCredentialInfo({ type: "single", account: result.account });
      }
      setNotice(`Compte GP provisionne pour ${agentName}.`);
      await reload();
      await loadGpAudit();
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function batchProvisionGpAccounts() {
    if (!canManageUsers || gpActionSelectedKeys.length === 0) return;
    setGpActionProvisioning(true);
    try {
      const selectedRows = gpActionRows.filter((row) =>
        gpActionSelectedKeys.includes(row.normalized_key)
      );
      const agentNames = selectedRows.map((row) => row.agent_name);
      const result = await api.batchProvisionGpAccounts(agentNames);
      const visibleAccounts = (result.accounts || []).filter((account) => account.temporary_password);
      if (visibleAccounts.length > 0) {
        setTemporaryCredentialInfo({ type: "bulk", accounts: visibleAccounts });
      }
      const msg = `${result.provisioned_count || 0} compte(s) provisionne(s).`;
      setNotice(result.skipped_count > 0 ? `${msg} ${result.skipped_count} ignore(s).` : msg);
      setGpActionSelectedKeys([]);
      await reload();
      await loadGpAudit();
    } catch (err) {
      setNotice(err.message);
    } finally {
      setGpActionProvisioning(false);
    }
  }

  const auditBatch = gpAudit?.import_batch || null;
  const gpActionRows = gpAudit?.new_gp_without_accounts || [];
  const gpMissingRows = gpAudit?.existing_accounts_not_in_mcr || [];

  return (
    <section className="users-stack">
      {canManageUsers && (
      <div className="panel">
        <div className="panel-header">
          <h3>{editingId ? "Modifier un compte" : "Creer un compte"}</h3>
        </div>
        <p className="muted">
          {isSuperAdmin
            ? "Le Super Admin peut creer et gerer les profils Super Admin, Admin, Support, Chef d'agence et Portfolio Manager."
            : "Le profil Support peut gerer les comptes Admin, Support, Chef d'agence et Portfolio Manager."}
        </p>
        {temporaryCredentialInfo && (
          <div className="notice-panel">
            <strong>Mot de passe temporaire a communiquer</strong>
            <p className="muted">
              Visible dans le tableau tant que l'utilisateur ne l'a pas remplace. Il devra le modifier a sa premiere connexion.
            </p>
            {temporaryCredentialInfo.type === "single" ? (
              <div className="temporary-password-grid">
                <span>Email</span>
                <code>{temporaryCredentialInfo.account.email}</code>
                <span>Mot de passe</span>
                <code>{temporaryCredentialInfo.account.temporary_password}</code>
              </div>
            ) : (
              <div className="table-scroll compact-scroll">
                <table>
                  <thead><tr><th>Email</th><th>Nom</th><th>Mot de passe temporaire</th></tr></thead>
                  <tbody>
                    {temporaryCredentialInfo.accounts.map((account) => (
                      <tr key={account.user_id}>
                        <td>{account.email}</td>
                        <td>{account.full_name}</td>
                        <td><code>{account.temporary_password}</code></td>
                      </tr>
                    ))}
                    {temporaryCredentialInfo.accounts.length === 0 && (
                      <tr><td colSpan="3" className="muted">Aucun nouveau mot de passe a afficher.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
        <div className="form-grid two">
          <label>Nom complet<input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></label>
          <label>Email<input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
          <label>Role
            <select
              value={form.role}
              disabled={isSupport && editingId === currentUser?.id}
              onChange={(e) => {
                const nextRole = e.target.value;
                setForm((prev) => ({
                  ...prev,
                  role: nextRole,
                  agency_id: (nextRole === "super_admin" || nextRole === "admin" || nextRole === "support" || nextRole === "committee_member") ? "" : prev.agency_id,
                  agent_id: nextRole === "portfolio_manager" ? prev.agent_id : "",
                }));
              }}
            >
              {isSuperAdmin && <option value="super_admin">Super Admin</option>}
              <option value="admin">Admin</option>
              <option value="support">Support</option>
              {isSuperAdmin && <option value="committee_member">Membre comité</option>}
              <option value="agency_manager">Chef d'agence</option>
              <option value="portfolio_manager">Portfolio manager</option>
            </select>
          </label>
          <label>Agence
            <select
              value={form.agency_id}
              disabled={form.role === "super_admin" || form.role === "admin" || form.role === "support" || form.role === "committee_member"}
              onChange={(e) => setForm({ ...form, agency_id: e.target.value, agent_id: "" })}
            >
              <option value="">Aucune</option>
              {agencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}
            </select>
          </label>
          <label>Agent
            <select
              value={form.agent_id}
              disabled={form.role !== "portfolio_manager" || !form.agency_id}
              onChange={(e) => setForm({ ...form, agent_id: e.target.value })}
            >
              <option value="">{form.role !== "portfolio_manager" ? "Non requis" : "Selectionner..."}</option>
              {formAgents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
            </select>
          </label>
          {!editingId && form.role !== "portfolio_manager" && (
            <label>Mot de passe initial
              <input
                type="password"
                value={form.initial_password}
                onChange={(e) => setForm({ ...form, initial_password: e.target.value })}
                placeholder="Minimum 12 caracteres"
              />
            </label>
          )}
        </div>
        <div className="button-row">
          <button className="primary fit" onClick={editingId ? saveUser : createUser}>
            <Plus size={16} />
            {editingId ? "Enregistrer" : "Creer compte"}
          </button>
          {editingId && <button className="icon-button" onClick={resetForm}>Annuler</button>}
          {!editingId && (
            <button className="icon-button" type="button" onClick={autoCreateAgents}>
              <Users size={16} />
              Generer comptes GP
            </button>
          )}
        </div>
      </div>
      )}

      {canSeeAdvancedAudits && (
      <div className="panel table-panel">
        <div className="panel-header users-audit-header">
          <div>
            <h3>{usersTab === "gp-audit" ? "Verification comptes GP / dernier MCR" : "Audit des connexions"}</h3>
            <p className="muted">
              {usersTab === "gp-audit"
                ? (auditBatch
                  ? `Dernier MCR analyse : ${auditBatch.file_name} - ${formatDateLabel(auditBatch.snapshot_date)}`
                  : "Aucun MCR importe pour lancer la verification.")
                : "Historique des connexions reussies des utilisateurs."}
            </p>
          </div>
          <div className="segment-control users-tab-switcher" role="tablist" aria-label="Onglets utilisateurs">
            <button type="button" className={usersTab === "gp-audit" ? "segment-active" : ""} onClick={() => setUsersTab("gp-audit")}>Verification GP</button>
            <button type="button" className={usersTab === "login-audit" ? "segment-active" : ""} onClick={() => setUsersTab("login-audit")}>Audit des connexions</button>
          </div>
        </div>
        {usersTab === "gp-audit" ? (
          <div className="audit-grid">
            <div>
              <div className="subsection-title">
                <h4>Nouveaux GP detectes dans le MCR mais sans compte provisionne</h4>
                <span className="count-badge">{gpActionRows.length}</span>
              </div>
              <div className="button-row wrap">
                {canManageUsers && gpActionSelectedKeys.length > 0 && (
                  <span className="selection-info">
                    ☑ {gpActionSelectedKeys.length} utilisateur(s) selectionne(s)
                  </span>
                )}
                {canManageUsers && (
                  <button
                    type="button"
                    className="primary fit"
                    disabled={gpActionSelectedKeys.length === 0 || gpAuditLoading || gpActionProvisioning}
                    onClick={batchProvisionGpAccounts}
                  >
                    {gpActionProvisioning
                      ? "Provisionnement..."
                      : `Provisionner les utilisateurs selectionnes (${gpActionSelectedKeys.length})`}
                  </button>
                )}
              </div>
              <div className="table-scroll compact-scroll">
                <table className="audit-table">
                  <thead>
                    <tr>
                      <th>
                        {canManageUsers && gpActionRows.length > 0 && (
                          <input
                            type="checkbox"
                            checked={
                              gpActionSelectedKeys.length > 0 &&
                              gpActionRows.every((row) =>
                                gpActionSelectedKeys.includes(row.normalized_key)
                              )
                            }
                            indeterminate={
                              gpActionSelectedKeys.length > 0 &&
                              !gpActionRows.every((row) =>
                                gpActionSelectedKeys.includes(row.normalized_key)
                              )
                            }
                            onChange={(e) => {
                              if (e.target.checked) {
                                setGpActionSelectedKeys(
                                  gpActionRows.map((row) => row.normalized_key)
                                );
                              } else {
                                setGpActionSelectedKeys([]);
                              }
                            }}
                            onClick={(e) => e.stopPropagation()}
                          />
                        )}
                      </th>
                      <th>Nom GP</th>
                      <th>Agences MCR</th>
                      <th>Credits</th>
                      <th>Statut compte</th>
                      <th>Email</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gpActionRows.map((row) => {
                      const isSelected = gpActionSelectedKeys.includes(row.normalized_key);
                      return (
                        <tr key={`${row.normalized_key}-${row.user_id || "missing"}`}>
                          <td>
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  setGpActionSelectedKeys((prev) => [...prev, row.normalized_key]);
                                } else {
                                  setGpActionSelectedKeys((prev) => prev.filter((k) => k !== row.normalized_key));
                                }
                              }}
                              onClick={(e) => e.stopPropagation()}
                            />
                          </td>
                          <td>{row.agent_name}</td>
                          <td>{row.agency_names?.join(", ") || "-"}</td>
                          <td>{row.loan_count}</td>
                          <td>
                            <span className={row.has_account ? "status-pill warning" : "status-pill danger"}>
                              {row.account_status}
                            </span>
                          </td>
                          <td>{row.email || "-"}</td>
                          <td>
                            <button className="icon-button" type="button" onClick={() => provisionSingleGpAccount(row)}>
                              {row.has_account ? "Provisionner" : "Creer compte"}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                    {!gpAuditLoading && gpActionRows.length === 0 && (
                      <tr>
                        <td colSpan="7" className="muted">
                          Aucun GP a traiter pour le dernier MCR.
                        </td>
                      </tr>
                    )}
                    {gpAuditLoading && (
                      <tr>
                        <td colSpan="7" className="muted">Verification en cours...</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              {gpActionSelectedKeys.length > 0 && (
                <div className="action-bar">
                  <button
                    type="button"
                    className="primary fit"
                    disabled={gpAuditLoading || gpActionProvisioning}
                    onClick={() => setGpActionSelectedKeys([])}
                  >
                    Tout deselectionner
                  </button>
                </div>
              )}
            </div>

            <div>
              <div className="subsection-title">
                <h4>Comptes GP existants non trouves dans le MCR</h4>
                <span className="count-badge muted-badge">{gpMissingRows.length}</span>
              </div>
              <div className="button-row wrap">
                {canManageUsers && (
                  <button
                    type="button"
                    className="danger-button fit"
                    disabled={gpMissingSelectedIds.length === 0 || gpAuditLoading || gpMissingDeleting}
                    onClick={() => setGpMissingConfirmOpen(true)}
                  >
                    <Trash2 size={16} />
                    Supprimer la selection ({gpMissingSelectedIds.length})
                  </button>
                )}
              </div>
              <div className="table-scroll compact-scroll">
                <table className="audit-table">
                  <thead>
                    <tr>
                      {canManageUsers && (
                        <th className="select-cell">
                          <input
                            type="checkbox"
                            aria-label="Selectionner tous les comptes GP affiches"
                            checked={gpMissingRows.length > 0 && gpMissingRows.every((row) => gpMissingSelectedIds.includes(row.user_id))}
                            ref={(el) => {
                              if (el) {
                                const visibleIds = gpMissingRows.map((row) => row.user_id).filter(Boolean);
                                const allSelected = visibleIds.length > 0 && visibleIds.every((id) => gpMissingSelectedIds.includes(id));
                                const someSelected = visibleIds.some((id) => gpMissingSelectedIds.includes(id));
                                el.indeterminate = !allSelected && someSelected;
                              }
                            }}
                            onChange={() => {
                              const visibleIds = gpMissingRows.map((row) => row.user_id).filter(Boolean);
                              const allSelected = visibleIds.length > 0 && visibleIds.every((id) => gpMissingSelectedIds.includes(id));
                              setGpMissingSelectedIds(allSelected ? [] : visibleIds);
                            }}
                            disabled={gpMissingRows.length === 0 || gpAuditLoading}
                          />
                        </th>
                      )}
                      <th>Nom GP</th>
                      <th>Email</th>
                      <th>Agence compte</th>
                      <th>Statut</th>
                      <th>MDP provisoire</th>
                    </tr>
                  </thead>
                  <tbody>
                    {!gpAuditLoading && gpMissingRows.map((row) => {
                      const isSelected = gpMissingSelectedIds.includes(row.user_id);
                      return (
                        <tr key={row.user_id}>
                          {canManageUsers && (
                            <td className="select-cell">
                              <input
                                type="checkbox"
                                aria-label={`Selectionner le compte GP ${row.agent_name}`}
                                checked={isSelected}
                                onChange={() => setGpMissingSelectedIds((current) =>
                                  current.includes(row.user_id)
                                    ? current.filter((id) => id !== row.user_id)
                                    : [...current, row.user_id]
                                )}
                                disabled={gpMissingDeleting}
                              />
                            </td>
                          )}
                          <td>{row.agent_name}</td>
                          <td>{row.email}</td>
                          <td>{row.agency_name || "-"}</td>
                          <td>
                            <span className={row.is_active ? "status-pill neutral" : "status-pill danger"}>
                              {row.account_status}
                            </span>
                          </td>
                          <td>{row.temporary_password_available ? "Disponible" : "-"}</td>
                        </tr>
                      );
                    })}
                    {!gpAuditLoading && gpMissingRows.length === 0 && (
                      <tr>
                        <td colSpan={canManageUsers ? "6" : "5"} className="muted">
                          Tous les comptes GP existants sont presents dans le dernier MCR.
                        </td>
                      </tr>
                    )}
                    {gpAuditLoading && (
                      <tr>
                        <td colSpan={canManageUsers ? "6" : "5"} className="muted">Verification en cours...</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {gpMissingConfirmOpen && (
                <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="gp-mcr-delete-title">
                  <div className="modal-card">
                    <div className="modal-title">
                      <AlertTriangle size={18} />
                      <h3 id="gp-mcr-delete-title">Supprimer les comptes GP selectionnes ?</h3>
                    </div>
                    <p className="muted">
                      {gpMissingSelectedIds.length} compte(s) GP seront supprimes de la base.
                    </p>
                    <div className="button-row">
                      <button
                        type="button"
                        className="icon-button"
                        onClick={() => setGpMissingConfirmOpen(false)}
                        disabled={gpMissingDeleting}
                      >
                        Annuler
                      </button>
                      <button
                        type="button"
                        className="danger-button"
                        onClick={() => {
                          setGpMissingConfirmOpen(false);
                          deleteMissingGpMcrAccounts(gpMissingSelectedIds);
                        }}
                        disabled={gpMissingDeleting || gpMissingSelectedIds.length === 0}
                      >
                        <Trash2 size={16} />
                        {gpMissingDeleting ? "Suppression..." : "Confirmer la suppression"}
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        ) : (
          <>
            <div className="audit-toolbar">
              <select value={loginAuditFilters.user_id} onChange={(e) => setLoginAuditFilters((current) => ({ ...current, user_id: e.target.value }))}>
                <option value="">Tous les utilisateurs</option>
                {users.map((item) => <option key={item.id} value={item.id}>{item.full_name}</option>)}
              </select>
              <select value={loginAuditFilters.role} onChange={(e) => setLoginAuditFilters((current) => ({ ...current, role: e.target.value }))}>
                <option value="">Tous les roles</option>
                <option value="super_admin">Super Admin</option>
                <option value="admin">Admin</option>
                <option value="support">Support</option>
                <option value="committee_member">Membre comité</option>
                <option value="agency_manager">Chef d'agence</option>
                <option value="portfolio_manager">Portfolio Manager</option>
              </select>
              <input type="date" value={loginAuditFilters.date_from} onChange={(e) => setLoginAuditFilters((current) => ({ ...current, date_from: e.target.value }))} />
              <input type="date" value={loginAuditFilters.date_to} onChange={(e) => setLoginAuditFilters((current) => ({ ...current, date_to: e.target.value }))} />
              <button className="icon-button" type="button" onClick={() => exportLoginAudit("xlsx")}>Excel</button>
              <button className="icon-button" type="button" onClick={() => exportLoginAudit("pdf")}>PDF</button>
            </div>
            <div className="audit-summary-grid">
              <div className="audit-stat-card"><span>Total connexions</span><strong>{money(loginAudit?.total_connections || 0)}</strong></div>
              <div className="audit-stat-card"><span>Utilisateurs distincts</span><strong>{money(loginAudit?.by_user?.length || 0)}</strong></div>
              <div className="audit-stat-card"><span>Jours observes</span><strong>{money(loginAudit?.by_day?.length || 0)}</strong></div>
              <div className="audit-stat-card"><span>Heures observees</span><strong>{money(loginAudit?.by_hour?.length || 0)}</strong></div>
            </div>
            <div className="audit-grid">
              <div>
                <div className="subsection-title"><h4>Connexions par utilisateur</h4></div>
                <div className="table-scroll compact-scroll">
                  <table className="audit-table">
                    <thead><tr><th>Utilisateur</th><th>Connexions</th></tr></thead>
                    <tbody>
                      {(loginAudit?.by_user || []).map((row) => <tr key={row.label}><td>{row.label}</td><td>{row.count}</td></tr>)}
                      {!loginAuditLoading && (loginAudit?.by_user || []).length === 0 && <tr><td colSpan="2" className="muted">Aucune connexion.</td></tr>}
                    </tbody>
                  </table>
                </div>
              </div>
              <div>
                <div className="subsection-title"><h4>Connexions par jour</h4></div>
                <div className="table-scroll compact-scroll">
                  <table className="audit-table">
                    <thead><tr><th>Jour</th><th>Connexions</th></tr></thead>
                    <tbody>
                      {(loginAudit?.by_day || []).map((row) => <tr key={row.label}><td>{row.label}</td><td>{row.count}</td></tr>)}
                      {!loginAuditLoading && (loginAudit?.by_day || []).length === 0 && <tr><td colSpan="2" className="muted">Aucune connexion.</td></tr>}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
            <div className="table-scroll compact-scroll">
              <table className="audit-table">
                <thead>
                  <tr>
                    <th>Utilisateur</th>
                    <th>Email</th>
                    <th>Role</th>
                    <th>Date</th>
                    <th>Heure</th>
                    <th>Adresse IP</th>
                    <th>User Agent</th>
                    <th>Nb connexions</th>
                  </tr>
                </thead>
                <tbody>
                  {(loginAudit?.rows || []).map((row, index) => (
                    <tr key={`${row.email}-${row.login_date}-${row.login_hour}-${index}`}>
                      <td>{row.full_name}</td>
                      <td>{row.email}</td>
                      <td>{roleLabel(row.role)}</td>
                      <td>{formatDateLabel(row.login_date)}</td>
                      <td>{row.login_hour}</td>
                      <td>{row.ip_address || "-"}</td>
                      <td>{row.user_agent || "-"}</td>
                      <td>{row.connection_count}</td>
                    </tr>
                  ))}
                  {!loginAuditLoading && (loginAudit?.rows || []).length === 0 && <tr><td colSpan="8" className="muted">Aucune connexion enregistree pour ce filtre.</td></tr>}
                  {loginAuditLoading && <tr><td colSpan="8" className="muted">Chargement de l'audit...</td></tr>}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
      )}

      <div className="panel table-panel">
        <div className="panel-header">
          <h3>Comptes existants</h3>
          <label className="search-box">
            <Search size={16} />
            <input
              placeholder="Rechercher nom, email, role, agence..."
              value={userQuery}
              onChange={(e) => setUserQuery(e.target.value)}
            />
          </label>
        </div>
        <div className="table-scroll">
          {userFilterCount > 0 && (
            <div className="table-filter-summary">
              <span>{userFilterCount} filtre(s) actif(s)</span>
              <button type="button" className="icon-button" onClick={resetAllUserFilters}>Reinitialiser tous les filtres</button>
            </div>
          )}
          <table>
            <thead>
              <tr>
                {userColumns.map((column) => (
                  <SortableHeader
                    key={column.key}
                    label={column.label}
                    columnKey={column.key}
                    sortState={userSortState}
                    sortableType={column.sortableType}
                    onToggle={applyUserSort}
                    rows={filteredUsers}
                    column={column}
                    filterState={userColumnFilters[column.key]}
                    onFilterChange={(nextFilter) => updateUserFilter(column.key, nextFilter)}
                    onFilterReset={() => resetUserFilter(column.key)}
                  />
                ))}
              </tr>
            </thead>
            <tbody>
              {userPage.visible.map((item) => (
                <tr key={item.id}>
                  <td>{item.full_name}</td>
                  <td>{item.email}</td>
                  <td>{roleLabel(item.role)}</td>
                  <td>{item.agency_id || "-"}</td>
                  <td>{item.agent_id || "-"}</td>
                  <td>{item.is_active ? "Actif" : "Inactif"}</td>
                  {isSuperAdmin && <td>{item.temporary_password ? <code>{item.temporary_password}</code> : "-"}</td>}
                  <td className="row-actions">
                    {canManageUsers && (
                      <button
                        className="icon-button"
                        onClick={() => editUser(item)}
                        disabled={isSupport && isProtectedRoleForSupport(item.role)}
                      >
                        Modifier
                      </button>
                    )}
                    <button className="icon-button" onClick={() => resetPassword(item)} disabled={currentUser?.id === item.id || (isSupport && isProtectedRoleForSupport(item.role))}>Reset MDP</button>
                    {canManageUsers && (
                      <button
                        className="danger-button"
                        disabled={currentUser?.id === item.id || (isSupport && isProtectedRoleForSupport(item.role))}
                        onClick={() => removeUser(item)}
                      >
                        <Trash2 size={14} />
                        Supprimer
                      </button>
                    )}
                    <button
                      className={item.is_active ? "danger-button" : "icon-button"}
                      disabled={currentUser?.id === item.id || (isSupport && isProtectedRoleForSupport(item.role))}
                      onClick={() => toggleUserStatus(item)}
                    >
                      {item.is_active ? "Desactiver" : "Reactiver"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {userPage.pager}
      </div>
    </section>
  );
}

function TaegScreen({ user, agencies, agents, setNotice, committeeSelectedMonth }) {
  const isCommitteeMember = user?.role === "committee_member";
  const [periods, setPeriods] = useState([]);
  const [monthlyHistoryPeriods, setMonthlyHistoryPeriods] = useState([]);
  const [selectedPeriodKey, setSelectedPeriodKey] = useState("");
  const [selectedMonthlyHistoryPeriod, setSelectedMonthlyHistoryPeriod] = useState("");
  const [selectedAcmSegmentKey, setSelectedAcmSegmentKey] = useState("");
  const [agencyId, setAgencyId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [sectorId, setSectorId] = useState("");
  const [customPeriodKeys, setCustomPeriodKeys] = useState([]);
  const [detailPage, setDetailPage] = useState({ items: [], total: 0, limit: 10, offset: 0 });
  const [dashboardData, setDashboardData] = useState({
    period: null,
    used_periods: [],
    acm_segments: [],
    active_acm_segment: null,
    acm_coverage_message: null,
    rows: [],
  });
  const [monthlyHistoryData, setMonthlyHistoryData] = useState({ period: null, days_count: 0, sectors: [], points: [] });
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(true);
  const [monthlyHistoryLoading, setMonthlyHistoryLoading] = useState(false);
  const [exportingExcel, setExportingExcel] = useState(false);
  const [availableAgents, setAvailableAgents] = useState(agents || []);
  const [detailSortState, setDetailSortState] = useState({ key: null, direction: null });
  const [detailColumnFilters, setDetailColumnFilters] = useState({});
  const monthlyHistoryChartContainerRef = useRef(null);
  const taegComparisonChartContainerRef = useRef(null);
  const [selectedMonthlyHistoryDayKey, setSelectedMonthlyHistoryDayKey] = useState("");
  const [selectedMonthlyHistoryDayDetails, setSelectedMonthlyHistoryDayDetails] = useState(null);
  const historicalPeriods = useMemo(
    () => periods.filter((item) => !item.is_current && item.batch_type === "HISTORICAL_MONTH"),
    [periods],
  );
  const monthlyHistoricalPeriods = historicalPeriods;
  const isMonthlyHistoryTab = selectedPeriodKey === "monthly_history";
  const customSelectionInvalid = selectedPeriodKey === "custom" && customPeriodKeys.length < 2;
  const usedPeriods = dashboardData.used_periods || [];
  const usedPeriodsLabel = usedPeriods.length > 0
    ? usedPeriods.map((item) => formatShortMonthOnlyLabel(item.snapshot_date)).join(" & ")
    : "Aucun mois disponible";
  const tabItems = useMemo(() => [
    ...(!isCommitteeMember && periods.find((item) => item.key === "current") ? [{ key: "current", label: "Etat actuel" }] : []),
    { key: "semester:s1", label: "S1" },
    { key: "semester:s2", label: "S2" },
    { key: "custom", label: "Personnalise" },
    ...monthlyHistoricalPeriods.map((item) => ({ key: item.key, label: item.label })),
  ], [isCommitteeMember, periods, monthlyHistoricalPeriods]);
  const taegTabItems = useMemo(() => [
    ...(!isCommitteeMember && periods.find((item) => item.key === "current") ? [{ key: "current", label: "Etat actuel" }] : []),
    { key: "semester:s1", label: "S1" },
    { key: "semester:s2", label: "S2" },
    { key: "custom", label: "Personnalise" },
    ...(!isCommitteeMember ? [{ key: "monthly_history", label: "Historique mensuel" }] : []),
    ...historicalPeriods.map((item) => ({ key: item.key, label: item.label })),
  ], [historicalPeriods, isCommitteeMember, periods]);
  const selectedMonthlyHistoryMeta = monthlyHistoryPeriods.find((item) => item.key === selectedMonthlyHistoryPeriod) || null;
  const taegUsedPeriodsLabel = isMonthlyHistoryTab
    ? (selectedMonthlyHistoryMeta
      ? `${selectedMonthlyHistoryMeta.label} - ${monthlyHistoryData.days_count || 0} jour(s) historise(s)`
      : "Aucun mois historise disponible")
    : usedPeriodsLabel;
  const taegSummaryColumns = useMemo(() => [
    {
      key: "sector_name",
      label: "Secteur d'activite",
      render: (item) => item.sector_name,
      sortableType: "text",
      sortAccessor: (item) => item.sector_name,
      filterType: "text",
    },
    {
      key: "credits_count",
      label: "Nbre Credits",
      render: (item) => money(item.credits_count),
      sortableType: "number",
      sortAccessor: (item) => item.credits_count,
      filterType: "number",
    },
    {
      key: "disbursement_amount",
      label: "Montant decaisse",
      render: (item) => money(item.disbursement_amount),
      sortableType: "number",
      sortAccessor: (item) => item.disbursement_amount,
      filterType: "number",
    },
    {
      key: "taeg_calculated",
      label: "TAEG calcule",
      render: (item) => money(item.taeg_calculated),
      sortableType: "number",
      sortAccessor: (item) => item.taeg_calculated,
      filterType: "number",
    },
    {
      key: "taeg_weighted_rate",
      label: "TAEG pondere (%)",
      render: (item) => chartPercent(item.taeg_weighted_rate),
      sortableType: "number",
      sortAccessor: (item) => item.taeg_weighted_rate,
      filterType: "number",
    },
    {
      key: "acm_rate",
      label: "Taux ACM (%)",
      render: (item) => chartPercentNullable(item.acm_rate),
      sortableType: "number",
      sortAccessor: (item) => item.acm_rate,
      filterType: "number",
    },
    {
      key: "status",
      label: "Statut",
      render: (item) => {
        const statusMeta = taegStatusMeta(item.status);
        return (
          <span className={`status-pill ${statusMeta.className}`}>
            {statusMeta.label}
          </span>
        );
      },
      sortableType: "text",
      sortAccessor: (item) => item.status,
      filterType: "enum",
      filterAccessor: (item) => item.status,
      filterOptions: [
        { value: "conforme", label: "Conforme" },
        { value: "non_conforme", label: "Non Conforme" },
        { value: "non_couvert", label: "Non couvert ACM" },
      ],
    },
  ], []);
  const taegDetailColumns = useMemo(() => [
    {
      key: "contract_no",
      label: "CONTRACT_NO",
      render: (item) => item.contract_no,
      sortableType: "text",
      sortAccessor: (item) => item.contract_no,
      filterType: "text",
    },
    {
      key: "disbursement_date",
      label: "DISBURSEMENT_DATE",
      render: (item) => shortDate(item.disbursement_date),
      sortAccessor: (item) => item.disbursement_date,
      filterType: "date",
    },
    {
      key: "disbursement_amount",
      label: "DISBURSEMENT_AMOUNT",
      render: (item) => money(item.disbursement_amount),
      sortableType: "number",
      sortAccessor: (item) => item.disbursement_amount,
      filterType: "number",
    },
    {
      key: "teg_rate",
      label: "TEG_RATE",
      render: (item) => chartPercent(item.teg_rate),
      sortableType: "number",
      sortAccessor: (item) => item.teg_rate,
      filterType: "number",
    },
    {
      key: "taeg_calculated",
      label: "TAEG calcule",
      render: (item) => money(item.taeg_calculated),
      sortableType: "number",
      sortAccessor: (item) => item.taeg_calculated,
      filterType: "number",
    },
    {
      key: "taeg_weighted_rate",
      label: "TAEG pondere (%)",
      render: (item) => chartPercent(item.taeg_weighted_rate),
      sortableType: "number",
      sortAccessor: (item) => item.taeg_weighted_rate,
      filterType: "number",
    },
    {
      key: "sector_name",
      label: "Secteur",
      render: (item) => item.sector_name,
      sortableType: "text",
      sortAccessor: (item) => item.sector_name,
      filterType: "text",
    },
    {
      key: "acm_block_label",
      label: "Bloc ACM applique",
      render: (item) => item.acm_block_label || "Aucun bloc",
      sortAccessor: (item) => item.acm_block_label,
      filterType: "text",
    },
    {
      key: "acm_rate",
      label: "Taux ACM (%)",
      render: (item) => chartPercentNullable(item.acm_rate),
      sortableType: "number",
      sortAccessor: (item) => item.acm_rate,
      filterType: "number",
    },
    {
      key: "status",
      label: "Statut",
      render: (item) => {
        const statusMeta = taegStatusMeta(item.status);
        return (
          <span className={`status-pill ${statusMeta.className}`}>
            {statusMeta.label}
          </span>
        );
      },
      sortableType: "text",
      sortAccessor: (item) => item.status,
      filterType: "enum",
      filterAccessor: (item) => item.status,
      filterOptions: [
        { value: "conforme", label: "Conforme" },
        { value: "non_conforme", label: "Non Conforme" },
        { value: "non_couvert", label: "Non couvert ACM" },
      ],
    },
  ], []);
  const {
    sortState: summarySortState,
    sortedRows: summaryRows,
    columnFilters: summaryColumnFilters,
    activeFilterCount: summaryFilterCount,
    applySort: applySummarySort,
    updateFilter: updateSummaryFilter,
    resetFilter: resetSummaryFilter,
    resetAllFilters: resetAllSummaryFilters,
  } = useAdvancedTableState(
    useMemo(() => sortBySectorOrder(dashboardData.rows, (row) => row.sector_name), [dashboardData.rows]),
    taegSummaryColumns,
  );
  const detailFilterCount = useMemo(
    () => countActiveColumnFilters(detailColumnFilters, taegDetailColumns),
    [detailColumnFilters, taegDetailColumns],
  );
  const serializedSummaryFilters = useMemo(
    () => JSON.stringify(summaryColumnFilters || {}),
    [summaryColumnFilters],
  );
  const serializedDetailFilters = useMemo(
    () => JSON.stringify(detailColumnFilters || {}),
    [detailColumnFilters],
  );

  useEffect(() => {
    let mounted = true;
    api.taegPeriods()
      .then((items) => {
        if (!mounted) return;
        const nextItems = items || [];
        setPeriods(nextItems);
        setSelectedPeriodKey(nextItems[0]?.key || "semester:s1");
      })
      .catch((err) => setNotice(err.message));
    return () => {
      mounted = false;
    };
  }, [setNotice]);

  useEffect(() => {
    if (!isCommitteeMember) return;
    if (!periods.length) return;
    const matchingHistoricalPeriod = periods.find(
      (item) => !item.is_current && monthKeyFromDate(item.snapshot_date) === committeeSelectedMonth,
    );
    const fallbackHistoricalPeriod = periods.find((item) => !item.is_current) || null;
    const nextPeriodKey = matchingHistoricalPeriod?.key || fallbackHistoricalPeriod?.key || "";
    if (nextPeriodKey && selectedPeriodKey !== nextPeriodKey) {
      setSelectedPeriodKey(nextPeriodKey);
      setSectorId("");
      setDetailPage((current) => ({ ...current, offset: 0 }));
    }
  }, [committeeSelectedMonth, isCommitteeMember, periods]);

  useEffect(() => {
    if (isCommitteeMember) {
      setMonthlyHistoryPeriods([]);
      if (selectedPeriodKey === "monthly_history") {
        setSelectedPeriodKey(periods[0]?.key || "semester:s1");
      }
      return undefined;
    }
    let mounted = true;
    api.taegMonthlyHistoryPeriods()
      .then((items) => {
        if (!mounted) return;
        const nextItems = items || [];
        setMonthlyHistoryPeriods(nextItems);
        if (!selectedMonthlyHistoryPeriod && nextItems[0]?.key) {
          setSelectedMonthlyHistoryPeriod(nextItems[0].key);
        }
        if (!selectedPeriodKey && !periods.length && nextItems[0]?.key) {
          setSelectedPeriodKey("monthly_history");
        }
      })
      .catch((err) => setNotice(err.message));
    return () => {
      mounted = false;
    };
  }, [isCommitteeMember, periods, periods.length, selectedMonthlyHistoryPeriod, selectedPeriodKey, setNotice]);

  useEffect(() => {
    if (!monthlyHistoryPeriods.length) return;
    if (!monthlyHistoryPeriods.some((item) => item.key === selectedMonthlyHistoryPeriod)) {
      setSelectedMonthlyHistoryPeriod(monthlyHistoryPeriods[0].key);
    }
  }, [monthlyHistoryPeriods, selectedMonthlyHistoryPeriod]);

  useEffect(() => {
    setSelectedAcmSegmentKey("");
  }, [selectedPeriodKey, customPeriodKeys.join(",")]);

  useEffect(() => {
    if (!agencyId) {
      setAvailableAgents(agents || []);
      setAgentId("");
      return;
    }
    api.agents(agencyId)
      .then((page) => setAvailableAgents(page.items || []))
      .catch(() => setAvailableAgents([]));
  }, [agencyId, agents]);

  useEffect(() => {
    if (!selectedPeriodKey || customSelectionInvalid || isMonthlyHistoryTab) {
      setLoading(false);
      setDashboardData({
        period: {
          key: isMonthlyHistoryTab ? "monthly_history" : "custom",
          label: isMonthlyHistoryTab ? "Historique mensuel" : "Personnalise",
          snapshot_date: periods[0]?.snapshot_date || new Date().toISOString().slice(0, 10),
          batch_type: "AGGREGATE",
          batch_id: null,
          is_current: false,
        },
        used_periods: [],
        acm_segments: [],
        active_acm_segment: null,
        acm_coverage_message: null,
        rows: [],
      });
      return;
    }
    const selectedSegment = dashboardData.period?.key === selectedPeriodKey
      ? (dashboardData.acm_segments.find((segment) => segment.segment_key === selectedAcmSegmentKey) || null)
      : null;
    setLoading(true);
    api.taegDashboard(clean({
      period_key: selectedPeriodKey,
      period_keys: selectedPeriodKey === "custom" ? customPeriodKeys.join(",") : undefined,
      agency_id: agencyId || undefined,
      agent_id: agentId || undefined,
      acm_block_id: selectedSegment?.version_id ?? undefined,
      period_start: selectedSegment?.range_start ?? undefined,
      period_end: selectedSegment?.range_end ?? undefined,
    }))
      .then((result) => {
        const payload = result || {
          period: null,
          used_periods: [],
          acm_segments: [],
          active_acm_segment: null,
          acm_coverage_message: null,
          rows: [],
        };
        setDashboardData(payload);
        setSelectedAcmSegmentKey(payload.active_acm_segment?.segment_key || payload.acm_segments?.[0]?.segment_key || "");
      })
      .catch((err) => {
        setDashboardData({ period: null, used_periods: [], acm_segments: [], active_acm_segment: null, acm_coverage_message: null, rows: [] });
        setNotice(err.message);
      })
      .finally(() => setLoading(false));
  }, [selectedPeriodKey, customPeriodKeys, customSelectionInvalid, agencyId, agentId, periods, isMonthlyHistoryTab, selectedAcmSegmentKey, setNotice]);

  useEffect(() => {
    if (!selectedPeriodKey || customSelectionInvalid || isMonthlyHistoryTab) {
      setDetailLoading(false);
      setDetailPage((current) => ({ ...current, items: [], total: 0 }));
      return;
    }
    setDetailLoading(true);
    api.taegDetails(clean({
      period_key: selectedPeriodKey,
      period_keys: selectedPeriodKey === "custom" ? customPeriodKeys.join(",") : undefined,
      agency_id: agencyId || undefined,
      agent_id: agentId || undefined,
      sector_id: sectorId || undefined,
      acm_block_id: dashboardData.active_acm_segment?.version_id ?? undefined,
      period_start: dashboardData.active_acm_segment?.range_start ?? undefined,
      period_end: dashboardData.active_acm_segment?.range_end ?? undefined,
      table_filters: detailFilterCount > 0 ? serializedDetailFilters : undefined,
      sort_key: detailSortState.key || undefined,
      sort_direction: detailSortState.direction || undefined,
      limit: detailPage.limit,
      offset: detailPage.offset,
    }))
      .then((result) => setDetailPage(result || { items: [], total: 0, limit: 10, offset: 0 }))
      .catch((err) => {
        setDetailPage((current) => ({ ...current, items: [], total: 0 }));
        setNotice(err.message);
      })
      .finally(() => setDetailLoading(false));
  }, [
    selectedPeriodKey,
    customPeriodKeys,
    customSelectionInvalid,
    agencyId,
    agentId,
    sectorId,
    detailFilterCount,
    serializedDetailFilters,
    detailSortState.key,
    detailSortState.direction,
    detailPage.limit,
    detailPage.offset,
    dashboardData.active_acm_segment?.version_id,
    dashboardData.active_acm_segment?.range_start,
    dashboardData.active_acm_segment?.range_end,
    isMonthlyHistoryTab,
    setNotice,
  ]);

  useEffect(() => {
    if (!isMonthlyHistoryTab || !selectedMonthlyHistoryPeriod) {
      setMonthlyHistoryLoading(false);
      setMonthlyHistoryData({ period: null, days_count: 0, sectors: [], points: [] });
      return;
    }
    setMonthlyHistoryLoading(true);
    api.taegMonthlyHistory(clean({
      period: selectedMonthlyHistoryPeriod,
      agency_id: agencyId || undefined,
      agent_id: agentId || undefined,
    }))
      .then((result) => setMonthlyHistoryData(result || { period: null, days_count: 0, sectors: [], points: [] }))
      .catch((err) => {
        setMonthlyHistoryData({ period: null, days_count: 0, sectors: [], points: [] });
        setNotice(err.message);
      })
      .finally(() => setMonthlyHistoryLoading(false));
  }, [isMonthlyHistoryTab, selectedMonthlyHistoryPeriod, agencyId, agentId, setNotice]);

  const chartData = useMemo(
    () => sortBySectorOrder(
      dashboardData.rows.map((row) => ({
        sectorName: row.sector_name,
        taegWeightedRate: Number(row.taeg_weighted_rate || 0),
        acmRate: row.acm_rate === null || row.acm_rate === undefined ? null : Number(row.acm_rate),
        creditsCount: Number(row.credits_count || 0),
        disbursementAmount: Number(row.disbursement_amount || 0),
        status: row.status,
        compliantCreditsCount: Number(row.compliant_credits_count || 0),
        nonCompliantCreditsCount: Number(row.non_compliant_credits_count || 0),
        uncoveredCreditsCount: Number(row.uncovered_credits_count || 0),
      })),
      (item) => item.sectorName,
    ),
    [dashboardData.rows],
  );

  const chartMax = useMemo(() => {
    const maxValue = chartData.reduce(
      (highest, row) => Math.max(highest, row.taegWeightedRate || 0, row.acmRate || 0),
      0,
    );
    if (maxValue <= 0.1) return 0.1;
    if (maxValue <= 0.25) return 0.25;
    if (maxValue <= 0.5) return 0.5;
    return Math.ceil(maxValue * 1.2 * 100) / 100;
  }, [chartData]);

  const monthlyHistorySeries = useMemo(
    () => (monthlyHistoryData.sectors || []).map((item) => item.sector_name).filter(Boolean),
    [monthlyHistoryData.sectors],
  );

  const monthlyHistoryChartData = useMemo(() => {
    const rowsByDay = new Map();
    (monthlyHistoryData.points || []).forEach((point) => {
      const dayKey = String(point.snapshot_date);
      const current = rowsByDay.get(dayKey) || {
        snapshotDate: point.snapshot_date,
        dayLabel: point.day_label,
        pointDetails: {},
      };
      current[point.sector_name] = Number(point.taeg_weighted_rate || 0);
      current.pointDetails[point.sector_name] = {
        sectorName: point.sector_name,
        snapshotDate: point.snapshot_date,
        acmRate: point.acm_rate === null || point.acm_rate === undefined ? null : Number(point.acm_rate),
        taegCalculated: Number(point.taeg_calculated || 0),
        taegWeightedRate: Number(point.taeg_weighted_rate || 0),
        status: point.status,
        creditsCount: Number(point.credits_count || 0),
        disbursementAmount: Number(point.disbursement_amount || 0),
      };
      rowsByDay.set(dayKey, current);
    });
    return Array.from(rowsByDay.values()).sort((left, right) => String(left.snapshotDate).localeCompare(String(right.snapshotDate)));
  }, [monthlyHistoryData.points]);

  const monthlyHistoryChartMax = useMemo(() => {
    const maxValue = monthlyHistoryChartData.reduce((highest, row) => {
      const seriesMax = monthlyHistorySeries.reduce(
        (sectorHighest, sectorName) => Math.max(sectorHighest, Number(row[sectorName] || 0)),
        0,
      );
      const acmMax = Object.values(row.pointDetails || {}).reduce(
        (detailHighest, detail) => Math.max(detailHighest, Number(detail.acmRate || 0)),
        0,
      );
      return Math.max(highest, seriesMax, acmMax);
    }, 0);
    if (maxValue <= 0.1) return 0.1;
    if (maxValue <= 0.25) return 0.25;
    if (maxValue <= 0.5) return 0.5;
    return Math.ceil(maxValue * 1.2 * 100) / 100;
  }, [monthlyHistoryChartData, monthlyHistorySeries]);

  const monthlyHistoryRowsByDate = useMemo(
    () => new Map(monthlyHistoryChartData.map((row) => [String(row.snapshotDate), row])),
    [monthlyHistoryChartData],
  );

  const monthlyHistoryRowsByDayLabel = useMemo(
    () => new Map(monthlyHistoryChartData.map((row) => [String(row.dayLabel), row])),
    [monthlyHistoryChartData],
  );

  useEffect(() => {
    if (!selectedMonthlyHistoryDayKey) {
      setSelectedMonthlyHistoryDayDetails(null);
      return;
    }
    const nextRow = monthlyHistoryRowsByDate.get(selectedMonthlyHistoryDayKey);
    if (!nextRow) {
      setSelectedMonthlyHistoryDayKey("");
      setSelectedMonthlyHistoryDayDetails(null);
      return;
    }
    setSelectedMonthlyHistoryDayDetails(buildMonthlyHistoryDayDetails(nextRow, dashboardData.acm_segments || []));
  }, [selectedMonthlyHistoryDayKey, monthlyHistoryRowsByDate, dashboardData.acm_segments]);

  const selectedPeriod = periods.find((item) => item.key === selectedPeriodKey) || dashboardData.period || null;
  const hasMultipleAcmSegments = (dashboardData.acm_segments || []).length > 1;
  const activeAcmSegment = dashboardData.active_acm_segment || dashboardData.acm_segments.find((segment) => segment.segment_key === selectedAcmSegmentKey) || null;
  const selectedSectorName = dashboardData.rows.find((row) => String(row.sector_id) === String(sectorId))?.sector_name || "-";
  const headerBadgeLabel = isMonthlyHistoryTab
    ? (selectedMonthlyHistoryMeta ? `Mois : ${selectedMonthlyHistoryMeta.label}` : "Aucun mois")
    : (selectedPeriod?.snapshot_date ? `DateEOD : ${formatDateLabel(selectedPeriod.snapshot_date)}` : "Aucune periode");

  function toggleCustomPeriod(periodKey) {
    setCustomPeriodKeys((current) => (
      current.includes(periodKey)
        ? current.filter((item) => item !== periodKey)
        : [...current, periodKey].sort((left, right) => {
          const leftPeriod = monthlyHistoricalPeriods.find((item) => item.key === left);
          const rightPeriod = monthlyHistoricalPeriods.find((item) => item.key === right);
          const leftDate = leftPeriod?.snapshot_date || "";
          const rightDate = rightPeriod?.snapshot_date || "";
          return String(leftDate).localeCompare(String(rightDate));
        })
    ));
    setDetailPage((current) => ({ ...current, offset: 0 }));
  }

  function resetMonthlyHistorySelection() {
    setSelectedMonthlyHistoryDayKey("");
    setSelectedMonthlyHistoryDayDetails(null);
  }

  function selectMonthlyHistoryDay(row) {
    if (!row?.snapshotDate) return;
    const nextKey = String(row.snapshotDate);
    setSelectedMonthlyHistoryDayKey(nextKey);
    setSelectedMonthlyHistoryDayDetails(buildMonthlyHistoryDayDetails(row, dashboardData.acm_segments || []));
  }

  function handleMonthlyHistoryChartClick(chartState) {
    const row = chartState?.activePayload?.[0]?.payload || null;
    if (!row) return;
    selectMonthlyHistoryDay(row);
  }

  function handleMonthlyHistoryTickClick(dayLabel) {
    const row = monthlyHistoryRowsByDayLabel.get(String(dayLabel));
    if (!row) return;
    selectMonthlyHistoryDay(row);
  }

  async function exportExcel() {
    if (!selectedPeriodKey || customSelectionInvalid || isMonthlyHistoryTab) {
      setNotice(isMonthlyHistoryTab
        ? "L'export Excel n'est pas disponible pour l'historique mensuel."
        : "Veuillez selectionner au moins deux mois avant l'export TAEG.");
      return;
    }
    setExportingExcel(true);
    try {
      const { blob, filename } = await api.downloadTaegReport(clean({
        period_key: selectedPeriodKey,
        period_keys: selectedPeriodKey === "custom" ? customPeriodKeys.join(",") : undefined,
        agency_id: agencyId || undefined,
        agent_id: agentId || undefined,
        acm_block_id: activeAcmSegment?.version_id ?? undefined,
        period_start: activeAcmSegment?.range_start ?? undefined,
        period_end: activeAcmSegment?.range_end ?? undefined,
        table_filters: summaryFilterCount > 0 ? serializedSummaryFilters : undefined,
        sort_key: summarySortState.key || undefined,
        sort_direction: summarySortState.direction || undefined,
      }));
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename || "TAEG_export.xlsx";
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setNotice(err.message);
    } finally {
      setExportingExcel(false);
    }
  }

  return (
    <section className="taeg-stack">
      <div className="panel">
        <div className="panel-header taeg-header">
          <div>
            <h3>Suivi TAEG mensuel</h3>
            <p className="muted">
              Credits retenus uniquement sur le mois du DateEOD de l&apos;onglet selectionne.
            </p>
          </div>
          <span className="state-date-pill">
            <CalendarDays size={14} />
            {headerBadgeLabel}
          </span>
        </div>
        <div className="taeg-tabs" role="tablist" aria-label="Periodes TAEG">
          {taegTabItems.map((period) => (
            <button
              key={period.key}
              type="button"
              className={selectedPeriodKey === period.key ? "taeg-tab active" : "taeg-tab"}
              onClick={() => {
                setSelectedPeriodKey(period.key);
                setSectorId("");
                setDetailPage((current) => ({ ...current, offset: 0 }));
              }}
            >
              {period.label}
            </button>
          ))}
        </div>
        {selectedPeriodKey === "custom" && (
          <div className="taeg-custom-panel">
            <div className="panel-header">
              <div>
                <h3>Selection des mois</h3>
                <p className="muted">Choisir au moins deux mois historiques pour agreger le calcul TAEG.</p>
              </div>
            </div>
            <div className="taeg-month-picker" role="group" aria-label="Mois personnalises TAEG">
              {monthlyHistoricalPeriods.map((period) => {
                const checked = customPeriodKeys.includes(period.key);
                return (
                  <label key={period.key} className={checked ? "taeg-month-option active" : "taeg-month-option"}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleCustomPeriod(period.key)}
                    />
                    <span>{formatLongMonthLabel(period.snapshot_date)}</span>
                  </label>
                );
              })}
            </div>
            {customSelectionInvalid && (
              <p className="form-error">Veuillez sélectionner au moins deux mois.</p>
            )}
          </div>
        )}
        {isMonthlyHistoryTab && (
          <div className="taeg-custom-panel">
            <div className="panel-header">
              <div>
                <h3>Selection du mois historise</h3>
                <p className="muted">Le diagramme charge tous les snapshots journaliers TAEG du mois selectionne.</p>
              </div>
            </div>
            <div className="taeg-history-selector">
              <label>Mois
                <select
                  value={selectedMonthlyHistoryPeriod}
                  onChange={(event) => setSelectedMonthlyHistoryPeriod(event.target.value)}
                >
                  <option value="">Selectionner un mois</option>
                  {monthlyHistoryPeriods.map((period) => (
                    <option key={period.key} value={period.key}>
                      {period.label} ({period.days_count} jour(s))
                    </option>
                  ))}
                </select>
              </label>
              {selectedMonthlyHistoryMeta && (
                <div className="taeg-history-summary-card">
                  <strong>{selectedMonthlyHistoryMeta.label}</strong>
                  <span>{monthlyHistoryData.days_count || 0} jour(s) historise(s)</span>
                  <span>{monthlyHistorySeries.length} secteur(s)</span>
                </div>
              )}
            </div>
          </div>
        )}
        <div className={`form-grid taeg-filter-grid ${isMonthlyHistoryTab ? "history-mode" : ""}`}>
          <label>Agence
            <AgencyMultiSelect
              options={agencies}
              selectedIds={selectedIds(agencyId)}
              responsiveTags
              overflowLabel="agences"
              onChange={(nextAgencyIds) => {
                setAgencyId(nextAgencyIds);
                setAgentId("");
                setDetailPage((current) => ({ ...current, offset: 0 }));
              }}
            />
          </label>
          <label>Agent
            <select
              value={agentId}
              onChange={(event) => {
                setAgentId(event.target.value);
                setDetailPage((current) => ({ ...current, offset: 0 }));
              }}
            >
              <option value="">Tous les agents</option>
              {availableAgents.map((agent) => (
                <option key={agent.id} value={agent.id}>{agent.name}</option>
              ))}
            </select>
          </label>
          {!isMonthlyHistoryTab && (
            <label>Secteur (liste detaillee)
              <select
                value={sectorId}
                onChange={(event) => {
                  setSectorId(event.target.value);
                  setDetailPage((current) => ({ ...current, offset: 0 }));
                }}
              >
                <option value="">Tous les secteurs</option>
                {dashboardData.rows.map((row) => (
                  <option key={row.sector_id} value={row.sector_id}>{row.sector_name}</option>
                ))}
              </select>
            </label>
          )}
        </div>
        <div className="taeg-period-summary">
          <strong>{isMonthlyHistoryTab ? "Periode historisee :" : "Mois utilises :"}</strong>
          <span>{taegUsedPeriodsLabel}</span>
        </div>
        {!isMonthlyHistoryTab && (
          <div className="taeg-acm-summary-card">
            <div className="taeg-acm-summary-header">
              <strong>Couverture ACM appliquee</strong>
              {dashboardData.acm_coverage_message ? (
                <span className="status-pill warning">Couverture partielle</span>
              ) : (
                <span className="status-pill success">Couverture complete</span>
              )}
            </div>
            {dashboardData.acm_coverage_message ? (
              <p className="form-error taeg-acm-warning">{dashboardData.acm_coverage_message}</p>
            ) : null}
            <div className="taeg-acm-segments">
              {(dashboardData.acm_segments || []).map((segment, index) => (
                <button
                  key={`${segment.period_key || "segment"}-${segment.range_start}-${segment.range_end}-${index}`}
                  type="button"
                  className={[
                    "taeg-acm-segment",
                    hasMultipleAcmSegments ? "clickable" : "static",
                    segment.covered ? "" : "uncovered",
                    activeAcmSegment?.segment_key === segment.segment_key ? "active" : "",
                  ].filter(Boolean).join(" ")}
                  disabled={!hasMultipleAcmSegments}
                  onClick={() => {
                    if (!hasMultipleAcmSegments || activeAcmSegment?.segment_key === segment.segment_key) {
                      return;
                    }
                    setSelectedAcmSegmentKey(segment.segment_key);
                    setSectorId("");
                    setDetailPage((current) => ({ ...current, offset: 0 }));
                  }}
                >
                  <strong>{segment.block_label || segment.period_label || "Bloc ACM"}</strong>
                  <span>{formatDateLabel(segment.range_start)} - {formatDateLabel(segment.range_end)}</span>
                  <span>{segment.covered ? "Couverture complete" : "Aucun bloc ACM configure"}</span>
                  <span>{money(segment.credits_count || 0)} credit(s)</span>
                  <span>{money(segment.sectors_count || 0)} secteur(s)</span>
                </button>
              ))}
              {(!dashboardData.acm_segments || dashboardData.acm_segments.length === 0) && (
                <div className="taeg-acm-segment uncovered">
                  <strong>Aucune couverture ACM</strong>
                  <span>Aucun bloc ACM n&apos;a pu etre resolu pour cette selection.</span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {isMonthlyHistoryTab && (
        <>
          <div className="panel chart-panel">
            <div className="chart-panel-header">
              <div>
                <h3>Historique mensuel du TAEG pondere</h3>
                <p className="chart-subtitle">Cliquez sur un jour pour afficher ses details sous le graphique.</p>
              </div>
            </div>
            {!selectedMonthlyHistoryPeriod ? (
              <div className="chart-empty">Selectionner un mois pour afficher l'historique journalier.</div>
            ) : monthlyHistoryLoading ? (
              <div className="chart-empty">Chargement de l'historique mensuel...</div>
            ) : monthlyHistoryChartData.length === 0 ? (
              <div className="chart-empty">Aucun snapshot journalier TAEG disponible pour ce mois et ces filtres.</div>
            ) : (
              <div ref={monthlyHistoryChartContainerRef} className="monthly-history-chart-shell chart-tooltip-shell">
                <ResponsiveContainer width="100%" height={380}>
                  <LineChart
                    data={monthlyHistoryChartData}
                    margin={{ top: 12, right: 18, bottom: 8, left: 0 }}
                    onClick={handleMonthlyHistoryChartClick}
                  >
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis
                      dataKey="dayLabel"
                      tickLine={false}
                      tick={(tickProps) => (
                        <MonthlyHistoryXAxisTick
                          {...tickProps}
                          active={String(tickProps?.payload?.value || "") === String(selectedMonthlyHistoryDayDetails?.dayLabel || "")}
                          onSelect={handleMonthlyHistoryTickClick}
                        />
                      )}
                    />
                    <YAxis tickFormatter={chartPercent} domain={[0, monthlyHistoryChartMax]} width={88} />
                    {selectedMonthlyHistoryDayDetails?.dayLabel && (
                      <ReferenceLine
                        x={selectedMonthlyHistoryDayDetails.dayLabel}
                        stroke="#2563eb"
                        strokeDasharray="6 4"
                        strokeWidth={2}
                      />
                    )}
                    <Tooltip
                      isAnimationActive={false}
                      cursor={{ stroke: "#94a3b8", strokeWidth: 1.25, strokeDasharray: "4 4" }}
                      content={<TaegMonthlyHistoryTooltip containerRef={monthlyHistoryChartContainerRef} />}
                    />
                    <Legend />
                    {monthlyHistorySeries.map((sectorName, index) => (
                      <Line
                        key={sectorName}
                        type="monotone"
                        dataKey={sectorName}
                        name={sectorName}
                        stroke={TAEG_HISTORY_LINE_COLORS[index % TAEG_HISTORY_LINE_COLORS.length]}
                        strokeWidth={2.5}
                        dot={(
                          <MonthlyHistoryDot
                            selectedDayKey={selectedMonthlyHistoryDayKey}
                            onSelect={selectMonthlyHistoryDay}
                          />
                        )}
                        activeDot={{ r: 5 }}
                      />
                    ))}
                    <Brush dataKey="dayLabel" height={20} stroke="#94a3b8" travellerWidth={12} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          <div className="panel table-panel">
            <div className="panel-header">
              <div>
                <h3>{selectedMonthlyHistoryDayDetails ? `Details du ${selectedMonthlyHistoryDayDetails.dateLabel}` : "Details journaliers"}</h3>
                <p className="muted">
                  {selectedMonthlyHistoryDayDetails
                    ? "Les informations detaillees remplacent l'ancienne carte de survol."
                    : "Cliquez sur un jour du graphique pour afficher les details."}
                </p>
              </div>
              {selectedMonthlyHistoryDayDetails && (
                <button type="button" className="icon-button" onClick={resetMonthlyHistorySelection}>
                  Fermer les details
                </button>
              )}
            </div>

            {!selectedMonthlyHistoryDayDetails ? (
              <div className="chart-empty">Cliquez sur un jour du graphique pour afficher les details.</div>
            ) : (
              <div className="monthly-history-details-stack">
                <div className="monthly-history-summary-grid">
                  <div className="monthly-history-summary-card">
                    <span>Date selectionnee</span>
                    <strong>{selectedMonthlyHistoryDayDetails.dateLabel}</strong>
                  </div>
                  {/* <div className="monthly-history-summary-card">
                    <span>Bloc ACM</span>
                    <strong>{selectedMonthlyHistoryDayDetails.acmSegment?.block_label || "Bloc ACM non resolu"}</strong>
                    <small>{selectedMonthlyHistoryDayDetails.acmSegment?.range_start && selectedMonthlyHistoryDayDetails.acmSegment?.range_end ? `${formatDateLabel(selectedMonthlyHistoryDayDetails.acmSegment.range_start)} -> ${formatDateLabel(selectedMonthlyHistoryDayDetails.acmSegment.range_end)}` : "-"}</small>
                  </div> */}
                  <div className="monthly-history-summary-card">
                    <span>Secteurs conformes</span>
                    <strong>{formatNumber(selectedMonthlyHistoryDayDetails.compliantCount)}</strong>
                  </div>
                  <div className="monthly-history-summary-card">
                    <span>Secteurs non conformes</span>
                    <strong>{formatNumber(selectedMonthlyHistoryDayDetails.nonCompliantCount)}</strong>
                  </div>
                  <div className="monthly-history-summary-card">
                    <span>Secteurs non couverts</span>
                    <strong>{formatNumber(selectedMonthlyHistoryDayDetails.uncoveredCount)}</strong>
                  </div>
                  <div className="monthly-history-summary-card">
                    <span>TAEG moyen</span>
                    <strong>{chartPercentNullable(selectedMonthlyHistoryDayDetails.taegAverage)}</strong>
                  </div>
                  <div className="monthly-history-summary-card">
                    <span>Taux ACM moyen</span>
                    <strong>{chartPercentNullable(selectedMonthlyHistoryDayDetails.acmAverage)}</strong>
                  </div>
                  <div className="monthly-history-summary-card">
                    <span>Montant decaisse</span>
                    <strong>{money(selectedMonthlyHistoryDayDetails.disbursementAmount)}</strong>
                  </div>
                </div>

                <div className="table-scroll monthly-history-details-table">
                  <table className="credits-table">
                    <thead>
                      <tr>
                        <th>Date</th>
                        
                        <th>Secteur</th>
                        <th>Statut</th>
                        
                        <th>TAEG pondere</th>
                        <th>Taux ACM</th>
                        <th>Nombre de credits</th>
                        <th>Montant decaisse</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedMonthlyHistoryDayDetails.rows.map((detail) => {
                        const statusMeta = taegStatusMeta(detail.status);
                        return (
                          <tr key={`${detail.dateLabel}-${detail.sectorName}`}>
                            <td>{detail.dateLabel}</td>
                            
                            <td>{detail.sectorName}</td>
                            <td><span className={`status-pill ${statusMeta.className}`}>{statusMeta.label}</span></td>
                            
                            <td className="table-number-cell">{chartPercent(detail.taegWeightedRate)}</td>
                            <td className="table-number-cell">{chartPercentNullable(detail.acmRate)}</td>
                            <td className="table-number-cell">{formatNumber(detail.creditsCount)}</td>
                            <td className="table-number-cell">{money(detail.disbursementAmount)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </>
      )}

      {!isMonthlyHistoryTab && (
      <>
      <div className="panel table-panel">
        <div className="panel-header">
          <div>
            <h3>Tableau principal TAEG</h3>
            <p className="muted">
              {selectedPeriod?.label || "Periode"} - {activeAcmSegment?.block_label || "Bloc ACM"}
              {" "}• Periode analysee : {activeAcmSegment ? `${formatDateLabel(activeAcmSegment.range_start)} -> ${formatDateLabel(activeAcmSegment.range_end)}` : "Selection complete"}
            </p>
          </div>
          <button
            className="icon-button"
            type="button"
            onClick={exportExcel}
            disabled={loading || exportingExcel || customSelectionInvalid}
          >
            <FileDown size={16} />
            {exportingExcel ? "Export en cours..." : "Exporter Excel"}
          </button>
        </div>
        {summaryFilterCount > 0 && (
          <div className="table-filter-summary">
            <span>{summaryFilterCount} filtre(s) actif(s)</span>
            <button type="button" className="icon-button" onClick={resetAllSummaryFilters}>Reinitialiser tous les filtres</button>
          </div>
        )}
        <div className="table-scroll">
          <table className="credits-table">
            <thead>
              <tr>
                {taegSummaryColumns.map((column) => (
                  <SortableHeader
                    key={column.key}
                    label={column.label}
                    columnKey={column.key}
                    sortState={summarySortState}
                    onToggle={applySummarySort}
                    rows={dashboardData.rows}
                    column={column}
                    filterState={summaryColumnFilters[column.key]}
                    onFilterChange={(nextFilter) => updateSummaryFilter(column.key, nextFilter)}
                    onFilterReset={() => resetSummaryFilter(column.key)}
                  />
                ))}
              </tr>
            </thead>
            <tbody>
              {!loading && summaryRows.map((row) => (
                <tr key={row.sector_id}>
                  {taegSummaryColumns.map((column) => (
                    <td key={`${row.sector_id}-${column.key}`}>{column.render(row)}</td>
                  ))}
                </tr>
              ))}
              {!loading && summaryRows.length === 0 && (
                <tr>
                  <td colSpan={taegSummaryColumns.length} className="muted">Aucune donnee TAEG disponible pour cette periode et ces filtres.</td>
                </tr>
              )}
              {loading && (
                <tr>
                  <td colSpan={taegSummaryColumns.length} className="muted">Chargement du tableau TAEG...</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel chart-panel">
        <div className="chart-panel-header">
          <div>
            <h3>Comparaison TAEG pondere / Taux ACM</h3>
            <p className="chart-subtitle">
              {activeAcmSegment
                ? `Bloc actif : ${activeAcmSegment.block_label || "Bloc ACM"} • ${formatDateLabel(activeAcmSegment.range_start)} -> ${formatDateLabel(activeAcmSegment.range_end)}`
                : "Deux barres par secteur pour verifier la conformite mensuelle."}
            </p>
          </div>
        </div>
        {chartData.length === 0 && !loading ? (
          <div className="chart-empty">Aucune donnee a afficher pour le diagramme TAEG.</div>
        ) : (
          <div ref={taegComparisonChartContainerRef} className="chart-tooltip-shell">
            <ResponsiveContainer width="100%" height={360}>
              <BarChart data={chartData} margin={{ top: 12, right: 18, bottom: 8, left: 0 }} barCategoryGap="18%">
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="sectorName" tickLine={false} angle={-12} textAnchor="end" height={64} />
                <YAxis tickFormatter={chartPercent} domain={[0, chartMax]} width={88} />
                <Tooltip
                  content={<TaegChartTooltip containerRef={taegComparisonChartContainerRef} />}
                  allowEscapeViewBox={{ x: true, y: true }}
                  isAnimationActive={false}
                />
                <Legend />
                <Bar dataKey="taegWeightedRate" name="TAEG pondere" fill="#2563eb" radius={[8, 8, 0, 0]} />
                <Bar dataKey="acmRate" name="Taux ACM" fill="#0f766e" radius={[8, 8, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      <div className="panel table-panel">
        <div className="panel-header">
          <div>
            <h3>Liste detaillee des credits</h3>
            <p className="muted">
              {sectorId ? `Secteur filtre : ${selectedSectorName}` : "Tous les secteurs"}
              {activeAcmSegment ? ` • Bloc actif : ${activeAcmSegment.block_label || "Bloc ACM"} • ${formatDateLabel(activeAcmSegment.range_start)} -> ${formatDateLabel(activeAcmSegment.range_end)}` : ""}
            </p>
          </div>
        </div>
        {detailFilterCount > 0 && (
          <div className="table-filter-summary">
            <span>{detailFilterCount} filtre(s) actif(s)</span>
            <button
              type="button"
              className="icon-button"
              onClick={() => {
                setDetailColumnFilters({});
                setDetailPage((current) => ({ ...current, offset: 0 }));
              }}
            >
              Reinitialiser tous les filtres
            </button>
          </div>
        )}
        <div className="table-scroll">
          <table className="credits-table">
            <thead>
              <tr>
                {taegDetailColumns.map((column) => (
                  <SortableHeader
                    key={column.key}
                    label={column.label}
                    columnKey={column.key}
                    sortState={detailSortState}
                    onToggle={(columnKey, direction) => {
                      setDetailSortState(direction ? { key: columnKey, direction } : { key: null, direction: null });
                      setDetailPage((current) => ({ ...current, offset: 0 }));
                    }}
                    rows={detailPage.items}
                    column={column}
                    filterState={detailColumnFilters[column.key]}
                    onFilterChange={(nextFilter) => {
                      setDetailColumnFilters((current) => ({ ...current, [column.key]: nextFilter }));
                      setDetailPage((current) => ({ ...current, offset: 0 }));
                    }}
                    onFilterReset={() => {
                      setDetailColumnFilters((current) => {
                        if (!(column.key in current)) return current;
                        const next = { ...current };
                        delete next[column.key];
                        return next;
                      });
                      setDetailPage((current) => ({ ...current, offset: 0 }));
                    }}
                  />
                ))}
              </tr>
            </thead>
            <tbody>
              {!detailLoading && detailPage.items.map((item) => (
                <tr key={`${item.contract_no}-${item.sector_id}`}>
                  {taegDetailColumns.map((column) => (
                    <td key={`${item.contract_no}-${item.sector_id}-${column.key}`}>{column.render(item)}</td>
                  ))}
                </tr>
              ))}
              {!detailLoading && detailPage.items.length === 0 && (
                <tr>
                  <td colSpan={taegDetailColumns.length} className="muted">Aucun credit detaille trouve pour cette selection.</td>
                </tr>
              )}
              {detailLoading && (
                <tr>
                  <td colSpan={taegDetailColumns.length} className="muted">Chargement de la liste detaillee...</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <Pager
          total={detailPage.total}
          limit={detailPage.limit}
          offset={detailPage.offset}
          onPage={(nextOffset) => setDetailPage((current) => ({ ...current, offset: nextOffset }))}
          onLimitChange={(nextLimit) => setDetailPage((current) => ({ ...current, limit: nextLimit, offset: 0 }))}
        />
      </div>
      </>
      )}
    </section>
  );
}

function ConfigurationScreen({ setNotice, onAcmLimitsUpdated }) {
  const emptySectorForm = { name: "" };
  const emptyVersionForm = {
    effective_start_date: "",
    end_mode: "until_change",
    effective_end_date: "",
    comment: "",
  };
  const [activeConfigTab, setActiveConfigTab] = useState("setup");
  const [sectors, setSectors] = useState([]);
  const [mappings, setMappings] = useState([]);
  const [acmRateVersions, setAcmRateVersions] = useState([]);
  const [selectedAcmVersion, setSelectedAcmVersion] = useState(null);
  const [editingAcmVersion, setEditingAcmVersion] = useState(null);
  const [referenceAcmVersion, setReferenceAcmVersion] = useState(null);
  const [sectorForm, setSectorForm] = useState(emptySectorForm);
  const [versionForm, setVersionForm] = useState(emptyVersionForm);
  const [blockRates, setBlockRates] = useState({});
  const [editingVersionForm, setEditingVersionForm] = useState({
    effective_start_date: "",
    end_mode: "until_change",
    effective_end_date: "",
    comment: "",
    modification_comment: "",
    confirm_impact: false,
  });
  const [editingBlockRates, setEditingBlockRates] = useState({});
  const [editingSectorId, setEditingSectorId] = useState(null);
  const [mappingDrafts, setMappingDrafts] = useState({});
  const [loading, setLoading] = useState(true);
  const [savingSector, setSavingSector] = useState(false);
  const [publishingVersion, setPublishingVersion] = useState(false);
  const [savingVersionUpdate, setSavingVersionUpdate] = useState(false);
  const [versionLoading, setVersionLoading] = useState(false);
  const [acmLimits, setAcmLimits] = useState(null);
  const [acmSaving, setAcmSaving] = useState(false);
  const [acmForm, setAcmForm] = useState({
    par_0_limit: "",
    par_30_limit: "",
    par_120_limit: "",
    cohort_1_30_limit: "",
    cohort_31_60_limit: "",
    cohort_61_90_limit: "",
    cohort_91_120_limit: "",
  });

  const currentSectorRateMap = useMemo(() => {
    const rates = Object.fromEntries(
      sectors.map((sector) => [String(sector.id), Number(sector.acm_rate ?? 0)])
    );
    for (const detail of referenceAcmVersion?.details || []) {
      rates[String(detail.sector_id)] = Number(detail.acm_rate ?? 0);
    }
    return rates;
  }, [referenceAcmVersion, sectors]);

  const missingBlockSectors = useMemo(
    () =>
      sectors.filter((sector) => {
        const rawValue = blockRates[String(sector.id)];
        const numericValue = Number(rawValue);
        return rawValue === "" || !Number.isFinite(numericValue) || numericValue < 0;
      }),
    [blockRates, sectors]
  );

  const modifiedBlockRatesCount = useMemo(
    () =>
      sectors.reduce((count, sector) => {
        const draftValue = blockRates[String(sector.id)];
        const draftNumber = Number(draftValue);
        const currentValue = Number(currentSectorRateMap[String(sector.id)] ?? 0);
        if (!Number.isFinite(draftNumber)) {
          return count;
        }
        return Math.abs(draftNumber - currentValue) > 0.000001 ? count + 1 : count;
      }, 0),
    [blockRates, currentSectorRateMap, sectors]
  );

  const editingReferenceRateMap = useMemo(() => {
    const rates = {};
    for (const detail of editingAcmVersion?.details || []) {
      rates[String(detail.sector_id)] = Number(detail.acm_rate ?? 0);
    }
    return rates;
  }, [editingAcmVersion]);

  const missingEditingBlockSectors = useMemo(
    () =>
      sectors.filter((sector) => {
        const rawValue = editingBlockRates[String(sector.id)];
        const numericValue = Number(rawValue);
        return rawValue === "" || !Number.isFinite(numericValue) || numericValue < 0;
      }),
    [editingBlockRates, sectors]
  );

  const modifiedEditingBlockRatesCount = useMemo(
    () =>
      sectors.reduce((count, sector) => {
        const draftValue = editingBlockRates[String(sector.id)];
        const draftNumber = Number(draftValue);
        const currentValue = Number(editingReferenceRateMap[String(sector.id)] ?? 0);
        if (!Number.isFinite(draftNumber)) {
          return count;
        }
        return Math.abs(draftNumber - currentValue) > 0.000001 ? count + 1 : count;
      }, 0),
    [editingBlockRates, editingReferenceRateMap, sectors]
  );

  function buildBlockRates(sectorItems, versionPayload) {
    const detailsMap = new Map(
      (versionPayload?.details || []).map((detail) => [String(detail.sector_id), detail.acm_rate])
    );
    return Object.fromEntries(
      (sectorItems || []).map((sector) => {
        const detailValue = detailsMap.get(String(sector.id));
        const sourceValue = detailValue ?? sector.acm_rate ?? 0;
        return [String(sector.id), sourceValue === null || sourceValue === undefined ? "" : String(sourceValue)];
      })
    );
  }

  function buildEditableVersionForm(versionPayload) {
    return {
      effective_start_date: versionPayload?.effective_start_date || "",
      end_mode: versionPayload?.is_open_ended ? "until_change" : "fixed",
      effective_end_date: versionPayload?.is_open_ended ? "" : (versionPayload?.effective_end_date || ""),
      comment: versionPayload?.comment || "",
      modification_comment: "",
      confirm_impact: false,
    };
  }

  function syncAcmForm(nextLimits) {
    setAcmForm({
      par_0_limit: nextLimits?.par_0_limit ?? "",
      par_30_limit: nextLimits?.par_30_limit ?? "",
      par_120_limit: nextLimits?.par_120_limit ?? "",
      cohort_1_30_limit: nextLimits?.cohort_1_30_limit ?? "",
      cohort_31_60_limit: nextLimits?.cohort_31_60_limit ?? "",
      cohort_61_90_limit: nextLimits?.cohort_61_90_limit ?? "",
      cohort_91_120_limit: nextLimits?.cohort_91_120_limit ?? "",
    });
  }

  async function loadAcmLimits() {
    try {
      const result = await api.acmLimits();
      setAcmLimits(result);
      syncAcmForm(result);
    } catch (err) {
      setAcmLimits(null);
      setNotice(err.message);
    }
  }

  async function saveAcmLimits() {
    setAcmSaving(true);
    try {
      const payload = Object.fromEntries(
        Object.entries(acmForm).map(([key, value]) => [key, value === "" ? null : Number(value)])
      );
      const result = await api.updateAcmLimits(payload);
      setAcmLimits(result);
      syncAcmForm(result);
      setNotice("Limites PAR enregistrees.");
      await onAcmLimitsUpdated?.();
    } catch (err) {
      setNotice(err.message);
    } finally {
      setAcmSaving(false);
    }
  }

  async function loadConfiguration() {
    setLoading(true);
    try {
      const [sectorItems, mappingItems, versionItems] = await Promise.all([
        api.taegSectors(),
        api.taegCategoryMappings(),
        api.taegAcmRateVersions(),
      ]);
      setSectors(sectorItems || []);
      setMappings(mappingItems || []);
      setAcmRateVersions(versionItems || []);
      setMappingDrafts(
        Object.fromEntries((mappingItems || []).map((item) => [item.category_desc, item.activity_sector_id ? String(item.activity_sector_id) : ""]))
      );

      const preferredVersion =
        (versionItems || []).find((item) => item.status === "actif")
        || (versionItems || [])[0]
        || null;
      let referenceVersionPayload = null;
      if (preferredVersion?.id) {
        try {
          referenceVersionPayload = await api.taegAcmRateVersion(preferredVersion.id);
        } catch (err) {
          setNotice(err.message);
        }
      }
      setReferenceAcmVersion(referenceVersionPayload);
      setBlockRates(buildBlockRates(sectorItems || [], referenceVersionPayload));
    } catch (err) {
      setNotice(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadConfiguration();
    loadAcmLimits();
  }, []);

  const sectorPage = useClientPagination(sectors, 10);
  const mappingPage = useClientPagination(mappings, 12);
  const historyPage = useClientPagination(acmRateVersions, 8);

  async function saveSector() {
    if (!sectorForm.name.trim()) {
      setNotice("Le nom du secteur est obligatoire.");
      return;
    }
    setSavingSector(true);
    try {
      const sectorKey = editingSectorId ? String(editingSectorId) : null;
      const fallbackRate = sectorKey ? Number(currentSectorRateMap[sectorKey] ?? 0) : 0;
      const payload = {
        name: sectorForm.name.trim(),
        acm_rate: Number.isFinite(fallbackRate) && fallbackRate >= 0 ? fallbackRate : 0,
      };
      if (editingSectorId) {
        await api.updateTaegSector(editingSectorId, payload);
        setNotice("Secteur mis a jour.");
      } else {
        await api.createTaegSector(payload);
        setNotice("Secteur cree.");
      }
      setSectorForm(emptySectorForm);
      setEditingSectorId(null);
      await loadConfiguration();
    } catch (err) {
      setNotice(err.message);
    } finally {
      setSavingSector(false);
    }
  }

  function editSector(sector) {
    setEditingSectorId(sector.id);
    setSectorForm({
      name: sector.name || "",
    });
  }

  async function removeSector(sector) {
    const confirmed = window.confirm(`Supprimer le secteur "${sector.name}" ainsi que ses mappings ?`);
    if (!confirmed) return;
    try {
      await api.deleteTaegSector(sector.id);
      setNotice("Secteur supprime.");
      if (editingSectorId === sector.id) {
        setEditingSectorId(null);
        setSectorForm(emptySectorForm);
      }
      await loadConfiguration();
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function saveMapping(item) {
    const selectedSectorId = Number(mappingDrafts[item.category_desc]);
    if (!Number.isFinite(selectedSectorId) || selectedSectorId <= 0) {
      setNotice("Selectionner un secteur avant d'enregistrer le mapping.");
      return;
    }
    try {
      await api.upsertTaegCategoryMapping({
        category_desc: item.category_desc,
        activity_sector_id: selectedSectorId,
      });
      setNotice("Mapping enregistre.");
      await loadConfiguration();
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function removeMapping(item) {
    if (!item.id) return;
    const confirmed = window.confirm(`Supprimer le mapping pour "${item.category_desc}" ?`);
    if (!confirmed) return;
    try {
      await api.deleteTaegCategoryMapping(item.id);
      setNotice("Mapping supprime.");
      await loadConfiguration();
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function openAcmVersion(versionId) {
    setVersionLoading(true);
    try {
      const payload = await api.taegAcmRateVersion(versionId);
      setSelectedAcmVersion(payload || null);
    } catch (err) {
      setNotice(err.message);
    } finally {
      setVersionLoading(false);
    }
  }

  async function openEditAcmVersion(versionId) {
    setVersionLoading(true);
    try {
      const payload = await api.taegAcmRateVersion(versionId);
      setEditingAcmVersion(payload || null);
      setEditingVersionForm(buildEditableVersionForm(payload));
      setEditingBlockRates(buildBlockRates(sectors, payload));
    } catch (err) {
      setNotice(err.message);
    } finally {
      setVersionLoading(false);
    }
  }

  function copyPreviousBlockRates() {
    if (!referenceAcmVersion) {
      setNotice("Aucun bloc ACM precedent n'est disponible.");
      return;
    }
    setBlockRates(buildBlockRates(sectors, referenceAcmVersion));
    setNotice("Les taux du bloc precedent ont ete copies.");
  }

  async function publishAcmVersion() {
    if (sectors.length === 0) {
      setNotice("Aucun secteur actif n'est disponible pour creer un bloc ACM.");
      return;
    }
    if (!versionForm.effective_start_date) {
      setNotice("La date de debut est obligatoire pour publier un bloc ACM.");
      return;
    }
    if (versionForm.end_mode === "fixed" && !versionForm.effective_end_date) {
      setNotice("Selectionnez une date de fin ou choisissez 'Jusqu'a modification'.");
      return;
    }
    if (versionForm.end_mode === "fixed" && versionForm.effective_end_date < versionForm.effective_start_date) {
      setNotice("La date de fin ACM doit etre superieure ou egale a la date de debut.");
      return;
    }
    if (missingBlockSectors.length > 0) {
      setNotice(`Tous les secteurs doivent recevoir un taux ACM valide. Secteurs concernes : ${missingBlockSectors.map((sector) => sector.name).join(", ")}`);
      return;
    }
    setPublishingVersion(true);
    try {
      const payload = await api.createTaegAcmRateVersion({
        effective_start_date: versionForm.effective_start_date,
        effective_end_date: versionForm.end_mode === "fixed" ? versionForm.effective_end_date : null,
        is_open_ended: versionForm.end_mode !== "fixed",
        comment: versionForm.comment.trim() || null,
        details: sectors.map((sector) => ({
          sector_id: sector.id,
          acm_rate: Number(blockRates[String(sector.id)]),
        })),
      });
      setNotice("Bloc ACM enregistre.");
      setVersionForm(emptyVersionForm);
      setSelectedAcmVersion(payload || null);
      await loadConfiguration();
    } catch (err) {
      setNotice(err.message);
    } finally {
      setPublishingVersion(false);
    }
  }

  async function saveEditedAcmVersion() {
    if (!editingAcmVersion?.id) return;
    if (!editingVersionForm.effective_start_date) {
      setNotice("La date de debut est obligatoire pour modifier un bloc ACM.");
      return;
    }
    if (editingVersionForm.end_mode === "fixed" && !editingVersionForm.effective_end_date) {
      setNotice("Selectionnez une date de fin ou choisissez 'Jusqu'a modification'.");
      return;
    }
    if (
      editingVersionForm.end_mode === "fixed"
      && editingVersionForm.effective_end_date < editingVersionForm.effective_start_date
    ) {
      setNotice("La date de fin ACM doit etre superieure ou egale a la date de debut.");
      return;
    }
    if (!editingVersionForm.modification_comment.trim()) {
      setNotice("Le commentaire de modification est obligatoire.");
      return;
    }
    if (missingEditingBlockSectors.length > 0) {
      setNotice(`Tous les secteurs doivent recevoir un taux ACM valide. Secteurs concernes : ${missingEditingBlockSectors.map((sector) => sector.name).join(", ")}`);
      return;
    }

    let confirmImpact = false;
    if (editingAcmVersion.may_affect_existing_results) {
      confirmImpact = window.confirm("Cette modification peut changer les resultats TAEG des periodes couvertes par ce bloc. Voulez-vous continuer ?");
      if (!confirmImpact) {
        return;
      }
    }

    setSavingVersionUpdate(true);
    try {
      const payload = await api.updateTaegAcmRateVersion(editingAcmVersion.id, {
        effective_start_date: editingVersionForm.effective_start_date,
        effective_end_date: editingVersionForm.end_mode === "fixed" ? editingVersionForm.effective_end_date : null,
        is_open_ended: editingVersionForm.end_mode !== "fixed",
        comment: editingVersionForm.comment.trim() || null,
        modification_comment: editingVersionForm.modification_comment.trim(),
        confirm_impact: confirmImpact,
        details: sectors.map((sector) => ({
          sector_id: sector.id,
          acm_rate: Number(editingBlockRates[String(sector.id)]),
        })),
      });
      setNotice("Bloc ACM modifie.");
      setEditingAcmVersion(null);
      setEditingVersionForm({
        effective_start_date: "",
        end_mode: "until_change",
        effective_end_date: "",
        comment: "",
        modification_comment: "",
        confirm_impact: false,
      });
      setEditingBlockRates({});
      setSelectedAcmVersion(payload || null);
      await loadConfiguration();
    } catch (err) {
      setNotice(err.message);
    } finally {
      setSavingVersionUpdate(false);
    }
  }

  return (
    <section className="configuration-stack">
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>Configuration TAEG</h3>
            <p className="muted">Gerer les secteurs, les mappings CATEGORY_DESC et les blocs complets de taux ACM versionnes.</p>
          </div>
        </div>
        <div className="segment-control config-segment-control" role="tablist" aria-label="Sections configuration TAEG">
          <button
            type="button"
            className={activeConfigTab === "setup" ? "segment-active" : ""}
            onClick={() => setActiveConfigTab("setup")}
          >
            Secteurs et mappings
          </button>
          <button
            type="button"
            className={activeConfigTab === "history" ? "segment-active" : ""}
            onClick={() => setActiveConfigTab("history")}
          >
            Historique ACM
          </button>
          <button
            type="button"
            className={activeConfigTab === "par_limits" ? "segment-active" : ""}
            onClick={() => setActiveConfigTab("par_limits")}
          >
            Limites PAR
          </button>
        </div>
      </div>

      {activeConfigTab === "setup" && (
        <div className="config-grid">
          <div className="panel narrow-panel">
            <h3>{editingSectorId ? "Modifier un secteur" : "Ajouter un secteur"}</h3>
            <div className="form-grid">
              <label>Nom du secteur
                <input
                  value={sectorForm.name}
                  onChange={(event) => setSectorForm((current) => ({ ...current, name: event.target.value }))}
                />
              </label>
            </div>
            <div className="button-row">
              <button className="primary fit" type="button" onClick={saveSector} disabled={savingSector}>
                <Save size={16} />
                {savingSector ? "Enregistrement..." : (editingSectorId ? "Mettre a jour" : "Ajouter")}
              </button>
              {editingSectorId && (
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => {
                    setEditingSectorId(null);
                    setSectorForm(emptySectorForm);
                  }}
                >
                  Annuler
                </button>
              )}
            </div>
          </div>

          <div className="panel table-panel">
            <div className="panel-header">
              <h3>Secteurs d'activite</h3>
              <span className="count-badge">{sectors.length}</span>
            </div>
            <div className="table-scroll compact-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Secteur</th>
                    <th>Taux du bloc actif (%)</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {!loading && sectorPage.visible.map((sector) => (
                    <tr key={sector.id}>
                      <td>{sector.name}</td>
                      <td>{chartPercent(currentSectorRateMap[String(sector.id)] ?? 0)}</td>
                      <td className="row-actions">
                        <button className="icon-button" type="button" onClick={() => editSector(sector)}>Modifier</button>
                        <button className="danger-button" type="button" onClick={() => removeSector(sector)}>Supprimer</button>
                      </td>
                    </tr>
                  ))}
                  {!loading && sectors.length === 0 && (
                    <tr>
                      <td colSpan="3" className="muted">Aucun secteur configure.</td>
                    </tr>
                  )}
                  {loading && (
                    <tr>
                      <td colSpan="3" className="muted">Chargement des secteurs...</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {sectorPage.pager}
          </div>
        </div>
      )}

      {activeConfigTab === "setup" && (
        <div className="panel table-panel">
          <div className="panel-header">
            <div>
              <h3>Mapping CATEGORY_DESC</h3>
              <p className="muted">Chaque libelle importe peut etre rattache a un secteur ACM.</p>
            </div>
            <span className="count-badge">{mappings.length}</span>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>CATEGORY_DESC</th>
                  <th>Occurrences MCR</th>
                  <th>Secteur d&apos;activite</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {!loading && mappingPage.visible.map((item) => (
                  <tr key={item.category_desc}>
                    <td>{item.category_desc}</td>
                    <td>{money(item.occurrence_count)}</td>
                    <td>
                      <select
                        value={mappingDrafts[item.category_desc] ?? ""}
                        onChange={(event) =>
                          setMappingDrafts((current) => ({ ...current, [item.category_desc]: event.target.value }))
                        }
                      >
                        <option value="">Aucun secteur</option>
                        {sectors.map((sector) => (
                          <option key={sector.id} value={sector.id}>{sector.name}</option>
                        ))}
                      </select>
                    </td>
                    <td className="row-actions">
                      <button className="icon-button" type="button" onClick={() => saveMapping(item)}>Enregistrer</button>
                      <button className="danger-button" type="button" disabled={!item.id} onClick={() => removeMapping(item)}>Supprimer</button>
                    </td>
                  </tr>
                ))}
                {!loading && mappings.length === 0 && (
                  <tr>
                    <td colSpan="4" className="muted">Aucune valeur CATEGORY_DESC detectee dans les MCR importes.</td>
                  </tr>
                )}
                {loading && (
                  <tr>
                    <td colSpan="4" className="muted">Chargement des mappings...</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {mappingPage.pager}
        </div>
      )}

      {activeConfigTab === "history" && (
        <div className="panel table-panel">
          <div className="panel-header">
            <div>
              <h3>Historique des taux ACM</h3>
              <p className="muted">Chaque enregistrement publie un bloc complet couvrant tous les secteurs pour une periode donnee.</p>
            </div>
            <span className="count-badge">{acmRateVersions.length}</span>
          </div>
          <div className="config-history-grid">
            <div className="panel subtle-panel">
              <h3>Creer un bloc de taux ACM</h3>
              <div className="form-grid two">
                <label>Date de debut
                  <input
                    type="date"
                    value={versionForm.effective_start_date}
                    onChange={(event) =>
                      setVersionForm((current) => ({ ...current, effective_start_date: event.target.value }))
                    }
                  />
                </label>
                <label>Mode de fin
                  <select
                    value={versionForm.end_mode}
                    onChange={(event) =>
                      setVersionForm((current) => ({
                        ...current,
                        end_mode: event.target.value,
                        effective_end_date: event.target.value === "fixed" ? current.effective_end_date : "",
                      }))
                    }
                  >
                    <option value="until_change">Jusqu&apos;a modification</option>
                    <option value="fixed">Date precise</option>
                  </select>
                </label>
                {versionForm.end_mode === "fixed" && (
                  <label>Date de fin
                    <input
                      type="date"
                      value={versionForm.effective_end_date}
                      onChange={(event) =>
                        setVersionForm((current) => ({ ...current, effective_end_date: event.target.value }))
                      }
                    />
                  </label>
                )}
                <label className={versionForm.end_mode === "fixed" ? "" : "span-two"}>
                  Commentaire
                  <textarea
                    rows={versionForm.end_mode === "fixed" ? 2 : 3}
                    value={versionForm.comment}
                    onChange={(event) =>
                      setVersionForm((current) => ({ ...current, comment: event.target.value }))
                    }
                    placeholder="Ex: grille ACM S2 2026"
                  />
                </label>
              </div>

              <div className="panel subtle-panel">
                <div className="panel-header">
                  <div>
                    <h3>Bloc complet des secteurs</h3>
                    <p className="muted">Tous les secteurs actifs doivent etre renseignes dans une seule operation.</p>
                  </div>
                  <span className="count-badge">{sectors.length}</span>
                </div>
                <div className="table-scroll compact-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Secteur</th>
                        <th>Taux ACM actuel (%)</th>
                        <th>Nouveau taux ACM (%)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {!loading && sectors.map((sector) => (
                        <tr key={sector.id}>
                          <td>{sector.name}</td>
                          <td>{chartPercent(currentSectorRateMap[String(sector.id)] ?? 0)}</td>
                          <td>
                            <input
                              type="number"
                              step="0.01"
                              min="0"
                              value={blockRates[String(sector.id)] ?? ""}
                              onChange={(event) =>
                                setBlockRates((current) => ({
                                  ...current,
                                  [String(sector.id)]: event.target.value,
                                }))
                              }
                            />
                          </td>
                        </tr>
                      ))}
                      {!loading && sectors.length === 0 && (
                        <tr>
                          <td colSpan="3" className="muted">Aucun secteur configure.</td>
                        </tr>
                      )}
                      {loading && (
                        <tr>
                          <td colSpan="3" className="muted">Chargement des secteurs...</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="config-summary-card">
                <div><strong>Nombre de secteurs :</strong> {sectors.length}</div>
                <div><strong>Taux modifies :</strong> {modifiedBlockRatesCount}</div>
                <div>
                  <strong>Periode choisie :</strong>{" "}
                  {versionForm.effective_start_date
                    ? formatAcmPeriodLabel(
                        versionForm.effective_start_date,
                        versionForm.end_mode === "fixed" ? versionForm.effective_end_date : null
                      )
                    : "A definir"}
                </div>
                <div>
                  <strong>Bloc precedent :</strong>{" "}
                  {referenceAcmVersion
                    ? formatAcmPeriodLabel(referenceAcmVersion.effective_start_date, referenceAcmVersion.effective_end_date)
                    : "Aucun"}
                </div>
              </div>

              <div className="button-row">
                <button className="primary fit" type="button" onClick={publishAcmVersion} disabled={publishingVersion}>
                  <Save size={16} />
                  {publishingVersion ? "Enregistrement..." : "Enregistrer le bloc"}
                </button>
                <button
                  className="icon-button"
                  type="button"
                  onClick={copyPreviousBlockRates}
                  disabled={publishingVersion || !referenceAcmVersion}
                >
                  Copier les taux du bloc precedent
                </button>
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => {
                    setVersionForm(emptyVersionForm);
                    setBlockRates(buildBlockRates(sectors, referenceAcmVersion));
                  }}
                  disabled={publishingVersion}
                >
                  Reinitialiser
                </button>
              </div>
            </div>
          </div>

          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Periode</th>
                  <th>Nombre de secteurs</th>
                  <th>Date de creation</th>
                  <th>Heure</th>
                  <th>Cree par</th>
                  <th>Statut</th>
                  <th>Commentaire</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {!loading && historyPage.visible.map((item) => (
                  <tr key={item.id}>
                    <td>{formatAcmPeriodLabel(item.effective_start_date, item.is_open_ended ? null : item.effective_end_date)}</td>
                    <td>{money(item.sector_count)}</td>
                    <td>{formatDateLabel(item.created_at)}</td>
                    <td>{formatTimeLabel(item.created_at)}</td>
                    <td>{item.created_by_name || "Systeme"}</td>
                    <td>
                      <span className={`status-pill ${item.status === "actif" ? "success" : "neutral"}`}>
                        {item.status === "actif" ? "Actif" : "Historique"}
                      </span>
                    </td>
                    <td>{item.comment || "-"}</td>
                    <td className="row-actions">
                      <button className="icon-button" type="button" onClick={() => openAcmVersion(item.id)}>
                        Consulter
                      </button>
                      <button className="icon-button" type="button" onClick={() => openEditAcmVersion(item.id)}>
                        Modifier
                      </button>
                    </td>
                  </tr>
                ))}
                {!loading && acmRateVersions.length === 0 && (
                  <tr>
                    <td colSpan="8" className="muted">Aucun bloc ACM enregistre pour le moment.</td>
                  </tr>
                )}
                {loading && (
                  <tr>
                    <td colSpan="8" className="muted">Chargement de l&apos;historique ACM...</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {historyPage.pager}
        </div>
      )}

      {activeConfigTab === "par_limits" && (
        <div className="panel table-panel">
          <div className="panel-header">
            <div>
              <h3>Configuration des Limites PAR</h3>
              <p className="muted">Renseignez les seuils de reference en pourcentage.</p>
            </div>
          </div>
          <div className="panel subtle-panel">
            <div className="form-grid two acm-form-grid">
              <label>PAR0
                <input
                  type="number"
                  step="0.01"
                  value={acmForm.par_0_limit}
                  onChange={(e) => setAcmForm((current) => ({ ...current, par_0_limit: e.target.value }))}
                />
              </label>
              <label>PAR30
                <input
                  type="number"
                  step="0.01"
                  value={acmForm.par_30_limit}
                  onChange={(e) => setAcmForm((current) => ({ ...current, par_30_limit: e.target.value }))}
                />
              </label>
              <label>PAR120
                <input
                  type="number"
                  step="0.01"
                  value={acmForm.par_120_limit}
                  onChange={(e) => setAcmForm((current) => ({ ...current, par_120_limit: e.target.value }))}
                />
              </label>
              <label>Cohorte 1-30
                <input
                  type="number"
                  step="0.01"
                  value={acmForm.cohort_1_30_limit}
                  onChange={(e) => setAcmForm((current) => ({ ...current, cohort_1_30_limit: e.target.value }))}
                />
              </label>
              <label>Cohorte 31-60
                <input
                  type="number"
                  step="0.01"
                  value={acmForm.cohort_31_60_limit}
                  onChange={(e) => setAcmForm((current) => ({ ...current, cohort_31_60_limit: e.target.value }))}
                />
              </label>
              <label>Cohorte 61-90
                <input
                  type="number"
                  step="0.01"
                  value={acmForm.cohort_61_90_limit}
                  onChange={(e) => setAcmForm((current) => ({ ...current, cohort_61_90_limit: e.target.value }))}
                />
              </label>
              <label>Cohorte 91-120
                <input
                  type="number"
                  step="0.01"
                  value={acmForm.cohort_91_120_limit}
                  onChange={(e) => setAcmForm((current) => ({ ...current, cohort_91_120_limit: e.target.value }))}
                />
              </label>
            </div>
            <div className="button-row">
              <button className="primary fit" type="button" onClick={saveAcmLimits} disabled={acmSaving}>
                <Save size={16} />
                {acmSaving ? "Enregistrement..." : "Enregistrer"}
              </button>
            </div>
          </div>
        </div>
      )}

      {selectedAcmVersion && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="acm-version-title">
          <div className="modal-card modal-card-xl acm-version-modal">
            <div className="modal-title modal-title-neutral acm-version-modal-header">
              <div>
                <h3 id="acm-version-title">Bloc ACM - {formatAcmPeriodLabel(selectedAcmVersion.effective_start_date, selectedAcmVersion.is_open_ended ? null : selectedAcmVersion.effective_end_date)}</h3>
                {selectedAcmVersion.comment && <p className="muted">{selectedAcmVersion.comment}</p>}
              </div>
              <button className="icon-button" type="button" onClick={() => setSelectedAcmVersion(null)}>
                <X size={16} />
              </button>
            </div>
            {versionLoading ? (
              <p className="muted">Chargement du bloc ACM...</p>
            ) : (
              <div className="acm-version-modal-body">
                <div className="acm-version-summary-grid">
                  <div className="acm-version-summary-card">
                    <strong>Periode</strong>
                    <span>{formatAcmPeriodLabel(selectedAcmVersion.effective_start_date, selectedAcmVersion.is_open_ended ? null : selectedAcmVersion.effective_end_date)}</span>
                  </div>
                  <div className="acm-version-summary-card">
                    <strong>Date de creation</strong>
                    <span>{formatDateLabel(selectedAcmVersion.created_at)}</span>
                  </div>
                  <div className="acm-version-summary-card">
                    <strong>Heure</strong>
                    <span>{formatTimeLabel(selectedAcmVersion.created_at) || "-"}</span>
                  </div>
                  <div className="acm-version-summary-card">
                    <strong>Cree par</strong>
                    <span>{selectedAcmVersion.created_by_name || "Systeme"}</span>
                  </div>
                  <div className="acm-version-summary-card">
                    <strong>Statut</strong>
                    <span>{selectedAcmVersion.status === "actif" ? "Actif" : "Historique"}</span>
                  </div>
                  <div className="acm-version-summary-card">
                    <strong>Nombre de secteurs</strong>
                    <span>{money((selectedAcmVersion.details || []).length)}</span>
                  </div>
                </div>
                <div className="table-scroll acm-version-table-wrap">
                  <table className="acm-version-table">
                    <thead>
                      <tr>
                        <th>Secteur d'activite</th>
                        <th>Taux ACM (%)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(selectedAcmVersion.details || []).map((detail) => (
                        <tr key={detail.id}>
                          <td>{detail.sector_name}</td>
                          <td><span className="table-number-cell">{Number(detail.acm_rate || 0).toFixed(2)}%</span></td>
                        </tr>
                      ))}
                      {(selectedAcmVersion.details || []).length === 0 && (
                        <tr>
                          <td colSpan="2" className="muted">Aucun secteur enregistre pour ce bloc.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
                {(selectedAcmVersion.audit_entries || []).length > 0 && (
                  <div className="panel subtle-panel">
                    <div className="panel-header">
                      <h3>Historique des modifications</h3>
                      <span className="count-badge">{selectedAcmVersion.audit_entries.length}</span>
                    </div>
                    <div className="table-scroll acm-version-table-wrap">
                      <table className="acm-version-table">
                        <thead>
                          <tr>
                            <th>Date</th>
                            <th>Heure</th>
                            <th>Modifie par</th>
                            <th>Commentaire</th>
                            <th>Ancienne periode</th>
                            <th>Nouvelle periode</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(selectedAcmVersion.audit_entries || []).map((entry) => (
                            <tr key={entry.id}>
                              <td>{formatDateLabel(entry.modified_at)}</td>
                              <td>{formatTimeLabel(entry.modified_at) || "-"}</td>
                              <td>{entry.modified_by_name || "Systeme"}</td>
                              <td>{entry.comment}</td>
                              <td>{formatAcmPeriodLabel(entry.previous_start_date, entry.previous_is_open_ended ? null : entry.previous_end_date)}</td>
                              <td>{formatAcmPeriodLabel(entry.new_start_date, entry.new_is_open_ended ? null : entry.new_end_date)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
                <div className="button-row button-row-end">
                  <button className="icon-button" type="button" onClick={() => setSelectedAcmVersion(null)}>
                    Fermer
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {editingAcmVersion && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="acm-edit-title">
          <div className="modal-card modal-card-xl acm-version-modal">
            <div className="modal-title modal-title-neutral acm-version-modal-header">
              <div>
                <h3 id="acm-edit-title">Modifier le bloc ACM</h3>
                <p className="muted">
                  Periode actuelle : {formatAcmPeriodLabel(
                    editingAcmVersion.effective_start_date,
                    editingAcmVersion.is_open_ended ? null : editingAcmVersion.effective_end_date,
                  )}
                </p>
              </div>
              <button className="icon-button" type="button" onClick={() => setEditingAcmVersion(null)}>
                <X size={16} />
              </button>
            </div>
            <div className="acm-version-modal-body">
              {editingAcmVersion.may_affect_existing_results && (
                <div className="form-error acm-edit-warning">
                  Cette modification peut changer les resultats TAEG des periodes couvertes par ce bloc.
                </div>
              )}
              <div className="acm-version-summary-grid">
                <div className="acm-version-summary-card">
                  <strong>Periode actuelle</strong>
                  <span>{formatAcmPeriodLabel(editingAcmVersion.effective_start_date, editingAcmVersion.is_open_ended ? null : editingAcmVersion.effective_end_date)}</span>
                </div>
                <div className="acm-version-summary-card">
                  <strong>Snapshots impactes</strong>
                  <span>{money(editingAcmVersion.affected_snapshot_count || 0)}</span>
                </div>
                <div className="acm-version-summary-card">
                  <strong>Statut</strong>
                  <span>{editingAcmVersion.status === "actif" ? "Actif" : "Historique"}</span>
                </div>
                <div className="acm-version-summary-card">
                  <strong>Cree par</strong>
                  <span>{editingAcmVersion.created_by_name || "Systeme"}</span>
                </div>
              </div>

              <div className="form-grid two">
                <label>Date de debut
                  <input
                    type="date"
                    value={editingVersionForm.effective_start_date}
                    onChange={(event) =>
                      setEditingVersionForm((current) => ({ ...current, effective_start_date: event.target.value }))
                    }
                  />
                </label>
                <label>Mode de fin
                  <select
                    value={editingVersionForm.end_mode}
                    onChange={(event) =>
                      setEditingVersionForm((current) => ({
                        ...current,
                        end_mode: event.target.value,
                        effective_end_date: event.target.value === "fixed" ? current.effective_end_date : "",
                      }))
                    }
                  >
                    <option value="until_change">Jusqu&apos;a modification</option>
                    <option value="fixed">Date precise</option>
                  </select>
                </label>
                {editingVersionForm.end_mode === "fixed" && (
                  <label>Date de fin
                    <input
                      type="date"
                      value={editingVersionForm.effective_end_date}
                      onChange={(event) =>
                        setEditingVersionForm((current) => ({ ...current, effective_end_date: event.target.value }))
                      }
                    />
                  </label>
                )}
                <label className={editingVersionForm.end_mode === "fixed" ? "" : "span-two"}>
                  Commentaire du bloc
                  <textarea
                    rows={editingVersionForm.end_mode === "fixed" ? 2 : 3}
                    value={editingVersionForm.comment}
                    onChange={(event) =>
                      setEditingVersionForm((current) => ({ ...current, comment: event.target.value }))
                    }
                  />
                </label>
                <label className="span-two">
                  Commentaire de modification
                  <textarea
                    rows={3}
                    value={editingVersionForm.modification_comment}
                    onChange={(event) =>
                      setEditingVersionForm((current) => ({ ...current, modification_comment: event.target.value }))
                    }
                    placeholder="Expliquez precisement la raison de la modification."
                  />
                </label>
              </div>

              <div className="panel subtle-panel">
                <div className="panel-header">
                  <div>
                    <h3>Taux ACM par secteur</h3>
                    <p className="muted">Tous les secteurs actifs doivent etre valides dans la meme modification.</p>
                  </div>
                  <span className="count-badge">{sectors.length}</span>
                </div>
                <div className="table-scroll compact-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Secteur</th>
                        <th>Taux actuel (%)</th>
                        <th>Nouveau taux (%)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sectors.map((sector) => (
                        <tr key={`edit-${sector.id}`}>
                          <td>{sector.name}</td>
                          <td>{chartPercent(editingReferenceRateMap[String(sector.id)] ?? 0)}</td>
                          <td>
                            <input
                              type="number"
                              step="0.01"
                              min="0"
                              value={editingBlockRates[String(sector.id)] ?? ""}
                              onChange={(event) =>
                                setEditingBlockRates((current) => ({
                                  ...current,
                                  [String(sector.id)]: event.target.value,
                                }))
                              }
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="config-summary-card">
                <div><strong>Nombre de secteurs :</strong> {sectors.length}</div>
                <div><strong>Taux modifies :</strong> {modifiedEditingBlockRatesCount}</div>
                <div>
                  <strong>Nouvelle periode :</strong>{" "}
                  {editingVersionForm.effective_start_date
                    ? formatAcmPeriodLabel(
                      editingVersionForm.effective_start_date,
                      editingVersionForm.end_mode === "fixed" ? editingVersionForm.effective_end_date : null,
                    )
                    : "A definir"}
                </div>
                <div><strong>Snapshots potentiellement impactes :</strong> {money(editingAcmVersion.affected_snapshot_count || 0)}</div>
              </div>

              <div className="button-row button-row-end">
                <button className="primary fit" type="button" onClick={saveEditedAcmVersion} disabled={savingVersionUpdate}>
                  <Save size={16} />
                  {savingVersionUpdate ? "Enregistrement..." : "Enregistrer les modifications"}
                </button>
                <button className="icon-button" type="button" onClick={() => setEditingAcmVersion(null)} disabled={savingVersionUpdate}>
                  Annuler
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function Metric({ label, value, sub, count, clientCount, tone, tooltip, onClick, interactive = false }) {
  const className = `metric ${tone || ""} ${interactive ? "metric-clickable" : ""}`.trim();
  const countLabel =
    count !== undefined && count !== null && clientCount !== undefined && clientCount !== null
      ? `${count} dossier${count === 1 ? "" : "s"} · ${clientCount} client${clientCount === 1 ? "" : "s"}`
      : count !== undefined && count !== null
        ? `${count} dossier${count === 1 ? "" : "s"}`
        : clientCount !== undefined && clientCount !== null
          ? `${clientCount} client${clientCount === 1 ? "" : "s"}`
          : null;
  if (onClick) {
    return (
      <button type="button" className={className} title={tooltip} onClick={onClick}>
        <span>{label}</span>
        <strong>{value}</strong>
        {sub && <small>{sub}</small>}
        {countLabel && <small>{countLabel}</small>}
      </button>
    );
  }
  return (
    <div className={className} title={tooltip}>
      <span>{label}</span>
      <strong>{value}</strong>
      {sub && <small>{sub}</small>}
      {countLabel && <small>{countLabel}</small>}
    </div>
  );
}

function findAcmSegmentForSnapshotDate(acmSegments, snapshotDate) {
  const dateKey = String(snapshotDate || "");
  if (!dateKey) return null;
  return (acmSegments || []).find((segment) => {
    const rangeStart = String(segment?.range_start || "");
    const rangeEnd = String(segment?.range_end || "");
    return rangeStart && rangeEnd && rangeStart <= dateKey && dateKey <= rangeEnd;
  }) || null;
}

function buildMonthlyHistoryDayDetails(row, acmSegments = []) {
  if (!row) return null;
  const acmSegment = findAcmSegmentForSnapshotDate(acmSegments, row.snapshotDate);
  const details = sortBySectorOrder(
    Object.values(row.pointDetails || {}),
    (item) => item.sectorName,
  )
    .map((detail) => ({
      dateLabel: formatDateLabel(detail.snapshotDate),
      blockLabel: acmSegment?.block_label || "Bloc ACM non resolu",
      blockPeriodLabel: acmSegment?.range_start && acmSegment?.range_end
        ? `${formatDateLabel(acmSegment.range_start)} -> ${formatDateLabel(acmSegment.range_end)}`
        : "-",
      sectorName: detail.sectorName || "-",
      status: detail.status || "non_couvert",
      taegCalculated: Number(detail.taegCalculated || 0),
      taegWeightedRate: Number(detail.taegWeightedRate || 0),
      acmRate: detail.acmRate === null || detail.acmRate === undefined ? null : Number(detail.acmRate),
      creditsCount: Number(detail.creditsCount || 0),
      disbursementAmount: Number(detail.disbursementAmount || 0),
    }));

  const compliantCount = details.filter((detail) => detail.status === "conforme").length;
  const nonCompliantCount = details.filter((detail) => detail.status === "non_conforme").length;
  const uncoveredCount = details.filter((detail) => detail.status === "non_couvert").length;
  const creditsCount = details.reduce((sum, detail) => sum + Number(detail.creditsCount || 0), 0);
  const disbursementAmount = details.reduce((sum, detail) => sum + Number(detail.disbursementAmount || 0), 0);
  const taegCalculated = details.reduce((sum, detail) => sum + Number(detail.taegCalculated || 0), 0);
  const acmWeightedNumerator = details.reduce(
    (sum, detail) => sum + ((detail.acmRate === null || detail.acmRate === undefined) ? 0 : Number(detail.acmRate || 0) * Number(detail.disbursementAmount || 0)),
    0,
  );
  const coveredDisbursementAmount = details.reduce(
    (sum, detail) => sum + ((detail.acmRate === null || detail.acmRate === undefined) ? 0 : Number(detail.disbursementAmount || 0)),
    0,
  );

  return {
    dayKey: String(row.snapshotDate || ""),
    dayLabel: row.dayLabel || "",
    dateLabel: formatDateLabel(row.snapshotDate),
    acmSegment,
    sectorsCount: details.length,
    compliantCount,
    nonCompliantCount,
    uncoveredCount,
    creditsCount,
    disbursementAmount,
    taegAverage: disbursementAmount > 0 ? taegCalculated / disbursementAmount : null,
    acmAverage: coveredDisbursementAmount > 0 ? acmWeightedNumerator / coveredDisbursementAmount : null,
    rows: details,
  };
}

function MonthlyHistoryXAxisTick({
  x,
  y,
  payload,
  active = false,
  onSelect,
}) {
  const label = String(payload?.value || "");
  return (
    <g
      transform={`translate(${x},${y})`}
      className={`monthly-history-axis-tick ${active ? "active" : ""}`}
      onClick={() => onSelect?.(label)}
    >
      <text
        x={0}
        y={0}
        dy={16}
        textAnchor="middle"
        fill={active ? "#0f172a" : "#52617a"}
        fontWeight={active ? 700 : 500}
        style={{ cursor: "pointer", userSelect: "none" }}
      >
        {label}
      </text>
    </g>
  );
}

function MonthlyHistoryDot({
  cx,
  cy,
  stroke,
  payload,
  selectedDayKey,
  onSelect,
}) {
  if (!Number.isFinite(cx) || !Number.isFinite(cy)) return null;
  const dayKey = String(payload?.snapshotDate || "");
  const isSelected = dayKey && dayKey === selectedDayKey;
  return (
    <g
      className={`monthly-history-dot ${isSelected ? "selected" : ""}`}
      onClick={() => onSelect?.(payload)}
      style={{ cursor: "pointer" }}
    >
      <circle cx={cx} cy={cy} r={10} fill="transparent" />
      <circle
        cx={cx}
        cy={cy}
        r={isSelected ? 5 : 3}
        fill="#ffffff"
        stroke={stroke || "#2563eb"}
        strokeWidth={isSelected ? 3 : 2}
      />
    </g>
  );
}


function AcmBenchmarkCard({ acmLimits }) {
  if (!acmLimits?.configured) {
    return <div className="acm-benchmark-card empty">Aucune Limites PAR configuree</div>;
  }

  const items = [
    ["PAR0", acmLimits.par_0_limit],
    ["PAR30", acmLimits.par_30_limit],
    ["PAR120", acmLimits.par_120_limit],
    ["Cohorte 1-30", acmLimits.cohort_1_30_limit],
    ["Cohorte 31-60", acmLimits.cohort_31_60_limit],
    ["Cohorte 61-90", acmLimits.cohort_61_90_limit],
    ["Cohorte 91-120", acmLimits.cohort_91_120_limit],
  ];

  return (
    <div className="acm-benchmark-card">
      <div className="acm-benchmark-header">
        <strong>Limites PAR</strong>
        <span>Reference dynamique</span>
      </div>
      <div className="acm-benchmark-grid">
        {items.map(([label, value]) => (
          <div key={label} className="acm-benchmark-item">
            <span>{label}</span>
            <b>{value === null || value === undefined ? "-" : chartPercent(value)}</b>
          </div>
        ))}
      </div>
    </div>
  );
}

function QualityPortfolioTooltip({ active, payload, label, coordinate, containerRef }) {
  if (!active || !payload?.length) return null;
  const data = payload[0]?.payload || {};
  const par0 = Number(data.par0Rate || 0);
  const par30 = Number(data.par30Rate || 0);
  const par120 = Number(data.par120Rate || 0);
  const cohortRows = [
    ["Cohorte 1-15%", data.par1_15Rate],
    ["Cohorte 16-30%", data.par16_30Rate],
    ["Cohorte 31-60%", data.par31_60Rate],
    ["Cohorte 61-90%", data.par61_90Rate],
    ["Cohorte 91-120%", data.par91_120Rate],
  ];

  return (
    <ResponsiveChartTooltip active={active} coordinate={coordinate} containerRef={containerRef}>
      <strong>{label}</strong>
      <div className="tooltip-row">
        <span>PAR0%</span>
        <b>{chartPercent(par0)}</b>
      </div>
      <div className="tooltip-row">
        <span>PAR30%</span>
        <b>{chartPercent(par30)}</b>
      </div>
      <div className="tooltip-row">
        <span>PAR120%</span>
        <b>{chartPercent(par120)}</b>
      </div>
      <div className="tooltip-divider" />
      {cohortRows.map(([rowLabel, rowValue]) => (
        <div className="tooltip-row" key={rowLabel}>
          <span>{rowLabel}</span>
          <b>{chartPercent(rowValue)}</b>
        </div>
      ))}
    </ResponsiveChartTooltip>
  );
}

function VolumeDisbursementTooltip({ active, payload, label, coordinate, containerRef }) {
  if (!active || !payload?.length) return null;
  const data = payload[0]?.payload || {};
  const rows = VOLUME_STACK_SERIES
    .map((serie) => ({
      label: serie.label,
      volume: Number(data[serie.key] || 0),
      count: Number(data[serie.countKey] || 0),
      color: serie.color,
    }))
    .filter((item) => item.volume > 0 || item.count > 0);

  return (
    <ResponsiveChartTooltip active={active} coordinate={coordinate} containerRef={containerRef}>
      <strong>{label}</strong>
      <div className="tooltip-row">
        <span>Volume total</span>
        <b>{money(data.disbursement)}</b>
      </div>
      <div className="tooltip-row">
        <span>Nb decaissements total</span>
        <b>{money(data.disbursementCount)}</b>
      </div>
      <div className="tooltip-divider" />
      {rows.map((row) => (
        <div className="tooltip-series" key={row.label}>
          <div className="tooltip-series-title">
            <span className="tooltip-dot" style={{ backgroundColor: row.color }} />
            <strong>{row.label}</strong>
          </div>
          <div className="tooltip-row">
            <span>Volume decaisse</span>
            <b>{money(row.volume)}</b>
          </div>
          <div className="tooltip-row">
            <span>Nb decaissements</span>
            <b>{money(row.count)}</b>
          </div>
        </div>
      ))}
    </ResponsiveChartTooltip>
  );
}

function TaegChartTooltip({ active, payload, label, coordinate, containerRef }) {
  if (!active || !payload?.length) return null;
  const data = payload[0]?.payload || {};
  const statusMeta = taegStatusMeta(data.status);

  return (
    <ResponsiveChartTooltip active={active} coordinate={coordinate} containerRef={containerRef}>
      <strong>{label}</strong>
      <div className="tooltip-row">
        <span>Secteur</span>
        <b>{data.sectorName || "-"}</b>
      </div>
      <div className="tooltip-row">
        <span>TAEG pondere</span>
        <b>{chartPercent(data.taegWeightedRate)}</b>
      </div>
      <div className="tooltip-row">
        <span>Taux ACM</span>
        <b>{chartPercentNullable(data.acmRate)}</b>
      </div>
      <div className="tooltip-row">
        <span>Statut</span>
        <b>{statusMeta.label}</b>
      </div>
      <div className="tooltip-divider" />
      <div className="tooltip-row">
        <span>Montant decaisse</span>
        <b>{money(data.disbursementAmount)}</b>
      </div>
      <div className="tooltip-row">
        <span>Nb credits</span>
        <b>{money(data.creditsCount)}</b>
      </div>
      <div className="tooltip-row">
        <span>Credits conformes</span>
        <b>{money(data.compliantCreditsCount)}</b>
      </div>
      <div className="tooltip-row">
        <span>Credits non conformes</span>
        <b>{money(data.nonCompliantCreditsCount)}</b>
      </div>
      <div className="tooltip-row">
        <span>Credits non couverts</span>
        <b>{money(data.uncoveredCreditsCount)}</b>
      </div>
    </ResponsiveChartTooltip>
  );
}

function TaegMonthlyHistoryTooltip({ active, payload, label, coordinate, containerRef }) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload || null;
  const dateLabel = formatDateLabel(row?.snapshotDate) || label;
  return (
    <ResponsiveChartTooltip active={active} coordinate={coordinate} containerRef={containerRef} className="chart-tooltip-compact">
      <strong>{dateLabel}</strong>
    </ResponsiveChartTooltip>
  );
}

function App() {
  const [loggedIn, setLoggedIn] = useState(false);

  useEffect(() => {
    if (FORCE_LOGIN_ON_START) return;
    api.me().then(() => setLoggedIn(true)).catch(() => setLoggedIn(false));
  }, []);

  return loggedIn ? <Dashboard /> : <Login onLogin={() => setLoggedIn(true)} />;
}

createRoot(document.getElementById("root")).render(
  <AppErrorBoundary>
    <App />
  </AppErrorBoundary>,
);
