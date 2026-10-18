"""BME280 temperature, pressure, and humidity driver (I2C).

Only the hardware driver lives here. Unit conversion, sea-level estimation,
and pressure-trend handling live in ``sensors/weather.py``.

Wiring for this device (confirmed, sensor tested on the ESP32):

- I2C SDA: GPIO 16
- I2C SCL: GPIO 17
- I2C address: 0x76 (0x77 is accepted as an alternative)

The MicroPython ``machine`` module is imported lazily inside
:meth:`BME280._get_i2c`, so this module can be imported and its pure
parsing/compensation helpers unit-tested on the development computer. The
``i2c`` constructor argument lets tests inject a fake bus.
"""

from sensors.base import SensorError

DEFAULT_ADDRESS = 0x76
ALTERNATE_ADDRESS = 0x77
DEFAULT_SDA_PIN = 16
DEFAULT_SCL_PIN = 17
DEFAULT_I2C_FREQ = 400000

CHIP_ID_REG = 0xD0
CHIP_ID_BME280 = 0x60
CALIB_0x88_REG = 0x88
CALIB_0x88_LEN = 26  # 0x88..0xA1
CALIB_0xE1_REG = 0xE1
CALIB_0xE1_LEN = 7   # 0xE1..0xE7
CTRL_HUM_REG = 0xF2
CTRL_MEAS_REG = 0xF4
CONFIG_REG = 0xF5
DATA_REG = 0xF7
DATA_LEN = 8         # 0xF7..0xFE

# Oversampling x1, normal mode (datasheet values; conservative and compact).
CTRL_HUM_VALUE = 0x01
CTRL_MEAS_VALUE = 0x27
CONFIG_VALUE = 0x00

# Temperature compensation returns hundredths of a degree Celsius; humidity
# compensation returns 1024ths of a percent relative humidity.
TEMPERATURE_SCALE = 100.0
HUMIDITY_SCALE = 1024.0


def _default_sleep_ms(milliseconds):
    """Sleep for a short configuration delay (MicroPython or host)."""
    import time
    if hasattr(time, "sleep_ms"):
        time.sleep_ms(milliseconds)
    else:
        time.sleep(milliseconds / 1000.0)


def _u16(data, offset):
    return data[offset] | (data[offset + 1] << 8)


def _s16(data, offset):
    value = data[offset] | (data[offset + 1] << 8)
    if value >= 0x8000:
        value -= 0x10000
    return value


def _s8(value):
    value &= 0xFF
    if value >= 0x80:
        value -= 0x100
    return value


def _s12(value):
    value &= 0x0FFF
    if value >= 0x0800:
        value -= 0x1000
    return value


def parse_calibration(block_88, block_e1):
    """Parse the two BME280 calibration blocks into a ``dig_*`` dict.

    ``block_88`` covers 0x88..0xA1 (26 bytes) and ``block_e1`` covers
    0xE1..0xE7 (7 bytes). Raises SensorError on a short block.
    """
    if block_88 is None or len(block_88) < CALIB_0x88_LEN:
        raise SensorError("short calibration block 0x88")
    if block_e1 is None or len(block_e1) < CALIB_0xE1_LEN:
        raise SensorError("short calibration block 0xE1")
    return {
        "t1": _u16(block_88, 0),
        "t2": _s16(block_88, 2),
        "t3": _s16(block_88, 4),
        "p1": _u16(block_88, 6),
        "p2": _s16(block_88, 8),
        "p3": _s16(block_88, 10),
        "p4": _s16(block_88, 12),
        "p5": _s16(block_88, 14),
        "p6": _s16(block_88, 16),
        "p7": _s16(block_88, 18),
        "p8": _s16(block_88, 20),
        "p9": _s16(block_88, 22),
        "h1": block_88[25],
        "h2": _s16(block_e1, 0),
        "h3": block_e1[2],
        "h4": _s12((block_e1[3] << 4) | (block_e1[4] & 0x0F)),
        "h5": _s12((block_e1[5] << 4) | (block_e1[4] >> 4)),
        "h6": _s8(block_e1[6]),
    }


def compensate_temperature(dig, adc_temperature):
    """Return ``(t_fine, temperature_centi_c)`` from a raw temperature ADC.

    Integer arithmetic follows the Bosch reference implementation.
    """
    var1 = ((((adc_temperature >> 3) - (dig["t1"] << 1))) * dig["t2"]) >> 11
    var2 = (((((adc_temperature >> 4) - dig["t1"])
              * ((adc_temperature >> 4) - dig["t1"])) >> 12) * dig["t3"]) >> 14
    t_fine = var1 + var2
    temperature = (t_fine * 5 + 128) >> 8
    return t_fine, temperature


