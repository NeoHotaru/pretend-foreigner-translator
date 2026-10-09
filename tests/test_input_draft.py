import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import translator_core as C
C.use_sandbox_config(str(Path(tempfile.gettempdir()) / 'pft_sandbox_input_unit'))
from input_draft import InputDraft


RESULT = dict(text='make the floating island smaller lol', source='zh', target='en', mode='casual', lane='toPeer')


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.session = object()
        self.draft = InputDraft()
        self.draft.edit('那个悬浮窗再小一点，哈哈。')

    def test_preview_ready_only_after_response(self):
        request = self.draft.begin(self.session, 'context')
        self.assertFalse(self.draft.can_insert(self.session, 'context'))
        self.assertTrue(self.draft.accept(request, RESULT, self.session, 'context'))
        self.assertTrue(self.draft.can_insert(self.session, 'context'))

    def test_edit_during_request_rejects_stale_response(self):
        request = self.draft.begin(self.session, 'context')
        self.draft.edit('不改尺寸了。')
        self.assertFalse(self.draft.accept(request, RESULT, self.session, 'context'))
        self.assertIsNone(self.draft.result)

    def test_edit_after_response_invalidates_insert(self):
        request = self.draft.begin(self.session, 'context')
        self.draft.accept(request, RESULT, self.session, 'context')
        self.draft.edit('换一个颜色。')
        self.assertFalse(self.draft.can_insert(self.session, 'context'))

    def test_cancel_rejects_late_response(self):
        request = self.draft.begin(self.session, 'context')
        self.draft.discard()
        self.assertFalse(self.draft.accept(request, RESULT, self.session, 'context'))

    def test_session_and_context_changes_reject_response(self):
        request = self.draft.begin(self.session, 'context')
        self.assertFalse(self.draft.accept(request, RESULT, object(), 'context'))
        request = self.draft.begin(self.session, 'context')
        self.assertFalse(self.draft.accept(request, RESULT, self.session, 'changed'))

    def test_old_request_cannot_override_newer_request(self):
        first = self.draft.begin(self.session, 'context')
        second = self.draft.begin(self.session, 'context')
        self.assertFalse(self.draft.accept(first, RESULT, self.session, 'context'))
        self.assertIs(self.draft.pending, second)
        self.assertTrue(self.draft.accept(second, RESULT, self.session, 'context'))

    def test_empty_result_cannot_be_inserted(self):
        request = self.draft.begin(self.session, 'context')
        self.assertFalse(self.draft.accept(request, {'text': ''}, self.session, 'context'))


class PreviewMemoryTests(unittest.TestCase):
    def setUp(self):
        session = C.new_session('输入试用')
        session['toPeer'] = [dict(src='叫 floating island', out='floating island', srcLang='zh', tgtLang='en')]
        session['fromPeer'] = [dict(src='Maya can refine the floating island.', out='Maya 可以优化悬浮岛。', srcLang='en', tgtLang='zh')]
        cfg = dict(C.DEFAULT_CONFIG, activeBackend='provider:fixture', providers=[
            dict(name='fixture', apiKey='local-test-fixture', baseUrl='http://example.invalid', model='fixture')])
        self.t = C.Translator(config=cfg, sessions=[session], active='输入试用')
        self.session = session

    def test_preview_uses_both_contexts_without_writing_memory(self):
        plan = self.t.plan('那个小一点', 'toPeer', remember=False)
        self.assertEqual((plan['ctx_count'], plan['cross_count']), (1, 1))
        with patch.object(self.t, '_runner', return_value=lambda sp, text: json.dumps(RESULT)), patch.object(self.t, 'save_sessions') as save:
            result = self.t.translate('那个小一点', 'toPeer', remember=False)
        self.assertEqual(result['text'], RESULT['text'])
        self.assertEqual(len(self.session['toPeer']), 1)
        save.assert_not_called()

    def test_confirmed_translation_appends_once(self):
        with patch.object(self.t, 'save_sessions', return_value=True) as save:
            self.assertTrue(self.t.remember_translation('那个小一点', RESULT, session=self.session))
        self.assertEqual(len(self.session['toPeer']), 2)
        self.assertEqual(self.session['toPeer'][-1]['out'], RESULT['text'])
        save.assert_called_once()

    def test_wrong_session_cannot_receive_preview_memory(self):
        self.t.add_session('另一个任务')
        with patch.object(self.t, 'save_sessions') as save:
            with self.assertRaises(C.ApiError):
                self.t.remember_translation('那个小一点', RESULT, session=self.session)
        self.assertEqual(len(self.t.current_session()['toPeer']), 0)
        self.assertEqual(len(self.session['toPeer']), 1)
        save.assert_not_called()

    def test_regular_translation_still_remembers(self):
        with patch.object(self.t, '_runner', return_value=lambda sp, text: json.dumps(RESULT)), patch.object(self.t, 'save_sessions', return_value=True) as save:
            result = self.t.translate('那个小一点', 'toPeer')
        self.assertEqual(result['memory_count'], 2)
        save.assert_called_once()


if __name__ == '__main__':
    unittest.main()
