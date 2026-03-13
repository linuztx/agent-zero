import { createStore } from "/js/AlpineStore.js";
import * as api from "/js/api.js";
import { openModal } from "/js/modals.js";
import { marked } from "/vendor/marked/marked.esm.js";
import { toastFrontendSuccess, toastFrontendError } from "/components/notifications/notification-store.js";
import { showConfirmDialog } from "/js/confirmDialog.js";
import { store as imageViewerStore } from "/components/modals/image-viewer/image-viewer-store.js";
import { store as pluginListStore } from "/components/plugins/list/pluginListStore.js";
import { store as pluginInitStore } from "/components/plugins/list/plugin-init-store.js";

const PLUGIN_API = "plugins/_plugin_installer/plugin_install";
const PER_PAGE = 20;

const SECURITY_WARNING = {
  title: "Security Warning",
  message: `
    <p><strong>Plugins from third parties can be a great risk, keep in mind that:</strong></p>
    <ul style="margin: 0.75em 0; padding-left: 1.5em;">
      <li>You can be hacked the moment you install it</li>
      <li>We can not prevent it or help you</li>
      <li>It is your responsibility</li>
    </ul>
    <p style="margin-top: 0.75em;">We can never fully guarantee that plugins are safe because there are many ways to obfuscate malicious code.</p>
  `,
  type: "warning",
  confirmText: "Install Anyway",
  cancelText: "Cancel",
};

