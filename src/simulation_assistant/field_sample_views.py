"""Focused native sensor editing and sampled XY rendering."""
import tkinter as tk
from tkinter import ttk

from simulation_assistant.field_samples import Sensor, make_sensor_grid, validate_layout


def field_table(parent, columns):
    frame = ttk.Frame(parent, style="Card.TFrame")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    tree = ttk.Treeview(frame, columns=columns, show="headings", height=7)
    for name in columns:
        tree.heading(name, text=name.replace("_", " "))
        tree.column(name, width=115, minwidth=100, stretch=False)
    tree.grid(row=0, column=0, sticky="nsew")
    for orient, row, column, sticky, command in (("vertical", 0, 1, "ns", tree.yview), ("horizontal", 1, 0, "ew", tree.xview)):
        bar = ttk.Scrollbar(frame, orient=orient, command=command)
        bar.grid(row=row, column=column, sticky=sticky)
        tree.configure(**{"yscrollcommand" if orient == "vertical" else "xscrollcommand": bar.set})
    return frame, tree


class SensorLayoutEditor(ttk.Frame):
    def __init__(self, parent, changed, notify):
        super().__init__(parent, style="Card.TFrame", padding=12)
        self.changed, self.notify = changed, notify
        self.sensors, self.dirty, self.loading = (), False, False
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text="Fixed locations in the dataset frame. IDs must match sampled point IDs. Entry positions are in mm.",
                  style="CardText.TLabel", wraplength=820).grid(row=0, column=0, sticky="w", pady=4)
        form = ttk.Frame(self, style="Card.TFrame")
        form.grid(row=1, column=0, sticky="ew")
        self.variables = {}
        for index, (name, value) in enumerate((("point_id", "S1"), ("x_mm", "0"), ("y_mm", "0"), ("z_mm", "0"),
                                               ("nx", "0"), ("ny", "0"), ("nz", "1"))):
            variable = tk.StringVar(value=value)
            self.variables[name] = variable
            ttk.Label(form, text=name.replace("_", " "), style="Field.TLabel").grid(row=0, column=index, sticky="w")
            ttk.Entry(form, textvariable=variable, width=12).grid(row=1, column=index, sticky="ew", padx=(0, 8), pady=4)
            form.columnconfigure(index, weight=1)
            variable.trace_add("write", self.edited)
        table, self.tree = field_table(self, ("point_id", "x_mm", "y_mm", "z_mm", "nx", "ny", "nz"))
        table.grid(row=2, column=0, sticky="nsew", pady=8)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.select_sensor())
        self.tree.bind("<Return>", lambda _event: self.select_sensor())
        actions = ttk.Frame(self, style="Card.TFrame")
        actions.grid(row=3, column=0, sticky="w", pady=4)
        for label, command in (("Apply sensor", self.apply), ("Remove selected", self.remove)):
            ttk.Button(actions, text=label, command=command, style="Secondary.TButton").pack(side="left", padx=(0, 8))
        grid = ttk.LabelFrame(self, text="Grid template (explicitly replaces current layout)", padding=8)
        grid.grid(row=4, column=0, sticky="ew", pady=4)
        self.grid_vars = {}
        for index, (name, value) in enumerate((("rows", "3"), ("columns", "3"), ("spacing_mm", "20"), ("z_mm", "0"))):
            self.grid_vars[name] = tk.StringVar(value=value)
            ttk.Label(grid, text=name.replace("_", " ")).grid(row=0, column=index, sticky="w")
            ttk.Entry(grid, textvariable=self.grid_vars[name], width=13).grid(row=1, column=index, sticky="ew", padx=(0, 12))
            grid.columnconfigure(index, weight=1)
        ttk.Button(grid, text="Replace with Z-axis grid", style="Secondary.TButton", command=self.grid_layout).grid(row=1, column=4)

    def edited(self, *_args):
        if not self.loading:
            self.dirty = True
            self.changed()
            self.notify("Sensor entry changed. Apply sensor, or select an existing row to discard the entry edits.")

    def set_sensors(self, sensors):
        validate_layout(sensors)
        self.sensors, self.dirty = sensors, False
        self.tree.delete(*self.tree.get_children())
        for sensor in sensors:
            self.tree.insert("", "end", iid=sensor.point_id, values=(sensor.point_id,
                             *(format(v*1000, ".12g") for v in sensor.position_m), *sensor.axis))
        self.select_sensor(sensors[0].point_id)
        self.changed()

    def get_sensors(self):
        if self.dirty:
            raise ValueError("Apply sensor edits before analyzing, saving or exporting")
        validate_layout(self.sensors)
        return self.sensors

    def clear(self):
        self.sensors, self.dirty = (), False
        self.tree.delete(*self.tree.get_children())
        self.changed()

    def select_sensor(self, point_id=None):
        selection = self.tree.selection()
        point_id = point_id or (selection[0] if selection else None)
        sensor = next((item for item in self.sensors if item.point_id == point_id), None)
        if sensor is None:
            return
        self.loading = True
        try:
            for name, value in zip(self.variables, (sensor.point_id, *(v*1000 for v in sensor.position_m), *sensor.axis)):
                self.variables[name].set(str(value))
            self.dirty = False
        finally:
            self.loading = False

    def apply(self):
        try:
            values = self.variables
            sensor = Sensor(values["point_id"].get().strip(),
                            tuple(float(values[name].get())*.001 for name in ("x_mm", "y_mm", "z_mm")),
                            tuple(float(values[name].get()) for name in ("nx", "ny", "nz")))
            sensors = list(self.sensors)
            index = next((i for i, item in enumerate(sensors) if item.point_id == sensor.point_id), len(sensors))
            if index == len(sensors):
                sensors.append(sensor)
            else:
                sensors[index] = sensor
            self.set_sensors(tuple(sensors))
            self.select_sensor(sensor.point_id)
            self.notify("Sensor applied. Analyze again; directions are normalized during projection.")
        except (ValueError, OverflowError) as exc:
            self.notify(f"Layout blocked: {exc}")

    def remove(self):
        selection = self.tree.selection()
        if not selection:
            return
        self.sensors = tuple(item for item in self.sensors if item.point_id not in selection)
        self.tree.delete(*selection)
        self.dirty = False
        self.changed()
        if self.sensors:
            self.select_sensor(self.sensors[0].point_id)
        self.notify("Selected sensors removed from this workspace only.")

    def grid_layout(self):
        try:
            v = self.grid_vars
            self.set_sensors(make_sensor_grid(int(v["rows"].get()), int(v["columns"].get()),
                                             float(v["spacing_mm"].get())*.001, float(v["z_mm"].get())*.001, (0., 0., 1.)))
            self.notify("Grid replaced. Export layout points or match existing sample IDs; no field values were generated.")
        except (ValueError, OverflowError) as exc:
            self.notify(f"Grid blocked: {exc}")


