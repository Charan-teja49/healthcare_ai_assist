"""Shared device payload validation and synthetic signal utilities.

The simulator and ECG waveform are educational test data, not measured clinical
signals or a diagnostic model. Live callers should supply their own timestamp
and prefix generated event IDs with a run identifier when replaying scenarios.
"""

import math
import time
from numbers import Real
from typing import Annotated, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_ACCELERATION_G = 32.0
MIN_ECG_SAMPLES = 25
MAX_ECG_SAMPLES = 7200
SUPPORTED_SAMPLE_RATES = (250, 360)
SCENARIOS = (
    "normal_rest",
    "arrhythmia_episode",
    "low_spo2",
    "fever",
    "fall",
    "leads_off",
)
FiniteNumber = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class AccelerationG(BaseModel):
    """Acceleration in g, represented by either x/y/z or a magnitude."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    x: FiniteNumber | None = Field(
        default=None, ge=-MAX_ACCELERATION_G, le=MAX_ACCELERATION_G
    )
    y: FiniteNumber | None = Field(
        default=None, ge=-MAX_ACCELERATION_G, le=MAX_ACCELERATION_G
    )
    z: FiniteNumber | None = Field(
        default=None, ge=-MAX_ACCELERATION_G, le=MAX_ACCELERATION_G
    )
    magnitude: FiniteNumber | None = Field(default=None, ge=0, le=MAX_ACCELERATION_G)

    @model_validator(mode="after")
    def validate_representation(self):
        axes = (self.x, self.y, self.z)
        if self.magnitude is not None:
            if any(value is not None for value in axes):
                raise ValueError("Use either x/y/z or magnitude, not both")
        elif not all(value is not None for value in axes):
            raise ValueError("Acceleration requires all of x/y/z, or magnitude")
        elif math.sqrt(sum(value * value for value in axes)) > MAX_ACCELERATION_G:
            raise ValueError("Acceleration vector magnitude exceeds 32 g")
        return self

    def magnitude_g(self) -> float:
        if self.magnitude is not None:
            return self.magnitude
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)


AccelerationValue = Annotated[
    float, Field(strict=True, ge=0, le=MAX_ACCELERATION_G, allow_inf_nan=False)
]


class SensorPacket(BaseModel):
    """Canonical JSON contract for authenticated HTTP and MQTT ingestion.

    Timestamps use Unix seconds. No historical lower bound is imposed because
    recorded-device replay is supported; future clock skew is limited to 60 s.
    """

    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False
    )
    kind: Literal["vitals", "ecg", "event"]
    device_id: str = Field(min_length=1, max_length=100)
    event_id: str = Field(min_length=1, max_length=100)
    timestamp: FiniteNumber = Field(gt=0)
    source: Literal["device", "simulator"] = "device"
    activity: Literal["rest", "walking", "running", "unknown"] = "unknown"
    acceleration_mode: Literal["linear", "raw"] = "linear"
    signal: bool = True
    hr: FiniteNumber | None = Field(default=None, ge=25, le=250)
    spo2: FiniteNumber | None = Field(default=None, ge=50, le=100)
    temperature: FiniteNumber | None = Field(default=None, ge=30, le=45)
    sample_rate: Literal[250, 360] | None = None
    samples: list[FiniteNumber] | None = Field(
        default=None, min_length=MIN_ECG_SAMPLES, max_length=MAX_ECG_SAMPLES
    )
    event: Literal["fall", "leads_off", "restored"] | None = None
    acceleration: AccelerationG | AccelerationValue | None = None

    @field_validator("sample_rate", mode="before")
    @classmethod
    def integer_sample_rate(cls, value):
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            raise ValueError("ECG sample rate must be an integer 250 or 360")
        return value

    @field_validator("timestamp")
    @classmethod
    def timestamp_not_in_future(cls, value):
        if value > time.time() + 60:
            raise ValueError("Timestamp must not be more than 60 seconds in the future")
        return value

    @model_validator(mode="after")
    def validate_kind_fields(self):
        vital_fields = (self.hr, self.spo2, self.temperature)
        ecg_fields = (self.samples, self.sample_rate)
        if self.kind == "vitals":
            if any(value is None for value in vital_fields):
                raise ValueError("Vitals packets require hr, spo2 and temperature")
            if any(value is not None for value in ecg_fields) or self.event is not None:
                raise ValueError("Vitals packets cannot contain ECG or event fields")
            if not self.signal:
                raise ValueError(
                    "Disconnected sensors must send a leads_off event, not vitals"
                )
        elif self.kind == "ecg":
            if any(value is None for value in ecg_fields):
                raise ValueError("ECG packets require samples and sample_rate")
            if (
                any(value is not None for value in vital_fields)
                or self.event is not None
            ):
                raise ValueError("ECG packets cannot contain vital or event fields")
            if not self.signal:
                raise ValueError(
                    "Disconnected sensors must send a leads_off event, not ECG"
                )
        else:
            if self.event is None:
                raise ValueError("Event packets require event")
            if any(value is not None for value in vital_fields + ecg_fields):
                raise ValueError(
                    "Event packets cannot contain vital or ECG measurements"
                )
            if self.event == "leads_off":
                self.signal = False
            elif self.event == "restored":
                self.signal = True
        return self

    def acceleration_magnitude(self) -> float | None:
        if self.acceleration is None:
            return None
        if isinstance(self.acceleration, AccelerationG):
            return self.acceleration.magnitude_g()
        return self.acceleration


def _sample_array(samples) -> np.ndarray:
    try:
        values = list(samples)
    except TypeError as exc:
        raise ValueError("ECG samples must be a numeric sequence") from exc
    if not MIN_ECG_SAMPLES <= len(values) <= MAX_ECG_SAMPLES:
        raise ValueError("ECG requires between 25 and 7200 samples")
    if any(isinstance(value, (bool, str, bytes)) for value in values):
        raise ValueError("ECG samples must be finite numbers")
    try:
        result = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("ECG samples must be finite numbers") from exc
    if result.ndim != 1 or not np.isfinite(result).all():
        raise ValueError("ECG samples must be a one-dimensional finite sequence")
    return result


def resample_ecg(samples, source_rate: int, target_rate: int = 250) -> list[float]:
    """NumPy-only polyphase windowed-sinc resampling, with both rates in Hz.

    A Kaiser-windowed low-pass interpolation kernel uses 94% of the smaller
    Nyquist bandwidth to suppress aliases during downsampling. Rational-rate
    phases are precomputed; linear endpoint extrapolation handles boundaries.
    Output length is ceil(input_length * target_rate / source_rate), preserving
    duration to within one output sample. Equal-rate input is copied unchanged.
    This signal-processing fixture is not a clinically validated ECG filter.
    """
    if (
        not isinstance(source_rate, int)
        or not isinstance(target_rate, int)
        or isinstance(source_rate, bool)
        or isinstance(target_rate, bool)
        or source_rate not in SUPPORTED_SAMPLE_RATES
        or target_rate not in SUPPORTED_SAMPLE_RATES
    ):
        raise ValueError("ECG rates must be 250 or 360 Hz")
    values = _sample_array(samples)
    if source_rate == target_rate:
        return values.tolist()
    common = math.gcd(source_rate, target_rate)
    up, down = target_rate // common, source_rate // common
    cutoff = 0.94 * min(1.0, target_rate / source_rate)
    radius = math.ceil(48.0 / cutoff)
    offsets = np.arange(-radius, radius + 1, dtype=np.int64)
    fractions = np.arange(up, dtype=float)[:, None] / up
    distance = fractions - offsets[None, :]
    scaled = distance / radius
    within_window = np.abs(scaled) <= 1.0
    window = np.where(
        within_window,
        np.i0(8.6 * np.sqrt(np.maximum(0.0, 1.0 - scaled * scaled))) / np.i0(8.6),
        0.0,
    )
    phase_weights = cutoff * np.sinc(cutoff * distance) * window
    phase_weights /= phase_weights.sum(axis=1, keepdims=True)
    count = (len(values) * up + down - 1) // down
    output = np.empty(count, dtype=float)
    left_slope = values[1] - values[0]
    right_slope = values[-1] - values[-2]
    # Bound temporary arrays independently of packet duration.
    for start in range(0, count, 512):
        stop = min(start + 512, count)
        numerators = np.arange(start, stop, dtype=np.int64) * down
        centers, phases = numerators // up, numerators % up
        indices = centers[:, None] + offsets[None, :]
        selected = values[np.clip(indices, 0, len(values) - 1)]
        selected = np.where(indices < 0, values[0] + indices * left_slope, selected)
        selected = np.where(
            indices >= len(values),
            values[-1] + (indices - len(values) + 1) * right_slope,
            selected,
        )
        output[start:stop] = np.sum(selected * phase_weights[phases], axis=1)
    if not np.isfinite(output).all():
        raise ValueError("ECG resampling produced a non-finite output")
    return output.tolist()


def synthetic_ecg(
    index: int = 0,
    sample_rate: int = 250,
    duration_seconds: float = 1.0,
    heart_rate: float = 72.0,
) -> list[float]:
    """Deterministic P/Q/R/S/T-shaped synthetic waveform; amplitude is in mV.

    index is the starting whole-second offset. This is a visualization and
    pipeline fixture only, not a physiological simulator or diagnostic signal.
    """
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise ValueError("Synthetic ECG index must be a non-negative integer")
    if (
        not isinstance(sample_rate, int)
        or isinstance(sample_rate, bool)
        or sample_rate not in SUPPORTED_SAMPLE_RATES
    ):
        raise ValueError("Synthetic ECG sample rate must be 250 or 360 Hz")
    if (
        not isinstance(duration_seconds, Real)
        or isinstance(duration_seconds, bool)
        or not math.isfinite(duration_seconds)
        or duration_seconds <= 0
        or not isinstance(heart_rate, Real)
        or isinstance(heart_rate, bool)
        or not math.isfinite(heart_rate)
        or not 25 <= heart_rate <= 250
    ):
        raise ValueError(
            "Synthetic ECG requires a positive duration and heart rate 25–250"
        )
    count = round(duration_seconds * sample_rate)
    if not MIN_ECG_SAMPLES <= count <= MAX_ECG_SAMPLES:
        raise ValueError("Synthetic ECG duration must yield 25–7200 samples")
    t = index + np.arange(count, dtype=float) / sample_rate
    phase = np.mod(t * heart_rate / 60.0, 1.0)

    def peak(location, width, amplitude):
        return amplitude * np.exp(-0.5 * ((phase - location) / width) ** 2)

    waveform = (
        peak(0.16, 0.028, 0.08)
        + peak(0.365, 0.009, -0.13)
        + peak(0.40, 0.011, 1.00)
        + peak(0.435, 0.012, -0.25)
        + peak(0.68, 0.062, 0.23)
        + 0.012 * np.sin(2.0 * np.pi * 0.2 * t)
    )
    return waveform.tolist()


def simulate_packet(
    scenario: str,
    index: int,
    device_id: str = "simulator",
    timestamp: float | None = None,
) -> SensorPacket:
    """Create deterministic scenario measurements with an explicit simulator tag.

    For fully reproducible packet equality, supply timestamp. Otherwise a live
    Unix timestamp is attached. IDs are deterministic within a scenario/index;
    callers replaying a new run should prefix event_id with a fresh run ID.
    """
    if scenario not in SCENARIOS:
        raise ValueError("Unknown sensor scenario")
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise ValueError("Simulation index must be a non-negative integer")
    base = {
        "device_id": device_id,
        "event_id": f"sim-{scenario}-{index}",
        "timestamp": time.time() if timestamp is None else timestamp,
        "source": "simulator",
        "activity": "rest",
    }
    if scenario == "leads_off":
        return SensorPacket(**base, kind="event", event="leads_off", signal=False)
    if scenario == "fall":
        return SensorPacket(
            **base,
            kind="event",
            event="fall",
            acceleration={"magnitude": 3.6 if index == 0 else 0.05},
        )
    hr, spo2, temperature = {
        "normal_rest": (72.0, 98.0, 36.7),
        "arrhythmia_episode": (136.0, 96.0, 36.8),
        "low_spo2": (108.0, 88.0, 37.1),
        "fever": (102.0, 96.0, 39.1),
    }[scenario]
    hr += 2.0 * math.sin(index * 0.3)
    return SensorPacket(
        **base,
        kind="vitals",
        hr=round(hr, 2),
        spo2=spo2,
        temperature=temperature,
        acceleration={"magnitude": 1.0},
    )
