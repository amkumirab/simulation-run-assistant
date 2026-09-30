# WPT Series-Series Circuit Study

The native circuit workspace converts accepted electromagnetic two-port results
into a repeatable Series-Series resonant operating-point study. It tunes one
nominal result, freezes the electrical controls, and evaluates the same controls
against every other result in the selected batch.

The study reads existing results only. It does not start COMSOL or modify a model.

## Required result metrics

Every eligible job must contain nine finite metrics in SI units:

| Quantity | Recommended result name | Unit |
| --- | --- | --- |
| Frequency | `frequency_Hz` | Hz |
| Primary self-inductance | `L1_H` | H |
| Secondary self-inductance | `L2_H` | H |
| Forward mutual inductance | `M12_H` | H |
| Reverse mutual inductance | `M21_H` | H |
| Primary self-resistance | `R1_ohm` or `R11_ohm` | ohm |
| Secondary self-resistance | `R2_ohm` or `R22_ohm` | ohm |
| Forward transfer resistance | `R12_ohm` | ohm |
| Reverse transfer resistance | `R21_ohm` | ohm |

The workspace detects these names automatically when possible. Each selector can
be remapped when a model contract uses another stable name. A metric cannot fill
more than one two-port position.

The electromagnetic model must provide a physically valid two-port. Self
inductances and self-resistances must be positive, the mutual inductance cannot
imply a coupling magnitude above one, and the Hermitian part of the impedance
matrix must be passive. Only successful jobs with a **Valid** or **Warning**
scientific validation state enter the calculation. Other jobs remain visible as
ineligible.

## Circuit model

At angular frequency `omega = 2*pi*f`, the stored two-port is interpreted as:

```text
Z11 = R11 + j*omega*L1
Z12 = R12 + j*omega*M12
Z21 = R21 + j*omega*M21
Z22 = R22 + j*omega*L2
```

The nominal compensation values are:

```text
C1 = 1 / (omega^2 * L1)
C2 = 1 / (omega^2 * L2)
```

The solver adds the selected equivalent AC load to the secondary loop and an
optional ESR to each capacitor. It solves the complete complex 2-by-2 system;
transfer resistance is not discarded.

The load search is logarithmic between the configured minimum and maximum. The
load with the highest modeled AC efficiency is selected, then the RMS source
voltage is scaled until the nominal load receives the requested power.

## Fixed-control scenario analysis

After nominal tuning, these values stay fixed for every scenario:

- frequency;
- primary and secondary compensation capacitance;
- equivalent AC load;
- RMS source voltage;
- capacitor ESR assumption.

This exposes operating-point stress caused by changes in gap, offset, tilt, or
geometry. Retuning each scenario would hide the current and voltage excursions
that a fixed controller and compensation network must handle.

All jobs must report the same frequency as the nominal result. A different
frequency makes the scenario ineligible instead of silently retuning it.

Each scenario reports:

- load and input AC power;
- modeled AC efficiency;
- primary and secondary RMS currents;
- primary and secondary capacitor RMS voltages;
- load-power retention relative to the nominal job;
- modeled electromagnetic and capacitor losses;
- relative energy-balance residual;
- individual limit results and an overall Passed, Failed, or Ineligible state.

The default screening limits are 100 A RMS coil current, 1200 V RMS capacitor
voltage, 80% minimum load-power retention, and `1e-8` maximum relative
energy-balance residual. These defaults are editable assumptions, not component
ratings.

## Desktop workflow

1. Run the model through a Job Sequence that refreshes all required Derived
   Values and table outputs.
2. Confirm that scientific validation marks the results Valid or Warning.
3. Start the native application with `sim-assistant desktop`.
4. Open **Runs** and choose **Circuit study**.
5. Select the batch and the aligned or otherwise intended nominal job.
6. Review the detected two-port mappings and confirm that every value uses SI.
7. Set the target power, load-search bounds, ESR assumption, and safety limits.
8. Choose **Analyze**. Double-click a row to inspect its source job.
9. Export CSV for further processing or HTML for a portable review report.

The nominal job is shown in bold. Passed rows are green, failed rows are red,
and incomplete or rejected rows are muted.

## Interpretation boundary

The reported efficiency is the modeled sinusoidal AC resonant-stage efficiency.
It is not total charger efficiency. The calculation does not include inverter
switching, rectification, DC/DC conversion, battery behavior, thermal feedback,
control dynamics, measured component tolerances, or hardware calibration unless
those effects already appear in the supplied two-port results and ESR assumption.

The Passed state covers only the configured electrical limits. It does not screen
ferrite flux density, leakage field, temperature, or device switching stress.

Use real Litz-wire loss data, ferrite loss and saturation data, capacitor ratings,
semiconductor limits, thermal limits, and hardware measurements before treating a
Passed result as a production design decision.

## Reports and privacy

CSV and HTML reports contain calculated operating points, validation states, and
recorded input parameters. They do not contain local model paths, artifact paths,
or MPH file contents. The HTML report is self-contained and requires no server.
