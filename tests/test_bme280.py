"""Tests for device/sensors/bme280.py.

Uses a fake I2C bus and crafted calibration blocks, so no hardware is needed.
"""

import unittest

import _support  # noqa: F401  (adjusts sys.path so device/ modules import)
from sensors import bme280
from sensors.base import SensorError

# A realistic BME280 calibration dataset (datasheet-style values).
REALISTIC_DIG = {
    "t1": 27504, "t2": 26435, "t3": -1000,
    "p1": 36477, "p2": -10685, "p3": 3024, "p4": 2855, "p5": 140,
    "p6": -7, "p7": 15500, "p8": -14600, "p9": 6000,
    "h1": 75, "h2": 350, "h3": 0, "h4": 290, "h5": 50, "h6": 30,
}


def pack_u16(buffer, offset, value):
    value &= 0xFFFF
    buffer[offset] = value & 0xFF
    buffer[offset + 1] = (value >> 8) & 0xFF


def calibration_blocks(dig):
    """Build the 0x88 (26-byte) and 0xE1 (7-byte) calibration blocks."""
    block_88 = bytearray(bme280.CALIB_0x88_LEN)
    pack_u16(block_88, 0, dig["t1"])
    pack_u16(block_88, 2, dig["t2"])
    pack_u16(block_88, 4, dig["t3"])
    pack_u16(block_88, 6, dig["p1"])
    pack_u16(block_88, 8, dig["p2"])
    pack_u16(block_88, 10, dig["p3"])
    pack_u16(block_88, 12, dig["p4"])
    pack_u16(block_88, 14, dig["p5"])
    pack_u16(block_88, 16, dig["p6"])
    pack_u16(block_88, 18, dig["p7"])
    pack_u16(block_88, 20, dig["p8"])
    pack_u16(block_88, 22, dig["p9"])
    block_88[25] = dig["h1"] & 0xFF

    block_e1 = bytearray(bme280.CALIB_0xE1_LEN)
    pack_u16(block_e1, 0, dig["h2"])
    block_e1[2] = dig["h3"] & 0xFF
    h4 = dig["h4"] & 0x0FFF
    h5 = dig["h5"] & 0x0FFF
    block_e1[3] = (h4 >> 4) & 0xFF
    block_e1[4] = (h4 & 0x0F) | ((h5 & 0x0F) << 4)
    block_e1[5] = (h5 >> 4) & 0xFF
    block_e1[6] = dig["h6"] & 0xFF
    return bytes(block_88), bytes(block_e1)


def make_registers(dig, adc_t=519888, adc_p=415148, adc_h=26214, chip_id=0x60):
    registers = bytearray(256)
    registers[bme280.CHIP_ID_REG] = chip_id
    block_88, block_e1 = calibration_blocks(dig)
    registers[bme280.CALIB_0x88_REG:
              bme280.CALIB_0x88_REG + len(block_88)] = block_88
    registers[bme280.CALIB_0xE1_REG:
              bme280.CALIB_0xE1_REG + len(block_e1)] = block_e1
    registers[0xF7] = (adc_p >> 12) & 0xFF
    registers[0xF8] = (adc_p >> 4) & 0xFF
    registers[0xF9] = (adc_p & 0x0F) << 4
    registers[0xFA] = (adc_t >> 12) & 0xFF
    registers[0xFB] = (adc_t >> 4) & 0xFF
    registers[0xFC] = (adc_t & 0x0F) << 4
    registers[0xFD] = (adc_h >> 8) & 0xFF
    registers[0xFE] = adc_h & 0xFF
    return registers


class FakeI2C:
    def __init__(self, registers, fail_read=False, fail_write=False,
                 short_read=False):
        self.registers = registers
        self.fail_read = fail_read
        self.fail_write = fail_write
        self.short_read = short_read
        self.writes = []

    def readfrom_mem(self, address, register, length):
        if self.fail_read:
            raise OSError("bus error")
        if self.short_read:
            return bytes(self.registers[register:register + max(0, length - 1)])
        return bytes(self.registers[register:register + length])

    def writeto_mem(self, address, register, data):
        if self.fail_write:
            raise OSError("bus error")
        self.writes.append((register, bytes(data)))
        for index, byte in enumerate(data):
            self.registers[register + index] = byte


def noop_sleep(milliseconds):
    return None


def make_driver(registers, **kwargs):
    return bme280.BME280(i2c=FakeI2C(registers, **kwargs), sleep=noop_sleep)


class CalibrationParsingTests(unittest.TestCase):
    def test_round_trip_realistic_values(self):
        block_88, block_e1 = calibration_blocks(REALISTIC_DIG)
        parsed = bme280.parse_calibration(block_88, block_e1)
        self.assertEqual(REALISTIC_DIG, parsed)

    def test_signed_values_are_handled(self):
        dig = dict(REALISTIC_DIG)
        dig.update({"t2": -100, "t3": -1, "p2": -2000, "p3": -1,
                    "h2": -300, "h4": -1000, "h5": -2000, "h6": -50})
        block_88, block_e1 = calibration_blocks(dig)
        parsed = bme280.parse_calibration(block_88, block_e1)
        self.assertEqual(-100, parsed["t2"])
        self.assertEqual(-2000, parsed["p2"])
        self.assertEqual(-300, parsed["h2"])
        self.assertEqual(-1000, parsed["h4"])
        self.assertEqual(-2000, parsed["h5"])
        self.assertEqual(-50, parsed["h6"])

    def test_short_blocks_are_rejected(self):
        with self.assertRaises(SensorError):
            bme280.parse_calibration(b"\x00", b"\x00")


