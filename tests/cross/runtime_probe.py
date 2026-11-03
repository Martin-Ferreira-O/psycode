"""CLI autónoma instalada con OBS/FFmpeg simulados; transporte y archivos reales."""
import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch
from psycode_agent.config import AgentConfig
from psycode_agent.runtime import run

base,token,root=sys.argv[1:]
stop=threading.Event();started=threading.Event();stopped=threading.Event();errors=[]
class Controller:
    active=False
    client=None
    def __init__(self,config):pass
    def connect(self):return 'simulated'
    def disconnect(self):pass
    def status(self):return {'recording':self.active,'streaming':self.active}
    def start_capture(self):self.active=True;started.set()
    def wait_for_audio_stream(self):pass
    def stop_capture(self):self.active=False;stopped.set()
class Pipe:
    count=0
    def __init__(self,event):self.event=event
    def read(self,size):
        if self.count<10:
            time.sleep(.02);self.count+=1;return b'\0\0'*320
        self.event.wait(20);return b''
    def close(self):pass
class Process:
    returncode=None
    def __init__(self,*args,**kwargs):self.event=threading.Event();self.stdout=Pipe(self.event)
    def poll(self):return self.returncode
    def terminate(self):self.returncode=-15;self.event.set()
    def kill(self):self.terminate()
    def wait(self,timeout=None):self.event.wait(timeout);return self.returncode
cfg=AgentConfig('box-3','127.0.0.1',4455,'synthetic','rtsp://127.0.0.1/synthetic',10,1,
    backend_url=base,agent_token=token,agent_state_root=root,websocket_url=base.replace('http:','ws:')+'/ws/v1/agents',
    max_retries=2,retry_backoff=0,http_timeout=2,heartbeat_interval=.2,min_free_bytes=1,reserve_bytes=1024)
def finish():
    try:
        assert started.wait(10),'START_TIMEOUT'
        assert stopped.wait(15),'STOP_TIMEOUT'
        # El cierre físico y el envío terminan independientemente. Mantener el
        # runtime disponible hasta observar también los recibos durables.
        for _ in range(200):
            manifests=[json.loads(p.read_text()) for p in (Path(root)/'fragments').glob('*/*.json')]
            ends=[json.loads(p.read_text()) for p in (Path(root)/'box-3'/'session-state').glob('*.json')]
            entries=[json.loads(p.read_text()) for p in (Path(root)/'box-3').glob('*.json')]
            started_ack=any(e.get('kind')=='inicio' and e.get('state')=='acknowledged' for e in entries)
            if started_ack and manifests and all(m['status']=='accepted' for m in manifests) and any('receipt' in e for e in ends):
                return
            time.sleep(.05)
        raise AssertionError('RECEPTION_TIMEOUT')
    except Exception as exc:
        errors.append(str(exc))
    finally:
        stop.set()
threading.Thread(target=finish,daemon=True).start()
with patch('psycode_agent.session_coordinator.OBSController',Controller),patch('psycode_agent.audio_chunker.subprocess.Popen',Process):
    run(cfg,stop)
assert errors==[],errors
entries=[json.loads(p.read_text()) for p in (Path(root)/'box-3').glob('*.json')]
assert any(e.get('kind')=='inicio' and e.get('state')=='acknowledged' for e in entries),entries
manifests=[json.loads(p.read_text()) for p in (Path(root)/'fragments').glob('*/*.json')]
assert len(manifests)==1 and manifests[0]['status']=='accepted',manifests
assert manifests[0]['temporal']['session_end_sample']==3200
print(json.dumps({'stage':'autonomous_passed'}),flush=True)
