# Unit-aware Quantities

Simulation Run Assistant normalizes supported dimensional parameter values to SI
before using them in comparison charts or ranking constraints. This prevents
physically equal values such as `0.15[m]` and `15[cm]` from being treated as
different designs.

## Accepted syntax

Values may use COMSOL-style brackets or a separated unit:

```text
150[mm]
15 [cm]
0.15 m
85[kHz]
10[degree]
```

Bare finite numbers remain unitless. Arithmetic expressions such as
`2*pi*85[kHz]` are not evaluated by the quantity parser.

## Supported dimensions

| Dimension | Accepted units | SI reference |
| --- | --- | --- |
| Length | `m`, `cm`, `mm`, `um`, `nm` | `m` |
| Frequency | `Hz`, `kHz`, `MHz`, `GHz` | `Hz` |
| Angle | `rad`, `deg`, `degree`, `degrees` | `rad` |
| Time | `s`, `ms`, `us`, `min` | `s` |
| Current | `A`, `mA`, `kA` | `A` |
| Voltage | `V`, `mV`, `kV` | `V` |
| Power | `W`, `mW`, `kW` | `W` |
| Inductance | `H`, `mH`, `uH`, `nH` | `H` |
| Resistance | `ohm`, `mOhm`, `kOhm` | `ohm` |
| Magnetic flux density | `T`, `mT`, `uT` | `T` |
| Capacitance | `F`, `mF`, `uF`, `nF`, `pF` | `F` |
| Conductivity | `S/m`, `MS/m` | `S/m` |
| Ratio | `%` | `1` |

The micro symbols `u`, `µ`, and `μ` are accepted for supported micro-units. The
ohm symbol `Ω` and degree symbol `°` are also accepted.

## Safety behavior

- Unknown units are not reduced to a leading number.
- `NaN`, infinity, booleans, and incomplete expressions are rejected.
- A ranking constraint must have the same physical dimension as its input field.
- A comparison chart stops with a clear message if one parameter mixes physical
  dimensions.
- Ranking CSV constraint columns show the SI reference unit used for evaluation.

Unit metadata for result outputs belongs to the planned model-contract layer.
Until that layer is available, numeric output metrics retain their stored scale.
