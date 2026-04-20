import { createStore } from "/js/AlpineStore.js";
import * as API from "/js/api.js";

const API_BASE = "/plugins/_slack_integration";

function ensureConfig(config) {
  if (!config || typeof config !== "object") return;
  if (!Array.isArray(config.handlers)) config.handlers = [];
}

function ensureHandler(handler) {
  if (!handler) return;
  if (typeof handler.enabled !== "boolean") handler.enabled = false;
  if (typeof handler.listen_dm !== "boolean") handler.listen_dm = true;
  if (typeof handler.listen_channels !== "boolean") handler.listen_channels = true;
  if (typeof handler.use_thinking_reaction !== "boolean") handler.use_thinking_reaction = true;
  if (!handler.thinking_emoji) handler.thinking_emoji = "thinking_face";
  if (!handler.markdown_mode) handler.markdown_mode = "mrkdwn";
  if (!Array.isArray(handler.allowed_channels)) handler.allowed_channels = [];
  if (!Array.isArray(handler.allowed_users)) handler.allowed_users = [];
  if (!Array.isArray(handler.denied_users)) handler.denied_users = [];
  if (typeof handler.max_upload_size_mb !== "number") handler.max_upload_size_mb = 25;
  if (!("project" in handler)) handler.project = "";
  if (!("chat_model_preset" in handler)) handler.chat_model_preset = "";
  if (!("agent_instructions" in handler)) handler.agent_instructions = "";
}

export const store = createStore("slackConfig", {
  config: null,
  context: null,
  editing: null,
  testing: null,
  testResults: null,
  testResultsFor: null,
  didInit: false,
  projects: [],
  modelPresets: [],

  get handlers() {
    ensureConfig(this.config);
    return Array.isArray(this.config?.handlers) ? this.config.handlers : [];
  },

  async init(config, context = null) {
    this.config = config || null;
    this.context = context;
    this.didInit = false;
    ensureConfig(this.config);
    this.handlers.forEach(ensureHandler);
    this.editing = this.handlers.length === 1 ? 0 : null;
    this.testing = null;
    this.testResults = null;
    this.testResultsFor = null;
    if (this.handlers.length === 0) this._startInitialHandlerFlow();
    this.didInit = true;

    const [projectsResult, presetsResult] = await Promise.allSettled([
      API.callJsonApi("projects", { action: "list" }),
      API.callJsonApi("/plugins/_model_config/model_presets", { action: "get" }),
    ]);

    this.projects = projectsResult.status === "fulfilled" ? (projectsResult.value.data || []) : [];
    this.modelPresets = presetsResult.status === "fulfilled" && Array.isArray(presetsResult.value.presets)
      ? presetsResult.value.presets
      : [];
  },

  cleanup() {
    this.config = null;
    this.context = null;
    this.editing = null;
    this.testing = null;
    this.testResults = null;
    this.testResultsFor = null;
    this.didInit = false;
  },

  newHandler() {
    return {
      name: "",
      enabled: false,
      bot_token: "",
      app_token: "",
      team_id: "",
      bot_user_id: "",
      listen_dm: true,
      listen_channels: true,
      allowed_channels: [],
      allowed_users: [],
      denied_users: [],
      use_thinking_reaction: true,
      thinking_emoji: "thinking_face",
      markdown_mode: "mrkdwn",
      project: "",
      chat_model_preset: "",
      agent_instructions: "",
      max_upload_size_mb: 25,
    };
  },

  addHandler() {
    ensureConfig(this.config);
    const handler = this.newHandler();
    this.config.handlers.push(handler);
    this.editing = this.config.handlers.length - 1;
    this.testResults = null;
    this.testResultsFor = null;
  },

  removeHandler(idx) {
    this.handlers.splice(idx, 1);
    if (this.editing === idx) this.editing = null;
    if (this.editing !== null && this.editing > idx) this.editing -= 1;
    if (this.testResultsFor === idx) {
      this.testResults = null;
      this.testResultsFor = null;
    }
  },

  toggleEditing(idx) {
    this.editing = this.editing === idx ? null : idx;
    if (this.testResultsFor !== idx) {
      this.testResults = null;
      this.testResultsFor = null;
    }
  },

  slugify(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
  },

  maybeAutoname(handler) {
    const current = String(handler.name || "").trim();
    if (current && !/^handler_\d+$/.test(current)) return;
    const token = String(handler.bot_token || "");
    const tail = token.split("-").slice(-1)[0] || "";
    const nextName = this.slugify(tail) || `workspace_${this.handlers.length}`;
    handler.name = nextName;
  },

  missingBits(handler) {
    const missing = [];
    if (!handler.name) missing.push("handler name");
    if (!handler.bot_token) missing.push("bot token");
    if (!handler.app_token) missing.push("app-level token");
    return missing;
  },

  canTest(handler) {
    return this.missingBits(handler).length === 0;
  },

  statusLabel(handler) {
    if (!handler.bot_token && !handler.app_token) return "New";
    if (handler.enabled && this.canTest(handler)) return "Live";
    if (this.canTest(handler)) return "Ready";
    return "Needs info";
  },

  statusTone(handler) {
    const label = this.statusLabel(handler);
    if (label === "Live") return "success";
    if (label === "Ready") return "ready";
    if (label === "New") return "muted";
    return "warning";
  },

  handlerTitle(handler, idx) {
    return handler.name || handler.team_id || `Workspace ${idx + 1}`;
  },

  handlerSubtitle(handler) {
    const pieces = [];
    if (handler.listen_dm) pieces.push("DMs");
    if (handler.listen_channels) pieces.push("Channels");
    if (handler.project) pieces.push(`Project: ${handler.project}`);
    return pieces.join(" · ") || "No listeners enabled";
  },

  testButtonLabel(handler, idx) {
    if (this.testing === idx) return "Checking...";
    if (this.canTest(handler)) return "Check connection";
    return "Add tokens first";
  },

  testIntro() {
    return "We will verify auth.test, the required OAuth scopes, and open a short Socket Mode handshake.";
  },

  resultTitle(result) {
    return result.test || "Check";
  },

  resultMessage(result) {
    return result.message || (result.ok ? "Done." : "Something went wrong.");
  },

  commaList(values) {
    return (values || []).join(", ");
  },

  setCommaList(handler, field, value) {
    handler[field] = String(value || "")
      .split(",")
      .map((item) => item.trim())
      .filter((item) => item);
  },

  _startInitialHandlerFlow() {
    this.addHandler();
    if (!this.context) return;
    const toComparableJson = typeof this.context._toComparableJson === "function"
      ? this.context._toComparableJson.bind(this.context)
      : JSON.stringify;
    this.context.settingsSnapshotJson = toComparableJson(this.context.settings);
  },

  async testConnection(idx) {
    const handler = this.handlers[idx];
    if (!handler || !this.canTest(handler)) return;

    this.testing = idx;
    this.testResults = null;
    this.testResultsFor = idx;

    try {
      this.testResults = await API.callJsonApi(`${API_BASE}/test_connection`, { handler });
    } catch (error) {
      this.testResults = {
        success: false,
        results: [{ test: "Connection", ok: false, message: String(error) }],
      };
    }

    this.testing = null;
  },
});
