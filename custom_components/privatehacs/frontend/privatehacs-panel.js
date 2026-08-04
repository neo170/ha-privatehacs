class PrivateHacsPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._repositories = [];
    this._loading = false;
    this._workingRepository = null;
    this._message = "";
    this._error = "";
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
          refresh: "Aktualisieren",
          loading: "Private Repositories werden geladen ...",
          empty: "Keine privaten Repositories gefunden.",
          install: "Installieren",
          update: "Aktualisieren",
          installed: "Installiert",
          externallyManaged: "Extern installiert",
          removeExternalFirst: "Diese Integration ist bereits außerhalb von PrivateHACS installiert. Entferne sie zuerst in HACS (oder manuell), bevor du sie mit PrivateHACS installierst.",
          updateAvailable: "Update verfügbar",
          archived: "Archiviert",
          installFailed: "Installation fehlgeschlagen",
          repository: "Repository öffnen",
          restart: "Neustart von Home Assistant erforderlich, um den Code der aktualisierten Integration zu laden.",
        }
      : {
          title: "PrivateHACS",
          refresh: "Refresh",
          loading: "Loading private repositories ...",
          empty: "No private repositories found.",
          install: "Install",
          update: "Update",
          installed: "Installed",
          externallyManaged: "Installed externally",
          removeExternalFirst: "This integration is already installed outside PrivateHACS. Remove it in HACS (or manually) before installing it with PrivateHACS.",
          updateAvailable: "Update available",
          archived: "Archived",
          installFailed: "Installation failed",
          repository: "Open repository",
          restart: "Restart Home Assistant to load the updated integration code.",
        };
  }

  async _loadRepositories() {
    if (!this._hass) {
      return;
    }

    this._loading = true;
    this._error = "";
    this._render();
    try {
      const result = await this._hass.callWS({ type: "privatehacs/repositories" });
      this._repositories = Array.isArray(result.repositories) ? result.repositories : [];
    } catch (error) {
      this._error = error?.message || String(error);
    } finally {
      this._loading = false;
      this._render();
    }
  }

  async _install(repository) {
    this._workingRepository = repository.full_name;
    this._error = "";
    this._message = "";
    this._render();
    try {
      const result = await this._hass.callWS({
        type: "privatehacs/install",
        repository: repository.full_name,
      });
      this._message = `${repository.full_name}: ${result.domains.join(", ")}`;
      if (result.restart_required) {
        this._message = `${this._message}. ${this._labels().restart}`;
      }
      await this._loadRepositories();
    } catch (error) {
      this._error = `${this._labels().installFailed}: ${error?.message || String(error)}`;
    } finally {
      this._workingRepository = null;
      this._render();
    }
  }

  _renderRepository(repository, labels) {
    const row = document.createElement("article");
    row.className = "repository";

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
      return remote ? `${domain}: ${local || "?"} -> ${remote}` : `${domain}: ${local || "?"}`;
    });
    metadata.textContent = versions.length
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
    if (!repository.archived && (canInstall || canUpdate)) {
      const install = document.createElement("button");
      install.textContent = canUpdate ? labels.update : labels.install;
      install.disabled = isWorking;
      install.addEventListener("click", () => this._install(repository));
      actions.append(install);
    }

    const link = document.createElement("a");
    link.href = repository.html_url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = labels.repository;
    actions.append(link);

    row.append(details, actions);
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
          box-sizing: border-box;
          margin: 0 auto;
          max-width: 1080px;
          padding: 28px 24px 48px;
        }
        header {
          align-items: center;
          border-bottom: 1px solid var(--divider-color);
          display: flex;
          justify-content: space-between;
          min-height: 58px;
        }
        h1 {
          font-size: 28px;
          font-weight: 500;
          letter-spacing: 0;
          margin: 0;
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
          grid-template-columns: minmax(0, 1fr) auto;
          padding: 16px;
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
        .error {
          border-color: var(--error-color);
        }
        @media (max-width: 600px) {
          main {
            padding: 18px 14px 36px;
          }
          .repository {
            align-items: stretch;
            grid-template-columns: minmax(0, 1fr);
          }
          .actions {
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
          <h1>${labels.title}</h1>
          <button id="refresh">${labels.refresh}</button>
        </header>
        <div id="feedback"></div>
        <section class="catalog" id="catalog"></section>
      </main>`;

    this.shadowRoot.querySelector("#refresh").addEventListener("click", () => {
      this._loadRepositories();
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

    const catalog = this.shadowRoot.querySelector("#catalog");
    if (this._loading) {
      const loading = document.createElement("p");
      loading.className = "loading";
      loading.textContent = labels.loading;
      catalog.append(loading);
      return;
    }
    if (!this._repositories.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = labels.empty;
      catalog.append(empty);
      return;
    }
    this._repositories.forEach((repository) => {
      catalog.append(this._renderRepository(repository, labels));
    });
  }
}

customElements.define("privatehacs-panel", PrivateHacsPanel);