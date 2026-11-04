# Real stored WPT geometry envelopes

These snapshots were read on 2026-11-04 with COMSOL Multiphysics 6.3 (Build 290)
from private copies of three existing saved 3RX models. No original was rebuilt,
meshed, solved or saved. Source hashes were checked before and after each read.
No MPH, solution data, author metadata or absolute source path is included.
Each JSON includes its original MPH SHA-256 and a portable content checksum.
The checksum detects accidental changes; it is not a digital signature.

| Snapshot | Original model basename | Domains | Left RX coil X bounds (mm) | Left RX coil Z bounds (mm) |
| --- | --- | --- | --- | --- |
| `original.json` | `01_Original_3RX.mph` | 13 | -380 to -180 | 155 to 160 |
| `overlap.json` | `02_Overlap_3RX_Geometry.mph` | 13 | -240 to -40 | 175 to 180 |
| `control.json` | `03_Height_Matched_Control_Geometry.mph` | 13 | -380 to -180 | 175 to 180 |

Values are rounded summaries of approximate global axis-aligned bounds, not
solid shapes. The side RX stacks move upward by 20 mm in overlap/control;
the overlap model additionally reduces side RX center offsets from 280 to
140 mm. These are geometry differences, not power, sensor or controller results.

For **these exact source hashes only**, the replay explicitly selects domains
2-13, excluding the saved air envelope (D1). D9 is the TX coil and D10 the
center RX coil, as cross-checked with the saved selections/model geometry.
The example explicitly declares their untilted parallel stack and shows about
150 mm global Z-envelope separation. The application itself does not assign
roles, exclude air, choose a pair or assert parallelism automatically.

```powershell
python examples/replay_saved_geometry.py --desktop
python examples/replay_saved_geometry.py --snapshot examples/saved_geometry_wpt/overlap.json --desktop
python examples/replay_saved_geometry.py --snapshot examples/saved_geometry_wpt/control.json
```

Replay needs Python/Tk, not COMSOL or a license. It uses an isolated temporary
database, leaves the real queue untouched and labels the display **offline
replay, not live**. `--capture-dir` optionally captures the real native window
on Windows when Pillow is already available; Pillow is not a runtime dependency.
The published screenshots are unretouched window captures from this replay.

To inspect a different saved model, use **Runs > Geometry inspector** or:

```powershell
python examples/check_saved_geometry.py "C:\Models\example.mph" --comsol "C:\Program Files\COMSOL\COMSOL63\Multiphysics\bin\win64\comsolbatch.exe" --output geometry.json
```

Choose a new output JSON; the script refuses overwrite. A finalized, saved,
single Cartesian 3D geometry is required. A missing/unbuilt or 2D geometry fails
closed without starting a build. Review selection names and geometry metadata
for confidential design details before sharing even a path-free snapshot.
