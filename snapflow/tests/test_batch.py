"""Batch queue regression: all model behavior is mocked; no paid inference."""
import base64
import json
import secrets
import threading
import time
import unittest
from unittest.mock import patch

from test_app import ARTIFACTS, PNG, CONFIG
from server import App, Problem


def unique_png(n):
    raw = base64.b64decode(PNG.split(',')[1]) + str(n).encode()
    return 'data:image/png;base64,' + base64.b64encode(raw).decode()


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.app = App(ARTIFACTS / self._testMethodName, config={})
        self.batch = secrets.token_hex(16)

    def tearDown(self):
        self.app.batch_pool.shutdown(wait=True)

    def enqueue(self, n=0, **extras):
        body = dict(batch_id=self.batch, request_id=secrets.token_hex(16), filename=f'image-{n}.png', image=unique_png(n))
        body.update(extras)
        return self.app.enqueue_image(body)

    def wait_done(self, expected=1):
        for _ in range(150):
            jobs = self.app.batch_jobs(self.batch)['jobs']
            if len(jobs) == expected and not any(j['status'] in ['queued', 'running'] for j in jobs):
                return jobs
            time.sleep(.02)
        self.fail('Batch did not finish')

    def test_manual_intake_and_reload_preserve_image_and_draft(self):
        with patch.object(self.app, 'call_vision') as model:
            self.enqueue()
            jobs = self.wait_done()
            model.assert_not_called()
        self.assertEqual(jobs[0]['status'], 'ready')
        self.assertEqual(jobs[0]['draft']['source'], 'manual')
        other = App(self.app.data, config={})
        self.assertEqual(other.current_batch()['jobs'][0]['draft']['id'], jobs[0]['draft']['id'])
        other.batch_pool.shutdown()
        self.assertEqual(self.app.items(), [])

    def test_auto_classification_needs_no_user_context(self):
        self.app.config = CONFIG
        calls = []
        def model(image, body):
            calls.append(body)
            return {'kind': 'bookmark', 'title': '自动分类资料'}, {'requested_model': 'fixture'}
        with patch.object(self.app, 'call_vision', side_effect=model):
            self.enqueue()
            job = self.wait_done()[0]
        self.assertEqual(calls[0]['context'], '')
        self.assertEqual(job['draft']['kind'], 'bookmark')
        self.assertEqual(job['draft']['title'], '自动分类资料')
        self.assertEqual(self.app.items(), [])

    def test_identical_image_and_request_retries_do_not_repeat_model_calls(self):
        self.app.config = CONFIG
        with patch.object(self.app, 'call_vision', return_value=({'kind': 'bookmark', 'title': '参考'}, {})) as model:
            first = self.enqueue()
            second = self.enqueue()
            third = self.enqueue(request_id=first['job_id'])
            self.wait_done()
        self.assertEqual(first['job_id'], second['job_id'])
        self.assertTrue(third['duplicate'])
        model.assert_called_once()

    def test_batch_limit_and_bad_files_are_isolated(self):
        with patch.object(self.app.batch_pool, 'submit'):
            for n in range(30): self.enqueue(n)
            with self.assertRaisesRegex(Problem, '最多 30'): self.enqueue(30)
            with self.assertRaises(Problem): self.enqueue(11, image='data:image/png;base64,SGVsbG8=')
        self.assertEqual(len(self.app.batch_jobs(self.batch)['jobs']), 30)

    def test_two_worker_limit_and_queued_cancellation(self):
        self.app.config = CONFIG
        gate, two_started = threading.Event(), threading.Event()
        lock = threading.Lock()
        counts = {'active': 0, 'peak': 0, 'calls': 0}
        def model(image, body):
            with lock:
                counts['active'] += 1; counts['calls'] += 1
                counts['peak'] = max(counts['peak'], counts['active'])
                if counts['active'] == 2: two_started.set()
            gate.wait(2)
            with lock: counts['active'] -= 1
            return {'kind': 'bookmark', 'title': '参考'}, {}
        with patch.object(self.app, 'call_vision', side_effect=model):
            self.enqueue(0); self.enqueue(1)
            self.assertTrue(two_started.wait(1))
            queued = self.enqueue(2)
            self.app.update_image_job(queued['job_id'], {'action': 'cancel'})
            gate.set()
            jobs = self.wait_done(3)
        self.assertEqual(counts['peak'], 2)
        self.assertEqual(counts['calls'], 2)
        self.assertEqual(jobs[-1]['status'], 'cancelled')

    def test_running_cancellation_cannot_create_action(self):
        self.app.config = CONFIG
        entered, release = threading.Event(), threading.Event()
        def model(image, body):
            entered.set(); release.wait(2)
            return {'kind': 'bookmark', 'title': '应取消'}, {}
        with patch.object(self.app, 'call_vision', side_effect=model):
            result = self.enqueue()
            self.assertTrue(entered.wait(1))
            self.app.update_image_job(result['job_id'], {'action': 'cancel'})
            release.set()
            self.app.batch_pool.shutdown(wait=True)
        self.assertEqual(self.app.items(), [])
        with self.app.db() as db:
            self.assertEqual(db.execute('SELECT cancelled FROM drafts').fetchone()[0], 1)

    def test_failure_does_not_block_other_images_and_retry_is_explicit(self):
        self.app.config = CONFIG
        with patch.object(self.app, 'call_vision', side_effect=[Problem('测试失败', 502), ({'kind': 'task', 'title': '作业'}, {})]):
            self.enqueue(0)
            self.wait_done(1)
            self.enqueue(1)
            jobs = self.wait_done(2)
        self.assertEqual([j['status'] for j in jobs], ['failed', 'ready'])
        with patch.object(self.app, 'call_vision', return_value=({'kind': 'event', 'title': '活动'}, {})) as retry:
            self.app.update_image_job(jobs[0]['id'], {'action': 'retry'})
            jobs = self.wait_done(2)
            retry.assert_called_once()
        self.assertEqual(jobs[0]['draft']['kind'], 'event')

    def test_restart_does_not_automatically_repeat_paid_calls(self):
        with patch.object(self.app.batch_pool, 'submit') as submit:
            self.enqueue()
            self.app.recover_batches()
            self.assertEqual(submit.call_count, 1)
        self.assertEqual(self.app.current_batch()['jobs'][0]['status'], 'interrupted')

    def test_batch_confirmation_is_partial_safe_and_idempotent(self):
        self.enqueue(0); self.enqueue(1)
        jobs = self.wait_done(2)
        body = {'batch_id': self.batch, 'confirmed': True, 'entries': [
            {'job_id': jobs[0]['id'], 'fields': {'kind': 'task', 'title': '交作业'}},
            {'job_id': jobs[1]['id'], 'fields': {'kind': 'event', 'title': '缺时间的活动'}}]}
        result = self.app.confirm_batch(body)
        self.assertTrue(result['results'][0]['saved'])
        self.assertFalse(result['results'][1]['saved'])
        self.assertEqual(len(self.app.items()), 1)
        self.app.confirm_batch(body)
        self.assertEqual(len(self.app.items()), 1)
        body['entries'][1]['fields'] = {'kind': 'bookmark', 'title': '改为资料'}
        result = self.app.confirm_batch(body)
        self.assertTrue(all(r['saved'] for r in result['results']))
        self.assertEqual(len(self.app.items()), 2)
        self.assertEqual(self.app.current_batch()['jobs'], [])

    def test_batch_confirmation_requires_explicit_approval(self):
        self.enqueue()
        job = self.wait_done()[0]
        with self.assertRaises(Problem):
            self.app.confirm_batch({'batch_id': self.batch, 'entries': [{'job_id': job['id'], 'fields': {'kind': 'bookmark', 'title': '资料'}}]})
        self.assertEqual(self.app.items(), [])


    def multi_result(self):
        return {'actions': [
            {'kind': 'task', 'title': '办理设备借用', 'time_text': '11月3日14:00开放；年份未注明',
             'notes': '适用于本科生', 'questions': ['需要定时提醒时，请核对年份。']},
            {'kind': 'task', 'title': '提交奖学金申请', 'time_text': '11月5日10:00开放；年份未注明',
             'notes': '适用于符合申请条件的同学', 'questions': ['需要定时提醒时，请核对年份。']}
        ]}

    def prepare_multi(self):
        self.app.config = CONFIG
        with patch.object(self.app, 'call_vision', return_value=(self.multi_result(), {})) as model:
            first = self.enqueue()
            jobs = self.wait_done(2)
            model.assert_called_once()
        return first, jobs

    def test_multi_notice_one_image_two_independent_drafts(self):
        first, jobs = self.prepare_multi()
        self.assertEqual(jobs[0]['id'], first['job_id'])
        self.assertEqual(len({j['draft_id'] for j in jobs}), 2)
        self.assertEqual(len({j['image_job_id'] for j in jobs}), 1)
        self.assertEqual([j['action_index'] for j in jobs], [1, 2])
        for job in jobs:
            self.assertEqual(job['draft']['due_at'], '')
            self.assertIn(job['draft']['time_text'], job['draft']['notes'])
        self.assertEqual(self.app.items(), [])
        entries = [{'job_id': j['id'], 'fields': j['draft']} for j in jobs]
        result = self.app.confirm_batch(dict(batch_id=self.batch, confirmed=True, entries=entries))
        self.assertTrue(all(r['saved'] for r in result['results']))
        self.app.confirm_batch(dict(batch_id=self.batch, confirmed=True, entries=entries))
        self.assertEqual(len(self.app.items()), 2)
        self.assertEqual(self.app.current_batch()['jobs'], [])

    def test_cancel_one_notice_preserves_its_sibling(self):
        _, jobs = self.prepare_multi()
        result = self.app.update_image_job(jobs[0]['id'], {'action': 'cancel'})
        self.assertEqual([j['status'] for j in result['jobs']], ['cancelled', 'ready'])
        entries = [{'job_id': j['id'], 'fields': j['draft']} for j in jobs]
        result = self.app.confirm_batch(dict(batch_id=self.batch, confirmed=True, entries=entries))
        self.assertEqual([r['saved'] for r in result['results']], [False, True])
        self.assertEqual(len(self.app.items()), 1)
        self.assertEqual(self.app.current_batch()['jobs'], [])

    def test_image_limit_counts_images_not_extracted_actions(self):
        self.app.config = CONFIG
        with patch.object(self.app, 'call_vision', return_value=(self.multi_result(), {})):
            for n in range(30):
                self.enqueue(n)
                self.wait_done((n + 1) * 2)
            with self.assertRaisesRegex(Problem, '最多 30'): self.enqueue(30)
        entries = [{'job_id': j['id'], 'fields': j['draft']} for j in self.app.batch_jobs(self.batch)['jobs']]
        result = self.app.confirm_batch(dict(batch_id=self.batch, confirmed=True, entries=entries))
        self.assertEqual(sum(r['saved'] for r in result['results']), 60)

    def test_multi_notice_reload_and_partial_save(self):
        _, jobs = self.prepare_multi()
        body = dict(batch_id=self.batch, confirmed=True, entries=[{'job_id': jobs[0]['id'], 'fields': jobs[0]['draft']}])
        self.app.confirm_batch(body)
        other = App(self.app.data, config={})
        try:
            found = other.current_batch()['jobs']
            self.assertEqual([j['status'] for j in found], ['saved', 'ready'])
            self.assertEqual([j['draft_id'] for j in found], [j['draft_id'] for j in jobs])
            wrong = other.confirm_batch(dict(body, batch_id=secrets.token_hex(16)))
            self.assertFalse(wrong['results'][0]['saved'])
        finally: other.batch_pool.shutdown()

    def test_invalid_action_array_does_not_create_partial_drafts(self):
        self.app.config = CONFIG
        for actions in [[], ['bad'], [self.multi_result()['actions'][0], None], [{}] * 11]:
            with patch.object(self.app, 'call_vision', return_value=({'actions': actions}, {})):
                with self.assertRaises(Problem): self.app.analyze({'image': PNG, 'mode': 'ai', 'multiple': True})
        with self.app.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM drafts').fetchone()[0], 0)

    def test_legacy_single_draft_is_migrated_without_replacement(self):
        draft = self.app.demo('task')
        job_id = secrets.token_hex(16)
        with self.app.db() as db:
            db.execute("""INSERT INTO image_jobs(id,batch_id,image,filename,mode,status,draft_id,created_at,updated_at)
                VALUES(?,?,?,?,?,'ready',?,'old','old')""", (job_id,self.batch,'legacy.png','legacy.png','manual',draft['id']))
        other = App(self.app.data, config={})
        try:
            found = other.current_batch()['jobs'][0]
            self.assertEqual(found['id'], job_id)
            self.assertEqual(found['draft_id'], draft['id'])
            result = other.confirm_batch(dict(batch_id=self.batch, confirmed=True,
                entries=[{'job_id':job_id,'fields':draft}]))
            self.assertTrue(result['results'][0]['saved'])
        finally: other.batch_pool.shutdown()

    def test_running_multi_notice_cancellation_cancels_all_drafts(self):
        self.app.config = CONFIG
        entered, release = threading.Event(), threading.Event()
        def model(image, body):
            entered.set(); release.wait(2)
            return self.multi_result(), {}
        with patch.object(self.app, 'call_vision', side_effect=model):
            job = self.enqueue()
            self.assertTrue(entered.wait(1))
            self.app.update_image_job(job['job_id'], {'action': 'cancel'})
            release.set()
            self.app.batch_pool.shutdown(wait=True)
        with self.app.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM drafts WHERE cancelled=1').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT count(*) FROM image_job_actions').fetchone()[0], 0)


if __name__ == '__main__': unittest.main(verbosity=2)
