"""Deterministic-capable urban traffic and roadside PM2.5 emission model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import random
from typing import Dict, List, Optional


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


@dataclass(frozen=True)
class CorridorProfile:
    """Static physical parameters of a monitored arterial intersection."""

    device_id: str
    corridor_name: str
    free_flow_kmh: float
    lane_count: int
    ambient_pm25_ug_m3: float = 18.0


@dataclass(frozen=True)
class TelemetryReading:
    """Immutable Device-to-Cloud (D2C) telemetry payload."""

    device_id: str
    corridor_name: str
    timestamp_utc: str
    avg_velocity_kmh: float
    free_flow_kmh: float
    congestion_index: float
    estimated_queue_vehicles: int
    co2_emission_g_per_km: float
    pm25_ug_m3: float
    signal_recommendation: str
    schema_version: str = "1.0"

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "device_id": self.device_id,
            "corridor_name": self.corridor_name,
            "timestamp_utc": self.timestamp_utc,
            "avg_velocity_kmh": self.avg_velocity_kmh,
            "free_flow_kmh": self.free_flow_kmh,
            "congestion_index": self.congestion_index,
            "estimated_queue_vehicles": self.estimated_queue_vehicles,
            "co2_emission_g_per_km": self.co2_emission_g_per_km,
            "pm25_ug_m3": self.pm25_ug_m3,
            "signal_recommendation": self.signal_recommendation,
        }


DEFAULT_CORRIDORS: tuple[CorridorProfile, ...] = (
    CorridorProfile(
        device_id="BKK-RAMA4-01",
        corridor_name="Rama IV - Silom",
        free_flow_kmh=55.0,
        lane_count=4,
        ambient_pm25_ug_m3=19.5,
    ),
    CorridorProfile(
        device_id="BKK-ASOKE-02",
        corridor_name="Asoke - Sukhumvit",
        free_flow_kmh=50.0,
        lane_count=4,
        ambient_pm25_ug_m3=20.0,
    ),
    CorridorProfile(
        device_id="BKK-SATHORN-03",
        corridor_name="North Sathorn - Naradhiwas",
        free_flow_kmh=58.0,
        lane_count=5,
        ambient_pm25_ug_m3=18.5,
    ),
)


def compute_diurnal_demand(local_hour: float) -> float:
    """Returns normalized traffic demand [0.12, 0.96] for a 24-hour local clock."""
    h = local_hour % 24.0
    morning_peak = 0.68 * math.exp(-((h - 8.0) ** 2) / 2.2)
    midday_activity = 0.28 * math.exp(-((h - 13.0) ** 2) / 8.5)
    evening_peak = 0.74 * math.exp(-((h - 17.75) ** 2) / 2.8)
    overnight_base = 0.14
    return _clamp(overnight_base + morning_peak + midday_activity + evening_peak, 0.12, 0.96)


def estimate_emissions_and_policy(
    profile: CorridorProfile,
    velocity_kmh: float,
) -> tuple[float, int, float, float, str]:
    """Computes congestion ratio, queue length, CO2, PM2.5, and signal action."""
    bounded_speed = _clamp(velocity_kmh, 4.0, profile.free_flow_kmh)
    congestion_idx = _clamp(1.0 - (bounded_speed / profile.free_flow_kmh), 0.0, 1.0)

    queue_vehicles = int(round(profile.lane_count * 13.5 * (congestion_idx ** 1.35)))

    low_gear_penalty = 0.0
    if bounded_speed < 25.0:
        low_gear_penalty = 185.0 * (((25.0 - bounded_speed) / 21.0) ** 1.35)
    co2_g_km = 142.0 + low_gear_penalty + (queue_vehicles * 0.95)

    idling_exhaust_pm25 = (congestion_idx ** 1.25) * 34.0
    resuspension_pm25 = queue_vehicles * 0.38
    pm25_ug_m3 = profile.ambient_pm25_ug_m3 + idling_exhaust_pm25 + resuspension_pm25

    if bounded_speed < 15.0 or pm25_ug_m3 >= 50.0:
        recommendation = "EXTEND_GREEN"
    elif bounded_speed < 25.0 or pm25_ug_m3 >= 37.5:
        recommendation = "ADAPTIVE_HOLD"
    else:
        recommendation = "NORMAL_CYCLE"

    return (
        round(congestion_idx, 3),
        queue_vehicles,
        round(co2_g_km, 1),
        round(pm25_ug_m3, 1),
        recommendation,
    )


class CorridorSensorNode:
    """Stateful edge sensor node with mean-reverting velocity transitions."""

    def __init__(
        self,
        profile: CorridorProfile,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.profile = profile
        self._rng = rng if rng is not None else random.Random()
        self._current_velocity = profile.free_flow_kmh * 0.65

    def next_reading(
        self,
        now_utc: Optional[datetime] = None,
        local_hour_override: Optional[float] = None,
    ) -> TelemetryReading:
        ts_utc = now_utc.astimezone(timezone.utc) if now_utc else datetime.now(timezone.utc)

        if local_hour_override is not None:
            effective_bkk_hour = float(local_hour_override) % 24.0
        else:
            effective_bkk_hour = ((ts_utc.hour + 7) % 24) + (ts_utc.minute / 60.0)

        demand = compute_diurnal_demand(effective_bkk_hour)
        target_speed = self.profile.free_flow_kmh * (1.0 - (0.82 * demand))
        jitter = self._rng.gauss(0.0, 1.85)

        next_speed = (0.55 * self._current_velocity) + (0.45 * target_speed) + jitter
        self._current_velocity = _clamp(next_speed, 4.5, self.profile.free_flow_kmh)
        rounded_speed = round(self._current_velocity, 1)

        congestion_idx, queue_len, co2_val, pm25_val, action = estimate_emissions_and_policy(
            self.profile,
            rounded_speed,
        )

        return TelemetryReading(
            device_id=self.profile.device_id,
            corridor_name=self.profile.corridor_name,
            timestamp_utc=ts_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            avg_velocity_kmh=rounded_speed,
            free_flow_kmh=self.profile.free_flow_kmh,
            congestion_index=congestion_idx,
            estimated_queue_vehicles=queue_len,
            co2_emission_g_per_km=co2_val,
            pm25_ug_m3=pm25_val,
            signal_recommendation=action,
        )


def build_default_fleet(seed: Optional[int] = None) -> List[CorridorSensorNode]:
    """Creates the 3-intersection sensor fleet with optional deterministic seeding."""
    master_rng = random.Random(seed)
    return [
        CorridorSensorNode(profile=corridor, rng=random.Random(master_rng.randint(0, 10**9)))
        for corridor in DEFAULT_CORRIDORS
    ]
