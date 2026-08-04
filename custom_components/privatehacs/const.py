"""Constants for PrivateHACS."""

DOMAIN = "privatehacs"
NAME = "PrivateHACS"

CONF_GITHUB_USERNAME = "github_username"
CONF_GITHUB_TOKEN = "github_token"

PLATFORMS: list[str] = []
STORAGE_KEY = f"{DOMAIN}.repositories"
STORAGE_VERSION = 1

GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"

DATA_RUNTIMES = "runtimes"
DATA_WEBSOCKET_REGISTERED = "websocket_registered"
DATA_PANEL_STATIC_REGISTERED = "panel_static_registered"

PANEL_URL_PATH = DOMAIN
PANEL_COMPONENT_NAME = "privatehacs-panel"
PANEL_MODULE_URL = f"/{DOMAIN}_static/privatehacs-panel.js"

WS_LIST_REPOSITORIES = f"{DOMAIN}/repositories"
WS_INSTALL_REPOSITORY = f"{DOMAIN}/install"