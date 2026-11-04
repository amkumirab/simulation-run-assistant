"""Offline native editor for explicitly declared model assumptions."""
import tkinter as tk
from dataclasses import asdict
from tkinter import filedialog, messagebox, ttk

from simulation_assistant.model_briefs import (
    SECTIONS, STATUSES, BriefEntry, ModelBrief, load_model_brief, save_model_brief, validate_brief,
)


class ModelBriefDialog:
    def __init__(self, parent):
        self.entries, self.selected = (), None
        self.header = {name: tk.StringVar(value=value) for name, value in
                       (('name', ''), ('revision', 'draft'), ('model_sha256', ''))}
        self.fields = {name: tk.StringVar(value=value) for name, value in asdict(BriefEntry('Geometry', '')).items()}
        self._entry_base = self._entry_values()
        self._saved = self._snapshot()
        self.window = tk.Toplevel(parent)
        self.window.title('WPT Model Brief')
        self.window.geometry('1160x780')
        self.window.minsize(920, 700)
        self.window.transient(parent)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.bind('<Escape>', lambda _event: self.close())
        self.window.bind('<Control-s>', lambda _event: self.save())
        body = ttk.Frame(self.window, style='Card.TFrame', padding=18)
        body.pack(fill='both', expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)
        ttk.Label(body, text='WPT Model Brief', style='CardTitle.TLabel').grid(row=0, column=0, sticky='w')
        self.notice = ttk.Label(body, text='User-declared specifications and assumptions. No solver starts here.\n'
                                'Confirmed means recorded by you, not scientific, hardware or safety approval.',
                                style='CardText.TLabel', wraplength=880)
        self.notice.grid(row=1, column=0, sticky='ew', pady=8)
        identity = ttk.Frame(body, style='Card.TFrame')
        identity.grid(row=2, column=0, sticky='ew')
        identity.columnconfigure(0, weight=2)
        identity.columnconfigure(1, weight=1)
        self.name_entry = self._input(identity, 'Model name', self.header['name'], 0, 0)
        self._input(identity, 'Revision', self.header['revision'], 0, 1)
        self._input(identity, 'Model SHA-256 (optional, user-declared; not verified)', self.header['model_sha256'], 1, 0, span=2)
        table = ttk.Frame(body, style='Card.TFrame')
        table.grid(row=3, column=0, sticky='nsew', pady=10)
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        columns = tuple(self.fields)
        self.tree = ttk.Treeview(table, columns=columns, show='headings', selectmode='browse', height=7)
        for name, width in zip(columns, (110, 180, 190, 60, 100, 260, 110)):
            self.tree.heading(name, text=name.replace('_', ' ').title())
            self.tree.column(name, width=width, minwidth=60, stretch=False)
        self.tree.grid(row=0, column=0, sticky='nsew')
        for orient, row, column in (('vertical', 0, 1), ('horizontal', 1, 0)):
            scroll = ttk.Scrollbar(table, orient=orient, command=self.tree.yview if row == 0 else self.tree.xview)
            scroll.grid(row=row, column=column, sticky='ns' if row == 0 else 'ew')
            self.tree.configure(**{'yscrollcommand' if row == 0 else 'xscrollcommand': scroll.set})
        self.tree.bind('<<TreeviewSelect>>', self.select_entry)
        self.tree.bind('<Return>', self.select_entry)
        editor = ttk.Frame(body, style='Card.TFrame')
        editor.grid(row=4, column=0, sticky='ew')
        for column in range(4):
            editor.columnconfigure(column, weight=1, uniform='brief')
        self._input(editor, 'Section', self.fields['section'], 0, 0, SECTIONS)
        self.entry_name = self._input(editor, 'Specification name', self.fields['name'], 0, 1)
        self._input(editor, 'Value (empty if unknown)', self.fields['value'], 0, 2)
        self._input(editor, 'Unit (blank = text; 1 = count)', self.fields['unit'], 0, 3)
        self._input(editor, 'Status', self.fields['status'], 1, 0, STATUSES)
        self._input(editor, 'Source / decision reference', self.fields['source'], 1, 1, span=2)
        self._input(editor, 'Review date (YYYY-MM-DD)', self.fields['reviewed_on'], 1, 3)
        actions = ttk.Frame(body, style='Card.TFrame')
        actions.grid(row=5, column=0, sticky='ew', pady=8)
        for title, command in (('Apply entry', self.apply_entry), ('New entry', self.new_entry), ('Remove entry', self.remove_entry)):
            ttk.Button(actions, text=title, command=command, style='Secondary.TButton').pack(side='left', padx=(0, 8))
        self.status = tk.StringVar(value='No specifications yet. Add entries; do not fill unknown values with guesses.')
        self.feedback = ttk.Label(body, textvariable=self.status, style='CardText.TLabel', wraplength=880)
        self.feedback.grid(row=6, column=0, sticky='ew', pady=8)
        files = ttk.Frame(body, style='Card.TFrame')
        files.grid(row=7, column=0, sticky='ew')
        for title, command in (('New brief', self.new_brief), ('Load JSON', self.load), ('Save JSON', self.save)):
            ttk.Button(files, text=title, command=command, style='Primary.TButton' if title == 'Save JSON' else 'Secondary.TButton').pack(side='left', padx=(0, 8))
        ttk.Button(files, text='Close', command=self.close, style='Secondary.TButton').pack(side='right')
        for variable in (*self.header.values(), *self.fields.values()):
            variable.trace_add('write', self._mark)
        body.bind('<Configure>', lambda event: [label.configure(wraplength=max(300, event.width-20))
                                              for label in (self.notice, self.feedback)])
        self.name_entry.focus_set()

    @staticmethod
    def _input(parent, label, variable, row, column, options=None, span=1):
        frame = ttk.Frame(parent, style='Card.TFrame')
        frame.grid(row=row, column=column, columnspan=span, sticky='ew', padx=(0, 8), pady=4)
        ttk.Label(frame, text=label, style='Field.TLabel').pack(anchor='w')
        widget = (ttk.Combobox(frame, textvariable=variable, values=options, state='readonly', width=16)
                  if options else ttk.Entry(frame, textvariable=variable, width=16))
        widget.pack(fill='x', pady=(4, 0))
        return widget

    def _entry_values(self):
        return tuple(variable.get() for variable in self.fields.values())

    def _snapshot(self):
        return tuple(variable.get() for variable in self.header.values()), self.entries

    def pending(self):
        return self._entry_values() != self._entry_base

    def dirty(self):
        return self.pending() or self._snapshot() != self._saved

    def _mark(self, *_args):
        self.window.title('WPT Model Brief' + (' *' if self.dirty() else ''))

    def _reset_entry(self):
        self.selected = None
        self.tree.selection_remove(self.tree.selection())
        self._set_fields(BriefEntry('Geometry', ''))

    def _set_fields(self, entry):
        for name, value in asdict(entry).items():
            self.fields[name].set(value)
        self._entry_base = self._entry_values()
        self._mark()

    def select_entry(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        index = int(selection[0])
        if self.pending():
            if self.selected != index:
                self.status.set('Apply the pending entry, or choose New entry to discard its edits, before selecting another row.')
                self.tree.selection_set(str(self.selected)) if self.selected is not None else self.tree.selection_remove(selection)
            return
        self.selected = index
        self._set_fields(self.entries[index])
        if _event is not None and _event.type == tk.EventType.KeyPress:
            self.entry_name.focus_set()

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        for index, entry in enumerate(self.entries):
            self.tree.insert('', 'end', iid=str(index), values=tuple(asdict(entry).values()))
        if self.selected is not None:
            self.tree.selection_set(str(self.selected))
            self.tree.see(str(self.selected))
        self._mark()

    def apply_entry(self):
        try:
            entry = BriefEntry(**{name: variable.get() for name, variable in self.fields.items()})
            entries = list(self.entries)
            if self.selected is None:
                entries.append(entry)
            else:
                entries[self.selected] = entry
            validate_brief(ModelBrief('Draft', 'draft', '', tuple(entries)))
            self.entries = tuple(entries)
            self.selected = len(entries)-1 if self.selected is None else self.selected
            self._entry_base = self._entry_values()
            self._refresh()
            self.status.set(f'{len(entries)} entries | {sum(e.status == "unknown" for e in entries)} unknown. Entry applied; save JSON to retain changes.')
            return True
        except ValueError as exc:
            self.status.set(str(exc))
            return False

    def new_entry(self):
        if self.pending() and not messagebox.askyesno('Pending entry', 'Discard unapplied entry edits?', parent=self.window):
            return
        self._reset_entry()
        self.entry_name.focus_set()
        self.status.set('New entry. Unknown values stay empty; other statuses need a source.')

    def remove_entry(self):
        if self.pending():
            self.status.set('Apply or discard pending entry edits before removing a row.')
        elif self.selected is not None:
            self.entries = tuple(entry for index, entry in enumerate(self.entries) if index != self.selected)
            self._reset_entry()
            self._refresh()
            self.status.set('Entry removed from this draft. Save JSON to retain the change.')

    def _can_discard(self):
        return not self.dirty() or messagebox.askyesno('Unsaved model brief', 'Discard unsaved brief and entry changes?', parent=self.window)

    def new_brief(self):
        if self._can_discard():
            self.entries = ()
            for name, value in (('name', ''), ('revision', 'draft'), ('model_sha256', '')):
                self.header[name].set(value)
            self._reset_entry()
            self._saved = self._snapshot()
            self._refresh()
            self.status.set('New brief. Enter a model name and revision; nothing is inferred from COMSOL.')

    def save(self):
        if self.pending():
            self.status.set('Apply the pending entry, or discard its edits with New entry, before saving.')
            return False
        try:
            brief = ModelBrief(**{name: variable.get() for name, variable in self.header.items()}, entries=self.entries)
            validate_brief(brief)
            path = filedialog.asksaveasfilename(parent=self.window, title='Save model brief', defaultextension='.json', filetypes=[('Model brief', '*.json')])
            if not path:
                return False
            save_model_brief(path, brief)
            self._saved = self._snapshot()
            self._mark()
            self.status.set('Model brief saved. Review free-text sources for private details before sharing.')
            return True
        except (ValueError, OSError) as exc:
            self.status.set(f'Could not save: {exc}')
            return False

    def load(self):
        path = filedialog.askopenfilename(parent=self.window, title='Load model brief', filetypes=[('Model brief', '*.json')])
        if not path:
            return
        try:
            brief = load_model_brief(path)
        except (ValueError, OSError) as exc:
            self.status.set(f'Could not load; current work kept: {exc}')
            return
        self.set_brief(brief, saved=True)

    def set_brief(self, brief, *, saved=False):
        """Open a validated draft, asking before replacing unsaved user edits."""
        validate_brief(brief)
        if not self._can_discard():
            return False
        self.entries = brief.entries
        for name, variable in self.header.items():
            variable.set(getattr(brief, name))
        self._reset_entry()
        if saved:
            self._saved = self._snapshot()
        self._refresh()
        self.status.set(f'{len(self.entries)} entries. ' + ('Loaded saved brief.' if saved else 'New unsaved proposal; review and save JSON.'))
        return True

    def close(self):
        if self._can_discard():
            self.window.destroy()
