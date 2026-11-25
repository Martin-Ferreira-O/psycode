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
class Process:
    def __init__(self):
        self.stdout = self
        self.stdin = self
        self.opened = time.monotonic()
        self.index = 0

    def close(self):
        stopped.set()


def open_worker(*args, **kwargs):
    started.set()
    return Process()


def read_pcm(process):
    if process.index < 10:
        tick = process.opened + process.index * .02
        time.sleep(max(0, tick + .02 - time.monotonic()))
        process.index += 1
        return tick, b"\0\0" * 320
    stopped.wait(20)
    return None


def close_worker(process):
    stopped.set()
    return 0


cfg=AgentConfig('box-3',10,1,
    backend_url=base,agent_token=token,agent_state_root=root,
    websocket_url=base.replace('https:','wss:').replace('http:','ws:')+'/ws/v1/agents',
    control_ca_file=__import__("os").environ.get("SSL_CERT_FILE", ""),
    max_retries=2,retry_backoff=0,http_timeout=2,heartbeat_interval=.2,min_free_bytes=1,reserve_bytes=1024)
def finish():
    try:
        assert started.wait(10),'START_TIMEOUT'
        assert stopped.wait(15),'STOP_TIMEOUT'
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
with (patch('psycode_agent.audio_chunker.open_worker', open_worker),
      patch('psycode_agent.audio_chunker.read_pcm', read_pcm),
      patch('psycode_agent.audio_chunker.close_worker', close_worker)):
    run(cfg,stop)
assert errors==[],errors
entries=[json.loads(p.read_text()) for p in (Path(root)/'box-3').glob('*.json')]
assert any(e.get('kind')=='inicio' and e.get('state')=='acknowledged' for e in entries),entries
manifests=[json.loads(p.read_text()) for p in (Path(root)/'fragments').glob('*/*.json')]
assert len(manifests)==1 and manifests[0]['status']=='accepted',manifests
assert manifests[0]['temporal']['session_end_sample']==3200
print(json.dumps({'stage':'autonomous_passed'}),flush=True)
