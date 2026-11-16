"""Test control bounds, authenticated API, persistence and real EQ PCM output."""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'receiver'))
import equalizer_state as state
import equalizer_web as web
from audio import Gst, speaker_path


class EqualizerTest(unittest.TestCase):
    def test_bounds_and_headroom(self):
        for invalid in [dict(state.DEFAULT, volume=101), dict(state.DEFAULT, bass=float('nan')),
                        dict(state.DEFAULT, mute='false'), dict(state.DEFAULT, source='hw:0'),
                        dict(state.DEFAULT, treble=7), dict(state.DEFAULT, volume=True)]:
            with self.assertRaises(ValueError): state.validate(invalid)
        self.assertEqual(state.gain(state.DEFAULT), .1)
        self.assertEqual(state.gain(dict(state.DEFAULT, mute=True)), 0)
        self.assertAlmostEqual(state.gain(dict(state.DEFAULT, volume=100, bass=6, mid=6, treble=6)), .25*10**(-18/20))

    def test_api_auth_persistence_and_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp); path=directory/'settings.json'
            state.atomic_json(path,state.DEFAULT)
            def read():return state.read_settings(path)
            with patch.multiple(web, STATE_DIR=directory, STATE_FILE=path, STATUS_FILE=directory/'status.json', read_settings=read):
                server=web.ThreadingHTTPServer(('127.0.0.1',0),web.Handler);server.token='test-secret'
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                def call(method,url,data=None,auth=True,origin=None):
                    c=http.client.HTTPConnection(*server.server_address,timeout=3)
                    headers={'Content-Type':'application/json'}
                    if auth:headers['Authorization']='Bearer test-secret'
                    if origin:headers['Origin']=origin
                    c.request(method,url,None if data is None else json.dumps(data),headers)
                    r=c.getresponse();result=(r.status,json.loads(r.read()));c.close();return result
                try:
                    self.assertEqual(call('GET','/api/state',auth=False)[0],401)
                    self.assertEqual(call('POST','/api/settings',dict(state.DEFAULT,bass=3),origin='http://other.test')[0],403)
                    self.assertEqual(call('POST','/api/settings',dict(state.DEFAULT,volume=999))[0],400)
                    self.assertEqual(read(),state.DEFAULT)
                    new=dict(state.DEFAULT,bass=3,mid=-2,mute=True)
                    self.assertEqual(call('POST','/api/settings',new)[0],200)
                    self.assertEqual(state.read_settings(path),new)
                    self.assertEqual(call('POST','/api/profiles',{'name':'Mein Klang','delete':False})[0],200)
                    saved=call('GET','/api/state')[1]
                    self.assertEqual(saved['profiles']['Mein Klang'],dict(bass=3,mid=-2,treble=0))
                    self.assertEqual(call('POST','/api/profiles',{'name':'Neutral','delete':False})[0],400)
                    self.assertEqual(call('POST','/api/profiles',{'name':'Mein Klang','delete':True})[0],200)
                    self.assertNotIn('Mein Klang',call('GET','/api/state')[1]['profiles'])
                finally:server.shutdown();server.server_close();thread.join()

    def test_real_boosted_pcm_has_headroom(self):
        Gst.init(None)
        settings=dict(state.DEFAULT,volume=100,bass=6,mid=6,treble=6)
        for hz in (100,1100,11000):
            pipeline=Gst.parse_launch(f'audiotestsrc freq={hz} volume=1 num-buffers=12 ! audio/x-raw,channels=2,rate=44100 ! '+speaker_path(state.gain(settings),tweeter_gain=.63)+' ! appsink name=out sync=false')
            for n in range(3):pipeline.get_by_name('equalizer').set_property('band'+str(n),6)
            out=pipeline.get_by_name('out');chunks=[]
            try:
                pipeline.set_state(Gst.State.PLAYING)
                while True:
                    sample=out.emit('try-pull-sample',Gst.SECOND)
                    if sample:
                        b=sample.get_buffer();chunks.append(np.frombuffer(b.extract_dup(0,b.get_size()),dtype='<i4'))
                    elif out.get_property('eos'):break
                    else:self.fail('EQ pipeline stalled')
            finally:pipeline.set_state(Gst.State.NULL)
            self.assertTrue(chunks)
            self.assertLess(np.abs(np.concatenate(chunks).astype(float)).max(),.25*2**31)

if __name__=='__main__':unittest.main()
