"""Compact native controls; exact readings remain accessible without plot picking."""
import tkinter as tk
from tkinter import ttk
from simulation_assistant.geometry_comparison_widgets import table


def text_panel(parent, height):
    frame = ttk.Frame(parent)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    text = tk.Text(frame, height=height, wrap='word', state='disabled', font=('Consolas', 9))
    text.grid(row=0, column=0, sticky='nsew')
    scroll = ttk.Scrollbar(frame, orient='vertical', command=text.yview)
    scroll.grid(row=0, column=1, sticky='ns')
    text.configure(yscrollcommand=scroll.set)
    return frame, text


def build_field_widgets(owner):
    tab = ttk.Frame(owner.owner.tabs, padding=8)
    owner.owner.tabs.add(tab, text='4. Field overlay')
    owner.tab = tab
    tab.columnconfigure(0, weight=1)
    tab.rowconfigure(5, weight=2)
    tab.rowconfigure(6, weight=1)
    controls = ttk.Frame(tab)
    controls.grid(row=0, column=0, sticky='ew')
    for label, command in (('Load saved-field bundle', owner.load), ('Use bundle layout', owner.use_layout),
                           ('Analyze overlay', owner.analyze), ('Export field SVG', owner.export),
                           ('Sensor profiles', owner.open_sensor_profiles)):
        ttk.Button(controls, text=label, command=command).pack(side='left', padx=(0, 6))
    scenarios = ttk.Frame(tab)
    scenarios.grid(row=1, column=0, sticky='ew', pady=8)
    owner.boxes = {}
    for name, variable in (('Current', owner.current), ('Reference', owner.reference)):
        ttk.Label(scenarios, text=name).pack(side='left', padx=(0, 6))
        box = ttk.Combobox(scenarios, textvariable=variable, state='readonly', width=25)
        box.pack(side='left', padx=(0, 12))
        owner.boxes[name] = box
    ttk.Button(scenarios, text='Show placement views', command=lambda: owner.owner.tabs.select(2)).pack(side='left')
    frame, owner.source_info = text_panel(tab, 5)
    frame.grid(row=2, column=0, sticky='nsew')
    ttk.Checkbutton(tab, text='I confirm the shown saved geometry is appropriate for the CURRENT solution state above',
                    variable=owner.state_matches).grid(row=3, column=0, sticky='w', pady=6)
    notice = ttk.Label(tab, text='Ideal-axis phasor amplitude (uT). Delta = current minus reference amplitude. '
                       'Current geometry only; no reference geometry, interpolation or calibrated MTJ response.', wraplength=1000)
    notice.grid(row=4, column=0, sticky='ew')
    host = ttk.Frame(tab)
    host.grid(row=5, column=0, sticky='nsew')
    owner.tree = table(host, (('sensor', 100), ('current_status', 140), ('current_uT', 105), ('reference_status', 140),
                             ('reference_uT', 105), ('delta_uT', 100), ('phase_deg', 110), ('phase_delta_deg', 130)), height=5)
    for name, title in (('current_uT', 'Current (uT)'), ('reference_uT', 'Reference (uT)'), ('delta_uT', 'Delta (uT)'),
                        ('phase_deg', 'Phase (deg)'), ('phase_delta_deg', 'Phase delta (deg)')):
        owner.tree.heading(name, text=title)
    owner.tree.bind('<<TreeviewSelect>>', owner.selected)
    owner.tree.bind('<Return>', owner.selected)
    frame, owner.detail = text_panel(tab, 7)
    frame.grid(row=6, column=0, sticky='nsew', pady=(6, 0))
    tab.bind('<Configure>', lambda event: notice.configure(wraplength=max(400, event.width-20)))
