"""Explicit correspondences and approximate global-envelope differences only."""
from dataclasses import dataclass
import math
from simulation_assistant.geometry_inspector import GeometrySnapshot, validate_snapshot

METRICS = ('xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax',
           'midpoint_x', 'midpoint_y', 'midpoint_z', 'span_x', 'span_y', 'span_z')


@dataclass(frozen=True)
class DomainPair:
    label: str
    baseline_domain: int
    candidate_domain: int


@dataclass(frozen=True)
class EnvelopeMetric:
    name: str
    baseline_mm: float
    candidate_mm: float
    delta_mm: float
    changed: bool


@dataclass(frozen=True)
class PairedDifference:
    pair: DomainPair
    metrics: tuple[EnvelopeMetric, ...]

    @property
    def changed(self) -> bool:
        return any(metric.changed for metric in self.metrics)


@dataclass(frozen=True)
class GeometryComparison:
    baseline: GeometrySnapshot
    candidate: GeometrySnapshot
    comparable_frames: bool
    tolerance_mm: float
    differences: tuple[PairedDifference, ...]
    baseline_unmapped: tuple[int, ...]
    candidate_unmapped: tuple[int, ...]

    @property
    def pairs(self) -> tuple[DomainPair, ...]:
        return tuple(difference.pair for difference in self.differences)


def validate_pairs(baseline: GeometrySnapshot, candidate: GeometrySnapshot, pairs: tuple[DomainPair, ...]) -> None:
    validate_snapshot(baseline)
    validate_snapshot(candidate)
    if not isinstance(pairs, tuple) or not 1 <= len(pairs) <= 256:
        raise ValueError('Explicitly map 1-256 corresponding domain pairs')
    labels, used_base, used_candidate = set(), set(), set()
    base_ids = {p.domain for p in baseline.parts}
    candidate_ids = {p.domain for p in candidate.parts}
    for pair in pairs:
        if (not isinstance(pair, DomainPair) or not isinstance(pair.label, str)
                or not 1 <= len(pair.label) <= 80 or pair.label != pair.label.strip()
                or any(not 32 <= ord(c) < 127 for c in pair.label)):
            raise ValueError('Each pair needs a trimmed printable English label of 1-80 characters')
        if pair.label.casefold() in labels:
            raise ValueError('Pair labels must be unique, ignoring case')
        if (type(pair.baseline_domain) is not int or type(pair.candidate_domain) is not int
                or pair.baseline_domain not in base_ids or pair.candidate_domain not in candidate_ids):
            raise ValueError('Choose an existing integer domain ID on each side')
        if pair.baseline_domain in used_base or pair.candidate_domain in used_candidate:
            raise ValueError('A domain can belong to only one pair on each side')
        labels.add(pair.label.casefold())
        used_base.add(pair.baseline_domain)
        used_candidate.add(pair.candidate_domain)


def _quantities(bounds):
    return (*bounds, *((bounds[i]+bounds[i+1])/2 for i in (0, 2, 4)),
            *(bounds[i+1]-bounds[i] for i in (0, 2, 4)))


def compare_geometry(baseline: GeometrySnapshot, candidate: GeometrySnapshot,
                     pairs: tuple[DomainPair, ...], *, comparable_frames: bool,
                     tolerance_mm: float = .01) -> GeometryComparison:
    validate_pairs(baseline, candidate, pairs)
    if comparable_frames is not True:
        raise ValueError('Explicitly declare comparable global coordinate frames first')
    if (type(tolerance_mm) not in (int, float) or not 0 <= tolerance_mm <= 1000
            or not math.isfinite(tolerance_mm)):
        raise ValueError('Comparison threshold must be a finite number from 0 to 1000 mm')
    base = {p.domain: p for p in baseline.parts}
    candidate_index = {p.domain: p for p in candidate.parts}
    differences = []
    for pair in pairs:
        a = _quantities(base[pair.baseline_domain].bounds_m)
        b = _quantities(candidate_index[pair.candidate_domain].bounds_m)
        metrics = tuple(EnvelopeMetric(name, x*1000, y*1000, (y-x)*1000, abs((y-x)*1000) > tolerance_mm)
                        for name, x, y in zip(METRICS, a, b))
        differences.append(PairedDifference(pair, metrics))
    used_baseline = {pair.baseline_domain for pair in pairs}
    used_candidate = {pair.candidate_domain for pair in pairs}
    return GeometryComparison(baseline, candidate, True, float(tolerance_mm), tuple(differences),
                              tuple(p.domain for p in baseline.parts if p.domain not in used_baseline),
                              tuple(p.domain for p in candidate.parts if p.domain not in used_candidate))
