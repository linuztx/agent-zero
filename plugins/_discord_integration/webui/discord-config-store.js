import { createStore } from "/js/AlpineStore.js";
import * as API from "/js/api.js";

const API_BASE = "/plugins/_discord_integration";
const DEFAULT_INVITE_PERMS = "274878024704";
const STEPS = [
  {
    title: "Connect your bot",
    description: "Create a Discord application, paste the bot token here, and enable the required privileged intents.",
  },
  {
    title: "Choose who can use it",
    description: "Finish the core setup, decide which users and servers can reach the bot.",
  },
  {
    title: "Shape the conversation",
    description: "Choose how the bot behaves in servers and how the agent should reply.",
  },
];

function ensureConfig(config) {
  if (!config || typeof config !== "object") return;
  if (!Array.isArray(config.bots)) config.bots = [];
}

export const store = createStore("discordConfig", {
  config: null,
  projects: [],
  editing: null,
  testing: null,
  testResults: null,
  testResultsFor: null,
  botSteps: [],
  didInit: false,
  steps: STEPS,
  _projectsLoaded: false,
  context: null,

  get bots() {
    ensureConfig(this.config);
    return Array.isArray(this.config?.bots) ? this.config.bots : [];
  },

  get activeIndex() {
    return typeof this.editing === "number" ? this.editing : -1;
  },

  get activeBot() {
    return this.activeIndex >= 0 ? this.bots[this.activeIndex] || null : null;
  },

  get showFooterNav() {
    return this.activeIndex >= 0;
  },

  get currentStep() {
    return this.activeIndex >= 0 && typeof this.botSteps[this.activeIndex] === "number"
      ? this.botSteps[this.activeIndex]
      : 0;
  },

  get isFirstStep() {
    return this.currentStep === 0;
  },

  get isLastStep() {
    return this.currentStep >= this.steps.length - 1;
  },

  get nextDisabled() {
    return !!this.stepBlockedReason();
  },

  get nextButtonLabel() {
    return this.isLastStep ? "Done" : "Next";
  },

  get footerStepLabel() {
    return `Step ${this.currentStep + 1} of ${this.steps.length}`;
  },

  async init(config, context = null) {
    this.config = config || null;
    this.context = context;
    this.didInit = false;
    ensureConfig(this.config);
    this.editing = this.bots.length === 1 ? 0 : null;
    this.testing = null;
    this.testResults = null;
    this.testResultsFor = null;
    this.botSteps = this.bots.map((bot) => this.initialStepForBot(bot));
    if (this.bots.length === 0) this._startInitialBotFlow();
    this._installWizardFooter();
    this.didInit = true;

    if (this._projectsLoaded) return;
    try {
      const response = await API.callJsonApi("projects", { action: "list" });
      this.projects = response.data || [];
    } catch (_) {
      this.projects = [];
    }
    this._projectsLoaded = true;
  },

  cleanup() {
    if (this.context?.wizardFooter?.owner === "discordConfig") {
      this.context.wizardFooter = null;
    }
    this.config = null;
    this.context = null;
    this.editing = null;
    this.testing = null;
    this.testResults = null;
    this.testResultsFor = null;
    this.botSteps = [];
    this.didInit = false;
  },

  defaultBot() {
    return {
      name: "",
      enabled: false,
      notify_messages: false,
      token: "",
      client_id: "",
      allowed_users: [],
      allowed_guilds: [],
      server_mode: "mention",
      welcome_enabled: false,
      welcome_message: "",
      user_projects: {},
      default_project: "",
      agent_instructions: "",
      attachment_max_age_hours: 0,
    };
  },

  addBot() {
    ensureConfig(this.config);
    this.config.bots.push(this.defaultBot());
    this.botSteps.push(0);
    this.editing = this.config.bots.length - 1;
    this.testResults = null;
    this.testResultsFor = null;
  },

  removeBot(idx) {
    this.bots.splice(idx, 1);
    this.botSteps.splice(idx, 1);
    if (this.editing === idx) this.editing = null;
    if (this.editing !== null && this.editing > idx) this.editing -= 1;
    if (this.testResultsFor === idx) {
      this.testResults = null;
      this.testResultsFor = null;
    }
  },

  toggleEditing(idx) {
    this.editing = this.editing === idx ? null : idx;
    if (this.editing !== null && typeof this.botSteps[this.editing] !== "number") {
      this.botSteps[this.editing] = this.initialStepForBot(this.bots[this.editing]);
    }
    if (this.testResultsFor !== idx) {
      this.testResults = null;
      this.testResultsFor = null;
    }
  },

  currentStepMeta() {
    return this.steps[this.currentStep] || this.steps[0];
  },

  setStep(step) {
    if (this.activeIndex < 0) return;
    const next = Math.max(0, Math.min(this.steps.length - 1, Number(step) || 0));
    this.botSteps[this.activeIndex] = next;
  },

  previousStep() {
    if (this.isFirstStep) return;
    this.setStep(this.currentStep - 1);
  },

  nextStep() {
    if (this.stepBlockedReason()) return;
    if (this.isLastStep) {
      this.editing = null;
      return;
    }
    this.setStep(this.currentStep + 1);
  },

  stepBlockedReason() {
    const bot = this.activeBot;
    if (!bot) return "";
    if (this.currentStep === 0 && !String(bot.token || "").trim()) {
      return "Add your bot token first.";
    }
    return "";
  },

  canTest(bot) {
    if (!bot) return false;
    return !!String(bot.token || "").trim();
  },

  botStatusLabel(bot) {
    if (!String(bot?.token || "").trim()) return "New";
    if (bot?.enabled && this.canTest(bot)) return "Live";
    if (this.canTest(bot)) return "Ready";
    return "Needs info";
  },

  botStatusTone(bot) {
    const label = this.botStatusLabel(bot);
    if (label === "Live") return "success";
    if (label === "Ready") return "ready";
    if (label === "New") return "muted";
    return "warning";
  },

  botTitle(bot, idx) {
    return String(bot?.name || "").trim() || `Bot ${idx + 1}`;
  },

  botSubtitle(bot) {
    const pieces = [];
    const mode = bot.server_mode || "mention";
    if (mode === "off") pieces.push("DMs only");
    else if (mode === "all") pieces.push("All server messages");
    else pieces.push("Mention in servers");
    pieces.push(Array.isArray(bot.allowed_users) && bot.allowed_users.length > 0 ? "Private access" : "Open access");
    if (bot.default_project) pieces.push(`Project: ${bot.default_project}`);
    return pieces.join(" · ");
  },

  allowedUsersText(bot) {
    return (bot.allowed_users || []).join(", ");
  },

  setAllowedUsers(bot, value) {
    bot.allowed_users = value
      .split(",")
      .map((item) => item.trim())
      .filter((item) => item);
  },

  allowedGuildsText(bot) {
    return (bot.allowed_guilds || []).join(", ");
  },

  setAllowedGuilds(bot, value) {
    bot.allowed_guilds = value
      .split(",")
      .map((item) => item.trim())
      .filter((item) => item);
  },

  userProjectsText(bot) {
    return Object.entries(bot.user_projects || {})
      .map(([userId, project]) => `${userId}=${project}`)
      .join(", ");
  },

  setUserProjects(bot, value) {
    const mapping = {};
    value
      .split(",")
      .map((item) => item.trim())
      .filter((item) => item)
      .forEach((item) => {
        const [userId, project] = item.split("=").map((part) => part.trim());
        if (userId) mapping[userId] = project || "";
      });
    bot.user_projects = mapping;
  },

  accessWarning(bot) {
    if (!bot?.enabled) return "";
    const users = Array.isArray(bot.allowed_users) ? bot.allowed_users : [];
    const guilds = Array.isArray(bot.allowed_guilds) ? bot.allowed_guilds : [];
    if (users.length === 0 && guilds.length === 0) {
      return "Both allowed users and allowed guilds are empty. Anyone in any server the bot joins can reach your Agent Zero.";
    }
    return "";
  },

  intentsWarning(bot) {
    if (!bot) return "";
    const parts = ["Enable MESSAGE CONTENT intent in the Discord Developer Portal."];
    if (bot.welcome_enabled) parts.push("Enable SERVER MEMBERS intent for welcome messages.");
    return parts.join(" ");
  },

  inviteUrl(bot) {
    const clientId = String(bot?.client_id || "").trim();
    if (!clientId) return "";
    const perms = DEFAULT_INVITE_PERMS;
    const scopes = encodeURIComponent("bot applications.commands");
    return `https://discord.com/oauth2/authorize?client_id=${encodeURIComponent(clientId)}&scope=${scopes}&permissions=${perms}`;
  },

  async copyInviteUrl(bot) {
    const url = this.inviteUrl(bot);
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
    } catch (_) {
      // ignore — the user can still click the anchor
    }
  },

  async testConnection(idx) {
    const bot = this.bots[idx];
    if (!this.canTest(bot)) return;

    this.testing = idx;
    this.testResults = null;
    this.testResultsFor = idx;

    try {
      const response = await API.callJsonApi(`${API_BASE}/test_connection`, { bot });
      this.testResults = response;
      // Auto-populate client_id for the invite URL builder
      if (response?.client_id && !String(bot.client_id || "").trim()) {
        bot.client_id = response.client_id;
      }
    } catch (error) {
      this.testResults = {
        success: false,
        results: [{ test: "Discord bot", ok: false, message: String(error) }],
      };
    }

    this.testing = null;
  },

  testButtonLabel(bot, idx) {
    if (this.testing === idx) return "Checking...";
    if (this.canTest(bot)) return "Check Discord connection";
    return "Fill in the basics first";
  },

  testIntro() {
    return "We will validate the bot token with Discord so you know this bot can connect.";
  },

  resultTitle(result) {
    return result.test || "Check";
  },

  resultMessage(result) {
    return result.message || (result.ok ? "Done." : "Something went wrong.");
  },

  initialStepForBot(bot) {
    return String(bot?.token || "").trim() ? 1 : 0;
  },

  _startInitialBotFlow() {
    this.addBot();
    if (!this.context) return;
    const toComparableJson = typeof this.context._toComparableJson === "function"
      ? this.context._toComparableJson.bind(this.context)
      : JSON.stringify;
    this.context.settingsSnapshotJson = toComparableJson(this.context.settings);
  },

  _installWizardFooter() {
    if (!this.context) return;
    this.context.wizardFooter = {
      owner: "discordConfig",
      visible: () => this.showFooterNav,
      canGoBack: () => !this.isFirstStep,
      backLabel: () => "Back",
      note: () => this.footerStepLabel,
      showNext: () => this.showFooterNav && !this.isLastStep,
      nextLabel: () => this.nextButtonLabel,
      nextDisabled: () => this.nextDisabled,
      showSave: () => this.showFooterNav && this.isLastStep,
      onBack: () => this.previousStep(),
      onNext: () => this.nextStep(),
    };
  },
});
