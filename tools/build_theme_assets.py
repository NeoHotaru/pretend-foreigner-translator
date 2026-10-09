"""Build code-defined, antialiased control surfaces; no runtime imaging dependency."""
import sys
from pathlib import Path
sys.path.append('D:/Aconnada/Lib/site-packages')
from PIL import Image, ImageDraw
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'assets/theme';OUT.mkdir(parents=True,exist_ok=True)
S=4
def surface(name,fill,line=None,radius=9,size=256):
    image=Image.new('RGBA',(size*S,size*S));draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((S,S,(size-1)*S,(size-1)*S),radius=radius*S,fill=fill,outline=line,width=S)
    image.resize((size,size),Image.Resampling.LANCZOS).save(OUT/(name+'.png'))
for name,fill in {'neutral':'#FFFFFF','hover':'#EDF1F6','pressed':'#DFE6EF','disabled':'#F0F2F5',
    'primary':'#315FCC','primary-hover':'#2853B8','primary-pressed':'#204593',
    'peer':'#177C70','peer-hover':'#136B60','peer-pressed':'#10564E',
    'dark':'#18222F','dark-hover':'#263446','dark-pressed':'#33455B',
    'soft':'#EAF0FB','soft-hover':'#DAE5F8'}.items():surface(name,fill)
surface('field','#FFFFFF','#DFE5ED')
surface('field-focus','#FFFFFF','#7998DD')
surface('field-disabled','#F1F3F6','#E6EBF0')
for name,fill,line in [('neutral-focus','#FFFFFF','#315FCC'),('primary-focus','#315FCC','#17377D'),
                       ('peer-focus','#177C70','#08483F'),('soft-focus','#EAF0FB','#315FCC'),
                       ('dark-focus','#18222F','#83B9EF'),('quiet-focus','#FFFFFF','#315FCC')]:
    surface(name,fill,line)
surface('reading','#F6F8FC','#E3E8EF')
surface('reading-focus','#F6F8FC','#7998DD')
Image.new('RGBA',(256,256)).save(OUT/'quiet.png')
Image.new('RGBA',(256,256),'#E3E8EF').save(OUT/'separator.png')
# ttk tiles image centres; avoid thousands of GDI alpha-blends per large frame.
surface('card','#FFFFFF','#E6EBF2',radius=16,size=512)
surface('dark-card','#18222F','#324153',radius=16,size=512)
surface('scroll','#BEC8D5',radius=3,size=8)
surface('scroll-hover','#8998AE',radius=3,size=8)
for selected in (False,True):
    for disabled in (False,True):
        im=Image.new('RGBA',(20*S,20*S));d=ImageDraw.Draw(im)
        fill=('#C7D2E5' if disabled else '#315FCC') if selected else '#FFFFFF'
        d.rounded_rectangle((2*S,2*S,18*S,18*S),radius=4*S,fill=fill,outline=fill if selected else '#C6CFDC',width=S)
        if selected:d.line([(6*S,10*S),(9*S,13*S),(14*S,7*S)],fill='white',width=2*S,joint='curve')
        im.resize((20,20),Image.Resampling.LANCZOS).save(OUT/('check%s%s.png'%('-on' if selected else '', '-disabled' if disabled else '')))
for selected in (False,True):
    im=Image.new('RGBA',(20*S,20*S));d=ImageDraw.Draw(im)
    d.ellipse((2*S,2*S,18*S,18*S),fill='#315FCC' if selected else '#FFFFFF',outline='#315FCC' if selected else '#C6CFDC',width=S)
    if selected:d.ellipse((7*S,7*S,13*S,13*S),fill='white')
    im.resize((20,20),Image.Resampling.LANCZOS).save(OUT/('radio-on.png' if selected else 'radio.png'))
im=Image.new('RGBA',(20*S,20*S));d=ImageDraw.Draw(im)
d.line([(6*S,8*S),(10*S,12*S),(14*S,8*S)],fill='#718097',width=2*S,joint='curve')
im.resize((20,20),Image.Resampling.LANCZOS).save(OUT/'chevron.png')
print('Built %d theme assets'%len(list(OUT.glob('*.png'))))
