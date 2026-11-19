"""Native declared-limit workspace using the existing profile/field styles."""
from tkinter import ttk

from simulation_assistant.geometry_comparison_widgets import table
from simulation_assistant.sensor_field_widgets import text_panel
from simulation_assistant.sensor_profiles import BASES, FIELD_PURPOSES


def build_profile_widgets(owner):
    body = ttk.Frame(owner.window, style='Card.TFrame', padding=16)
    body.pack(fill='both', expand=True)
    body.columnconfigure(0, weight=1)
    body.rowconfigure(3, weight=1)
    ttk.Label(body, text='Sensor profiles and declared limits', style='CardTitle.TLabel').grid(row=0, column=0, sticky='w')
    scope = ttk.Label(body, textvariable=owner.scope, wraplength=1100, style='CardText.TLabel')
    scope.grid(row=1, column=0, sticky='ew', pady=8)
    actions = ttk.Frame(body)
    actions.grid(row=2, column=0, sticky='ew', pady=(0, 8))
    for label, command in (('New profile', owner.new), ('Load profile', owner.load), ('Save profile', owner.save),
                           ('Evaluate current fields', owner.evaluate), ('Export report JSON', owner.export), ('Close', owner.close)):
        ttk.Button(actions, text=label, command=command).pack(side='left', padx=(0, 6))
    owner.tabs = ttk.Notebook(body)
    owner.tabs.grid(row=3, column=0, sticky='nsew')
    profile = ttk.Frame(owner.tabs, padding=10)
    assessment = ttk.Frame(owner.tabs, padding=8)
    owner.tabs.add(profile, text='1. Profile and assumptions')
    owner.tabs.add(assessment, text='2. Declared-limit screening')
    profile.columnconfigure(1, weight=1)
    for row, (name, label) in enumerate((('name', 'Profile name'), ('basis', 'Evidence basis'), ('device', 'Device/model (optional for hypothetical)'),
                                       ('target_field', 'Intended field purpose'), ('notes', 'Notes (not proof of physical performance)'))):
        ttk.Label(profile, text=label).grid(row=row, column=0, sticky='w', pady=5, padx=(0, 12))
        if name in ('basis', 'target_field'):
            widget = ttk.Combobox(profile, textvariable=owner.form[name], state='readonly',
                                  values=BASES if name == 'basis' else FIELD_PURPOSES)
        else:
            widget = ttk.Entry(profile, textvariable=owner.form[name])
        widget.grid(row=row, column=1, sticky='ew', pady=5)
    specs = ttk.LabelFrame(profile, text='Optional specifications - blank numbers remain unknown', padding=8)
    specs.grid(row=5, column=0, columnspan=2, sticky='ew', pady=12)
    specs.columnconfigure(4, weight=1)
    specs.columnconfigure(5, weight=2)
    for column, label in enumerate(('Specification', 'Low / value', 'High', 'Unit', 'Source / assumption rationale', 'Applicable conditions')):
        ttk.Label(specs, text=label).grid(row=0, column=column, sticky='w', padx=4, pady=6)
    for row, (name, label) in enumerate((('frequency', 'Frequency range'), ('field', 'Signed axis B range'),
                                        ('sensitivity', 'Sensitivity (record only)'), ('noise', 'Noise (record only)')), 1):
        ttk.Label(specs, text=label).grid(row=row, column=0, sticky='w', padx=4, pady=8)
        for key, variable in owner.spec_vars[name].items():
            column = {'low': 1, 'value': 1, 'high': 2, 'unit': 3, 'source': 4, 'conditions': 5}[key]
            if key == 'unit' and name in ('frequency', 'field'):
                widget = ttk.Combobox(specs, textvariable=variable, state='readonly', width=7,
                                      values=('Hz', 'kHz', 'MHz') if name == 'frequency' else ('T', 'mT', 'uT'))
            else:
                widget = ttk.Entry(specs, textvariable=variable, width=10 if column < 4 else 22)
            widget.grid(row=row, column=column, sticky='ew', padx=4)
    help_label = ttk.Label(profile, wraplength=1100, text='Hypothetical profiles are design assumptions, not real-device data. '
                           'No numeric defaults are provided. Known values need a rationale/reference and applicable conditions. '
                           'Sensitivity/noise units are stored as reported; no voltage, SNR or detectability is calculated. '
                           'Frequency and signed B-axis ranges are the only implemented checks.')
    help_label.grid(row=6, column=0, columnspan=2, sticky='ew', pady=8)
    assessment.columnconfigure(0, weight=1)
    assessment.rowconfigure(4, weight=2)
    assessment.rowconfigure(5, weight=1)
    frame, owner.source_info = text_panel(assessment, 5)
    frame.grid(row=0, column=0, sticky='ew')
    context = ttk.Frame(assessment)
    context.grid(row=1, column=0, sticky='ew', pady=8)
    ttk.Label(context, text='Sampled field').pack(side='left', padx=(0, 6))
    ttk.Combobox(context, textvariable=owner.context['sampled_field'], values=FIELD_PURPOSES, state='readonly', width=20).pack(side='left')
    ttk.Label(context, text='Uniform global DC B (X, Y, Z)').pack(side='left', padx=8)
    for axis in 'xyz':
        ttk.Entry(context, textvariable=owner.context['dc_'+axis], width=9).pack(side='left', padx=3)
    ttk.Combobox(context, textvariable=owner.context['dc_unit'], values=('T', 'mT', 'uT'), state='readonly', width=5).pack(side='left', padx=6)
    ttk.Checkbutton(assessment, variable=owner.confirmed,
                    text='I confirm supplied profile conditions and uniform DC bias apply to both scenarios and every sensor').grid(row=2, column=0, sticky='w')
    context_help = ttk.Label(assessment, wraplength=1100, text='Blank DC components mean unknown, not zero. '
                             'Checks use single-frequency sinusoidal axis excursion plus declared uniform DC bias. '
                             'No transverse-field, saturation, noise or vehicle-detection approval. Confirmations are never restored from files.')
    context_help.grid(row=3, column=0, sticky='ew', pady=6)
    host = ttk.Frame(assessment)
    host.grid(row=4, column=0, sticky='nsew')
    owner.tree = table(host, (('sensor', 80), ('scenario', 115), ('result', 200), ('frequency', 180), ('axis_range', 180),
                             ('peak_uT', 105), ('minimum_uT', 105), ('maximum_uT', 105), ('sample', 140)), height=5)
    for name, label in (('peak_uT', 'AC peak (uT)'), ('minimum_uT', 'Axis min (uT)'), ('maximum_uT', 'Axis max (uT)')):
        owner.tree.heading(name, text=label)
    owner.tree.bind('<<TreeviewSelect>>', owner.show_detail)
    owner.tree.bind('<Return>', owner.show_detail)
    frame, owner.detail = text_panel(assessment, 6)
    frame.grid(row=5, column=0, sticky='nsew', pady=(6, 0))
    status = ttk.Label(body, textvariable=owner.status, style='CardText.TLabel', wraplength=1100)
    status.grid(row=4, column=0, sticky='ew', pady=(8, 0))
    body.bind('<Configure>', lambda event: [label.configure(wraplength=max(400, event.width-40)) for label in (scope, status)])
    profile.bind('<Configure>', lambda event: help_label.configure(wraplength=max(400, event.width-24)))
    assessment.bind('<Configure>', lambda event: context_help.configure(wraplength=max(400, event.width-24)))
