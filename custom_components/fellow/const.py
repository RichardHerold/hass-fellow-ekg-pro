"""Constants for the Fellow integration."""

DOMAIN = "fellow"

# Configuration
CONF_TEMPERATURE_UNIT = "temperature_unit"
CONF_TEMP_SET_METHOD = "temp_set_method"
CONF_POLL_INTERVAL = "poll_interval"
CONF_SYNC_UNITS = "sync_kettle_units"

# Temperature units (matches kettle's internal values)
UNIT_CELSIUS = "celsius"
UNIT_FAHRENHEIT = "fahrenheit"

# Temperature-setting methods
# - direct: firmware set-target command with verification (fast, preferred)
# - dial:   emulate physical dial via left/right step commands (compatible fallback)
TEMP_METHOD_DIRECT = "direct"
TEMP_METHOD_DIAL = "dial"

# Polling. The idle interval applies when the kettle is off; while a
# heat/hold cycle is active the coordinator switches to the faster active
# interval so the climbing temperature (and Water Ready) track closely.
CONF_ACTIVE_POLL_INTERVAL = "active_poll_interval"
DEFAULT_POLL_INTERVAL = 10  # seconds, idle
MIN_POLL_INTERVAL = 5
MAX_POLL_INTERVAL = 60
DEFAULT_ACTIVE_POLL_INTERVAL = 3  # seconds, while heating/holding
MIN_ACTIVE_POLL_INTERVAL = 2
MAX_ACTIVE_POLL_INTERVAL = 60

DEFAULT_SYNC_UNITS = False

# User-defined temperature presets ("Name: temp" pairs, see presets.py)
CONF_PRESETS = "presets"
DEFAULT_PRESETS = ""

# Keep the kettle's display clock synced to HA time (daily + on setup)
CONF_SYNC_CLOCK = "sync_clock"
DEFAULT_SYNC_CLOCK = False

# Custom action: set target and start heating in one call
SERVICE_HEAT_TO = "heat_to"

# Temperature limits
MIN_TEMP_C = 40  # Minimum kettle can be set to
MAX_TEMP_C = 100  # Maximum (boiling point)
MIN_TEMP_F = 104  # Minimum in Fahrenheit
MAX_TEMP_F = 212  # Maximum in Fahrenheit (boiling point)
