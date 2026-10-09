"""Read the exact messages sent with one completed translation."""
import tkinter as tk
from tkinter import ttk
from ui_kit import C_BG,C_TEXT,C_MUTED,C_MINE,C_PEER,FONT_HEAD,text_surface,readonly_text
from island_window import work_area


def usage_summary(record):
    usage=record['usage']
    prefix={'main':'这次翻译','inline':'上次原位翻译','reference':'对方消息翻译'}[record['origin']]
    if usage['backend']=='google':return prefix+'未使用上下文 · 查看'
    other='对方' if usage['lane']=='toPeer' else '我的'
    own='我的' if usage['lane']=='toPeer' else '对方'
    if usage['cross']:return '%s参考%s %d 条 · 查看'%(prefix,other,len(usage['cross']))
    if usage['own']:return '使用%s %d 条历史消息 · 查看'%(own,len(usage['own']))
    if usage['note']:return '本次带入了语境与术语 · 查看'
    return '本次未带入会话记忆 · 查看'


class ContextView(tk.Toplevel):
    def __init__(self,app,record,owner=None):
        super().__init__(app)
        self.record=record
        self.title('翻译时带入的上下文')
        self.configure(bg=C_BG)
        if app.winfo_viewable():self.transient(app)
        self.minsize(560,380)
        self.bind('<Escape>',lambda e:self.destroy())
        body=ttk.Frame(self,padding=24);body.pack(fill='both',expand=True)
        ttk.Label(body,text='翻译时带入的上下文',style='Head.TLabel').pack(anchor='w')
        usage=record['usage']
        origin={'main':'主界面 / 悬浮岛','inline':'原位翻译','reference':'对方消息翻译'}[record['origin']]
        ttk.Label(body,text='会话：%s · %s'%(usage['session'],origin),style='Hint.TLabel').pack(anchor='w',pady=(6,16))
        surface,self.text=text_surface(body,height=16,spacing1=0,spacing3=2)
        surface.pack(fill='both',expand=True)
        self.text.tag_configure('head',font=FONT_HEAD,foreground=C_TEXT,spacing1=12,spacing3=6)
        self.text.tag_configure('muted',foreground=C_MUTED)
        self.text.tag_configure('result',foreground=C_MINE if usage['lane']=='toPeer' else C_PEER)
        def add(value,tag=None):self.text.insert('end',value+'\n',tag or ())
        add('这次翻译','head');add(record['source']);add(record['translation'],'result')
        if usage['backend']=='google':
            add('免费机翻未使用上下文','head')
            add('本次只翻译当前句子，没有带入历史消息、对方参考或术语。','muted')
        else:
            other='参考的对方消息' if usage['lane']=='toPeer' else '参考的我的消息'
            own='我的历史表达' if usage['lane']=='toPeer' else '对方的历史表达'
            for title,entries in ((other,usage['cross']),(own,usage['own'])):
                add('%s · %d 条'%(title,len(entries)),'head')
                if not entries:
                    explanation=('参照另一侧消息已关闭。' if title==other and not usage['cross_depth']
                                 else '本次没有带入这类消息。')
                    add(explanation,'muted')
                for index,entry in enumerate(entries,1):
                    add('%d. %s'%(index,entry.get('src','')))
                    if entry.get('out'):add('译文：'+entry['out'],'muted')
                    else:add('这条消息带入的是原文，译文尚未生成。','muted')
            if usage['note']:
                add('语境与术语','head');add(usage['note'])
            add('以上是这次请求中带入的内容。之后修改记忆，不会改变这份记录。','muted')
        readonly_text(self.text)
        self.text.configure(state='disabled')
        footer=ttk.Frame(body);footer.pack(fill='x',pady=(16,0))
        ttk.Button(footer,text='关闭',style='Go.TButton',command=self.destroy).pack(side='right')
        self.btn_settings=ttk.Button(footer,text='调整上下文记忆',command=self.adjust_context)
        self.btn_settings.pack(side='left')
        anchor=owner or app
        x,y=anchor.winfo_rootx(),anchor.winfo_rooty()
        left,top,right,bottom=work_area(x,y,(self.winfo_screenwidth(),self.winfo_screenheight()))
        w,h=min(720,right-left-24),min(660,bottom-top-24)
        x=max(left+12,min(x+(anchor.winfo_width()-w)//2,right-w-12))
        y=max(top+12,min(y+(anchor.winfo_height()-h)//2,bottom-h-12))
        self.geometry('%dx%d+%d+%d'%(w,h,x,y))
        self.lift()

    def adjust_context(self):
        # A reference viewer can be opened while the main window is minimized.
        # Its settings sheet needs a visible transient parent.
        self.master.deiconify()
        self.master.lift()
        self.master.open_context_settings()
