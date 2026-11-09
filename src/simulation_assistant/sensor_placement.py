"""Read-only orthogonal placement sketches; no fields or solid-CAD inference."""
import math
from dataclasses import asdict, dataclass

from simulation_assistant.field_samples import Sensor, validate_layout
from simulation_assistant.geometry_files import _digest, selected_parts
from simulation_assistant.geometry_inspector import GeometrySnapshot


@dataclass(frozen=True)
class ProjectedEnvelope:
    domain: int
    bounds: tuple[float, ...]


@dataclass(frozen=True)
class ProjectedSensor:
    sensor: Sensor
    point: tuple[float, float]
    axis_xyz: tuple[float, ...]
    axis_uv: tuple[float, float]
    normal_component: float


@dataclass(frozen=True)
class PlacementView:
    plane: str
    normal_axis: str
    width: int
    height: int
    scale: float
    xmin_mm: float
    ymin_mm: float
    envelopes: tuple[ProjectedEnvelope, ...]
    sensors: tuple[ProjectedSensor, ...]

    def point(self, horizontal_mm, vertical_mm):
        return (70+(horizontal_mm-self.xmin_mm)*self.scale,
                self.height-50-(vertical_mm-self.ymin_mm)*self.scale)


def layout_digest(sensors: tuple[Sensor, ...]) -> str:
    """Input identity includes raw axes; normalization is a display transform."""
    validate_layout(sensors)
    return _digest({'schema': 'wpt.sensor-placement-layout.v1', 'sensors': [asdict(s) for s in sensors]})


def unit_axis(sensor: Sensor) -> tuple[float, ...]:
    validate_layout((sensor,))
    # Scale before the norm so subnormal input components do not underflow.
    largest = max(abs(a) for a in sensor.axis)
    scaled = tuple(a/largest for a in sensor.axis)
    length = math.hypot(*scaled)
    return tuple(a/length for a in scaled)


def project_placement(snapshot: GeometrySnapshot, sensors: tuple[Sensor, ...], domains: tuple[int, ...],
                      plane: str, *, comparable_frames: bool, width=580, height=420) -> PlacementView:
    if not isinstance(snapshot, GeometrySnapshot):
        raise ValueError('Load a geometry snapshot first')
    parts = selected_parts(snapshot, domains)
    validate_layout(sensors)
    if comparable_frames is not True:
        raise ValueError('Explicitly declare comparable global coordinate frames first')
    if plane not in ('XY', 'XZ'):
        raise ValueError('Choose the XY or XZ view')
    if (type(width) is not int or type(height) is not int
            or not 400 <= width <= 4000 or not 300 <= height <= 4000):
        raise ValueError('View dimensions must be 400-4000 by 300-4000 pixels')
    vertical, normal = (1, 2) if plane == 'XY' else (2, 1)
    xvalues = [v*1000 for p in parts for v in p.bounds_m[:2]]+[s.position_m[0]*1000 for s in sensors]
    yvalues = [p.bounds_m[i]*1000 for p in parts for i in (2*vertical, 2*vertical+1)]+[s.position_m[vertical]*1000 for s in sensors]
    xmin, xmax, ymin, ymax = min(xvalues), max(xvalues), min(yvalues), max(yvalues)
    margin = max(xmax-xmin, ymax-ymin, 1.)*.1
    scale = min((width-110)/(xmax-xmin+2*margin), (height-120)/(ymax-ymin+2*margin))
    # Equal physical scale in both directions, including a finite margin at tiny spans.
    xstart = (xmin+xmax)/2-(width-110)/(2*scale)
    ystart = (ymin+ymax)/2-(height-120)/(2*scale)
    view = PlacementView(plane, 'XYZ'[normal], width, height, scale, xstart, ystart, (), ())
    envelopes = tuple(ProjectedEnvelope(p.domain, (*view.point(p.bounds_m[0]*1000, p.bounds_m[2*vertical+1]*1000),
                                                  *view.point(p.bounds_m[1]*1000, p.bounds_m[2*vertical]*1000))) for p in parts)
    projected = []
    for sensor in sensors:
        axis = unit_axis(sensor)
        projected.append(ProjectedSensor(sensor, view.point(sensor.position_m[0]*1000, sensor.position_m[vertical]*1000),
                                          axis, (axis[0], axis[vertical]), axis[normal]))
    return PlacementView(plane, view.normal_axis, width, height, scale, xstart, ystart, envelopes, tuple(projected))


def projected_hits(view: PlacementView, x: float, y: float) -> tuple[str, ...]:
    return tuple(s.sensor.point_id for s in view.sensors if math.hypot(s.point[0]-x, s.point[1]-y) <= 10)
