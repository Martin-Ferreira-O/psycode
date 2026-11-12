"""Proceso del paquete instalado: OBS simulado y transportes WS/HTTP reales."""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from psycode_agent.config import AgentConfig
from psycode_agent.control import WebSocketControl
from psycode_agent.command_journal import CommandJournal
from psycode_agent.session_coordinator import SessionCoordinator
from psycode_agent.audio_chunker import save_fragment
from psycode_agent.backend_client import BackendClient
from psycode_agent.upload_queue import UploadQueue
from psycode_agent.fragment_store import FragmentStore

base, token, root, alternate=sys.argv[1:]
from dataclasses import replace
config=AgentConfig('box-3','127.0.0.1',4455,'synthetic','rtsp://127.0.0.1/synthetic',10,1,
    backend_url=base,agent_token=token,agent_state_root=root,websocket_url=base.replace('http:','ws:')+'/ws/v1/agents',
    max_retries=2,retry_backoff=0,autonomous=False,audio_v2=True)
control=WebSocketControl(config)
try:
    control.open()
    controller=Mock();runner=Mock();runner.store=FragmentStore(Path(root)/'fragments')
    coordinator=SessionCoordinator(config,control,controller=controller,runner_factory=lambda cfg:runner,
                                   journal=CommandJournal(root,'box-3'))
    commands=control.commands('box-3')
    if not commands:
        time.sleep(1.1);commands=control.commands('box-3')
    start,=commands
    assert start.audio_chunk_duration == 60, "Default duration did not reach agent"
    original=control._request
    dropped=[]
    def lose_receipt(kind,payload,expected):
        result=original(kind,payload,expected)
        if kind=='command_ack' and not dropped:
            dropped.append(dict(payload));raise TimeoutError('synthetic lost receipt after commit')
        return result
    control._request=lose_receipt
    try:coordinator.handle_command(start)
    except TimeoutError:pass
    # Reintenta sin reentrega y conserva identidad, instante y una sola acción OBS.
    # La reconexión toma propiedad en OTRO proceso ASGI, antes de cerrar el viejo.
    replacement=WebSocketControl(replace(config,websocket_url=alternate.replace('http:','ws:')+'/ws/v1/agents'))
    replacement.open()
    deadline=time.monotonic()+3
    while control._error is None and time.monotonic()<deadline:time.sleep(.05)
    assert control._error is not None,'Old ASGI connection retained ownership'
    control.close();control=replacement;coordinator.control=control
    coordinator.retry_pending_confirmation()
    coordinator.thread.join(1)
    assert controller.start_capture.call_count==1
    captured=datetime.now(timezone.utc)
    # Esperar la duración representada en el WAV para no enviar audio futuro.
    metadata=save_fragment(Path(root)/'fragments'/str(start.session_id),'box-3',start.session_id,0,
        b'\0\0'*1600,captured,temporal=dict(session_start_sample=0,session_end_sample=1600,new_audio_start_sample=0,
        sample_rate=16000,chunk_samples=start.audio_chunk_duration * 16000,overlap_samples=16000))
    # Incluye el margen de 200 ms que exige el subidor v2.
    time.sleep(.32)
    client=BackendClient(config)
    path=Path(root)/'fragments'/str(start.session_id)/'000000.wav'
    first=client.upload_fragment(path,str(start.session_id),0,metadata['captured_at'],metadata['checksum_sha256'],metadata['temporal'])
    again=client.upload_fragment(path,str(start.session_id),0,metadata['captured_at'],metadata['checksum_sha256'],metadata['temporal'])
    assert first==again
    assert UploadQueue(runner.store,client).process_pending()==1
    assert not path.exists()
    print(json.dumps({'stage':'uploaded','session_id':str(start.session_id),'job_id':first['job_id']}),flush=True)
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        for command in control.commands('box-3'):
            if command.kind=='detencion':
                coordinator.handle_command(command)
                assert controller.stop_capture.call_count==1
                print(json.dumps({'stage':'stopped','last_sequence':0}),flush=True)
                sys.exit(0)
        time.sleep(.1)
    raise RuntimeError('STOP_NOT_DELIVERED')
finally:control.close()
