"""Explicit association of saved fields and current-state geometry, not calibration."""
from dataclasses import dataclass, replace

from simulation_assistant.field_samples import FieldReading, Sensor, analyze_field_samples, validate_layout
from simulation_assistant.geometry_inspector import GeometrySnapshot, validate_snapshot
from simulation_assistant.saved_field_bundles import FieldSource, SavedFieldBundle
from simulation_assistant.sensor_placement import unit_axis


@dataclass(frozen=True)
class SensorFieldOverlay:
    snapshot: GeometrySnapshot
    sensors: tuple[Sensor, ...]
    bundle: SavedFieldBundle
    current_source: FieldSource
    reference_source: FieldSource
    readings: tuple[FieldReading, ...]


def analyze_overlay(snapshot: GeometrySnapshot, sensors: tuple[Sensor, ...], bundle: SavedFieldBundle,
                    current: str, reference: str, *, comparable_frames: bool,
                    geometry_matches_state: bool) -> SensorFieldOverlay:
    """Bind a validated bundle to copied inputs. Both declarations must be True.

    Model identity is necessary, not proof of historical solution-state geometry.
    Callers load bundles with load_saved_field_bundle, never from a bare workspace.
    """
    validate_snapshot(snapshot)
    validate_layout(sensors)
    if comparable_frames is not True or geometry_matches_state is not True:
        raise ValueError('Confirm comparable frames AND geometry appropriate to the current saved solution state')
    if not isinstance(bundle, SavedFieldBundle):
        raise ValueError('Load a complete saved-field evidence bundle first')
    sources = {s.scenario: s for s in bundle.sources}
    if len(sources) != len(bundle.sources) or set(sources) != set(bundle.data.scenarios):
        raise ValueError('Every scenario requires exactly one source association')
    if current not in sources or reference not in sources:
        raise ValueError('Choose current and reference scenarios from the loaded bundle')
    if snapshot.source_sha256 != sources[current].model_sha256:
        raise ValueError('Geometry model SHA differs from the current scenario source; load matching geometry')
    normalized = tuple(replace(s, axis=unit_axis(s)) for s in sensors)
    readings = analyze_field_samples(bundle.data, normalized, current, reference)
    readings = tuple(replace(r, sensor=s) for r, s in zip(readings, sensors))
    return SensorFieldOverlay(snapshot, sensors, bundle, sources[current], sources[reference], readings)


def matching_sample(overlay, sensor_id, *, reference=False):
    """Return raw complex components only when the selected row is available."""
    row = next((r for r in overlay.readings if r.sensor.point_id == sensor_id), None)
    if row is None:
        raise ValueError('Choose an existing sensor ID')
    status = row.reference_status if reference else row.status
    if status != 'available':
        return None
    source = overlay.reference_source if reference else overlay.current_source
    return next(s for s in overlay.bundle.data.samples if s.scenario == source.scenario and s.point_id == sensor_id)
