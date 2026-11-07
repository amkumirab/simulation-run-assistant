"""Explicit native snapshot correspondence; never mutates models or starts a solver."""
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from simulation_assistant.geometry_comparison import DomainPair, compare_geometry, validate_pairs
from simulation_assistant.geometry_comparison_files import export_comparison_csv
from simulation_assistant.geometry_files import load_snapshot, snapshot_digest
from simulation_assistant.geometry_inspector import validate_snapshot
from simulation_assistant.geometry_comparison_widgets import build_comparison_widgets


class GeometryComparisonDialog:
    def __init__(self,parent):
        self.sources={'baseline':None,'candidate':None}
        self.pairs,self.result,self.closed=(),None,False
        self.window=tk.Toplevel(parent)
        self.window.title('Geometry Comparison')
        self.window.geometry('1240x850')
        self.window.minsize(1000,760)
        self.window.transient(parent)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.window.bind('<Escape>',lambda _event:self.close())
        self.window.bind('<Destroy>',self.destroyed)
        self.form={name:tk.StringVar() for name in ('label','baseline','candidate')}
        self.frames,self.threshold=tk.BooleanVar(value=False),tk.StringVar(value='0.01')
        self.result_label=tk.StringVar()
        self.pair_context=tk.StringVar(value='All deltas: Candidate - Baseline')
        self.source_info={side:tk.StringVar(value='No snapshot loaded.') for side in self.sources}
        self.domain_details={side:tk.StringVar(value='Select a domain to inspect its selection tags and bounds.') for side in self.sources}
        self.status=tk.StringVar(value='Load two stored snapshots. Explicit mapping and comparable-frame declaration are required.')
        build_comparison_widgets(self)
        self._saved=self.signature()
        self.traces=[(v,v.trace_add('write',self.invalidate)) for v in (*self.form.values(),self.frames,self.threshold)]
        self.traces.append((self.result_label,self.result_label.trace_add('write',self.show_metrics)))
        self.label_entry.focus_set()

    def signature(self):
        return (*self.sources.values(),self.pairs,self.frames.get(),self.threshold.get(),tuple(v.get() for v in self.form.values()))

    def pending(self):
        return any(v.get() for v in self.form.values())

    def dirty(self):
        return bool(self.pairs or self.pending()) and self.signature()!=self._saved

    def invalidate(self,*_args):
        if self.closed:
            return
        self.result=None
        self.metrics_tree.delete(*self.metrics_tree.get_children())
        self.result_box.configure(values=())
        self.result_label.set('')
        for item in self.pairs_tree.get_children():
            values=self.pairs_tree.item(item,'values')
            self.pairs_tree.item(item,values=(*values[:3],'Not compared'))
        for side,data in self.sources.items():
            selected=next((p for p in data.parts if str(p.domain)==self.form[side].get()),None) if data else None
            self.domain_details[side].set((selected.selections or 'No named selections')+'\nBounds (mm): '+', '.join(f'{v*1000:.6g}' for v in selected.bounds_m)
                                          if selected else 'Select a domain to inspect its selection tags and bounds.')
        self.status.set('Inputs changed; compare again. Apply a pending pair with Add pair, or Clear form.')
        self.window.title('Geometry Comparison'+(' *' if self.dirty() else ''))

    def set_snapshot(self,side,data,origin):
        if side not in self.sources:
            raise ValueError('Choose baseline or candidate')
        validate_snapshot(data)
        if (self.pairs or self.pending()) and not messagebox.askyesno('Replace snapshot','Replacing either snapshot clears all mapped pairs and unapplied fields. Continue?',parent=self.window):
            return False
        self.sources[side]=data
        self.pairs=()
        self.pairs_tree.delete(*self.pairs_tree.get_children())
        self.frames.set(False)
        self.clear_form()
        self.domain_boxes[side].configure(values=tuple(str(p.domain) for p in data.parts))
        self.source_info[side].set(f'{origin} | {data.component}/{data.geometry} | {len(data.parts)} domains | original unit {data.length_unit}\n'
                                   f'Model SHA: {data.source_sha256}\nSnapshot SHA: {snapshot_digest(data)}')
        self.status.set('Snapshot loaded. Domain IDs and selection tags do not establish correspondence automatically.')
        return True

    def load(self,side):
        path=filedialog.askopenfilename(parent=self.window,title='Load '+side+' geometry snapshot',filetypes=[('Geometry snapshot','*.json')])
        if path:
            try:
                self.set_snapshot(side,load_snapshot(path),Path(path).name)
            except (ValueError,OSError) as exc:
                self.status.set('Load failed; current work kept: '+str(exc)[-400:])

    def clear_form(self):
        for variable in self.form.values():
            variable.set('')

    def add_pair(self):
        try:
            self.require_sources()
            if not self.form['baseline'].get() or not self.form['candidate'].get():
                raise ValueError('Select a domain ID on each side first')
            pair=DomainPair(self.form['label'].get().strip(),int(self.form['baseline'].get()),int(self.form['candidate'].get()))
            validate_pairs(self.sources['baseline'],self.sources['candidate'],(*self.pairs,pair))
            self.pairs=(*self.pairs,pair)
            self.pairs_tree.insert('','end',iid=str(len(self.pairs)-1),values=(pair.label,pair.baseline_domain,pair.candidate_domain,'Not compared'))
            self.clear_form()
            self.status.set(f'{len(self.pairs)} explicit pairs. Review mappings and coordinate frames, then compare.')
            return True
        except ValueError as exc:
            self.status.set('Pair not added: '+str(exc))
            return False

    def remove_pair(self):
        if self.pending():
            self.status.set('Add or clear unapplied pair fields before removing a pair.')
            return
        selected=self.pairs_tree.selection()
        if selected:
            index=int(selected[0])
            self.pairs=tuple(p for i,p in enumerate(self.pairs) if i!=index)
            self.pairs_tree.delete(*self.pairs_tree.get_children())
            for i,p in enumerate(self.pairs):
                self.pairs_tree.insert('','end',iid=str(i),values=(p.label,p.baseline_domain,p.candidate_domain,'Not compared'))
            self.invalidate()

    def current_comparison(self):
        self.require_sources()
        if self.pending():
            raise ValueError('Add pair or Clear form before comparison/export')
        return compare_geometry(self.sources['baseline'],self.sources['candidate'],self.pairs,
                                comparable_frames=self.frames.get(),tolerance_mm=float(self.threshold.get()))

    def require_sources(self):
        if any(source is None for source in self.sources.values()):
            raise ValueError('Load a Baseline and Candidate snapshot first')

    def compare(self):
        self.result=None
        try:
            self.result=self.current_comparison()
            labels=tuple(p.label for p in self.pairs)
            self.result_box.configure(values=labels)
            self.result_label.set(labels[0])
            for i,difference in enumerate(self.result.differences):
                self.pairs_tree.item(str(i),values=(difference.pair.label,difference.pair.baseline_domain,difference.pair.candidate_domain,
                                                   'Changed' if difference.changed else 'Within threshold'))
            self.status.set(f'{len(self.pairs)} mapped pairs; {sum(d.changed for d in self.result.differences)} changed. '
                            f'Unmapped domains: Baseline {len(self.result.baseline_unmapped)}, Candidate {len(self.result.candidate_unmapped)}. '
                            'Unmapped is not added/deleted. Threshold is not manufacturing tolerance; envelopes are not solid geometry.')
            self.tabs.select(1)
            return True
        except ValueError as exc:
            self.metrics_tree.delete(*self.metrics_tree.get_children())
            self.status.set('Comparison blocked: '+str(exc))
            return False

    def show_metrics(self,*_args):
        self.metrics_tree.delete(*self.metrics_tree.get_children())
        self.pair_context.set('All deltas: Candidate - Baseline')
        if self.result:
            difference=next((d for d in self.result.differences if d.pair.label==self.result_label.get()),None)
            if difference:
                self.pair_context.set(f'Baseline D{difference.pair.baseline_domain} -> Candidate D{difference.pair.candidate_domain} | Delta: Candidate - Baseline')
                for metric in difference.metrics:
                    self.metrics_tree.insert('','end',values=(metric.name,format(metric.baseline_mm,'.6g'),format(metric.candidate_mm,'.6g'),
                                                             format(metric.delta_mm,'+.6g'),'Changed' if metric.changed else 'Within threshold'))

    def select_pair(self,_event=None):
        selected=self.pairs_tree.selection()
        if selected and self.result:
            self.result_label.set(self.pairs[int(selected[0])].label)
            if _event is not None and _event.type==tk.EventType.KeyPress:
                self.tabs.select(1)
                self.result_box.focus_set()

    def export(self):
        try:
            if self.result is None or self.current_comparison()!=self.result:
                raise ValueError('Compare current inputs before exporting')
            path=filedialog.asksaveasfilename(parent=self.window,title='Export geometry comparison',defaultextension='.csv',filetypes=[('Comparison CSV','*.csv')])
            if not path:
                return False
            export_comparison_csv(path,self.result)
            self._saved=self.signature()
            self.window.title('Geometry Comparison')
            self.status.set('Comparison CSV saved with explicit mappings, coverage and both source/content hashes. No model path or MPH included.')
            return True
        except (ValueError,OSError) as exc:
            self.status.set('Export blocked: '+str(exc)[-400:])
            return False

    def close(self):
        if not self.dirty() or messagebox.askyesno('Unsaved comparison','Discard mappings or unapplied fields not retained in the latest exported CSV?',parent=self.window):
            self.window.destroy()

    def destroyed(self,event):
        if event.widget is self.window:
            self.closed=True
            for variable,token in self.traces:
                variable.trace_remove('write',token)
            self.traces.clear()
