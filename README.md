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
after every installation or update so it loads the installed integration code.

PrivateHACS-managed repositories also appear on Home Assistant's **Settings >
System > Updates** page. Their update entities check GitHub every 15 minutes
and can install the current default-branch revision. HACS- or manually managed
integrations are intentionally not added there.
When a repository publishes manifest versions, Home Assistant displays those
versions. It falls back to a commit revision only when no manifest version is
available or a source update did not change it.

After updating **PrivateHACS** itself through HACS, restart Home Assistant. The
sidebar then loads the panel code that belongs to the installed version.

PrivateHACS also reads local `custom_components` manifests. If a displayed
repository contains an integration already installed by HACS or another method,
the sidebar shows the installed and current GitHub manifest versions for
reference. PrivateHACS does not mark externally managed integrations as
updatable and does not overwrite integrations it did not install itself; update
them in their original manager, such as HACS.

To move an integration from HACS to PrivateHACS, first remove it in HACS. Both
managers install the component into the same domain directory, so they cannot
manage two copies of the same integration.

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

## Release

Create the next patch release, including the commit, push, GitHub tag, and
generated GitHub release notes, with one command:

```powershell
.\scripts\Release.ps1
```

The script updates the version in `manifest.json` and `pyproject.toml`, runs the
test suite and panel syntax check, and then stages all non-ignored working-tree
changes in its release commit. It only releases from an up-to-date local `main`
branch and requires authenticated `git`, GitHub CLI (`gh`), Python, and Node.js.

Use `-Bump Minor`, `-Bump Major`, or `-Version 1.2.3` to select another version.
Use `-Prerelease` to create a GitHub prerelease. Run `-WhatIf` to validate the
working tree without changing files, Git, or GitHub.