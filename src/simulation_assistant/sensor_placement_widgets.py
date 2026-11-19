"""Native placement controls following the saved-geometry workspace styles."""
import tkinter as tk
from tkinter import ttk
from simulation_assistant.geometry_comparison_widgets import table
from simulation_assistant.sensor_placement_views import NOTICE


def build_placement_widgets(owner):
    body = ttk.Frame(owner.window, style='Card.TFrame', padding=18)
    body.pack(fill='both', expand=True)
    body.columnconfigure(0, weight=1)
    body.rowconfigure(4, weight=1)
    ttk.Label(body, text='Sensor Placement Preview', style='CardTitle.TLabel').grid(row=0, column=0, sticky='w')
    notice = ttk.Label(body, text=NOTICE+' Field overlay is opt-in and requires complete saved-source evidence.', style='CardText.TLabel', wraplength=1150)
    notice.grid(row=1, column=0, sticky='ew', pady=(6, 8))
    controls = ttk.Frame(body, style='Card.TFrame')
    controls.grid(row=2, column=0, sticky='ew', pady=(0, 8))
    for title, command in (('Load geometry JSON', owner.load_geometry), ('Load layout from workspace', owner.load_layout),
                           ('Preview selected domains', owner.preview)):
        ttk.Button(controls, text=title, command=command, style='Secondary.TButton').pack(side='left', padx=(0, 8))
    ttk.Checkbutton(body, text='I declare the sensor layout and geometry use comparable global Cartesian frames',
                    variable=owner.frames).grid(row=3, column=0, sticky='w', pady=(0, 8))
    owner.tabs = ttk.Notebook(body)
    owner.tabs.grid(row=4, column=0, sticky='nsew')
    geometry = ttk.Frame(owner.tabs, padding=8)
    layout = ttk.Frame(owner.tabs, padding=8)
    charts = ttk.Frame(owner.tabs, padding=4)
    for frame, title in ((geometry, '1. Geometry domains'), (layout, '2. Sensor coordinates'), (charts, '3. Placement views')):
        owner.tabs.add(frame, text=title)
    geometry_info = ttk.Label(geometry, textvariable=owner.geometry_info, wraplength=1100)
    geometry_info.pack(fill='x', pady=(0, 6))
    ttk.Label(geometry, text='Ctrl/Shift-select domains. IDs/tags do not identify TX/RX roles or certify physical dimensions.').pack(anchor='w')
    owner.domains_tree = table(geometry, (('domain', 90), ('selections', 600)), height=7)
    owner.domains_tree.configure(selectmode='extended')
    owner.domains_tree.bind('<<TreeviewSelect>>', owner.domains_changed)
    owner.domains_tree.bind('<Return>', lambda _e: owner.preview())
    layout_info = ttk.Label(layout, textvariable=owner.layout_info, wraplength=1100)
    layout_info.pack(fill='x', pady=(0, 6))
    ttk.Label(layout, text='Positions in mm; normalized directions. Independent copy: reopen from the editor to refresh.').pack(anchor='w')
    owner.sensor_tree = table(layout, (('sensor', 150), ('x_mm', 130), ('y_mm', 130), ('z_mm', 130), ('nx', 100), ('ny', 100), ('nz', 100)))
    owner.sensor_tree.bind('<<TreeviewSelect>>', owner.sensor_selected)
    owner.sensor_tree.bind('<Return>', owner.sensor_selected)
    owner.canvases = {}
    preview_note = ttk.Label(charts, textvariable=owner.preview_note, wraplength=1100)
    preview_note.grid(row=0, column=0, columnspan=2, sticky='ew', padx=8, pady=(0, 6))
    charts.rowconfigure(1, weight=1)
    for column, plane in enumerate(('XY', 'XZ')):
        charts.columnconfigure(column, weight=1, uniform='views')
        canvas = tk.Canvas(charts, background='white', highlightthickness=1, highlightbackground='#d7e0e8', takefocus=True)
        canvas.grid(row=1, column=column, sticky='nsew', padx=(0, 4) if column == 0 else (4, 0))
        canvas.bind('<Configure>', owner.redraw)
        canvas.bind('<Button-1>', lambda event, p=plane: owner.pick_sensor(p, event.x, event.y))
        owner.canvases[plane] = canvas
    details = ttk.Label(body, textvariable=owner.details, style='CardText.TLabel', wraplength=1150)
    details.grid(row=5, column=0, sticky='ew', pady=(8, 0))
    status = ttk.Label(body, textvariable=owner.status, style='CardText.TLabel', wraplength=1150)
    status.grid(row=6, column=0, sticky='ew', pady=8)
    actions = ttk.Frame(body, style='Card.TFrame')
    actions.grid(row=7, column=0, sticky='ew')
    ttk.Button(actions, text='Export placement SVG', command=owner.export, style='Primary.TButton').pack(side='left')
    ttk.Button(actions, text='Close', command=owner.close, style='Secondary.TButton').pack(side='right')
    body.bind('<Configure>', lambda event: [label.configure(wraplength=max(400, event.width-36))
                                           for label in (notice, geometry_info, layout_info, details, status, preview_note)])
