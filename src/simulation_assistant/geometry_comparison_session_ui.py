"""Manual native comparison session persistence; no automatic recovery."""
from pathlib import Path
from tkinter import filedialog, messagebox

from simulation_assistant.geometry_comparison_sessions import (
    GeometryComparisonSession, load_session, save_session, validate_session,
)


class ComparisonSessions:
    def __init__(self, owner):
        self.owner = owner

    def save(self):
        owner = self.owner
        try:
            owner.require_sources()
            if owner.pending():
                raise ValueError('Add pair or Clear form before saving a session')
            session = GeometryComparisonSession(owner.sources['baseline'], owner.sources['candidate'],
                                                owner.pairs, float(owner.threshold.get()))
            validate_session(session)
            path = filedialog.asksaveasfilename(parent=owner.window, title='Save geometry comparison session',
                                               defaultextension='.json', initialfile='comparison-session.json',
                                               filetypes=[('Comparison session', '*.json')])
            if not path:
                return False
            target = Path(path).resolve()
            for source in owner.snapshot_paths.values():
                if source is not None and (target == source or
                        (target.exists() and source.exists() and target.samefile(source))):
                    raise ValueError('Choose a separate session file; do not overwrite a source snapshot')
            save_session(target, session)
            owner._saved = owner.session_signature()
            owner.window.title('Geometry Comparison')
            owner.status.set('Session saved: '+target.name+'. Inputs only; frame approval and results are not stored.')
            return True
        except (ValueError, OSError) as exc:
            owner.status.set('Session save blocked; current work kept: '+str(exc)[-400:])
            return False

    def load(self):
        owner = self.owner
        path = filedialog.askopenfilename(parent=owner.window, title='Load geometry comparison session',
                                          filetypes=[('Comparison session', '*.json')])
        if not path:
            return False
        try:
            session = load_session(path)
            if owner.dirty() and not messagebox.askyesno('Unsaved comparison session',
                    'Discard unsaved comparison inputs and load this session?', parent=owner.window):
                return False
        except (ValueError, OSError) as exc:
            owner.status.set('Session load failed; current work kept: '+str(exc)[-400:])
            return False
        owner.sources = {'baseline': session.baseline, 'candidate': session.candidate}
        owner.snapshot_paths = dict.fromkeys(owner.sources)
        owner.pairs = session.pairs
        owner.pairs_tree.delete(*owner.pairs_tree.get_children())
        for i, pair in enumerate(owner.pairs):
            owner.pairs_tree.insert('', 'end', iid=str(i), values=(
                pair.label, pair.baseline_domain, pair.candidate_domain, 'Not compared'))
        owner.clear_form()
        owner.threshold.set(str(session.tolerance_mm))
        owner.frames.set(False)
        for side in owner.sources:
            owner.show_source(side, Path(path).name+' (embedded '+side+')')
        owner.tabs.select(0)
        owner._saved = owner.session_signature()
        owner.invalidate()
        owner.status.set('Session loaded: '+Path(path).name+'. Review mappings and coordinate frames; declare frames and compare again.')
        owner.label_entry.focus_set()
        return True
