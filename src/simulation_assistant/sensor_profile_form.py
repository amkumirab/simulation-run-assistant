"""Fixed native profile form conversion; numeric blanks are unknown, never zero."""
from dataclasses import asdict

from simulation_assistant.field_samples import FIELD_UNITS
from simulation_assistant.sensor_profiles import SensorProfile, StatedRange, StatedValue, validate_profile

PROFILE_FIELDS = ('name', 'device', 'basis', 'target_field', 'notes')
SPEC_FIELDS = ('frequency', 'field', 'sensitivity', 'noise')


def read_form(owner):
    values = {name: variable.get().strip() for name, variable in owner.form.items()}
    for name, variables in owner.spec_vars.items():
        row = {key: variable.get().strip() for key, variable in variables.items()}
        numeric_keys = ('low', 'high') if name in ('frequency', 'field') else ('value',)
        if not any(row[key] for key in (*numeric_keys, 'source', 'conditions')):
            values[name] = None
            continue
        if any(not row[key] for key in numeric_keys):
            raise ValueError(name+': supply every numeric bound/value, or leave the specification blank')
        try:
            row.update({key: float(row[key]) for key in numeric_keys})
        except ValueError as exc:
            raise ValueError(name+': use finite literal numbers, not expressions') from exc
        cls = StatedRange if name in ('frequency', 'field') else StatedValue
        values[name] = cls(**row)
    profile = SensorProfile(**values)
    validate_profile(profile)
    return profile


def write_form(owner, profile):
    values = asdict(profile)
    for name, variable in owner.form.items():
        variable.set(values[name])
    for name, variables in owner.spec_vars.items():
        row = values[name]
        for key, variable in variables.items():
            default = 'Hz' if name == 'frequency' and key == 'unit' else 'uT' if name == 'field' and key == 'unit' else ''
            variable.set(str(row[key]) if row is not None else default)


def read_context(owner):
    raw = [owner.context['dc_'+axis].get().strip() for axis in 'xyz']
    if not any(raw):
        bias = None
    elif not all(raw):
        raise ValueError('Supply all three uniform DC bias components, or leave all blank for unknown')
    else:
        try:
            scale = FIELD_UNITS[owner.context['dc_unit'].get()]
            bias = tuple(float(value)*scale for value in raw)
        except (ValueError, KeyError) as exc:
            raise ValueError('DC bias requires finite literal numbers and T/mT/uT units') from exc
    return dict(sampled_field=owner.context['sampled_field'].get(), dc_bias_t=bias,
                conditions_confirmed=owner.confirmed.get())