def draw_field_layout(canvas, readings, scenario, reference):
    """Two sampled XY views with numeric labels, no interpolated color map."""
    canvas.delete("all")
    width, height = canvas.winfo_width(), canvas.winfo_height()
    foreground = ttk.Style(canvas).lookup("Field.TLabel", "foreground") or "black"
    if not readings or width < 120 or height < 100:
        canvas.create_text(20, 20, anchor="nw", fill=foreground, text="Analyze to display sampled XY locations.")
        return
    xs, ys = zip(*(row.sensor.position_m[:2] for row in readings))
    span = max(max(xs)-min(xs), max(ys)-min(ys), .001)
    center_x, center_y = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
    scale = min(max(10, width/2-110), max(10, height-135))/span
    for column, (title, attribute) in enumerate(((scenario, "projected_t"), (reference+" (reference)", "reference_t"))):
        center = width*(.25+.5*column)
        canvas.create_text(center, 20, text=title, fill=foreground)
        for row in readings:
            x = center + (row.sensor.position_m[0]-center_x)*scale
            y = height/2-8 - (row.sensor.position_m[1]-center_y)*scale
            value = getattr(row, attribute)
            canvas.create_oval(x-4, y-4, x+4, y+4, outline=foreground, fill=foreground if value is not None else "")
            if len(readings) <= 16:
                caption = row.sensor.point_id
                if height >= 220:
                    caption += "\n" + (f"{abs(value)*1e6:.3g} uT" if value is not None else "N/A")
                canvas.create_text(x, y+19, text=caption, fill=foreground)
    canvas.create_text(width/2, height-12, fill=foreground,
                       text="X right, Y up; Z and full values in table. Open marker / N/A = unavailable. No interpolation.")
