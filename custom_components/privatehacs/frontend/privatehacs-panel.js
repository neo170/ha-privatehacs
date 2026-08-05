class PrivateHacsPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._repositories = [];
    this._loading = false;
    this._workingRepository = null;
    this._message = "";
    this._error = "";
    this._search = "";
    this._restarting = false;
    this._restartRequired = false;
  }

  set hass(value) {
    this._hass = value;
    if (!this._loaded) {
      this._loaded = true;
      this._loadRepositories();
    }
  }

  connectedCallback() {
    this._render();
  }

  _labels() {
    const german = this._hass?.language?.startsWith("de");
    return german
      ? {
          title: "PrivateHACS",
          refresh: "Repository-Liste aktualisieren",
          restartHomeAssistant: "Home Assistant neu starten",
          restartConfirmation: "Home Assistant wirklich neu starten?",
          restarting: "Home Assistant wird neu gestartet ...",
          search: "Repositories suchen",
          clearSearch: "Suche löschen",
          loading: "Private Repositories werden geladen ...",
          empty: "Keine privaten Repositories gefunden.",
          noSearchResults: "Keine passenden Repositories gefunden.",
          install: "Installieren",
          update: "Aktualisieren",
          uninstall: "Deinstallieren",
          uninstallConfirmation: "PrivateHACS entfernt die installierten Dateien. Entferne eine eingerichtete Integration vorher unter Einstellungen > Geräte & Dienste. Bei Lovelace-Karten wird auch die gespeicherte Modulressource entfernt. Bereits konfigurierte Dashboard-Karten musst du manuell entfernen. Fortfahren?",
          uninstalled: "Deinstalliert",
          takeOver: "In PrivateHACS übernehmen",
          takeOverConfirmation: "Die vorhandenen Dateien dieser Integration werden durch die aktuelle Version aus PrivateHACS ersetzt. Die Verwaltung geht an PrivateHACS über. Fortfahren?",
          installed: "Installiert",
          externallyManaged: "Extern installiert",
          removeExternalFirst: "Der Komponentenordner dieser früheren externen Installation ist noch vorhanden. Übernimm sie nur, wenn sie nicht mehr von HACS oder einem anderen Manager verwaltet wird.",
          updateAvailable: "Update verfügbar",
          archived: "Archiviert",
          installFailed: "Installation fehlgeschlagen",
          repository: "Repository öffnen",
          restart: "Home Assistant neu starten, um die installierte Integration zuverlässig zu laden.",
          reloadIntegration: "Integration neu laden",
          reloadConfirmation: "Eingerichtete Einträge für diese Integration neu laden? Ein Neustart von Home Assistant bleibt weiterhin möglich.",
          reloading: "Integrationen werden neu geladen ...",
          reloadComplete: "Integrationseinträge wurden neu geladen. Prüfe die Funktion und starte Home Assistant bei Bedarf neu.",
          reloadNoEntries: "Keine eingerichteten Integrationseinträge zum Neuladen gefunden.",
          reloadPartial: "Einige Integrationseinträge konnten nicht neu geladen werden:",
          reloadFailed: "Neuladen fehlgeschlagen",
          lovelaceCard: "Lovelace-Karte",
          lovelaceResourceRegistered: "Lovelace-Ressource registriert. Dashboard neu laden.",
          lovelaceResourceManual: "Füge diese Lovelace-Ressource manuell hinzu:",
          lovelaceResourceManualRemove: "Lovelace-Dateien entfernt. Entferne die manuell konfigurierte Ressource aus dem Dashboard.",
        }
      : {
          title: "PrivateHACS",
          refresh: "Refresh repository list",
          restartHomeAssistant: "Restart Home Assistant",
          restartConfirmation: "Restart Home Assistant now?",
          restarting: "Home Assistant is restarting ...",
          search: "Search repositories",
          clearSearch: "Clear search",
          loading: "Loading private repositories ...",
          empty: "No private repositories found.",
          noSearchResults: "No matching repositories found.",
          install: "Install",
          update: "Update",
          uninstall: "Uninstall",
          uninstallConfirmation: "PrivateHACS will remove the installed files. Remove a configured integration first under Settings > Devices & services. For Lovelace cards, it will also remove the stored module resource. Remove any configured dashboard cards manually. Continue?",
          uninstalled: "Uninstalled",
          takeOver: "Take over in PrivateHACS",
          takeOverConfirmation: "The existing files for this integration will be replaced with the current PrivateHACS version. PrivateHACS will take over management. Continue?",
          installed: "Installed",
          externallyManaged: "Installed externally",
          removeExternalFirst: "The component directory from an earlier external installation is still present. Take it over only when it is no longer managed by HACS or another manager.",
          updateAvailable: "Update available",
          archived: "Archived",
          installFailed: "Installation failed",
          repository: "Open repository",
          restart: "Restart Home Assistant to reliably load the installed integration.",
          reloadIntegration: "Reload integration",
          reloadConfirmation: "Reload configured entries for this integration? Restarting Home Assistant remains available.",
          reloading: "Reloading integrations ...",
          reloadComplete: "Integration entries were reloaded. Test the integration and restart Home Assistant if needed.",
          reloadNoEntries: "No configured integration entries were found to reload.",
          reloadPartial: "Some integration entries could not be reloaded:",
          reloadFailed: "Reload failed",
          lovelaceCard: "Lovelace card",
          lovelaceResourceRegistered: "Lovelace resource registered. Reload the dashboard.",
          lovelaceResourceManual: "Add this Lovelace resource manually:",
          lovelaceResourceManualRemove: "Lovelace files removed. Remove the manually configured resource from the dashboard.",
        };
  }

  async _loadRepositories(forceRefresh = false) {
    if (!this._hass) {
      return;
    }

    this._loading = true;
    this._error = "";
    this._render();
    try {
      const result = await this._hass.callWS({
        type: "privatehacs/repositories",
        refresh: forceRefresh,
      });
      this._repositories = Array.isArray(result.repositories) ? result.repositories : [];
      this._restartRequired = Boolean(result.restart_required);
    } catch (error) {
      this._error = error?.message || String(error);
    } finally {
      this._loading = false;
      this._render();
    }
  }

  async _install(repository, takeOver = false) {
    const labels = this._labels();
    if (takeOver && !window.confirm(labels.takeOverConfirmation)) {
      return;
    }

    this._workingRepository = repository.full_name;
    this._error = "";
    this._message = "";
    this._render();
    try {
      const result = await this._hass.callWS({
        type: "privatehacs/install",
        repository: repository.full_name,
        take_over: takeOver,
      });
      if (result.lovelace_resource) {
        this._message = `${repository.full_name}: ${result.lovelace_resource_registered
          ? this._labels().lovelaceResourceRegistered
          : `${this._labels().lovelaceResourceManual} ${result.lovelace_resource}`}`;
      } else {
        this._message = `${repository.full_name}: ${result.domains.join(", ")}`;
      }
      if (result.restart_required) {
        this._restartRequired = true;
      }
      await this._loadRepositories();
    } catch (error) {
      this._error = `${this._labels().installFailed}: ${error?.message || String(error)}`;
    } finally {
      this._workingRepository = null;
      this._render();
    }
  }

  async _uninstall(repository) {
    const labels = this._labels();
    if (!window.confirm(labels.uninstallConfirmation)) {
      return;
    }

    this._workingRepository = repository.full_name;
    this._error = "";
    this._message = "";
    this._render();
    try {
      const result = await this._hass.callWS({
        type: "privatehacs/uninstall",
        repository: repository.full_name,
      });
      this._message = repository.lovelace_filename && !result.lovelace_resource_removed
        ? `${repository.full_name}: ${labels.lovelaceResourceManualRemove}`
        : `${repository.full_name}: ${labels.uninstalled}`;
      if (result.restart_required) {
        this._restartRequired = true;
      }
      await this._loadRepositories();
    } catch (error) {
      this._error = `${labels.uninstall}: ${error?.message || String(error)}`;
    } finally {
      this._workingRepository = null;
      this._render();
    }
  }

  async _reload(repository) {
    const labels = this._labels();
    if (!window.confirm(labels.reloadConfirmation)) {
      return;
    }

    this._workingRepository = repository.full_name;
    this._error = "";
    this._message = labels.reloading;
    this._render();
    try {
      const result = await this._hass.callWS({
        type: "privatehacs/reload",
        repository: repository.full_name,
      });
      const reloadedEntries = Array.isArray(result.reloaded_entries)
        ? result.reloaded_entries
        : [];
      const failedEntries = Array.isArray(result.failed_entries)
        ? result.failed_entries
        : [];
      if (failedEntries.length) {
        const errors = failedEntries
          .map((entry) => entry?.error)
          .filter((error) => typeof error === "string" && error)
          .join(" ");
        this._message = `${repository.full_name}: ${labels.reloadPartial} ${errors}`;
      } else if (reloadedEntries.length) {
        this._message = `${repository.full_name}: ${labels.reloadComplete}`;
      } else {
        this._message = `${repository.full_name}: ${labels.reloadNoEntries}`;
      }
      this._restartRequired = Boolean(result.restart_required);
      await this._loadRepositories();
    } catch (error) {
      this._error = `${labels.reloadFailed}: ${error?.message || String(error)}`;
    } finally {
      this._workingRepository = null;
      this._render();
    }
  }

  async _restartHomeAssistant() {
    const labels = this._labels();
    if (!window.confirm(labels.restartConfirmation)) {
      return;
    }

    this._restarting = true;
    this._message = labels.restarting;
    this._error = "";
    this._render();
    try {
      await this._hass.callService("homeassistant", "restart", {});
    } catch (error) {
      this._restarting = false;
      this._error = error?.message || String(error);
      this._render();
    }
  }

  _filteredRepositories() {
    const query = this._search.trim().toLowerCase();
    if (!query) {
      return this._repositories;
    }

    return this._repositories.filter((repository) => [
      repository.full_name,
      repository.description,
      repository.default_branch,
      repository.lovelace_filename,
      ...(repository.domains || []),
    ].some((value) => typeof value === "string" && value.toLowerCase().includes(query)));
  }

  _renderCatalog() {
    const catalog = this.shadowRoot.querySelector("#catalog");
    if (!catalog) {
      return;
    }

    const labels = this._labels();
    catalog.replaceChildren();
    if (this._loading) {
      const loading = document.createElement("p");
      loading.className = "loading";
      loading.textContent = labels.loading;
      catalog.append(loading);
      return;
    }

    const repositories = this._filteredRepositories();
    if (!repositories.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = this._repositories.length ? labels.noSearchResults : labels.empty;
      catalog.append(empty);
      return;
    }
    repositories.forEach((repository) => {
      catalog.append(this._renderRepository(repository, labels));
    });
  }

  _renderRepository(repository, labels) {
    const row = document.createElement("article");
    row.className = "repository";

    const icon = document.createElement("img");
    icon.className = "integration-icon";
    const domain = repository.domains?.[0];
    icon.alt = domain || "";
    if (repository.icon_url) {
      icon.src = repository.icon_url;
      icon.addEventListener("error", () => {
        icon.removeAttribute("src");
      });
    }

    const details = document.createElement("div");
    details.className = "details";
    const name = document.createElement("h2");
    name.textContent = repository.full_name;
    details.append(name);

    if (repository.description) {
      const description = document.createElement("p");
      description.className = "description";
      description.textContent = repository.description;
      details.append(description);
    }

    const metadata = document.createElement("p");
    metadata.className = "metadata";
    const versions = Object.entries(repository.local_versions || {}).map(([domain, local]) => {
      const remote = repository.available_versions?.[domain];
      return repository.update_available && remote
        ? `${domain}: ${local || "?"} -> ${remote}`
        : `${domain}: ${local || "?"}`;
    });
    metadata.textContent = repository.lovelace_filename
      ? `${labels.lovelaceCard}: ${repository.lovelace_filename}`
      : versions.length
        ? versions.join(", ")
        : repository.domains.length
          ? repository.domains.join(", ")
          : repository.default_branch;
    details.append(metadata);

    if (repository.managed_externally) {
      const conflict = document.createElement("p");
      conflict.className = "conflict";
      conflict.textContent = labels.removeExternalFirst;
      details.append(conflict);
    }

    const actions = document.createElement("div");
    actions.className = "actions";
    const status = document.createElement("span");
    status.className = "status";
    if (repository.archived) {
      status.textContent = labels.archived;
    } else if (repository.managed_externally) {
      status.textContent = labels.externallyManaged;
    } else if (repository.update_available) {
      status.classList.add("update");
      status.textContent = labels.updateAvailable;
    } else if (repository.installed) {
      status.textContent = labels.installed;
    }
    actions.append(status);

    const isWorking = this._workingRepository === repository.full_name;
    const canInstall = !repository.installed && !repository.managed_externally;
    const canUpdate = repository.installed && repository.update_available;
    const canTakeOver = repository.managed_externally;
    if (!repository.archived && (canInstall || canUpdate || canTakeOver)) {
      const install = document.createElement("button");
      install.textContent = canTakeOver
        ? labels.takeOver
        : canUpdate
          ? labels.update
          : labels.install;
      install.disabled = isWorking;
      install.addEventListener("click", () => this._install(repository, canTakeOver));
      actions.append(install);
    }
    if (!repository.lovelace_filename && repository.managed_by_privatehacs) {
      const reload = document.createElement("button");
      reload.textContent = labels.reloadIntegration;
      reload.disabled = isWorking;
      reload.addEventListener("click", () => this._reload(repository));
      actions.append(reload);
    }
    if (!repository.archived && repository.managed_by_privatehacs) {
      const uninstall = document.createElement("button");
      uninstall.className = "uninstall-button";
      uninstall.textContent = labels.uninstall;
      uninstall.disabled = isWorking;
      uninstall.addEventListener("click", () => this._uninstall(repository));
      actions.append(uninstall);
    }

    const link = document.createElement("a");
    link.href = repository.html_url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = labels.repository;
    actions.append(link);

    row.append(icon, details, actions);
    return row;
  }

  _render() {
    const labels = this._labels();
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          color: var(--primary-text-color);
          display: block;
          min-height: 100%;
        }
        main {
          min-height: 100%;
        }
        header {
          align-items: center;
          background: var(--primary-background-color, var(--card-background-color));
          border-bottom: 1px solid var(--divider-color);
          box-sizing: border-box;
          color: var(--primary-text-color);
          display: flex;
          height: 56px;
          justify-content: space-between;
          min-height: 56px;
          padding: 0 24px;
        }
        .topbar-title {
          align-items: center;
          display: flex;
          font-size: 20px;
          font-weight: 500;
          gap: 12px;
          min-width: 0;
        }
        .topbar-title ha-icon {
          --mdi-icon-size: 24px;
          flex: 0 0 auto;
        }
        .topbar-title span {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .header-actions {
          align-items: center;
          display: flex;
        }
        .search-toolbar {
          padding: 14px 0;
        }
        .search-wrap {
          align-items: center;
          background: var(--secondary-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 4px;
          box-sizing: border-box;
          display: flex;
          gap: 8px;
          min-height: 42px;
          padding-left: 12px;
          width: 100%;
        }
        .search-wrap ha-icon {
          --mdi-icon-size: 20px;
          color: var(--secondary-text-color);
        }
        .search-wrap input {
          background: transparent;
          border: 0;
          color: var(--primary-text-color);
          flex: 1;
          font: inherit;
          min-width: 0;
          outline: 0;
        }
        .search-wrap ha-icon-button {
          --ha-icon-button-size: 40px;
          color: var(--secondary-text-color);
        }
        .content {
          box-sizing: border-box;
          margin: 0 auto;
          max-width: 1080px;
          padding: 0 24px 48px;
        }
        h2 {
          font-size: 17px;
          font-weight: 500;
          letter-spacing: 0;
          margin: 0;
          overflow-wrap: anywhere;
        }
        button {
          background: var(--primary-color);
          border: 0;
          border-radius: 4px;
          color: var(--text-primary-color, #fff);
          cursor: pointer;
          font: inherit;
          min-height: 36px;
          padding: 0 14px;
        }
        button:disabled {
          cursor: default;
          opacity: 0.5;
        }
        .uninstall-button {
          background: transparent;
          border: 1px solid var(--error-color);
          color: var(--error-color);
        }
        .uninstall-button:hover:not(:disabled) {
          background: color-mix(in srgb, var(--error-color) 12%, transparent);
        }
        .catalog {
          display: grid;
          gap: 10px;
          margin-top: 18px;
        }
        .repository {
          align-items: center;
          background: var(--card-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 6px;
          display: grid;
          gap: 20px;
          grid-template-columns: 48px minmax(0, 1fr) auto;
          padding: 16px;
        }
        .integration-icon {
          background: var(--secondary-background-color);
          border-radius: 4px;
          box-sizing: border-box;
          height: 48px;
          object-fit: contain;
          padding: 4px;
          width: 48px;
        }
        .integration-icon:not([src]) {
          border: 1px solid var(--divider-color);
        }
        .description {
          color: var(--secondary-text-color);
          margin: 7px 0 0;
          overflow-wrap: anywhere;
        }
        .metadata {
          color: var(--secondary-text-color);
          font-family: var(--code-font-family, monospace);
          font-size: 13px;
          margin: 8px 0 0;
          overflow-wrap: anywhere;
        }
        .conflict {
          color: var(--error-color);
          margin: 8px 0 0;
          overflow-wrap: anywhere;
        }
        .actions {
          align-items: center;
          display: grid;
          gap: 8px;
          justify-items: end;
        }
        .status {
          color: var(--secondary-text-color);
          font-size: 13px;
          min-height: 18px;
        }
        .status.update {
          color: var(--warning-color, #f39c12);
          font-weight: 500;
        }
        a {
          color: var(--primary-color);
          font-size: 13px;
        }
        .notice,
        .error,
        .empty,
        .loading {
          border-left: 3px solid var(--primary-color);
          margin: 18px 0 0;
          padding: 10px 12px;
        }
        .restart-required {
          align-items: center;
          border-left: 3px solid var(--warning-color, #f39c12);
          display: flex;
          flex-wrap: wrap;
          gap: 12px;
          margin: 18px 0 0;
          padding: 10px 12px;
        }
        .restart-required span {
          flex: 1 1 220px;
        }
        .error {
          border-color: var(--error-color);
        }
        @media (max-width: 600px) {
          header {
            height: 56px;
            min-height: 56px;
            padding: 0 8px 0 16px;
          }
          .search-toolbar {
            padding: 12px 0;
          }
          .content {
            padding: 0 14px 36px;
          }
          .repository {
            align-items: stretch;
            grid-template-columns: 48px minmax(0, 1fr);
          }
          .actions {
            grid-column: 1 / -1;
            align-items: center;
            grid-template-columns: 1fr auto;
            justify-items: start;
          }
          .actions a {
            grid-column: 1 / -1;
          }
        }
      </style>
      <main>
        <header>
          <div class="topbar-title">
            <ha-icon icon="mdi:github"></ha-icon>
            <span>${labels.title}</span>
          </div>
          <div class="header-actions">
            <ha-icon-button id="refresh" label="${labels.refresh}">
              <ha-icon icon="mdi:reload"></ha-icon>
            </ha-icon-button>
          </div>
        </header>
        <div class="content">
          <div class="search-toolbar">
            <div class="search-wrap">
              <ha-icon icon="mdi:magnify"></ha-icon>
              <input id="search" type="search" autocomplete="off" aria-label="${labels.search}">
              <ha-icon-button id="clear-search" label="${labels.clearSearch}">
                <ha-icon icon="mdi:close"></ha-icon>
              </ha-icon-button>
            </div>
          </div>
          <div id="feedback"></div>
          <section class="catalog" id="catalog"></section>
        </div>
      </main>`;

    const refresh = this.shadowRoot.querySelector("#refresh");
    refresh.disabled = this._loading || this._restarting;
    refresh.addEventListener("click", () => {
      this._loadRepositories(true);
    });
    const search = this.shadowRoot.querySelector("#search");
    search.value = this._search;
    search.placeholder = labels.search;
    const clearSearch = this.shadowRoot.querySelector("#clear-search");
    clearSearch.hidden = !this._search;
    search.addEventListener("input", (event) => {
      this._search = event.target.value;
      clearSearch.hidden = !this._search;
      this._renderCatalog();
    });
    clearSearch.addEventListener("click", () => {
      this._search = "";
      search.value = "";
      clearSearch.hidden = true;
      this._renderCatalog();
      search.focus();
    });

    const feedback = this.shadowRoot.querySelector("#feedback");
    if (this._error) {
      const error = document.createElement("p");
      error.className = "error";
      error.textContent = this._error;
      feedback.append(error);
    } else if (this._message) {
      const notice = document.createElement("p");
      notice.className = "notice";
      notice.textContent = this._message;
      feedback.append(notice);
    }
    if (this._restartRequired) {
      const restart = document.createElement("div");
      restart.className = "restart-required";
      const message = document.createElement("span");
      message.textContent = labels.restart;
      const action = document.createElement("button");
      action.className = "restart-button";
      action.textContent = labels.restartHomeAssistant;
      action.disabled = this._restarting;
      action.addEventListener("click", () => this._restartHomeAssistant());
      restart.append(message, action);
      feedback.append(restart);
    }

    this._renderCatalog();
  }
}

customElements.define("privatehacs-panel", PrivateHacsPanel);