const model = {
  // ZIP install state
  zipFile: null,
  zipFileName: "",

  // Git install state
  gitUrl: "",
  gitToken: "",

  // Index state
  index: { authors: {}, plugins: {} },
  installedPlugins: [],
  search: "",
  page: 1,
  sortBy: "stars",
  browseFilter: "all",
  selectedPlugin: null,

  // Shared state
  loading: false,
  loadingMessage: "",
  result: null,

  // README state
  readmeContent: null,
  readmeLoading: false,

  // Installed plugin detail (for manage buttons)
  installedPluginInfo: null,

  detailThumbnailUrl: null,

  // Tab state
  activeTab: "store",

  setTab(tab) {
    this.activeTab = tab;
    this.result = null;
  },

  setBrowseFilter(filter) {
    this.browseFilter = filter || "all";
    this.page = 1;
  },

  /** Normalize GitHub URL and return raw.githubusercontent.com base (no trailing slash). */
  _githubRawBase(githubUrl) {
    if (!githubUrl || typeof githubUrl !== "string") return null;
    let url = githubUrl.trim().replace(/\.git$/i, "");
    if (!url.includes("github.com")) return null;
    return url.replace("https://github.com/", "https://raw.githubusercontent.com/");
  },

  _pluginPrimaryTag(plugin) {
    const tags = Array.isArray(plugin?.tags) ? plugin.tags.filter(Boolean) : [];
    return tags[0] || "";
  },

  _formatBrowseTag(tag) {
    if (!tag || typeof tag !== "string") return "";
    return tag
      .split(/[-_]/)
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
  },

  _matchesBrowseFilter(plugin, filterKey) {
    if (!filterKey || filterKey === "all") return true;
    if (filterKey === "installed") return !!plugin?.installed;
    if (filterKey === "popular") return (plugin?.stars || 0) > 0;
    if (filterKey.startsWith("tag:")) {
      return this._pluginPrimaryTag(plugin) === filterKey.slice(4);
    }
    return false;
  },

  // ── ZIP Install ──────────────────────────────

  handleFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;
    this.zipFile = file;
    this.zipFileName = file.name;
    this.result = null;
  },

  async installZip() {
    if (!this.zipFile) {
      void toastFrontendError("Please select a ZIP file first", "Plugin Installer");
      return;
    }

    const confirmed = await showConfirmDialog(SECURITY_WARNING);
    if (!confirmed) return;

    try {
      this.loading = true;
      this.loadingMessage = "Installing plugin from ZIP...";
      this.result = null;

      const formData = new FormData();
      formData.append("action", "install_zip");
      formData.append("plugin_file", this.zipFile);

      const response = await api.fetchApi(PLUGIN_API, {
        method: "POST",
        body: formData,
      });

      const data = await response.json();
      if (!data.success) {
        void toastFrontendError(data.error || "Installation failed", "Plugin Installer");
        return;
      }

      this.result = data;

      toastFrontendSuccess(
        `Plugin "${data.title || data.plugin_name}" installed`,
        "Plugin Installer"
      );
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      void toastFrontendError(`Installation error: ${message}`, "Plugin Installer");
    } finally {
      this.loading = false;
      this.loadingMessage = "";
    }
  },

  // ── Git Install ──────────────────────────────

  async installGit() {
    const url = (this.gitUrl || "").trim();
    if (!url) {
      void toastFrontendError("Please enter a Git URL", "Plugin Installer");
      return;
    }

    const confirmed = await showConfirmDialog(SECURITY_WARNING);
    if (!confirmed) return;

    try {
      this.loading = true;
      this.loadingMessage = "Cloning repository...";
      this.result = null;

      const data = await api.callJsonApi(PLUGIN_API, {
        action: "install_git",
        git_url: url,
        git_token: this.gitToken || "",
      });

      if (!data.success) {
        void toastFrontendError(data.error || "Clone failed", "Plugin Installer");
        return;
      }

      this.result = data;

      toastFrontendSuccess(
        `Plugin "${data.title || data.plugin_name}" installed`,
        "Plugin Installer"
      );
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      void toastFrontendError(`Clone error: ${message}`, "Plugin Installer");
    } finally {
      this.loading = false;
      this.loadingMessage = "";
    }
  },

  // ── Index Browse ─────────────────────────────

  async fetchIndex() {
    try {
      this.loading = true;
      this.loadingMessage = "Loading plugin index...";

      const data = await api.callJsonApi(PLUGIN_API, {
        action: "fetch_index",
      });

      if (!data.success) {
        void toastFrontendError(data.error || "Failed to load index", "Plugin Installer");
        return;
      }

      this.index = data.index;
      this.installedPlugins = data.installed_plugins || [];
      this.page = 1;
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      void toastFrontendError(`Failed to load plugin index: ${message}`, "Plugin Installer");
    } finally {
      this.loading = false;
      this.loadingMessage = "";
    }
  },

  get pluginsList() {
    if (!this.index?.plugins) return [];
    return Object.entries(this.index.plugins).map(([key, val]) => ({
      key,
      ...val,
      installed: this.installedPlugins.includes(key),
    }));
  },

  get browseFilters() {
    const plugins = this.pluginsList;
    const filters = [{ key: "all", label: "All", count: plugins.length }];

    if (!plugins.length) return filters;

    const installedCount = plugins.filter((plugin) => plugin.installed).length;
    if (installedCount) {
      filters.push({ key: "installed", label: "Installed", count: installedCount });
    }

    const popularCount = plugins.filter((plugin) => (plugin.stars || 0) > 0).length;
    if (popularCount) {
      filters.push({ key: "popular", label: "Popular", count: popularCount });
    }

    const tagCounts = new Map();
    for (const plugin of plugins) {
      const tag = this._pluginPrimaryTag(plugin);
      if (!tag) continue;
      tagCounts.set(tag, (tagCounts.get(tag) || 0) + 1);
    }

    for (const [tag, count] of Array.from(tagCounts.entries())
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, 4)) {
      filters.push({
        key: `tag:${tag}`,
        label: this._formatBrowseTag(tag),
        count,
      });
    }

    return filters;
  },

  get filteredPlugins() {
    let list = this.pluginsList.filter((plugin) =>
      this._matchesBrowseFilter(plugin, this.browseFilter)
    );
    const q = (this.search || "").toLowerCase().trim();
    if (q) {
      list = list.filter(
        (p) =>
          (p.title || "").toLowerCase().includes(q) ||
          (p.author || "").toLowerCase().includes(q) ||
          (p.description || "").toLowerCase().includes(q) ||
          (p.key || "").toLowerCase().includes(q) ||
          (p.tags || []).some((t) => t.toLowerCase().includes(q))
      );
    }
    if (this.sortBy === "stars") {
      list.sort((a, b) => (b.stars || 0) - (a.stars || 0));
    } else {
      list.sort((a, b) =>
        (a.title || a.key).localeCompare(b.title || b.key)
      );
    }
    return list;
  },

  get browseResultsSummary() {
    const total = this.pluginsList.length;
    const visible = this.filteredPlugins.length;
    if (!total) return "No plugins available";
    if (visible === total) {
      return `${total} plugin${total === 1 ? "" : "s"} available`;
    }
    return `Showing ${visible} of ${total} plugins`;
  },

  get totalPages() {
    return Math.max(1, Math.ceil(this.filteredPlugins.length / PER_PAGE));
  },

  get paginatedPlugins() {
    const start = (this.page - 1) * PER_PAGE;
    return this.filteredPlugins.slice(start, start + PER_PAGE);
  },

  getBrowseSubtitle(plugin) {
    const author = (plugin?.author || "").trim();
    if (author) return author;
    const tag = this._pluginPrimaryTag(plugin);
    if (tag) return this._formatBrowseTag(tag);
    return plugin?.key || "";
  },

  getBrowsePrimaryTag(plugin) {
    return this._formatBrowseTag(this._pluginPrimaryTag(plugin));
  },

  setPage(p) {
    this.page = Math.max(1, Math.min(p, this.totalPages));
  },

  openDetail(plugin) {
    this.selectedPlugin = { ...plugin, name: plugin?.key || "" };
    this.result = null;
    this.installedPluginInfo = null;
    this.readmeContent = null;
    this.detailThumbnailUrl = this.getThumbnailUrl(this.selectedPlugin);
    if (this.selectedPlugin.installed) {
      this.fetchInstalledPluginInfo(this.selectedPlugin.name);
    }
    this.fetchReadme(this.selectedPlugin);
    openModal("/plugins/_plugin_installer/webui/install-detail.html");
  },

  async fetchReadme(plugin) {
    const rawBase = this._githubRawBase(plugin?.github);
    if (!rawBase) return;

    try {
      this.readmeLoading = true;
      this.readmeContent = null;
      let lastError = null;

      for (const branch of ["main", "master"]) {
        try {
          const response = await fetch(`${rawBase}/${branch}/README.md`);
          if (!response.ok) continue;

          const readme = await response.text();
          this.readmeContent = marked.parse(readme, { breaks: true });
          return;
        } catch (error) {
          lastError = error;
        }
      }

      if (lastError) {
        console.warn("Failed to fetch readme:", lastError);
      }
    } finally {
      this.readmeLoading = false;
    }
  },

  async installFromIndex(plugin) {
    if (!plugin?.github) {
      void toastFrontendError("No GitHub URL available for this plugin", "Plugin Installer");
      return;
    }

    const confirmed = await showConfirmDialog({
      ...SECURITY_WARNING,
      extensionContext: {
        kind: "marketplace_plugin_install_warning",
        source: "plugin_installer",
        pluginKey: plugin.key || "",
        pluginTitle: plugin.title || plugin.key || "",
        gitUrl: plugin.github,
      },
    });
    if (!confirmed) return;

    try {
      this.loading = true;
      this.loadingMessage = `Installing ${plugin.title || plugin.key}...`;

      const data = await api.callJsonApi(PLUGIN_API, {
        action: "install_git",
        git_url: plugin.github,
        plugin_name: plugin.key,
      });

      if (!data.success) {
        void toastFrontendError(data.error || "Installation failed", "Plugin Installer");
        return;
      }

      const installedKey = plugin.key || data.plugin_name;
      if (installedKey && !this.installedPlugins.includes(installedKey)) {
        this.installedPlugins = [...this.installedPlugins, installedKey];
      }

      this.selectedPlugin = {
        ...plugin,
        name: plugin.key || "",
        installed: true,
      };
      this.detailThumbnailUrl = this.getThumbnailUrl(this.selectedPlugin);
      this.fetchInstalledPluginInfo(plugin.key || data.plugin_name);

      toastFrontendSuccess(
        `Plugin "${data.title || data.plugin_name}" installed`,
        "Plugin Installer"
      );
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      void toastFrontendError(`Installation error: ${message}`, "Plugin Installer");
    } finally {
      this.loading = false;
      this.loadingMessage = "";
    }
  },

  // ── Installed Plugin Info ─────────────────────

  async fetchInstalledPluginInfo(pluginName) {
    this.installedPluginInfo = null;
    try {
      const response = await api.callJsonApi("plugins_list", {
        filter: { custom: true, builtin: true, search: "" },
      });
      const plugins = Array.isArray(response.plugins) ? response.plugins : [];
      this.installedPluginInfo = plugins.find((p) => p.name === pluginName) || null;
    } catch (_error) {
      this.installedPluginInfo = null;
    }
  },


  handleOpenPlugin() {
    const info = this.installedPluginInfo;
    if (!info || !info.name || !info.has_main_screen) return;
    openModal(`/plugins/${info.name}/webui/main.html`);
  },

  async handleOpenConfig() {
    if (this.installedPluginInfo) {
      await pluginListStore.openPluginConfig(this.installedPluginInfo);
    }
  },

  async handleOpenDoc(doc) {
    if (this.installedPluginInfo) {
      await pluginListStore.openPluginDoc(this.installedPluginInfo, doc);
    }
  },

  handleOpenInfo() {
    if (this.installedPluginInfo) {
      pluginListStore.openPluginInfo(this.installedPluginInfo);
    }
  },

  handleOpenInit() {
    if (this.installedPluginInfo) {
      pluginInitStore.open(this.installedPluginInfo);
    }
  },

  async handleDeletePlugin() {
    if (!this.installedPluginInfo) return;

    try {
      this.loading = true;
      this.loadingMessage = "Uninstalling plugin...";

      await pluginListStore.deletePlugin(this.installedPluginInfo);
      const currentPlugin = this.selectedPlugin;
      if (currentPlugin) {
        this.selectedPlugin = { ...currentPlugin, installed: false };
        this.installedPlugins = this.installedPlugins.filter(
          (key) => key !== currentPlugin.key
        );
      }
      this.installedPluginInfo = null;
    } finally {
      this.loading = false;
      this.loadingMessage = "";
    }
  },

  getIndexUrl(pluginKey) {
    if (!pluginKey) return "";
    return `https://github.com/agent0ai/a0-plugins/tree/main/plugins/${pluginKey}`;
  },

  getThumbnailUrl(plugin) {
    if (!plugin) return null;
    if (plugin.thumbnail && typeof plugin.thumbnail === "string") return plugin.thumbnail;
    const rawBase = this._githubRawBase(plugin?.github);
    return rawBase ? `${rawBase}/main/thumbnail.png` : null;
  },

  getDetailThumbnailUrl() {
    return this.detailThumbnailUrl;
  },

  openScreenshot(url) {
    if (!url) return;
    imageViewerStore.open(url, {
      name: this.selectedPlugin?.title || this.selectedPlugin?.key || "Plugin screenshot",
    });
  },

  // ── Shared ───────────────────────────────────

  resetZip() {
    this.zipFile = null;
    this.zipFileName = "";
    this.result = null;
  },

  resetGit() {
    this.gitUrl = "";
    this.gitToken = "";
    this.result = null;
  },

  resetIndex() {
    this.search = "";
    this.page = 1;
    this.sortBy = "stars";
    this.browseFilter = "all";
    this.result = null;
    this.selectedPlugin = null;
  },

  /** Refresh related list views after installer/detail actions. */
  refreshPluginList() {
    if (pluginListStore.activeTab === "marketplace") {
      void this.fetchIndex();
    }
    pluginListStore.refresh();
  },

  truncate(text, max) {
    if (!text || text.length <= max) return text || "";
    return text.substring(0, max) + "...";
  },
};

const store = createStore("pluginInstallStore", model);
export { store };
