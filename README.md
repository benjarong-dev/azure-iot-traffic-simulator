# Urban Traffic & Roadside PM2.5 IoT Telemetry Simulator (Azure IoT Hub)

Modular Python telemetry edge simulator modeling urban arterial traffic flow, vehicle queue length, and roadside particulate matter (`PM2.5`) emissions for **Azure IoT Hub** ingestion over **MQTT/TLS**. Includes a zero-credential `--dry-run` mode and deterministic unit tests for local verification.

## Architecture & Data Pipeline

```text
+-----------------------------------+        MQTT v3.1.1 / TLS 1.2         +-----------------------+
|   Edge Intersection Simulators    | ===================================> |     Azure IoT Hub     |
| (BKK-RAMA4, BKK-ASOKE, BKK-SATHORN)|   JSON Telemetry (Env-Scoped Auth)   | (Device-to-Cloud D2C) |
+-----------------------------------+                                      +-----------+-----------+
  | 1. Diurnal rush-hour traffic curve                                                 |
  | 2. Mean-reverting velocity & queue model                                           v
  | 3. Stop-and-go idling PM2.5 / CO2 estimator                            +-----------------------+
  +--> Adaptive signal recommendation                                      | Stream Analytics / DB |
       (NORMAL_CYCLE / ADAPTIVE_HOLD / EXTEND_GREEN)                       +-----------------------+
```

## Repository Structure

```text
azure-iot-traffic-simulator/
├── .env.example                    # Template for Azure IoT Hub environment variables
├── .gitignore                      # Excludes .env secrets, virtualenvs, and bytecode
├── LICENSE                         # MIT License
├── requirements.txt                # Pinned Azure IoT SDK dependency
├── src/
│   ├── __init__.py
│   ├── cli.py                      # Argparse CLI entrypoint & graceful signal handling
│   ├── iot_publisher.py            # Azure IoT Hub MQTT client & offline dry-run publisher
│   └── telemetry_model.py          # Diurnal congestion, queue, and PM2.5 emission model
└── tests/
    └── test_telemetry_model.py     # Built-in unittest suite (zero external dependencies)
```

## Telemetry & Emission Model Mechanics

Instead of uniform random numbers, each sensor node computes state transitions from time-of-day traffic demand and stop-and-go emission factors:

| Metric Field | Unit | Modeling Logic |
|---|---|---|
| `avg_velocity_kmh` | `km/h` | Mean-reverting speed driven by morning (`07:00-09:30`) and evening (`16:30-19:30`) rush-hour demand curves |
| `congestion_index` | `0.0 - 1.0` | Normalized ratio of speed reduction relative to corridor free-flow velocity |
| `estimated_queue_vehicles` | `vehicles` | Derived from lane count, congestion ratio, and signal cycle accumulation |
| `co2_emission_g_per_km` | `g/km` | Rises non-linearly below `20 km/h` due to inefficient low-gear stop-and-go combustion |
| `pm25_ug_m3` | `ug/m3` | Combines ambient urban background (`18.0 ug/m3`) with idling exhaust and brake/tire resuspension |
| `signal_recommendation` | `enum` | Emits `EXTEND_GREEN` when velocity drops below `15 km/h` or `PM2.5` exceeds `50 ug/m3` |

## Sample Device-to-Cloud JSON Payload

```json
{
  "schema_version": "1.0",
  "device_id": "BKK-ASOKE-02",
  "corridor_name": "Asoke - Sukhumvit",
  "timestamp_utc": "2026-11-23T01:30:00Z",
  "avg_velocity_kmh": 12.4,
  "free_flow_kmh": 50.0,
  "congestion_index": 0.752,
  "estimated_queue_vehicles": 34,
  "co2_emission_g_per_km": 298.6,
  "pm25_ug_m3": 56.4,
  "signal_recommendation": "EXTEND_GREEN"
}
```

## Security & Credential Management

Device credentials are **never** hardcoded in source files. Live MQTT transmission reads the connection string strictly from the `IOTHUB_DEVICE_CONNECTION_STRING` environment variable:

```bash
cp .env.example .env
# Populate IOTHUB_DEVICE_CONNECTION_STRING inside .env (ignored by Git)
```

## Local Verification & Usage

### 1. Run Unit Tests (No Cloud Credentials or Extra Packages Required)

```bash
git clone https://github.com/benjarong-dev/azure-iot-traffic-simulator.git
cd azure-iot-traffic-simulator

python3 -m unittest discover -s tests -v
```

### 2. Run Offline Telemetry Dry-Run (Streams JSON to Terminal)

```bash
python3 -m src.cli --ticks 3 --interval 1.0 --hour-override 8 --seed 42 --dry-run
```

### 3. Stream Live Telemetry to Azure IoT Hub (MQTT over TLS)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export IOTHUB_DEVICE_CONNECTION_STRING="HostName=<your-hub>.azure-devices.net;DeviceId=<device-id>;SharedAccessKey=<key>"
python3 -m src.cli --interval 5.0
```

## License

Distributed under the MIT License. See `LICENSE` for details.
