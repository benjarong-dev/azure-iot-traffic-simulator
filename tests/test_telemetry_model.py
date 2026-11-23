"""Unit tests for traffic emission calculations, auth validation, and CLI dry-run."""

from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
import unittest

from src.cli import main as cli_main
from src.iot_publisher import parse_and_validate_connection_string
from src.telemetry_model import (
    DEFAULT_CORRIDORS,
    build_default_fleet,
    compute_diurnal_demand,
    estimate_emissions_and_policy,
)


class TelemetryModelTestSuite(unittest.TestCase):
    def test_rush_hour_demand_exceeds_overnight_baseline(self) -> None:
        overnight = compute_diurnal_demand(2.0)
        morning_rush = compute_diurnal_demand(8.0)
        evening_rush = compute_diurnal_demand(17.75)

        self.assertGreater(morning_rush, overnight)
        self.assertGreater(evening_rush, overnight)
        self.assertGreater(morning_rush, 0.75)
        self.assertLess(overnight, 0.25)

    def test_severe_gridlock_triggers_extend_green_and_higher_pm25(self) -> None:
        asoke_profile = DEFAULT_CORRIDORS[1]
        _, free_queue, free_co2, free_pm25, free_action = estimate_emissions_and_policy(
            asoke_profile, velocity_kmh=46.0
        )
        _, jam_queue, jam_co2, jam_pm25, jam_action = estimate_emissions_and_policy(
            asoke_profile, velocity_kmh=11.0
        )

        self.assertEqual(free_action, "NORMAL_CYCLE")
        self.assertEqual(jam_action, "EXTEND_GREEN")
        self.assertGreater(jam_queue, free_queue)
        self.assertGreater(jam_co2, free_co2)
        self.assertGreater(jam_pm25, free_pm25)

    def test_deterministic_seed_reproduces_identical_fleet_readings(self) -> None:
        fixed_ts = datetime(2026, 11, 23, 1, 30, tzinfo=timezone.utc)
        fleet_a = build_default_fleet(seed=42)
        fleet_b = build_default_fleet(seed=42)

        readings_a = [
            node.next_reading(now_utc=fixed_ts, local_hour_override=8.0).to_dict()
            for node in fleet_a
        ]
        readings_b = [
            node.next_reading(now_utc=fixed_ts, local_hour_override=8.0).to_dict()
            for node in fleet_b
        ]
        self.assertEqual(readings_a, readings_b)

    def test_connection_string_validation_blocks_missing_and_placeholder_keys(self) -> None:
        with self.assertRaises(ValueError):
            parse_and_validate_connection_string("")

        with self.assertRaises(ValueError):
            parse_and_validate_connection_string(
                "HostName=test.azure-devices.net;DeviceId=dev01;"
                "SharedAccessKey=REPLACE_WITH_SHARED_ACCESS_KEY"
            )

        parsed = parse_and_validate_connection_string(
            "HostName=bkk-iot.azure-devices.net;DeviceId=BKK-ASOKE-02;SharedAccessKey=dGVzdGtleQ=="
        )
        self.assertEqual(parsed["HostName"], "bkk-iot.azure-devices.net")
        self.assertEqual(parsed["DeviceId"], "BKK-ASOKE-02")

    def test_cli_dry_run_emits_valid_json_lines_without_cloud_sdk(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = cli_main(
                ["--ticks", "2", "--interval", "0", "--hour-override", "8", "--seed", "42", "--dry-run"]
            )

        self.assertEqual(exit_code, 0)
        lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(lines), 6)

        sample = json.loads(lines[0])
        self.assertIn("pm25_ug_m3", sample)
        self.assertIn("co2_emission_g_per_km", sample)
        self.assertIn("signal_recommendation", sample)


if __name__ == "__main__":
    unittest.main()
