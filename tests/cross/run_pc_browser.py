"""Entorno de navegador aislado; no usa configuración privada ni bases de la clínica."""
import argparse
import sys
from pathlib import Path
import hashlib,json,os,socket,subprocess,tempfile,time
parser=argparse.ArgumentParser(description='Navegador + HTTPS/WSS sintéticos de gestión de PCs')
parser.add_argument('--agent-python', required=True, type=Path)
parser.add_argument('--playwright-module', default=os.environ.get('PLAYWRIGHT_MODULE', 'playwright'))
parser.add_argument('--chromium-path', default=os.environ.get('CHROMIUM_PATH'))
parser.add_argument('--artifacts-dir', type=Path)
args=parser.parse_args()
if not args.agent_python.is_file():
 parser.error('--agent-python debe señalar el Python del agente instalado')
root=Path(__file__).resolve().parents[2]
run=args.artifacts_dir.absolute() if args.artifacts_dir else Path(tempfile.mkdtemp(prefix='psycode-pcs-browser-'))
run.mkdir(parents=True,exist_ok=True)
if (run/'db.sqlite3').exists():
 parser.error('El directorio de evidencia ya contiene una base; utilizar uno nuevo')
cert=run/'cert.pem';key=run/'key.pem'
subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=127.0.0.1','-addext','subjectAltName=IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
with socket.socket() as sock:
 sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
env=dict(os.environ)
env.update(DJANGO_SETTINGS_MODULE='backend.config.test_settings', SQLITE_PATH=str(run/'db.sqlite3'),PSYCODE_TEST_SQLITE_PATH=str(run/'test.sqlite3'),
 CAPTURE_FRAGMENT_ROOT=str(run/'fragments'), CAPTURE_AGENTS=json.dumps({'collector-test':{'box':'box-3','token_sha256':hashlib.sha256(('collector-test.'+'S'*43).encode()).hexdigest()}}),
 CAPTURE_AGENDA_SOURCES=json.dumps({'smile':{'collector_id':'collector-test','boxes':['box-3','box-4','box-5','box-6','box-7']}}),
 FRONTEND_TEST_URL=f'https://127.0.0.1:{port}',PC_PAIRING_AGENT_PYTHON=str(args.agent_python.absolute()),SSL_CERT_FILE=str(cert),
 PLAYWRIGHT_MODULE=args.playwright_module,
 FRONTEND_SCREENSHOT_DIR=str(run))
if args.chromium_path:
 env['CHROMIUM_PATH']=args.chromium_path
python=sys.executable
subprocess.run([python,'manage.py','migrate','--noinput'],env=env,cwd=root,check=True,stdout=subprocess.DEVNULL)
script="from backend.apps.accounts.models import User; User.objects.create_user(username='pcs-browser',email='pcs-browser@example.test',password='Synthetic-browser-2026!',role='admin'); User.objects.create_user(username='pcs-supervisor',email='pcs-supervisor@example.test',password='Synthetic-browser-2026!',role='supervisor')"
subprocess.run([python,'manage.py','shell','-c',script],env=env,cwd=root,check=True,stdout=subprocess.DEVNULL)
log=(run/'server.log').open('w')
server_code = "import sys, uvicorn; from backend.config.asgi import application; from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler; uvicorn.run(ASGIStaticFilesHandler(application), host='127.0.0.1', port=int(sys.argv[1]), ssl_keyfile=sys.argv[2], ssl_certfile=sys.argv[3], log_level='warning')"
server=subprocess.Popen([python,'-c',server_code,str(port),str(key),str(cert)],env=env,cwd=root,stdout=log,stderr=log)
try:
 for _ in range(100):
  if server.poll() is not None: raise RuntimeError('El servidor de prueba no arrancó')
  try:
   with socket.create_connection(('127.0.0.1',port),timeout=.1):break
  except OSError:time.sleep(.1)
 result=subprocess.run(['node','backend/apps/web/tests/pcs.browser.cjs'],env=env,cwd=root)
 print(f'Evidencia de navegador: {run}',flush=True)
 raise SystemExit(result.returncode)
finally:
 server.terminate()
 try:server.wait(10)
 except subprocess.TimeoutExpired:server.kill();server.wait()
 log.close()
