"""Azure IoT Hub MQTT publisher with secret-safe validation and dry-run support."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Dict, Optional

from .telemetry_model import TelemetryReading

ENV_VAR_NAME = "IOTHUB_DEVICE_CONNECTION_STRING"
REQUIRED_CONN_KEYS = ("HostName", "DeviceId", "SharedAccessKey")


def load_dotenv_if_present(dotenv_path: Optional[Path] = None) -> None:
    """Loads key=value pairs from a local .env file without third-party packages."""
    target = dotenv_path if dotenv_path is not None else Path(".env")
    if not target.is_file():
        return

    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        clean_key = key.strip()
        clean_val = value.strip().strip('"').strip("'")
        if clean_key and clean_key not in os.environ:
            os.environ[clean_key] = clean_val


def parse_and_validate_connection_string(conn_str: str) -> Dict[str, str]:
    """Validates IoT Hub connection string structure without leaking secrets."""
    if not conn_str or not conn_str.strip():
        raise ValueError(
            f"Missing environment variable {ENV_VAR_NAME}. "
            "Set it or run with --dry-run for local verification."
        )

    parts: Dict[str, str] = {}
    for segment in conn_str.strip().split(";"):
        if not segment:
            continue
        if "=" not in segment:
            raise ValueError("Malformed connection string segment (expected Key=Value).")
        key, val = segment.split("=", 1)
        parts[key.strip()] = val.strip()

    missing = [k for k in REQUIRED_CONN_KEYS if not parts.get(k)]
    if missing:
        raise ValueError(
            f"Connection string missing required fields: {', '.join(missing)}"
        )

    if parts["SharedAccessKey"] == "REPLACE_WITH_SHARED_ACCESS_KEY":
        raise ValueError(
            "Placeholder SharedAccessKey detected. Replace with a valid device key "
            "or execute with --dry-run."
        )

    return parts


class TelemetryPublisher:
    """Publishes telemetry either to stdout (--dry-run) or Azure IoT Hub via MQTT."""

    def __init__(self, dry_run: bool = False, conn_str: Optional[str] = None) -> None:
        self.dry_run = dry_run
        self._client = None
        self.hub_hostname = "offline-dry-run"

        if not self.dry_run:
            load_dotenv_if_present()
            raw_conn = conn_str if conn_str is not None else os.environ.get(ENV_VAR_NAME, "")
            parsed = parse_and_validate_connection_string(raw_conn)
            self.hub_hostname = parsed["HostName"]

            try:
                from azure.iot.device import IoTHubDeviceClient
            except ImportError as exc:
                raise RuntimeError(
                    "Package 'azure-iot-device' is not installed. "
                    "Install requirements.txt or pass --dry-run."
                ) from exc

            self._client = IoTHubDeviceClient.create_from_connection_string(raw_conn)
            self._client.connect()

    def publish(self, reading: TelemetryReading) -> None:
        payload_json = json.dumps(reading.to_dict(), ensure_ascii=False)

        if self.dry_run:
            sys.stdout.write(payload_json + "\n")
            sys.stdout.flush()
            return

        from azure.iot.device import Message

        msg = Message(payload_json)
        msg.content_type = "application/json"
        msg.content_encoding = "utf-8"
        msg.custom_properties["signalAlert"] = (
            "true" if reading.signal_recommendation == "EXTEND_GREEN" else "false"
        )
        msg.custom_properties["highPm25"] = (
            "true" if reading.pm25_ug_m3 >= 50.0 else "false"
        )
        self._client.send_message(msg)

    def close(self) -> None:
        if self._client is not None:
            self._client.shutdown()
            self._client = None
