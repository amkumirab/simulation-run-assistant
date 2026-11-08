"""Compare real stored WPT envelopes; no COMSOL, license, MPH edits or new solve."""
import argparse
import csv
import tempfile
from pathlib import Path
from unittest.mock import patch
from simulation_assistant.geometry_files import load_snapshot
from simulation_assistant.geometry_comparison import DomainPair, compare_geometry
from simulation_assistant.geometry_comparison_files import export_comparison_csv
from simulation_assistant.geometry_comparison_sessions import GeometryComparisonSession, load_session, save_session

LABELS = ('Left RX shield','Left RX ferrite','Left RX coil','TX shield','Center RX shield',
          'TX ferrite','Center RX ferrite','TX coil','Center RX coil','Right RX shield',
          'Right RX ferrite','Right RX coil')
HASHES = {'original':'ffa0f12bc3b5877b0b039742ffab099795bc3d33fb188177112a896b8e56c3a8',
          'overlap':'80b6f71b59e0d36224dff386864d287adb6c231bbee65ffd7076f42796df7917',
          'control':'b5b4f573aee911b2249c7b1d34b6be2870b8d80aedc2b17d1cd6c90ffbef783a'}


def check(value,message):
    if not value:
        raise RuntimeError(message)


def capture(root,dialog,folder,name):
    import ctypes
    from PIL import ImageGrab
    folder.mkdir(parents=True,exist_ok=True)
    dialog.window.lift()
    root.update()
    handle=ctypes.windll.user32.GetAncestor(dialog.window.winfo_id(),2)
    ImageGrab.grab(window=handle).save(folder/name)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',choices=('overlap','control'),default='overlap')
    parser.add_argument('--headless',action='store_true')
    parser.add_argument('--output-dir',type=Path,help='Retain CSV in this folder; refuse existing report overwrite')
    parser.add_argument('--capture-dir',type=Path,help='Optional actual Windows native captures using existing Pillow')
    parser.add_argument('--desktop',action='store_true',help='Keep the isolated native example open')
    parser.add_argument('--session-roundtrip',action='store_true',help='Save/reopen portable inputs and require fresh frame confirmation')
    args=parser.parse_args()
    if args.headless and (args.capture_dir or args.desktop):
        parser.error('Native captures/desktop cannot be combined with --headless')
    fixtures=Path(__file__).with_name('saved_geometry_wpt')
    base,candidate=(load_snapshot(fixtures/(name+'.json')) for name in ('original',args.candidate))
    check(base.source_sha256==HASHES['original'] and candidate.source_sha256==HASHES[args.candidate], 'Worked-example source identity changed')
    # Explicit fixture-specific correspondence, verified for these exact saved models.
    pairs=tuple(DomainPair(label,domain,domain) for domain,label in enumerate(LABELS,2))
    result=compare_geometry(base,candidate,pairs,comparable_frames=True)
    left={m.name:m for m in result.differences[2].metrics}
    check(abs(left['midpoint_x'].delta_mm-(140. if args.candidate=='overlap' else 0.))<.001,'Incorrect left RX X delta')
    check(abs(left['midpoint_z'].delta_mm-20.)<.001,'Incorrect left RX Z delta')
    check(sum(d.changed for d in result.differences)==6,'Expected only the six side-stack envelopes to change')
    check(result.baseline_unmapped==result.candidate_unmapped==(1,),'Air coverage must remain explicit')
    with tempfile.TemporaryDirectory(prefix='geometry-comparison-review-') as directory:
        folder=Path(directory)
        output=args.output_dir or folder
        output.mkdir(parents=True,exist_ok=True)
        report=output/('original-vs-'+args.candidate+'.csv')
        check(not report.exists(),'Choose an output directory without an existing report')
        session_path=output/('original-vs-'+args.candidate+'-session.json')
        if args.session_roundtrip:
            check(not session_path.exists(),'Choose an output directory without an existing session')
        if args.headless:
            export_comparison_csv(report,result)
            if args.session_roundtrip:
                session=GeometryComparisonSession(base,candidate,pairs)
                save_session(session_path,session)
                restored=load_session(session_path)
                check(restored==session,'Session inputs changed during roundtrip')
                check(compare_geometry(restored.baseline,restored.candidate,restored.pairs,
                      comparable_frames=True,tolerance_mm=restored.tolerance_mm)==result,'Recomputed session differs')
        else:
            import tkinter as tk
            from simulation_assistant.desktop import DesktopApp
            from simulation_assistant.geometry_comparison_ui import GeometryComparisonDialog
            root=tk.Tk()
            errors=[]
            root.report_callback_exception=lambda *error:errors.append(error)
            try:
                app=DesktopApp(root,folder/'jobs.db',folder/'artifacts',folder/'profiles.json')
                app.notebook.select(1)
                dialog=GeometryComparisonDialog(root)
                dialog.set_snapshot('baseline',base,'Real stored Original | offline replay')
                dialog.set_snapshot('candidate',candidate,'Real stored '+args.candidate+' | offline replay')
                for pair in pairs:
                    for key,value in (('label',pair.label),('baseline',str(pair.baseline_domain)),('candidate',str(pair.candidate_domain))):
                        dialog.form[key].set(value)
                    check(dialog.add_pair(),dialog.status.get())
                dialog.frames.set(True)  # Explicit declaration for the documented unchanged global frames.
                check(dialog.compare(),dialog.status.get())
                check(dialog.result==result,'Native comparison differs from the validated result')
                for size in ('1000x760','1240x850'):
                    dialog.window.geometry(size+'+30+30')
                    root.update()
                    body=dialog.window.winfo_children()[0]
                    for widget in body.winfo_children():
                        check(widget.winfo_x()+widget.winfo_width()<=body.winfo_width(),'Horizontal clipping: '+str(widget))
                        check(widget.winfo_y()+widget.winfo_height()<=body.winfo_height(),'Vertical clipping: '+str(widget))
                dialog.tabs.select(0)
                root.update()  # Map the notebook page before sending its keyboard event.
                dialog.pairs_tree.selection_set('2')
                dialog.pairs_tree.focus_force()
                dialog.pairs_tree.event_generate('<Return>')
                root.update()
                check(root.focus_get()==dialog.result_box,'Enter did not focus the selected pair result')
                check(dialog.result_label.get()=='Left RX coil','Wrong selected pair')
                with patch('simulation_assistant.geometry_comparison_ui.filedialog.asksaveasfilename',return_value=str(report)):
                    check(dialog.export(),dialog.status.get())
                if args.session_roundtrip:
                    with patch('tkinter.filedialog.asksaveasfilename',return_value=str(session_path)):
                        check(dialog.sessions.save(),dialog.status.get())
                    check(not dialog.dirty(),'Saved inputs still marked dirty')
                    dialog.threshold.set('1')
                    with patch('tkinter.filedialog.askopenfilename',return_value=str(session_path)), \
                            patch('tkinter.messagebox.askyesno',return_value=True):
                        check(dialog.sessions.load(),dialog.status.get())
                    check(not dialog.frames.get() and dialog.result is None,'Loaded session trusted previous approval/results')
                    check(not dialog.metrics_tree.get_children() and not dialog.dirty(),'Loaded session state is stale or dirty')
                    check(dialog.pairs==pairs,'Session mapping changed')
                    if args.capture_dir:
                        capture(root,dialog,args.capture_dir,'geometry-session-'+args.candidate+'-loaded.png')
                    check(not dialog.compare(),'Comparison accepted without fresh frame confirmation')
                    dialog.frames.set(True)
                    check(dialog.compare(),dialog.status.get())
                    check(dialog.result==result and not dialog.dirty(),'Recomputed session differs or changed saved inputs')
                    dialog.result_label.set('Left RX coil')
                if args.capture_dir:
                    captures=((1,'recomputed'),) if args.session_roundtrip else ((0,'mapping'),(1,'differences'))
                    for tab,name in captures:
                        dialog.tabs.select(tab)
                        prefix='geometry-session-' if args.session_roundtrip else 'geometry-comparison-'
                        capture(root,dialog,args.capture_dir,prefix+args.candidate+'-'+name+'.png')
                check(not errors,'Native callback errors: '+str(errors))
                check(app.store.page_jobs().total==0 and app.connection_report is None,'Production workflow was touched')
                if args.desktop:
                    root.mainloop()
            finally:
                try:
                    alive=root.winfo_exists()
                except tk.TclError:
                    alive=False
                if alive:
                    root.update_idletasks()
                    for child in list(root.winfo_children()):
                        if isinstance(child,tk.Toplevel): child.destroy()
                    for timer in root.tk.call('after','info'): root.after_cancel(timer)
                    root.destroy()
        with report.open(encoding='utf-8',newline='') as stream:
            check(len(list(csv.DictReader(stream)))==144,'CSV must contain all 12 metrics for 12 explicit pairs')
        print('PASS: original vs '+args.candidate+' | 12 explicit pairs, 6 changed, air unmapped | 144 CSV metrics | no model/solver actions')
        if args.session_roundtrip:
            print('PASS: portable session roundtrip | embedded snapshots and mappings retained | fresh comparison required')


if __name__=='__main__':
    main()
