import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import translator_core as C
C.use_sandbox_config(str(Path(tempfile.gettempdir())/'pft_sandbox_peer_reference_unit'))

class ReferenceMemoryTests(unittest.TestCase):
    def setUp(self):
        self.session=C.new_session('参考测试')
        self.t=C.Translator(config=dict(C.DEFAULT_CONFIG),sessions=[self.session],active='参考测试')
        self.result=dict(text='Maya 明天可以缩小悬浮窗。',source='en',target='zh',lane='fromPeer')

    def test_raw_reference_is_available_even_before_translation(self):
        with patch.object(self.t,'save_sessions',return_value=True):
            entry,saved=self.t.remember_peer_reference('Maya can make the floating island smaller tomorrow.',self.session)
        self.assertTrue(saved);self.assertEqual(entry['out'],'')
        self.assertEqual(len(self.t.memory('toPeer')),0)
        plan=self.t.plan('那就让她明天改吧。','toPeer')
        self.assertEqual(plan['cross_count'],1)
        self.assertIn('Maya can make',plan['system_prompt'])

    def test_completion_updates_one_record_and_deduplicates_repeated_click(self):
        with patch.object(self.t,'save_sessions',return_value=True):
            first,_=self.t.remember_peer_reference('Maya can make it smaller.',self.session)
            second,_=self.t.remember_peer_reference('Maya can make it smaller.',self.session)
            self.assertIs(first,second)
            self.t.complete_peer_reference(first,self.result,self.session)
        self.assertEqual(len(self.t.memory('fromPeer')),1)
        self.assertEqual(first['out'],self.result['text'])
        self.assertNotIn('referenceOnly',first)

    def test_session_switch_cannot_write_translation_into_new_session(self):
        with patch.object(self.t,'save_sessions',return_value=True):
            entry,_=self.t.remember_peer_reference('Maya can help.',self.session)
            self.t.add_session('另一个')
            with self.assertRaises(C.ApiError):self.t.complete_peer_reference(entry,self.result,self.session)
        self.assertEqual(self.t.memory('fromPeer'),[])
        self.assertEqual(entry['out'],'')

    def test_removed_reference_is_not_resurrected(self):
        with patch.object(self.t,'save_sessions',return_value=True):
            entry,_=self.t.remember_peer_reference('Maya can help.',self.session)
            self.session['fromPeer'].clear()
            with self.assertRaises(C.ApiError):self.t.complete_peer_reference(entry,self.result,self.session)
        self.assertEqual(self.t.memory('fromPeer'),[])

if __name__=='__main__':unittest.main()
