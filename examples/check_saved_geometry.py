"""Inspect one existing saved 3D model without rebuilding, solving or saving it."""
import argparse
from pathlib import Path
from simulation_assistant.comsol_readonly import model_digest
from simulation_assistant.geometry_files import save_snapshot
from simulation_assistant.geometry_inspector import inspect_geometry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', type=Path)
    parser.add_argument('--comsol', required=True, type=Path, help='comsolbatch executable')
    parser.add_argument('--output', required=True, type=Path, help='New portable JSON snapshot; no MPH is exported')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output file; existing evidence is not overwritten')
    before = model_digest(args.model)
    data = inspect_geometry(args.model, args.comsol)
    if model_digest(args.model) != before:
        raise RuntimeError('Source changed; no evidence published')
    save_snapshot(args.output, data)
    print(f'PASS: {len(data.parts)} saved 3D domains; unchanged source SHA-256 {before}; no build, solve or source save')
    for part in data.parts:
        print(f'D{part.domain}: '+', '.join(f'{v*1000:.3f}' for v in part.bounds_m)+' mm')


if __name__ == '__main__':
    main()
