"""Native presentation for the explicit geometry comparison controller."""
from tkinter import ttk


def table(parent, columns, height=7):
    frame = ttk.Frame(parent)
    frame.pack(fill='both', expand=True, pady=6)
    frame.rowconfigure(0,weight=1)
    frame.columnconfigure(0,weight=1)
    tree = ttk.Treeview(frame,columns=tuple(name for name,_ in columns),show='headings',height=height,selectmode='browse')
    for name,width in columns:
        heading = name.replace('_', ' ').title()
        if name.endswith('_mm'):
            heading = name[:-3].replace('_', ' ').title()+' (mm)'
        tree.heading(name,text=heading)
        tree.column(name,width=width,minwidth=65,stretch=name in ('part','quantity'))
    tree.grid(row=0,column=0,sticky='nsew')
    for orient,row,col in (('vertical',0,1),('horizontal',1,0)):
        scrollbar=ttk.Scrollbar(frame,orient=orient,command=tree.yview if col else tree.xview)
        scrollbar.grid(row=row,column=col,sticky='ns' if col else 'ew')
        tree.configure(**{'yscrollcommand' if col else 'xscrollcommand':scrollbar.set})
    return tree


def build_comparison_widgets(owner):
    body=ttk.Frame(owner.window,style='Card.TFrame',padding=18)
    body.pack(fill='both',expand=True)
    body.columnconfigure(0,weight=1)
    body.rowconfigure(5,weight=1)
    ttk.Label(body,text='Geometry Comparison',style='CardTitle.TLabel').grid(row=0,column=0,sticky='w')
    notice=ttk.Label(body,text='STORED SNAPSHOTS ONLY | Candidate minus Baseline | Approximate global envelopes, '
                     'not solid centroids, topology, clearance or performance approval.',style='CardText.TLabel',wraplength=1150)
    notice.grid(row=1,column=0,sticky='ew',pady=(6,8))
    cards=ttk.Frame(body,style='Card.TFrame')
    cards.grid(row=2,column=0,sticky='ew')
    owner.domain_boxes={}
    owner.detail_labels={}
    for column,side in enumerate(('baseline','candidate')):
        cards.columnconfigure(column,weight=1,uniform='sources')
        card=ttk.LabelFrame(cards,text=side.title(),padding=8)
        card.grid(row=0,column=column,sticky='nsew',padx=(0,8) if column==0 else (8,0))
        card.columnconfigure(0,weight=1)
        ttk.Button(card,text='Load '+side+' JSON',command=lambda s=side:owner.load(s),style='Secondary.TButton').grid(row=0,column=0,sticky='w')
        info=ttk.Label(card,textvariable=owner.source_info[side],wraplength=520)
        info.grid(row=1,column=0,sticky='ew',pady=6)
        pick=ttk.Frame(card)
        pick.grid(row=2,column=0,sticky='ew')
        ttk.Label(pick,text='Domain ID').pack(side='left',padx=(0,8))
        box=ttk.Combobox(pick,textvariable=owner.form[side],state='readonly',width=10)
        box.pack(side='left')
        owner.domain_boxes[side]=box
        detail=ttk.Label(card,textvariable=owner.domain_details[side],wraplength=520)
        detail.grid(row=3,column=0,sticky='ew',pady=(6,0))
        owner.detail_labels[side]=detail
        card.bind('<Configure>',lambda event,a=info,b=detail:[label.configure(wraplength=max(200,event.width-24)) for label in (a,b)])
    pair=ttk.Frame(body,style='Card.TFrame')
    pair.grid(row=3,column=0,sticky='ew',pady=8)
    pair.columnconfigure(1,weight=1)
    ttk.Label(pair,text='Part / pair label',style='Field.TLabel').grid(row=0,column=0,padx=(0,10))
    owner.label_entry=ttk.Entry(pair,textvariable=owner.form['label'])
    owner.label_entry.grid(row=0,column=1,sticky='ew')
    for column,(text,command) in enumerate((('Add pair',owner.add_pair),('Clear form',owner.clear_form),('Remove selected pair',owner.remove_pair)),2):
        ttk.Button(pair,text=text,command=command,style='Secondary.TButton').grid(row=0,column=column,padx=(8,0))
    settings=ttk.Frame(body,style='Card.TFrame')
    settings.grid(row=4,column=0,sticky='ew',pady=(0,6))
    ttk.Checkbutton(settings,text='I declare both snapshots use comparable global coordinate frames',variable=owner.frames).pack(side='left')
    ttk.Label(settings,text='Comparison threshold (mm)').pack(side='left',padx=(18,8))
    ttk.Entry(settings,textvariable=owner.threshold,width=9).pack(side='left')
    owner.tabs=ttk.Notebook(body)
    owner.tabs.grid(row=5,column=0,sticky='nsew')
    mapping=ttk.Frame(owner.tabs,padding=8)
    owner.tabs.add(mapping,text='Explicit part mapping')
    ttk.Label(mapping,text='No automatic pairing. Unmapped domains are not assumed added or deleted.').pack(anchor='w')
    owner.pairs_tree=table(mapping,(('part',300),('baseline_domain',130),('candidate_domain',130),('state',200)))
    owner.pairs_tree.bind('<<TreeviewSelect>>',owner.select_pair)
    owner.pairs_tree.bind('<Return>',owner.select_pair)
    results=ttk.Frame(owner.tabs,padding=8)
    owner.tabs.add(results,text='Differences (mm)')
    selector=ttk.Frame(results)
    selector.pack(fill='x')
    ttk.Label(selector,text='Mapped part').pack(side='left',padx=(0,8))
    owner.result_box=ttk.Combobox(selector,textvariable=owner.result_label,state='readonly',width=42)
    owner.result_box.pack(side='left')
    ttk.Label(selector,textvariable=owner.pair_context).pack(side='left',padx=12)
    owner.metrics_tree=table(results,(('quantity',260),('baseline_mm',150),('candidate_mm',150),('delta_mm',150),('state',200)))
    owner.feedback=ttk.Label(body,textvariable=owner.status,style='CardText.TLabel',wraplength=1150)
    owner.feedback.grid(row=6,column=0,sticky='ew',pady=8)
    actions=ttk.Frame(body,style='Card.TFrame')
    actions.grid(row=7,column=0,sticky='ew')
    ttk.Button(actions,text='Compare current mappings',command=owner.compare,style='Primary.TButton').pack(side='left')
    ttk.Button(actions,text='Export comparison CSV',command=owner.export,style='Secondary.TButton').pack(side='left',padx=8)
    ttk.Button(actions,text='Close',command=owner.close,style='Secondary.TButton').pack(side='right')
    body.bind('<Configure>',lambda event:[label.configure(wraplength=max(400,event.width-36)) for label in (notice,owner.feedback)])
