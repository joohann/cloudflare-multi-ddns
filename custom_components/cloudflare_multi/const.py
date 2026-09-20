"""Constants for the Cloudflare Multi Dynamic DNS integration."""
from datetime import timedelta

DOMAIN = "cloudflare_multi"

# Config entry / options keys
CONF_API_TOKEN = "api_token"
CONF_RECORDS = "records"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_NOTIFY_PERSISTENT = "notify_persistent"
CONF_NOTIFY_EVENT = "notify_event"
CONF_NOTIFY_TARGETS = "notify_targets"

DEFAULT_NOTIFY_PERSISTENT = True
DEFAULT_NOTIFY_EVENT = True
DEFAULT_NOTIFY_TARGETS: list[str] = []

EVENT_DNS_UPDATED = "cloudflare_multi_updated"

CONF_DOMAIN_NAME = "domain"
CONF_RECORD_NAME = "name"
CONF_RECORD_TYPE = "record_type"

RECORD_TYPES = ["A", "AAAA"]
DEFAULT_RECORD_TYPE = "A"
DEFAULT_RECORD_NAME = "@"

DEFAULT_UPDATE_INTERVAL_MINUTES = 10
MIN_UPDATE_INTERVAL_MINUTES = 2
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=DEFAULT_UPDATE_INTERVAL_MINUTES)

# Cloudflare API v4
API_BASE_URL = "https://api.cloudflare.com/client/v4"
API_VERIFY_PATH = "/user/tokens/verify"
API_ZONES_PATH = "/zones"
API_DNS_PATH = "/zones/{zone_id}/dns_records"
API_DNS_RECORD_PATH = "/zones/{zone_id}/dns_records/{record_id}"

# Public IP lookup services (tried in order, first success wins)
IPV4_LOOKUP_URLS = [
    "https://api.ipify.org?format=json",
    "https://api4.ipify.org?format=json",
]
IPV6_LOOKUP_URLS = [
    "https://api6.ipify.org?format=json",
]

# Persistent storage for IP history (survives restarts)
STORAGE_VERSION = 1
STORAGE_KEY = DOMAIN

ATTR_DOMAIN = "domain"
ATTR_NAME = "name"
ATTR_TYPE = "type"
ATTR_LAST_CHECKED = "last_checked"
ATTR_LAST_UPDATED = "last_updated"
ATTR_STATUS = "status"
ATTR_PREVIOUS_IP = "previous_ip"
ATTR_CHANGED_AT = "changed_at"

STATUS_OK = "ok"
STATUS_UPDATED = "updated"
STATUS_NOT_FOUND = "record_not_found"
STATUS_ERROR = "error"
