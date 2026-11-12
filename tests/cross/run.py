"""Suite explícita: --agent-wheel identifica el paquete, sin depender de carpetas hermanas."""
import argparse
import hashlib
import io
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone

ROOT=Path(__file__).resolve().parents[2]

def stop_process(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--agent-wheel',required=True,type=Path)
    args=parser.parse_args();wheel=args.agent_wheel.resolve()
    assert wheel.is_file()
    with tempfile.TemporaryDirectory(prefix='psycode-cross-') as temporary, ExitStack() as resources, ExitStack() as processes:
        root=Path(temporary);env=os.environ.copy()
        token='cross-agent.'+'s'*43
        agents={'cross-agent':{'box':'box-3','token_sha256':hashlib.sha256(token.encode()).hexdigest()}}
        env.update(DJANGO_SETTINGS_MODULE='tests.cross.settings',SQLITE_PATH=str(root/'db.sqlite3'),
                   PSYCODE_TEST_SQLITE_PATH=str(root/'test.sqlite3'),CAPTURE_FRAGMENT_ROOT=str(root/'fragments'),CAPTURE_AGENTS=json.dumps(agents),
                   CAPTURE_AGENDA_SOURCES=json.dumps({'smile':{'collector_id':'cross-agent','boxes':['box-3']}}))
        os.environ.update(env)
        import django
        django.setup()
        from django.core.management import call_command
        from django.db import connections
        resources.callback(connections.close_all)
        call_command('migrate',verbosity=0,interactive=False)
        # Datos de agenda sintéticos por HTTP; otro proceso coordina desde SQL.
        agent_env=root/'agent-env'
        subprocess.run(['uv','venv',str(agent_env),'--python',sys.executable],check=True,capture_output=True)
        apython=agent_env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        subprocess.run(['uv','pip','install','--reinstall-package','psycode-agent',
                        '--python',str(apython),str(wheel)],check=True,capture_output=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        log=resources.enter_context((root/'server.log').open('w+'))
        server=subprocess.Popen([sys.executable,'-m','uvicorn','backend.config.asgi:application',
            '--host','127.0.0.1','--port',str(port),'--log-level','warning','--timeout-graceful-shutdown','2'],
            cwd=ROOT,env=env,stdout=log,stderr=log)
        processes.callback(stop_process, server)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port2=sock.getsockname()[1]
        alternate=f'http://127.0.0.1:{port2}'
        second_log=resources.enter_context((root/'server2.log').open('w+'))
        second_server=subprocess.Popen([sys.executable,'-m','uvicorn','backend.config.asgi:application',
            '--host','127.0.0.1','--port',str(port2),'--log-level','warning','--timeout-graceful-shutdown','2'],
            cwd=ROOT,env=env,stdout=second_log,stderr=second_log)
        processes.callback(stop_process, second_server)
        try:
            import httpx
            for _ in range(100):
                if server.poll() is not None:raise RuntimeError('ASGI startup failed')
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.1):break
                except OSError:time.sleep(.05)
            for _ in range(100):
                if second_server.poll() is not None:raise RuntimeError('Second ASGI startup failed')
                try:
                    with socket.create_connection(('127.0.0.1',port2),timeout=.1):break
                except OSError:time.sleep(.05)
            isolated=subprocess.run([str(apython),'-I','-c',
                'import importlib.util, pathlib, sys, zipfile; import psycode_agent; '
                'assert all(importlib.util.find_spec(n) is None for n in ("django","backend","pymongo")); '
                'root=pathlib.Path(psycode_agent.__file__).parent; wheel=zipfile.ZipFile(sys.argv[1]); '
                'assert all(p.read_bytes()==wheel.read("psycode_agent/"+p.name) for p in root.glob("*.py"))',str(wheel)],
                check=True,capture_output=True)
            from openpyxl import Workbook
            from zoneinfo import ZoneInfo
            local=datetime.now(ZoneInfo('America/Santiago')).replace(second=0,microsecond=0)
            start=local-timedelta(minutes=1)
            w=Workbook();s=w.active;s['A2']='CLINICA FISICA: box-3'
            for col,v in enumerate(('FECHA','HORA','DUR','ESTATUS'),1):s.cell(7,col,v)
            for col,v in enumerate((start.date().isoformat(),start.strftime('%H:%M'),'00:10','CONFIRMADA'),1):s.cell(8,col,v)
            out=io.BytesIO();w.save(out);raw=out.getvalue()
            headers={'Authorization':'Agent '+token}
            op=httpx.post(base+'/api/v1/internal/agenda-collections',headers=headers,json={'source':'smile'});op.raise_for_status()
            metadata=dict(collection_id=op.json()['data']['collection_id'],source='smile',boxes=['box-3'],
                agenda_date=local.date().isoformat(),obtained_at=datetime.now(timezone.utc).isoformat(),
                format_version='smile.excel.v1',checksum=hashlib.sha256(raw).hexdigest(),outcome='valid')
            for status in (201,200):
                response=httpx.post(base+'/api/v1/internal/agenda-reports',headers=headers,data={'metadata':json.dumps(metadata)},
                                    files={'archivo':('synthetic.xlsx',raw)})
                assert response.status_code==status,response.text
            from backend.apps.operational.models import OperationalConfiguration
            OperationalConfiguration.objects.create(enabled_days=list(range(7)),open_time='00:00',close_time='23:59',
                primary_email='synthetic@example.test',backup_email='synthetic-backup@example.test')
            def coordinate(*flags):subprocess.run([sys.executable,'manage.py','coordinate_capture','--once',*flags],cwd=ROOT,env=env,check=True,capture_output=True)
            coordinate()
            from backend.apps.capture.models import CaptureSession, FragmentJob
            sid=CaptureSession.objects.get(box='box-3').pk
            coordinate();assert CaptureSession.objects.get(box='box-3').pk==sid
            agent_log=resources.enter_context((root/'agent.log').open('w+'))
            agent=subprocess.Popen([str(apython),str(ROOT/'tests/cross/agent_probe.py'),base,token,str(root/'state'),alternate],
                                   cwd=root,env=env,stdout=agent_log,stderr=agent_log)
            processes.callback(stop_process, agent)
            for _ in range(200):
                agent_log.flush();agent_log.seek(0);content=agent_log.read()
                if '"stage": "uploaded"' in content:break
                if agent.poll() is not None:raise RuntimeError(content)
                time.sleep(.05)
            else:raise RuntimeError('Agent upload timeout: '+content)
            first_session = CaptureSession.objects.get(pk=sid)
            assert first_session.capture_chunk_config == {"audio_chunk_mode": "fixed", "audio_chunk_duration": 60}
            assert first_session.audio_profile["chunk_samples"] == 60 * 16000
            # Cambiar el ajuste no modifica la sesión activa; la siguiente toma 600 s.
            OperationalConfiguration.objects.filter(pk=1).update(audio_chunk_duration=600)
            coordinate()
            first_session.refresh_from_db()
            assert first_session.capture_chunk_config["audio_chunk_duration"] == 60
            # Simula cambio de agenda en el receptor y reinicio del coordinador.
            from backend.apps.agenda.models import AgendaBoxRevision
            AgendaBoxRevision.objects.filter(box='box-3').update(appointments=[])
            coordinate()
            agent.wait(timeout=15)
            agent_log.seek(0);content=agent_log.read()
            assert agent.returncode==0,content
            assert '"stage": "stopped"' in content,content
            assert CaptureSession.objects.get(pk=sid).state=='completada'
            assert FragmentJob.objects.filter(sequence__session_id=sid).count()==1
            assert FragmentJob.objects.filter(sequence__session_id=sid).get().state=='pendiente'
            # Procesamiento central con proveedores simulados, conserva unknown.
            from backend.apps.capture.processing import FragmentJobProcessor
            from backend.config.composition import fragment_storage
            from backend.apps.analysis.domain import AnalysisResult,AnalysisState
            class SimulatedAnalysis:
                def process(self,fragment,roles):
                    assert roles=={}
                    assert fragment.end==1600 and fragment.session_origin_sample==0
                    return AnalysisResult(fragment.session_id,fragment.sequence,AnalysisState.INDETERMINATE,
                                          error_codes=('CONTEXT_NOT_EVALUABLE',))
                def close_session(self,sid):pass
            FragmentJobProcessor(fragment_storage(),SimulatedAnalysis()).process_next()
            job=FragmentJob.objects.get(sequence__session_id=sid)
            assert job.state=='completado' and job.result=='indeterminado'
            # Un segundo ciclo usa el runtime autónomo real, con OBS/FFmpeg simulados.
            from backend.apps.agenda.persistence import receive, issue
            from backend.apps.capture.authentication import AgentIdentity
            identity=AgentIdentity('cross-agent','box-3')
            operation=issue(identity,'smile')
            metadata['collection_id']=operation['collection_id']
            metadata['format_version']='smile.json.v1'
            native_raw=json.dumps([dict(smile_cita_id='SYNTHETIC-NATIVE-001',box=3,smile_box_id='8',
                fecha=start.date().isoformat(),hora_inicio=start.strftime('%H:%M'),duracion_minutos=10,
                estado='CONFIRMADA',codigo_estado='SYNTHETIC')]).encode()
            metadata['checksum']=hashlib.sha256(native_raw).hexdigest()
            response=httpx.post(base+'/api/v1/internal/agenda-reports',headers=headers,data={'metadata':json.dumps(metadata)},
                files={'archivo':('synthetic.json',native_raw,'application/json')})
            assert response.status_code==201,response.text
            coordinate()
            sid2=CaptureSession.objects.get(box='box-3',state='iniciada').pk
            runtime_log=resources.enter_context((root/'runtime.log').open('w+'))
            agent=subprocess.Popen([str(apython),str(ROOT/'tests/cross/runtime_probe.py'),base,token,str(root/'runtime-state')],
                cwd=root,env=env,stdout=runtime_log,stderr=runtime_log)
            processes.callback(stop_process, agent)
            for _ in range(200):
                if CaptureSession.objects.get(pk=sid2).state=='activa':break
                if agent.poll() is not None:
                    runtime_log.seek(0);raise RuntimeError(runtime_log.read())
                time.sleep(.05)
            else:raise RuntimeError('Autonomous runtime did not start')
            time.sleep(.3)
            AgendaBoxRevision.objects.filter(box='box-3').update(appointments=[])
            coordinate()
            agent.wait(timeout=20)
            runtime_log.seek(0);runtime_content=runtime_log.read()
            assert agent.returncode==0,runtime_content
            assert 'autonomous_passed' in runtime_content,runtime_content
            second_session = CaptureSession.objects.get(pk=sid2)
            assert second_session.state == 'completada'
            assert second_session.capture_chunk_config['audio_chunk_duration'] == 600
            assert second_session.audio_profile['chunk_samples'] == 600 * 16000
            assert FragmentJob.objects.filter(sequence__session_id=sid2).count()==1
            # Ejecutar también la cobertura HTTP v1 y ACK históricos, fuera de la suite ordinaria.
            # Esta instalación temporal del servidor admite el agente solo para esas pruebas.
            result=subprocess.run(['uv','run','--with',str(wheel),'--reinstall-package','psycode-agent','--no-editable','python','manage.py','test','tests/cross',
                '--settings=backend.config.test_settings','--noinput'],cwd=ROOT,env=env,capture_output=True,text=True)
            if result.returncode:raise RuntimeError(result.stdout+result.stderr)
            test_count = re.search(r'Ran (\d+) tests?', result.stderr)
            assert test_count is not None, result.stderr
            print(json.dumps({'result':'passed','agent_wheel_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),
                'cross_test_count': int(test_count.group(1)),
                'coverage':['five concurrent simulated agents with consecutive sessions and old backlog',
                'lost HTTPS responses after commit for each agent','separate WS/HTTP processes','SQL agenda and coordinator restart','lost ACK after commit',
                'reconnect','idempotent uploads','stop and final sequence','queue to simulated unknown-speaker analysis','historical v1 HTTP and ACK tests','autonomous runtime with simulated OBS/FFmpeg','lease replacement across two ASGI processes','isolated agent without Django/backend/MongoDB','native delivered Smile JSON through HTTP to authorization']}))
        finally:
            processes.close()
            for server_log in (second_log, log):
                server_log.seek(0)
                content = server_log.read()
                if content:
                    print(content, file=sys.stderr)

if __name__=='__main__':main()
