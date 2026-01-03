"""Constants for the Fellow integration."""

DOMAIN = "fellow"

# Configuration
CONF_TEMPERATURE_UNIT = "temperature_unit"

# Temperature units (matches kettle's internal values)
UNIT_CELSIUS = "celsius"
UNIT_FAHRENHEIT = "fahrenheit"

# Temperature limits (verified from kettle hardware)
MIN_TEMP_C = 40  # Minimum kettle can be set to
MAX_TEMP_C = 100  # Maximum (boiling point)
MIN_TEMP_F = 104  # Minimum in Fahrenheit
MAX_TEMP_F = 212  # Maximum in Fahrenheit (boiling point)

# Internal value format ("2C" - 2x Celsius)
MIN_VALUE_2C = 80   # 40°C * 2
MAX_VALUE_2C = 200  # 100°C * 2
