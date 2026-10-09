import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import translator_core as C
C.use_sandbox_config(str(Path(tempfile.gettempdir())/'pft_sandbox_context_unit'))


class ContextUsageTests(unittest.TestCase):
    def setUp(self):
        self.session=C.new_session('Maya')
        self.session['note']='悬浮岛 = floating island'
        self.session['toPeer']=[dict(src='我叫小林',out='Call me Lin',srcLang='zh',tgtLang='en')]
        self.session['fromPeer']=[dict(src='Maya can help tomorrow.',out='',srcLang='en',tgtLang='zh')]
        self.config=dict(C.DEFAULT_CONFIG,activeBackend='provider:fixture',providers=[
            dict(name='fixture',apiKey='fixture-key',baseUrl='http://example.invalid',model='fixture')])
        self.t=C.Translator(config=self.config,sessions=[self.session],active='Maya')
        self.reply=json.dumps(dict(text='Let Maya help tomorrow.',source='zh',target='en',mode='casual'))

    def test_snapshot_matches_prompt_and_survives_later_memory_changes(self):
        captured=[]
        def run(prompt,text):
            captured.append(prompt)
            self.session['fromPeer'][0]['out']='后来补出的译文'
            self.session['toPeer'].clear()
            return self.reply
        with patch.object(self.t,'_runner',return_value=run):
            r=self.t.translate('那就让她明天帮忙', 'toPeer',remember=False)
        u=r['context_usage']
        self.assertEqual(u['session'],'Maya')
        self.assertEqual(u['cross'][0]['out'],'')
        self.assertEqual(u['own'][0]['src'],'我叫小林')
        self.assertIn(u['cross'][0]['src'],captured[0])
        self.assertIn(u['own'][0]['out'],captured[0])
        self.assertIn(u['note'],captured[0])
        self.assertNotIn('fixture-key',json.dumps(u))

    def test_cross_disabled_reports_no_peer_reference(self):
        self.t.config['crossMemoryDepth']=0
        with patch.object(self.t,'_runner',return_value=lambda *args:self.reply):
            r=self.t.translate('那就明天','toPeer',remember=False)
        self.assertEqual(r['context_usage']['cross'],[])
        self.assertEqual(r['cross_count'],0)
        self.assertEqual(r['context_usage']['cross_depth'],0)

    def test_google_reports_zero_used_context_even_with_saved_history(self):
        self.t.config['activeBackend']='google'
        with patch.object(C,'call_google_free',return_value=dict(text='Tomorrow.',source='zh',target='en')):
            r=self.t.translate('明天','toPeer',remember=False)
        self.assertEqual((r['ctx_count'],r['ctx_chars'],r['cross_count'],r['cross_chars']),(0,0,0,0))
        self.assertEqual(r['context_usage']['own'],[])
        self.assertEqual(r['context_usage']['cross'],[])
        self.assertEqual(r['context_usage']['note'],'')

    def test_budget_and_depth_snapshot_uses_the_selected_subset(self):
        self.session['fromPeer']=[dict(src='old '+str(i),out='旧消息') for i in range(5)]
        self.t.config['crossMemoryDepth']=2
        with patch.object(self.t,'_runner',return_value=lambda *args:self.reply):
            r=self.t.translate('好的','toPeer',remember=False)
        self.assertEqual([e['src'] for e in r['context_usage']['cross']],['old 3','old 4'])

if __name__=='__main__':unittest.main()
