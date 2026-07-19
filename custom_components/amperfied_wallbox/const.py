"""Constants for the Amperfied Wallbox integration.

See PROTOCOL.md in the repo root for the full protocol documentation these
constants are based on.
"""
from __future__ import annotations

DOMAIN = "amperfied_wallbox"

# --- Config Entry Keys ---
CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_DEVICE_PREFIX = "device_prefix"  # e.g. "hdm-smart-connect-abc123"

DEFAULT_PORT = 443
DEFAULT_MQTT_PATH = "/mqtt"

# --- Timing ---
# Per PROTOCOL.md, the access token is valid for ~10 minutes -> refresh well before that.
TOKEN_REFRESH_INTERVAL_SECONDS = 480

# --- Command Topics (relative to device_prefix) ---
CMD_USER_AUTH = "api/cmd/user/auth"
CMD_USER_REFRESH_AUTH = "api/cmd/user/refreshAuth"
CMD_LOGIN = "api/cmd/login"
CMD_RFID_LIST_GET = "api/cmd/rfidList/get"
CMD_CLOG_GET = "api/cmd/clog/get"
CMD_ENERGYMANAGER_AUTHENTICATE = "api/cmd/energymanager/authenticate"

# --- Response Topics ---
RESP_USER_AUTH = "api/resp/user/auth"
RESP_USER_REFRESH_AUTH = "api/resp/user/refreshAuth"
RESP_LOGIN = "api/resp/login"
RESP_RFID_LIST_GET = "api/resp/rfidList/get"
RESP_CLOG_GET = "api/resp/clog/get"
RESP_ENERGYMANAGER_AUTHENTICATE = "api/resp/energymanager/authenticate"

# --- Telemetry topics the coordinator subscribes to ---
TOPIC_EV_STATE = "api/t/power/evState"
TOPIC_TEMP = "api/t/power/temp"
TOPIC_PHASES = "api/t/power/phases"
TOPIC_POWER_LIMIT = "api/t/power/powerLimit"
TOPIC_LIMITER = "api/t/power/limiter"
TOPIC_PHASE_SWITCH_STATE = "api/t/power/phaseSwitchState"
TOPIC_POWERMETER_POWER = "api/t/powermeter/power"
TOPIC_POWERMETER_ENERGY = "api/t/powermeter/energy"
TOPIC_POWERMETER_POWER_PER_PHASES = "api/t/powermeter/powerPerPhases"
TOPIC_POWERMETER_SENSOR = "api/t/powermeter/sensor"
TOPIC_WB_STATE = "api/t/chargectrl/wbState"
TOPIC_EM_STATE = "api/t/energymanager/emState"
TOPIC_CHARGE_PERMISSION = "api/t/energymanager/chargePermission"
TOPIC_GRID_MONITOR_LEADER = "api/t/loadbalancer/grid/monitor/leader"

ALL_TELEMETRY_TOPICS = [
    TOPIC_EV_STATE,
    TOPIC_TEMP,
    TOPIC_PHASES,
    TOPIC_POWER_LIMIT,
    TOPIC_LIMITER,
    TOPIC_PHASE_SWITCH_STATE,
    TOPIC_POWERMETER_POWER,
    TOPIC_POWERMETER_ENERGY,
    TOPIC_POWERMETER_POWER_PER_PHASES,
    TOPIC_POWERMETER_SENSOR,
    TOPIC_WB_STATE,
    TOPIC_EM_STATE,
    TOPIC_CHARGE_PERMISSION,
    TOPIC_GRID_MONITOR_LEADER,
]

# --- Static factory/device info topics (retained, essentially never change) ---
# See PROTOCOL.md, "Device/factory info" section. Fetched once via
# api.async_get_device_info() and merged into coordinator.data like telemetry.
TOPIC_EOL_SOFTWARE_VERSION = "api/eol/config/softwareVersion"
TOPIC_EOL_HARDWARE_VERSION = "api/eol/config/hardwareVersion"
TOPIC_EOL_BOX_SERIAL = "api/eol/canstartup/boxSerial"
TOPIC_EOL_ETH0_MAC = "api/eol/config/eth0_MAC"
TOPIC_EOL_WIFI_MAC = "api/eol/config/wifi_MAC"
TOPIC_CONF_INITIAL_PASSWORD = "api/conf/mqttapi/user/initialPassword"

# Topics fetched once via api.async_get_diagnostics_device_details(), used only
# for the diagnostics export (not merged into coordinator.data / no entities).
TOPIC_EOL_PRODUCT_NAME = "api/eol/canstartup/productName"
TOPIC_EOL_SOFTWARE_VARIANT = "api/eol/config/softwareVariant"
TOPIC_EOL_VAN30 = "api/eol/config/van30"
TOPIC_EOL_BOX_PART = "api/eol/canstartup/boxPart"
TOPIC_EOL_BOX_DATE = "api/eol/canstartup/boxDate"
TOPIC_EOL_HCB_PART = "api/eol/canstartup/hcbPart"
TOPIC_EOL_HCB_SERIAL = "api/eol/canstartup/hcbSerial"
TOPIC_EOL_HCB_DATE = "api/eol/canstartup/hcbDate"
TOPIC_EOL_HMI_PART = "api/eol/canstartup/hmiPart"
TOPIC_EOL_HMI_SERIAL = "api/eol/canstartup/hmiSerial"
TOPIC_EOL_HMI_DATE = "api/eol/canstartup/hmiDate"
TOPIC_EOL_RELAIS_AVAILABLE = "api/eol/canstartup/relaisAvailable"
TOPIC_EOL_MID_AVAILABLE = "api/eol/canstartup/midAvailable"
TOPIC_EOL_RFID_AVAILABLE = "api/eol/canstartup/rfidAvailable"
TOPIC_EOL_PLC_AVAILABLE = "api/eol/canstartup/plcAvailable"
TOPIC_EOL_RS485_AVAILABLE = "api/eol/canstartup/RS485available"
TOPIC_EOL_INCO_AVAILABLE = "api/eol/canstartup/incoAvailable"
TOPIC_EOL_MID_IDENTIFICATION = "api/eol/mid/identification"
TOPIC_CONF_PARAGRAPH14A = "api/conf/canstartup/paragraph14a"

# Synthetic key (not a real MQTT topic) for the most recent completed charge
# session, refreshed on startup and whenever the car is unplugged. Stored in
# coordinator.data like a telemetry topic for the sensor to read uniformly.
LAST_CHARGE_SESSION_KEY = "_last_charge_session"

# EV state values per EN 61851-1 (see PROTOCOL.md)
EV_STATE_NO_CAR = "A1"