class CompensationTests(unittest.TestCase):
    def test_temperature_exact_value(self):
        dig = dict(REALISTIC_DIG)
        dig.update({"t1": 0, "t2": 2048, "t3": 0})
        t_fine, temperature = bme280.compensate_temperature(dig, 1024000)
        self.assertEqual(128000, t_fine)
        self.assertEqual(2500, temperature)  # hundredths of a degree C

    def test_pressure_is_physically_plausible(self):
        t_fine, _ = bme280.compensate_temperature(REALISTIC_DIG, 519888)
        pressure = bme280.compensate_pressure(REALISTIC_DIG, 415148, t_fine)
        self.assertTrue(90000 <= pressure <= 105000, pressure)

    def test_pressure_responds_monotonically_to_adc(self):
        t_fine, _ = bme280.compensate_temperature(REALISTIC_DIG, 519888)
        low = bme280.compensate_pressure(REALISTIC_DIG, 415148, t_fine)
        high = bme280.compensate_pressure(REALISTIC_DIG, 416148, t_fine)
        self.assertNotEqual(low, high)
        self.assertLess(high, low)  # larger raw ADC -> lower compensated value

    def test_humidity_range(self):
        t_fine, _ = bme280.compensate_temperature(REALISTIC_DIG, 519888)
        humidity = bme280.compensate_humidity(REALISTIC_DIG, 26214, t_fine)
        self.assertTrue(0 <= humidity <= 419430400, humidity)
        self.assertTrue(0.0 <= humidity / 1024.0 <= 100.0)

    # Exact-value reference checks against the values decoded from the Bosch
    # BME280 datasheet compensation example (same calibration coefficients as
    # REALISTIC_DIG, with the datasheet's raw ADC values).

    def test_reference_example_temperature(self):
        t_fine, temperature = bme280.compensate_temperature(
            REALISTIC_DIG, 519888)
        self.assertEqual(128422, t_fine)
        self.assertEqual(2508, temperature)  # hundredths of a degree C = 25.08

    def test_reference_example_pressure(self):
        # The datasheet's 64-bit routine gives 100653 Pa; our 32-bit reference
        # routine gives 100656 Pa, within a few Pa of the datasheet value.
        t_fine, _ = bme280.compensate_temperature(REALISTIC_DIG, 519888)
        pressure = bme280.compensate_pressure(REALISTIC_DIG, 415148, t_fine)
        self.assertEqual(100656, pressure)
        self.assertAlmostEqual(100653, pressure, delta=10)

    def test_reference_example_humidity(self):
        # adc_H=26214 -> about 40.72 %RH. Regression for the defect where the
        # quadratic factor used a reassigned intermediate instead of the
        # original t_fine - 76800.
        t_fine = 128422
        humidity = bme280.compensate_humidity(REALISTIC_DIG, 26214, t_fine)
        self.assertEqual(41694, humidity)
        self.assertAlmostEqual(40.72, humidity / 1024.0, delta=0.05)


class DriverTests(unittest.TestCase):
    def test_initialize_and_read(self):
        driver = make_driver(make_registers(REALISTIC_DIG))
        self.assertTrue(driver.initialize())
        reading = driver.read()
        self.assertIn("temperature_c", reading)
        self.assertIn("pressure_pa", reading)
        self.assertIn("humidity_pct", reading)
        self.assertIsInstance(reading["temperature_c"], float)
        self.assertIsInstance(reading["humidity_pct"], float)
        self.assertTrue(90000 <= reading["pressure_pa"] <= 105000)

    def test_wrong_chip_id_is_rejected(self):
        driver = make_driver(make_registers(REALISTIC_DIG, chip_id=0x58))
        with self.assertRaises(SensorError):
            driver.initialize()

    def test_read_before_initialize_is_rejected(self):
        driver = make_driver(make_registers(REALISTIC_DIG))
        with self.assertRaises(SensorError):
            driver.read()

    def test_read_failure_is_wrapped(self):
        driver = make_driver(make_registers(REALISTIC_DIG))
        driver.initialize()
        driver._i2c.fail_read = True
        with self.assertRaises(SensorError):
            driver.read()

    def test_short_read_is_rejected(self):
        driver = make_driver(make_registers(REALISTIC_DIG), short_read=True)
        with self.assertRaises(SensorError):
            driver.chip_id()

    def test_write_failure_is_wrapped(self):
        driver = make_driver(make_registers(REALISTIC_DIG), fail_write=True)
        with self.assertRaises(SensorError):
            driver.initialize()

    def test_configure_writes_expected_registers(self):
        fake = FakeI2C(make_registers(REALISTIC_DIG))
        driver = bme280.BME280(i2c=fake, sleep=noop_sleep)
        driver.initialize()
        written = dict(fake.writes)
        self.assertEqual(bme280.CTRL_HUM_VALUE, written[bme280.CTRL_HUM_REG][0])
        self.assertEqual(bme280.CTRL_MEAS_VALUE, written[bme280.CTRL_MEAS_REG][0])


if __name__ == "__main__":
    unittest.main()
