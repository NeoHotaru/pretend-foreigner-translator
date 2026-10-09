"""Shared native widget theme: rounded controls and consistent font fallbacks."""
import tkinter as tk
from tkinter import ttk
from ui_kit import asset_path,C_BG,C_SURFACE,C_TEXT,C_MUTED,C_MINE,C_PEER,C_LINE,C_SIDEBAR

def install(root):
    from ui_kit import configure_fonts
    configure_fonts(root)
    style=ttk.Style(root)
    images={}
    def photo(name):
        if name not in images:images[name]=tk.PhotoImage(master=root,file=str(asset_path('theme/'+name+'.png')))
        return images[name]
    root._theme_images=images
    def element(name,normal,*states,border=9):
        # Keep compact geometry independent of the larger centre tile.
        minimum = 1 if normal=='separator' else 40 if normal in ('card','dark-card') else 28 if border else photo(normal).width()
        try:style.element_create(name,'image',photo(normal),*[(state,photo(image)) for state,image in states],
                                  border=border,padding=0,sticky='nsew',width=minimum,height=minimum)
        except tk.TclError:pass
    for prefix,normal,hover,pressed in [('Neutral','neutral','hover','pressed'),
        ('Primary','primary','primary-hover','primary-pressed'),('Peer','peer','peer-hover','peer-pressed'),
        ('Soft','soft','soft-hover','pressed'),('Dark','dark','dark-hover','dark-pressed'),
        ('Quiet','quiet','hover','pressed')]:
        element('Pft.%s.button'%prefix,normal,('disabled','disabled'),('pressed',pressed),('active',hover),
                ('focus',prefix.lower()+'-focus'))
    def button(name,prefix,foreground=C_TEXT,padding=(14,9),background=C_BG):
        style.layout(name,[('Pft.%s.button'%prefix,{'sticky':'nsew','children':[
            ('Button.padding',{'sticky':'nsew','children':[('Button.label',{'sticky':'nsew'})]})]})])
        style.configure(name,font='PftUI',padding=padding,foreground=foreground,background=background,borderwidth=0,width=0)
        style.map(name,foreground=[('disabled','#9BA6B5')])
    button('TButton','Neutral')
    button('Go.TButton','Primary','white',background=C_SURFACE)
    button('PeerGo.TButton','Peer','white',background=C_SURFACE)
    button('Quiet.TButton','Quiet',C_MUTED,padding=(10,7))
    button('CardQuiet.TButton','Quiet',C_MUTED,padding=(10,7),background=C_SURFACE)
    button('Context.TButton','Quiet',C_MINE,padding=(4,4),background=C_SURFACE)
    button('PanelContext.TButton','Quiet',C_MINE,padding=(4,4))
    button('Side.TButton','Neutral',C_MUTED,padding=(10,8),background=C_SIDEBAR)
    button('Soft.TButton','Soft',C_MINE)
    button('Dark.TButton','Dark','white',background='#18222F')
    element('Pft.field','field',('disabled','field-disabled'),('focus','field-focus'))
    for name,normal in [('TextSurface','field'),('TextSurface.Focus','field-focus'),
                        ('ReadingSurface','reading'),('ReadingSurface.Focus','reading-focus')]:
        element('Pft.'+name,normal)
        style.layout(name+'.TFrame',[('Pft.'+name,{'sticky':'nsew'})])
        style.configure(name+'.TFrame',background=C_SURFACE,padding=7)
        style.configure('Panel.'+name+'.TFrame',background=C_BG)
    try:style.element_create('Pft.chevron','image',photo('chevron'),sticky='')
    except tk.TclError:pass
    style.layout('TEntry',[('Pft.field',{'sticky':'nsew','children':[
        ('Entry.padding',{'sticky':'nsew','children':[('Entry.textarea',{'sticky':'nsew'})]})]})])
    style.configure('TEntry',padding=(12,8),font='PftUI',background=C_BG,fieldbackground=C_SURFACE,foreground=C_TEXT)
    style.layout('TSpinbox',[('Pft.field',{'sticky':'nsew','children':[
        ('null',{'side':'right','sticky':'ns','children':[
            ('Spinbox.uparrow',{'side':'top','sticky':'e'}),
            ('Spinbox.downarrow',{'side':'bottom','sticky':'e'})]}),
        ('Spinbox.padding',{'sticky':'nsew','children':[('Spinbox.textarea',{'sticky':'nsew'})]})]})])
    style.configure('TSpinbox',padding=(12,8),font='PftUI',background=C_BG,fieldbackground=C_SURFACE,
                    foreground=C_TEXT,arrowsize=12,arrowcolor=C_MUTED)
    style.layout('TCombobox',[('Pft.field',{'sticky':'nsew','children':[
        ('Pft.chevron',{'side':'right','sticky':'ns'}),('Combobox.padding',{'sticky':'nsew','children':[
            ('Combobox.textarea',{'sticky':'nsew'})]})]})])
    style.configure('TCombobox',padding=(12,8),font='PftUI',background=C_BG,fieldbackground=C_SURFACE,
                    foreground=C_TEXT,selectbackground=C_SURFACE,selectforeground=C_TEXT)
    style.map('TCombobox',fieldbackground=[('readonly',C_SURFACE),('disabled','#F1F3F6')],
              selectbackground=[('readonly',C_SURFACE)],selectforeground=[('readonly',C_TEXT)])
    element('Pft.card','card',border=16)
    style.layout('Lane.TFrame',[('Pft.card',{'sticky':'nsew'})])
    style.configure('Lane.TFrame',background=C_BG)
    for element_name,normal,states in [('Pft.check','check',[('disabled selected','check-on-disabled'),
        ('disabled','check-disabled'),('selected','check-on')]),('Pft.radio','radio',[('selected','radio-on')])]:
        element(element_name,normal,*states,border=0)
    for cls,indicator in [('TCheckbutton','Pft.check'),('TRadiobutton','Pft.radio')]:
        style.layout(cls,[('Checkbutton.padding' if cls=='TCheckbutton' else 'Radiobutton.padding',{'sticky':'nsew','children':[
            (indicator,{'side':'left','sticky':''}),(('Checkbutton.label' if cls=='TCheckbutton' else 'Radiobutton.label'),{'side':'left','sticky':'nsew'})]})])
        style.configure(cls,font='PftUI',foreground=C_TEXT,background=C_BG,padding=(0,4))
    style.configure('Card.TRadiobutton',background=C_SURFACE)
    style.configure('TNotebook',background=C_BG,borderwidth=0,tabmargins=(0,0,0,14),
                    bordercolor=C_BG,lightcolor=C_BG,darkcolor=C_BG)
    element('Pft.tab','neutral',('selected','soft'),('active','hover'))
    style.layout('TNotebook.Tab',[('Pft.tab',{'sticky':'nsew','children':[
        ('Notebook.tab.padding',{'sticky':'nsew','children':[('Notebook.tab.label',{'sticky':'nsew'})]})]})])
    style.configure('TNotebook.Tab',font='PftUI',padding=(18,9),background=C_BG,foreground=C_MUTED)
    style.map('TNotebook.Tab',foreground=[('selected',C_MINE),('active',C_TEXT)],padding=[])
    element('Pft.separator','separator',border=0)
    for orient in ('Horizontal','Vertical'):
        style.layout(orient+'.TSeparator',[('Pft.separator',{'sticky':'nsew'})])
    style.configure('TSeparator',background=C_LINE)
    style.configure('TLabelframe',background=C_BG,bordercolor=C_LINE,lightcolor=C_BG,darkcolor=C_BG,borderwidth=0)
    style.configure('TLabelframe.Label',background=C_BG,foreground=C_TEXT,font='PftHead')
    style.configure('Treeview',font='PftSmall',rowheight=36,borderwidth=0,background=C_SURFACE,fieldbackground=C_SURFACE)
    style.configure('Treeview.Heading',font='PftSmall',padding=(12,10),background='#F1F4F8',foreground=C_MUTED,
                    relief='flat',borderwidth=0)
    style.map('Treeview',background=[('selected','#E6EEFC')],foreground=[('selected',C_TEXT)])
    style.configure('Vertical.TScrollbar',width=8,arrowsize=0,borderwidth=0,troughcolor=C_SURFACE,
                    background=C_SURFACE,bordercolor=C_SURFACE,lightcolor=C_SURFACE,darkcolor=C_SURFACE,gripcount=0)
    # Preserve ttk's thumb element name so its native drag bindings still work.
    try:style.element_create('Pft.Vertical.Scrollbar.thumb','image',photo('scroll'),
                             ('active',photo('scroll-hover')),border=3,padding=0,sticky='ns')
    except tk.TclError:pass
    style.layout('Vertical.TScrollbar',[('Vertical.Scrollbar.trough',{'sticky':'ns','children':[
        ('Pft.Vertical.Scrollbar.thumb',{'sticky':'ns','expand':True})]})])
    root.option_add('*TCombobox*Listbox.font','PftUI')
    root.option_add('*TCombobox*Listbox.background',C_SURFACE)
    root.option_add('*TCombobox*Listbox.foreground',C_TEXT)
    root.option_add('*TCombobox*Listbox.selectBackground','#E6EEFC')
    root.option_add('*TCombobox*Listbox.selectForeground',C_TEXT)
    return style