def compensate_pressure(dig, adc_pressure, t_fine):
    """Return pressure in pascals from a raw pressure ADC and ``t_fine``.

    Uses the 32-bit Bosch reference routine, which suits MicroPython's
    integer arithmetic.
    """
    var1 = (t_fine >> 1) - 64000
    var2 = ((((var1 >> 2) * (var1 >> 2)) >> 11) * dig["p6"])
    var2 = var2 + ((var1 * dig["p5"]) << 1)
    var2 = (var2 >> 2) + (dig["p4"] << 16)
    var1 = ((((dig["p3"] * (((var1 >> 2) * (var1 >> 2)) >> 13)) >> 3)
             + ((dig["p2"] * var1) >> 1)) >> 18)
    var1 = (((32768 + var1) * dig["p1"]) >> 15)
    if var1 == 0:
        return 0
    pressure = ((1048576 - adc_pressure) - (var2 >> 12)) * 3125
    if pressure < 0:
        return 0
    if pressure < 0x80000000:
        pressure = (pressure << 1) // var1
    else:
        pressure = (pressure // var1) * 2
    var1 = (dig["p9"] * (((pressure >> 3) * (pressure >> 3)) >> 13)) >> 12
    var2 = ((pressure >> 2) * dig["p8"]) >> 13
    pressure = pressure + ((var1 + var2 + dig["p7"]) >> 4)
    return pressure


def compensate_humidity(dig, adc_humidity, t_fine):
    """Return humidity in 1024ths of a percent from a raw humidity ADC.

    Uses the 32-bit Bosch reference routine. The intermediate value
    ``t_fine - 76800`` feeds both the linear term and the quadratic factor,
    so it is kept in its own variable (``v_x1``) to mirror the reference:
    both factors must use this original value, not a reassigned one.
    """
    v_x1 = t_fine - 76800
    var_h = ((((adc_humidity << 14) - (dig["h4"] << 20)
               - (dig["h5"] * v_x1)) + 16384) >> 15) \
        * (((((((v_x1 * dig["h6"]) >> 10)
               * (((v_x1 * dig["h3"]) >> 11) + 32768)) >> 10)
             + 2097152) * dig["h2"] + 8192) >> 14)
    var_h = var_h - (((((var_h >> 15) * (var_h >> 15)) >> 7)
                      * dig["h1"]) >> 4)
    if var_h < 0:
        var_h = 0
    elif var_h > 419430400:
        var_h = 419430400
    return var_h >> 12


class BME280:
    """Minimal BME280 driver returning temperature, pressure, and humidity."""

    def __init__(self, i2c=None, address=None, sda_pin=None, scl_pin=None,
                 freq=DEFAULT_I2C_FREQ, sleep=None):
        self._i2c = i2c
        self._address = DEFAULT_ADDRESS if address is None else address
        self._sda_pin = DEFAULT_SDA_PIN if sda_pin is None else sda_pin
        self._scl_pin = DEFAULT_SCL_PIN if scl_pin is None else scl_pin
        self._freq = freq
        self._sleep = sleep if sleep is not None else _default_sleep_ms
        self._dig = None
        self._initialized = False

    # -- low-level bus --------------------------------------------------
    def _get_i2c(self):
        if self._i2c is None:
            from machine import I2C, Pin
            self._i2c = I2C(0, sda=Pin(self._sda_pin), scl=Pin(self._scl_pin),
                            freq=self._freq)
        return self._i2c

    def _read_registers(self, register, length):
        try:
            data = self._get_i2c().readfrom_mem(self._address, register, length)
        except Exception as exc:  # noqa: BLE001 - report as a sensor failure
            raise SensorError("I2C read failed: %s" % exc)
        if data is None or len(data) < length:
            raise SensorError("short I2C read")
        return data

    def _write_register(self, register, value):
        try:
            self._get_i2c().writeto_mem(self._address, register, bytes([value]))
        except Exception as exc:  # noqa: BLE001 - report as a sensor failure
            raise SensorError("I2C write failed: %s" % exc)

    # -- API ------------------------------------------------------------
    def chip_id(self):
        """Return the BME280 chip id register (0x60 for a BME280)."""
        return self._read_registers(CHIP_ID_REG, 1)[0]

    def initialize(self):
        """Verify the chip id, load calibration, and start measurements."""
        chip_id = self.chip_id()
        if chip_id != CHIP_ID_BME280:
            raise SensorError("unexpected chip id 0x%02X (expected 0x60)"
                              % chip_id)
        self._dig = parse_calibration(
            self._read_registers(CALIB_0x88_REG, CALIB_0x88_LEN),
            self._read_registers(CALIB_0xE1_REG, CALIB_0xE1_LEN),
        )
        self._write_register(CTRL_HUM_REG, CTRL_HUM_VALUE)
        self._write_register(CONFIG_REG, CONFIG_VALUE)
        self._write_register(CTRL_MEAS_REG, CTRL_MEAS_VALUE)
        self._sleep(10)
        self._initialized = True
        return True

    def read(self):
        """Return ``{"temperature_c", "pressure_pa", "humidity_pct"}``."""
        if not self._initialized or self._dig is None:
            raise SensorError("BME280 not initialized")
        data = self._read_registers(DATA_REG, DATA_LEN)
        adc_pressure = (data[0] << 12) | (data[1] << 4) | (data[2] >> 4)
        adc_temperature = (data[3] << 12) | (data[4] << 4) | (data[5] >> 4)
        adc_humidity = (data[6] << 8) | data[7]

        t_fine, temperature = compensate_temperature(self._dig, adc_temperature)
        pressure = compensate_pressure(self._dig, adc_pressure, t_fine)
        humidity = compensate_humidity(self._dig, adc_humidity, t_fine)
        return {
            "temperature_c": temperature / TEMPERATURE_SCALE,
            "pressure_pa": pressure,
            "humidity_pct": humidity / HUMIDITY_SCALE,
        }
