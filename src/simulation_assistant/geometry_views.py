"""Explicit XZ projections of saved bounding envelopes, never solid CAD."""


def draw_envelopes(canvas, parts):
    canvas.delete('all')
    width, height = max(400, canvas.winfo_width()), max(200, canvas.winfo_height())
    canvas.create_text(16, 14, anchor='nw', text='XZ envelope projection | independent X / Z scales | mm', fill='#233954')
    if not parts:
        canvas.create_text(24, 65, anchor='nw', text='Select domains in the Bounds tab to draw their envelopes.', fill='#233954')
        return
    xmin, xmax = min(p.bounds_m[0] for p in parts), max(p.bounds_m[1] for p in parts)
    zmin, zmax = min(p.bounds_m[4] for p in parts), max(p.bounds_m[5] for p in parts)
    left, top, right, bottom = 80, 55, width-50, height-55
    x = lambda value: left+(value-xmin)/(xmax-xmin)*(right-left)
    z = lambda value: bottom-(value-zmin)/(zmax-zmin)*(bottom-top)
    canvas.create_line(left, top, left, bottom, right, bottom, fill='#233954')
    for fraction in (0, .25, .5, .75, 1):
        xv, zv = xmin+fraction*(xmax-xmin), zmin+fraction*(zmax-zmin)
        canvas.create_text(x(xv), bottom+16, text=f'{xv*1000:.1f}', fill='#233954')
        canvas.create_text(left-8, z(zv), anchor='e', text=f'{zv*1000:.1f}', fill='#233954')
    canvas.create_text(right, bottom+35, text='X (mm)', anchor='e', fill='#233954')
    canvas.create_text(16, 36, text='Z (mm)', anchor='w', fill='#233954')
    for part in parts:
        a, b, _, _, c, d = part.bounds_m
        canvas.create_rectangle(x(a), z(d), x(b), z(c), outline='#2459ad', width=2, dash=(5, 3))
        canvas.create_text(x((a+b)/2), z((c+d)/2), text=f'D{part.domain}', fill='#142d50', font=('Segoe UI', 9, 'bold'))
