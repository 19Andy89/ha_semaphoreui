"""Constants for the Semaphore UI integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "semaphore_ui"

CONF_API_TOKEN: Final = "api_token"
CONF_PROJECT_ID: Final = "project_id"
CONF_PROJECT_NAME: Final = "project_name"

# Polling: normal interval and the faster interval while a task is active.
DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 600
ACTIVE_SCAN_INTERVAL: Final = 5

# Action `run_template` with wait=true
WAIT_POLL_SECONDS: Final = 2.0
DEFAULT_WAIT_TIMEOUT: Final = 600

# Events (payload = the report dict, see report.py)
EVENT_TASK_STARTED: Final = f"{DOMAIN}_task_started"
EVENT_TASK_FINISHED: Final = f"{DOMAIN}_task_finished"

# Task status values used by Semaphore (pkg/task_logger/task_logger.go)
STATUS_NEVER_RUN: Final = "never_run"
STATUS_ACTIVE: Final = frozenset(
    {
        "waiting",
        "starting",
        "waiting_confirmation",
        "confirmed",
        "running",
        "stopping",
    }
)
# "rejected" is treated as final here, otherwise waiting for it could hang.
STATUS_FINISHED: Final = frozenset({"success", "error", "stopped", "rejected"})
STATUS_OPTIONS: Final = [
    STATUS_NEVER_RUN,
    "waiting",
    "starting",
    "waiting_confirmation",
    "confirmed",
    "running",
    "stopping",
    "success",
    "error",
    "stopped",
    "rejected",
]

# Template apps for which a dry run (ansible-playbook --check) makes sense
DRY_RUN_APPS: Final = frozenset({"", "ansible"})

MANUFACTURER: Final = "Semaphore UI"
MODEL_PROJECT: Final = "Project"
MODEL_TEMPLATE: Final = "Template"

# Option: start a template although one of its runs is already queued or running
CONF_ALLOW_PARALLEL: Final = "allow_parallel_runs"

# Option: templates that get no devices/entities in Home Assistant (ids). New templates
# of Semaphore are not in the list, so they show up as usual.
CONF_EXCLUDED_TEMPLATES: Final = "excluded_templates"
# Field of the options dialog: the templates that are *shown* (everything else is excluded)
CONF_TEMPLATES: Final = "templates"

# Repairs (Settings -> Repairs): a connection problem must last this long (seconds)
# before it is reported; a rejected token is reported at once.
REPAIR_AFTER: Final = 600
ISSUE_TOKEN: Final = "token_rejected"
ISSUE_UNREACHABLE: Final = "unreachable"
ISSUE_PROJECT: Final = "project_missing"
ISSUE_KINDS: Final = (ISSUE_TOKEN, ISSUE_UNREACHABLE, ISSUE_PROJECT)
# "the token expires soon" is managed by the token check (not removed by a successful poll)
ISSUE_TOKEN_EXPIRING: Final = "token_expiring"
ISSUE_ALL: Final = (*ISSUE_KINDS, ISSUE_TOKEN_EXPIRING)

# Token care (0.3.0): show when the API token expires, replace it before that and, with a
# stored login, replace a token that was rejected.
CONF_LIVE: Final = "live_updates"  # option: follow running tasks over the WebSocket
CONF_KEEP_RECENT: Final = "keep_recent"  # option: keep a template "visible" for 24 h after its run
RECENT_HOURS: Final = 24
CONF_RENEW_TOKEN: Final = "renew_token"  # option: replace the token before it expires
CONF_TOKEN_DAYS: Final = "token_days"  # option: warn / replace when fewer days are left
CONF_RENEW_USER: Final = "renew_username"  # option: stored login (optional)
CONF_RENEW_PASSWORD: Final = "renew_password"
CONF_CLEAR_LOGIN: Final = "clear_login"  # field of the options dialog only
DEFAULT_TOKEN_DAYS: Final = 7
MIN_TOKEN_DAYS: Final = 1
MAX_TOKEN_DAYS: Final = 60
# lifetime of a new token when the lifetime of the old one is not known
DEFAULT_NEW_TOKEN_DAYS: Final = 90
TOKEN_SCAN_INTERVAL: Final = 60 * 60
TOKEN_NAME: Final = "Home Assistant (semaphore_ui)"

# Optional check for a new Semaphore release (one request to GitHub per interval)
CONF_CHECK_UPDATES: Final = "check_for_updates"
GITHUB_LATEST_URL: Final = (
    "https://api.github.com/repos/semaphoreui/semaphore/releases/latest"
)
# A Docker installation can only update to a release whose image exists. GitHub and Docker Hub
# publish at different times, so for a Docker build the tag is looked up before an update is shown.
DOCKER_TAG_URL: Final = "https://hub.docker.com/v2/repositories/semaphoreui/semaphore/tags/{tag}"
VERSION_SCAN_INTERVAL: Final = 6 * 60 * 60

# Event types of the project "Tasks" event entity
EVENT_TYPES: Final = ["started", "success", "failed", "stopped"]

# Dashboard cards that ship with the integration
CARD_URL_BASE: Final = "/semaphore_ui_static"
CARD_FILE: Final = "semaphore-ui-card.js"
