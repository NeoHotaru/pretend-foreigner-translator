"""Isolated visual QA and checks for the settings save/close workflow."""
import sys, time, json, hashlib
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.append('D:/Aconnada/Lib/site-packages')
sys.path.insert(0,str(ROOT/'artifacts/ui-refresh'))
from window_capture import window_image
import translator_core as C
real=Path(C.default_user_data_dir())
def hashes():return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in real.glob('pretend_foreigner.*.json')}
before=hashes()
out=ROOT/'artifacts/ui-refresh-v2';out.mkdir(exist_ok=True,parents=True)
C.use_sandbox_config(str(out/'pft_sandbox_ui'))
C.save_json(C.CONFIG_FILE,dict(C.DEFAULT_CONFIG,setupDone=True,checkUpdates=False,asrWarmup=False,
    globalHotkeys=False,selectionButton=False,activeBackend='provider:Demo',providers=[
    dict(name='Demo',apiKey='local-fixture',baseUrl='http://example.invalid',model='demo')]))
session=C.new_session('和 Maya 聊设计')
session['fromPeer']=[dict(src='Maya can make the island smaller tomorrow.',out='Maya 明天可以把悬浮岛缩小。',srcLang='en',tgtLang='zh')]
C.save_json(C.SESSION_FILE,{'active':session['name'],'list':[session]})
from translate_app import App, SettingsDialog
from overlay import OverlayPanel
from peer_reference import ReferenceBubble
from selection_button import SelectionPopup
from setup_wizard import SetupWizard
app=App();errors=[]
chosen_font=app._pft_fonts['PftUI'].actual('family')
app.report_callback_exception=lambda *args:errors.append(str(args[1]))
def tick():
    for _ in range(15):app.update();time.sleep(.02)
def shot(window,name):
    window.lift();tick();window_image(window).save(out/(name+'.png'))
try:
    app.geometry('1240x860+80+60')
    app.lane_mine.set_input('那就让她明天改吧，尺寸小一点。')
    app.lane_mine.set_output('Then let Maya do it tomorrow. A little smaller would be great.')
    app.lane_peer.set_input('Maya can make the island smaller tomorrow.')
    app.lane_peer.set_output('Maya 明天可以把悬浮岛缩小。')
    shot(app,'main')
    settings=SettingsDialog(app)
    for i,name in enumerate(('settings-service','settings-input','settings-voice','settings-update')):
        settings.notebook.select(i);shot(settings,name)
        assert settings.winfo_height()<750, 'Settings must fit a normal desktop work area'
    # Editing voice/input preferences must not require a custom provider.
    settings.on_new();settings.v_asr.set('Whisper（多语言稳）')
    with patch('overlay.apply_hotkeys',return_value=(True,'fixture')):
        settings.save_and_close()
    assert not settings.winfo_exists()
    assert app.t.config['asrBackend']=='whisper'
    settings=SettingsDialog(app);settings.v_name.set('Changed Demo');settings.v_model.set('new-model')
    with patch('overlay.apply_hotkeys',return_value=(True,'fixture')):settings.save_and_close()
    assert any(p['name']=='Changed Demo' and p['model']=='new-model' for p in app.t.config['providers'])
    # Empty edited provider names keep the dialog open with an inline message.
    settings=SettingsDialog(app);settings.v_name.set('');settings.save_and_close()
    assert settings.winfo_exists() and '名称' in settings.lbl_tip.cget('text');settings.destroy()
    wizard=SetupWizard(app);shot(wizard,'setup');wizard.destroy()
    from modern_dialogs import TextPrompt,ask_text
    def complete_prompt():
        dialog=next(w for w in app.winfo_children() if isinstance(w,TextPrompt))
        shot(dialog,'session-name')
        dialog.entry.delete(0,'end');dialog.entry.insert(0,'周末旅行')
        dialog.ok()
    app.after(100,complete_prompt)
    assert ask_text('新建会话','给这段对话起个名字。',parent=app)=='周末旅行'
    app.open_context_settings();shot(app.context_dialog,'context');app.context_dialog.destroy()
    app.lane_peer.toggle_memory();shot(app.lane_peer.memory_window,'memory');app.lane_peer.toggle_memory()
    # The thumb hides for short text and returns for overflowing content.
    from tkinter import ttk
    surface=app.lane_peer.txt_out.master
    scrollbar=next(w for w in surface.winfo_children() if isinstance(w,ttk.Scrollbar))
    app.lane_peer.set_output('短译文');tick();assert not scrollbar.winfo_ismapped()
    app.lane_peer.set_output('这是用于检查长译文排版和滚动的测试文字。\n'*60)
    tick();assert scrollbar.winfo_ismapped()
    assert scrollbar.identify(scrollbar.winfo_width()//2,scrollbar.winfo_height()//2) in ('trough','thumb') or 'Scrollbar' in scrollbar.identify(scrollbar.winfo_width()//2,scrollbar.winfo_height()//2)
    # Exercise native thumb dragging, not just programmatic text scrolling.
    thumb_y=next(y for y in range(scrollbar.winfo_height()) if scrollbar.identify(4,y).endswith('thumb'))
    scrollbar.event_generate('<ButtonPress-1>',x=4,y=thumb_y)
    scrollbar.event_generate('<B1-Motion>',x=4,y=scrollbar.winfo_height()//2)
    scrollbar.event_generate('<ButtonRelease-1>',x=4,y=scrollbar.winfo_height()//2)
    tick();assert app.lane_peer.txt_out.yview()[0]>.1
    shot(app,'main-long');app.withdraw()
    island=OverlayPanel(app);island.show();tick();shot(island,'island-collapsed')
    island.expand(animate=False,focus=False);island.set_input('那就让她明天改吧。')
    island.set_output('Then let Maya do it tomorrow.');shot(island,'island-expanded');island.destroy()
    bubble=ReferenceBubble(app,SimpleNamespace(cancel=lambda:None,copy_translation=lambda:None,retry=lambda:None))
    request=SimpleNamespace(entry=app.t.memory('fromPeer')[0],session=app.t.current_session(),
        text='Maya can make the island smaller tomorrow.',selection={'bounds':[700,180,300,30]},
        result={'target':'zh'},translator=app.t)
    bubble.show(request,'后续翻译会参考这条消息。','Maya 明天可以把悬浮岛缩小。')
    shot(bubble,'reference');bubble.show(request,'后续翻译会参考这条消息。','这是一段比较长的对方消息译文。'*40)
    shot(bubble,'reference-long');bubble.destroy()
    popup=SelectionPopup(app,lambda:None);popup.show([800,250,250,30],reference=True)
    shot(popup,'selection');popup.destroy()
    assert not errors,errors
finally:
    app.on_close()
assert before==hashes(),'Real user config changed'
print(json.dumps({'passed':True,'font':chosen_font,
                  'screenshots':str(out),'callbacks':errors},ensure_ascii=False))
