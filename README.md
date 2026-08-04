# PrivateHACS

PrivateHACS is a public Home Assistant custom integration that exposes private
GitHub repositories as an installable integration catalog. It downloads source
archives through the GitHub REST API, extracts only valid Home Assistant custom
components, and tracks installed commits for updates.

## Installation

1. Add the public `ha-privatehacs` repository to HACS as an integration.
2. Install **PrivateHACS** through HACS and restart Home Assistant.
3. In **Settings > Devices & services**, add the **PrivateHACS** integration.
4. Enter the GitHub username and a personal access token (PAT).
5. Open **PrivateHACS** in the Home Assistant sidebar to install or update a
  private repository. PrivateHACS displays only repositories whose name starts
  with `ha-`.

No `configuration.yaml` changes are required.

## GitHub token

Use a fine-grained GitHub PAT scoped to the repositories that PrivateHACS may
install. It needs **Contents: Read-only** permission. A classic PAT with `repo`
scope also works. The token is sent only to `api.github.com`, is never included
in a clone URL, and is not exposed through the sidebar WebSocket API.

## Repository layout

Each private repository must include one or more integration directories below
`custom_components`:

```text
custom_components/
  my_integration/
    __init__.py
    manifest.json
    config_flow.py
```

The `domain` in each `manifest.json` must exactly match its directory name.
PrivateHACS installs every domain contained in the repository. It refuses ZIP
path traversal, symbolic links, malformed manifests, and overwriting a custom
component that it did not previously manage.

## Updates

The sidebar displays an update state by comparing the installed commit SHA with
the default branch on GitHub. Selecting **Update** downloads and atomically
replaces the managed component directories. Home Assistant must be restarted
after updating an already loaded integration so Python imports use the new code.
Newly installed integrations are made discoverable in **Settings > Devices &
services** immediately.

PrivateHACS also reads local `custom_components` manifests. If a displayed
repository contains an integration already installed by HACS or another method,
the sidebar shows the installed and current GitHub manifest versions and marks
an available newer version. PrivateHACS does not overwrite integrations it did
not install itself; update externally managed integrations in their original
manager, such as HACS.

## Diagnostics

When the sidebar says that no private repositories were found, select
**Refresh** once, then open **Settings > Devices & services > PrivateHACS** and
use the config entry menu to download diagnostics. The export contains only
counts and API metadata, never the PAT or private repository names. In
particular, check these fields:

- `visible_repositories`: repositories GitHub returned to the PAT.
- `private_repositories`: the subset PrivateHACS can offer for installation.
- `oauth_scopes` and `rate_limit_remaining`: GitHub response metadata when it
  is available.
- `error`: the last API error, if the lookup failed.

PrivateHACS writes a warning to Home Assistant's system log when GitHub returns
zero private repositories. For more detail without editing `configuration.yaml`,
run this action in **Developer tools > Actions**, refresh the sidebar, then open
the system log:

```yaml
action: logger.set_level
data:
  custom_components.privatehacs: debug
```

For a fine-grained PAT, ensure that every intended private repository is selected
and that it has **Contents: Read-only** permission. For organization repositories,
authorize the token for the organization's SSO if required.

## Development

The focused installer tests do not require a Home Assistant installation:

```powershell
py -3 -m pytest
```

For end-to-end config-flow and WebSocket tests, install Home Assistant's test
dependencies in a dedicated development environment.