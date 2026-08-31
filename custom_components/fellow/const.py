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

# Polling
DEFAULT_POLL_INTERVAL = 10  # seconds
MIN_POLL_INTERVAL = 5
MAX_POLL_INTERVAL = 60

DEFAULT_SYNC_UNITS = False

# Temperature limits
MIN_TEMP_C = 40  # Minimum kettle can be set to
MAX_TEMP_C = 100  # Maximum (boiling point)
MIN_TEMP_F = 104  # Minimum in Fahrenheit
MAX_TEMP_F = 212  # Maximum in Fahrenheit (boiling point)
