"""Traceable CSV of explicit envelope comparisons; no model paths or MPH data."""
import csv
import io
from pathlib import Path
from simulation_assistant.csv_export import safe_csv_cell
from simulation_assistant.geometry_files import _path, _write, snapshot_digest
from simulation_assistant.geometry_comparison import GeometryComparison, compare_geometry

LIMITATION = 'Approximate global envelopes only; unmapped is not added/deleted; no topology, clearance, performance or safety approval'
SCHEMA = 'wpt.geometry-comparison.v1'


def export_comparison_csv(path: str | Path, comparison: GeometryComparison) -> Path:
    if not isinstance(comparison, GeometryComparison):
        raise ValueError('Compare valid current inputs before exporting')
    checked = compare_geometry(comparison.baseline, comparison.candidate, comparison.pairs,
                               comparable_frames=comparison.comparable_frames, tolerance_mm=comparison.tolerance_mm)
    if checked != comparison:
        raise ValueError('Comparison is modified or stale; compare current inputs again')
    identities = {}
    for side, data, unmapped in (('baseline', checked.baseline, checked.baseline_unmapped),
                                 ('candidate', checked.candidate, checked.candidate_unmapped)):
        identities.update({side+'_model_sha256': data.source_sha256, side+'_snapshot_sha256': snapshot_digest(data),
                           side+'_component': data.component, side+'_geometry': data.geometry,
                           side+'_engine': data.engine_version, side+'_original_unit': data.length_unit,
                           side+'_total_domains': len(data.parts), side+'_unmapped_domains': ' '.join(map(str,unmapped))})
    base = {part.domain: part for part in checked.baseline.parts}
    candidate = {part.domain: part for part in checked.candidate.parts}
    columns = ('schema','pair_label','baseline_domain','candidate_domain','baseline_selections','candidate_selections',
               'quantity','baseline_mm','candidate_mm','delta_mm','state','comparison_threshold_mm',
               'comparable_frames_declared','mapped_pairs',*identities,'limitations')
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    for difference in checked.differences:
        pair = difference.pair
        for metric in difference.metrics:
            row = dict(schema=SCHEMA, pair_label=pair.label, baseline_domain=pair.baseline_domain, candidate_domain=pair.candidate_domain,
                       baseline_selections=base[pair.baseline_domain].selections, candidate_selections=candidate[pair.candidate_domain].selections,
                       quantity=metric.name, baseline_mm=metric.baseline_mm, candidate_mm=metric.candidate_mm,
                       delta_mm=metric.delta_mm, state='changed' if metric.changed else 'within_threshold',
                       comparison_threshold_mm=checked.tolerance_mm, comparable_frames_declared=True,
                       mapped_pairs=len(checked.differences), **identities, limitations=LIMITATION)
            writer.writerow({key:safe_csv_cell(value) for key,value in row.items()})
    return _write(_path(path,'.csv'), stream.getvalue())
