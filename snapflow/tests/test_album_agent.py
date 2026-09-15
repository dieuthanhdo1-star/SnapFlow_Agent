"""Offline regression: consent, persistence, routing and connector contracts."""
import base64
import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch
from test_app import App, ARTIFACTS, CONFIG, PNG, Problem
import unittest

class AlbumTests(unittest.TestCase):
    def setUp(self):
        self.app=App(ARTIFACTS/self._testMethodName,config=CONFIG)
        self.agent=self.app.agent
        self.folder=self.app.data/'album';self.folder.mkdir()
        self.futures=[]
        submit=self.app.batch_pool.submit
        def tracked_submit(*args,**kwargs):
            future=submit(*args,**kwargs);self.futures.append(future);return future
        self.app.batch_pool.submit=tracked_submit
        self.calls=0
        self.actions=[{'kind':'task','skill':'homework','title':'交设计作业','steps':['绘制流程图','提交 PDF'],'course':'交互设计','questions':[]}]
        def vision(*args):
            self.calls+=1
            return {'actions':self.actions},{'provider':'offline'}
        self.app.call_vision=vision
    def tearDown(self):self.app.batch_pool.shutdown(wait=True)
    def authorize(self,include=True):
        with patch('native_album.choose_folder',return_value=self.folder):candidate=self.agent.pick()
        self.agent.authorize({'token':candidate['token'],'confirmed':True,'include_existing':include})
        return self.agent.status()['sources'][0]
    def image(self,name='test.png',suffix=b''):
        p=self.folder/name;p.write_bytes(base64.b64decode(PNG.split(',')[1])+suffix)
        os.utime(p,(time.time()-10,time.time()-10))
        return p
    def settle(self):
        for future in list(self.futures):future.result(timeout=5)
    def scan(self):self.agent.scan_once();self.agent.scan_once();self.settle()
    def test_no_read_without_consent_and_token_cannot_replay(self):
        self.image();self.scan();self.assertEqual(self.calls,0)
        with self.assertRaises(Problem):self.agent.authorize({'confirmed':True,'token':'invented','path':str(self.folder)})
        with patch('native_album.choose_folder',return_value=self.folder):c=self.agent.pick()
        with self.assertRaises(Problem):self.agent.authorize({'token':c['token']})
        self.agent.authorize({'token':c['token'],'confirmed':True,'include_existing':True})
        with self.assertRaises(Problem):self.agent.authorize({'token':c['token'],'confirmed':True})
        self.scan();self.assertEqual(self.calls,1)
    def test_existing_new_files_dedup_and_restart(self):
        self.image();self.authorize();self.scan()
        self.assertEqual(self.calls,1);item=self.app.items()[0]
        self.assertEqual(item['skill'],'homework');self.assertEqual(json.loads(item['skill_data'])['steps'],['绘制流程图','提交 PDF'])
        self.image('renamed.png');self.scan();self.assertEqual(self.calls,1)
        self.image('new.png',b'new');self.scan();self.assertEqual(self.calls,2)
        again=App(self.app.data,config=CONFIG)
        try:self.assertEqual(len(again.items()),2);self.assertTrue(again.agent.status()['sources'][0]['enabled'])
        finally:again.batch_pool.shutdown(wait=True)
    def test_running_watcher_processes_new_and_changed_images_without_manual_scan(self):
        self.authorize();stop=threading.Event()
        def wait_count(expected):
            deadline=time.monotonic()+5
            while self.calls<expected and time.monotonic()<deadline:time.sleep(.02)
            self.assertEqual(self.calls,expected)
            self.settle()
        with patch('agent_engine.SCAN_INTERVAL',.03):
            worker=threading.Thread(target=self.agent.run,args=(stop,),daemon=True);worker.start()
            try:
                self.image('live.png');wait_count(1)
                self.image('live.png',b'changed');wait_count(2)
                time.sleep(.12);self.assertEqual(self.calls,2)
                source=self.agent.status()['sources'][0]
                self.agent.source_action({'id':source['id'],'action':'pause'})
                self.image('paused.png',b'paused');time.sleep(.12);self.assertEqual(self.calls,2)
                self.agent.source_action({'id':source['id'],'action':'resume'});wait_count(3)
                self.agent.source_action({'id':source['id'],'action':'revoke'})
                self.image('revoked.png',b'revoked');time.sleep(.12);self.assertEqual(self.calls,3)
            finally:stop.set();worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
    def test_incomplete_write_is_not_processed_until_stable(self):
        self.authorize();self.image('writing.png');self.agent.scan_once()
        self.image('writing.png',b'updated');self.agent.scan_once();self.assertEqual(self.calls,0)
        self.agent.scan_once();self.settle();self.assertEqual(self.calls,1)
    def test_exclude_existing_and_pause_resume_revoke(self):
        self.image();source=self.authorize(False);self.scan();self.assertEqual(self.calls,0)
        self.agent.source_action({'id':source['id'],'action':'pause'})
        self.image('new.png',b'new');self.scan();self.assertEqual(self.calls,0)
        self.agent.source_action({'id':source['id'],'action':'resume'});self.scan();self.assertEqual(self.calls,1)
        self.agent.source_action({'id':source['id'],'action':'revoke'});self.image('later.png',b'later');self.scan();self.assertEqual(self.calls,1)
        self.assertEqual(self.agent.status()['sources'],[])
    def test_revoke_during_model_call_leaves_draft_without_auto_save(self):
        started,release=threading.Event(),threading.Event()
        def vision(*args):started.set();release.wait(5);return {'actions':self.actions},{}
        self.app.call_vision=vision
        source=self.authorize();self.image();self.agent.scan_once();self.agent.scan_once()
        self.assertTrue(started.wait(2));self.agent.source_action({'id':source['id'],'action':'revoke'});release.set();self.settle()
        self.assertEqual(self.app.items(),[]);self.assertEqual(len(self.agent.status()['reviews']),1)
    def test_review_missing_date_no_invention_and_multi_skill(self):
        self.actions=[{'kind':'event','skill':'event','title':'课程讲座','start_at':'2027-01-01T12:00:00+08:00','questions':['结束时间是什么？']},
                      {'kind':'bookmark','skill':'idea','title':'海报灵感','questions':[]},
                      {'kind':'task','skill':'todo','title':'取快递','questions':[]}]
        self.authorize();self.image();self.scan()
        self.assertEqual({i['skill'] for i in self.app.items()},{'idea','todo'})
        review=self.agent.status()['reviews'][0]
        with self.assertRaises(Problem):self.agent.review({'id':review['id'],'fields':{}})
        self.agent.review({'id':review['id'],'fields':{'end_at':'2027-01-01T13:00:00+08:00'}})
        self.assertEqual(len(self.app.items()),3);self.assertEqual(self.agent.status()['reviews'],[])
    def test_disabled_skill_and_daily_quota(self):
        self.agent.configure({'skills':['reference'],'daily_limit':1})
        self.authorize();self.image();self.scan();self.assertEqual(self.app.items(),[])
        self.image('two.png',b'new');self.scan();self.assertEqual(self.calls,1)
        self.assertIn('今日',self.agent.error)
    def test_subdirectories_symlinks_invalid_files_and_unchanged_original(self):
        self.authorize();p=self.image();before=p.read_bytes()
        (self.folder/'sub').mkdir();(self.folder/'sub'/'hidden.png').write_bytes(before)
        (self.folder/'linked.png').symlink_to(p)
        (self.folder/'bad.png').write_bytes(b'invalid');os.utime(self.folder/'bad.png',(time.time()-10,time.time()-10))
        self.scan();self.assertEqual(self.calls,1);self.assertEqual(before,p.read_bytes());self.assertEqual(len(self.agent.status()['file_errors']),1)
    def test_failed_model_never_auto_retries(self):
        def fail(*args):self.calls+=1;raise Problem('test failure',502)
        self.app.call_vision=fail;self.authorize();self.image();self.scan();self.scan()
        self.assertEqual(self.calls,1);self.assertEqual(self.agent.status()['pending'][0]['status'],'failed')
    def task_connection(self):
        self.app.feishu.value.update(access_token='fake',expires_at=time.time()+3600,task_user_id='ou_fake',task_user_name='测试用户')
        return self.app.feishu.task_target()
    def test_task_connector_identity_milliseconds_and_idempotence(self):
        target=self.task_connection()
        draft=self.app.demo('task');item=self.app.confirm(dict(draft,draft_id=draft['id'],confirmed=True))
        with patch('server.remote_json',return_value={'code':0,'data':{'task':{'guid':'task-guid'}}}) as remote:
            self.app.sync_feishu(item['id'],{'confirmed':True,'expected_target':target})
            self.app.sync_feishu(item['id'],{'confirmed':True,'expected_target':target})
            self.assertEqual(remote.call_count,1)
            payload=remote.call_args.args[1]
            self.assertEqual(payload['client_token'],item['id']);self.assertGreater(payload['due']['timestamp'],10**12)
            self.assertEqual(payload['members'][0]['id'],'ou_fake')
    def test_auto_sync_only_with_explicit_target_consent(self):
        target=self.task_connection();self.authorize();self.image()
        with patch('server.remote_json',return_value={'code':0,'data':{'task':{'guid':'task-guid'}}}) as remote:
            self.scan();remote.assert_not_called()
            with self.assertRaises(Problem):self.agent.configure({'sync_tasks':True,'task_target':'wrong'})
            self.agent.configure({'sync_tasks':True,'task_target':target})
            self.image('two.png',b'two');self.scan();self.assertEqual(remote.call_count,1)
            self.app.feishu.value['task_user_id']='other-account'
            self.image('three.png',b'three');self.scan();self.assertEqual(remote.call_count,1)
    def test_edit_saved_classification_and_invalid_event(self):
        draft=self.app.demo('bookmark');item=self.app.confirm(dict(draft,draft_id=draft['id'],confirmed=True))
        edited=self.app.update_item(item['id'],{'action':'edit','fields':{'skill':'todo','title':'买一本设计书'}})
        self.assertEqual(edited['kind'],'task');self.assertEqual(edited['skill'],'todo')
        self.assertEqual(len(self.app.items()),1)
        with self.assertRaises(Problem):self.app.update_item(item['id'],{'action':'edit','fields':{'skill':'event'}})
        self.assertEqual(self.app.get_item(item['id'])['kind'],'task')
        with self.app.db() as db:db.execute("UPDATE items SET external_id='external',sync_state='synced' WHERE id=?",(item['id'],))
        edited=self.app.update_item(item['id'],{'action':'edit','fields':{'skill':'todo','title':'买两本书'}})
        self.assertIn('飞书仍保留原内容',edited['sync_error'])

    def test_manual_folder_path_requires_confirmation_and_valid_directory(self):
        self.image()
        candidate=self.agent.prepare_path({'path':str(self.folder)})
        self.assertEqual(self.agent.status()['sources'],[])
        with self.assertRaises(Problem):self.agent.authorize({'token':candidate['token']})
        for value in ['', '../relative',str(self.folder/'missing'),str(self.folder/'test.png'),None]:
            with self.subTest(value=value),self.assertRaises(Problem):self.agent.prepare_path({'path':value})
        self.agent.authorize({'token':candidate['token'],'confirmed':True,'include_existing':True})
        self.scan();self.assertEqual(self.calls,1)

    def test_folder_authorized_without_model_waits_then_processes(self):
        self.app.config['VISION_DISABLED']='1';self.image()
        candidate=self.agent.prepare_path({'path':str(self.folder)})
        self.agent.authorize({'token':candidate['token'],'confirmed':True,'include_existing':True})
        self.scan();self.assertEqual(self.calls,0)
        with self.app.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM album_files').fetchone()[0],0)
        self.app.config['VISION_DISABLED']='0';self.scan();self.assertEqual(self.calls,1)

    def test_manual_upload_requires_consent_and_deduplicates(self):
        with self.assertRaises(Problem):self.agent.ingest({'image':PNG})
        self.agent.ingest({'image':PNG,'confirmed':True});self.settle()
        result=self.agent.ingest({'image':PNG,'confirmed':True});self.assertTrue(result['duplicate']);self.assertEqual(self.calls,1)

if __name__=='__main__':unittest.main()
