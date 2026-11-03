"""Comprobar independencia de producción y hashes de contratos, sin servicios externos."""
import ast
import hashlib
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
for path in (root/'backend').rglob('*.py'):
    tree=ast.parse(path.read_text(encoding='utf-8-sig'))
    for node in ast.walk(tree):
        names=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
        assert not any(n.split('.')[0] in {'psycode_agent','obsws_python'} or n.startswith('backend.apps.capture.agent') for n in names),str(path)
manifest=json.loads((root/'contracts/manifest.json').read_text())
for name,digest in manifest['sha256'].items():
    assert hashlib.sha256((root/'contracts'/name).read_bytes()).hexdigest()==digest,name
assert not (root/'backend/apps/capture/agent').exists()
print('Boundaries and contract checksums: OK')
