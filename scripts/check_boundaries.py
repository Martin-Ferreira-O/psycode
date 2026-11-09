"""Comprobar independencia de producción y hashes de contratos, sin servicios externos."""
import ast
import hashlib
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
forbidden_modules = ('psycode_agent', 'obsws_python', 'backend.apps.capture.agent')
for path in (root/'backend').rglob('*.py'):
    tree=ast.parse(path.read_text(encoding='utf-8-sig'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module, *(f'{node.module}.{alias.name}' for alias in node.names)]
        else:
            continue
        for name in names:
            assert not any(
                name == module or name.startswith(f'{module}.')
                for module in forbidden_modules
            ), (path, name)
manifest=json.loads((root/'contracts/manifest.json').read_text())
for name,digest in manifest['sha256'].items():
    assert hashlib.sha256((root/'contracts'/name).read_bytes()).hexdigest()==digest,name
assert not (root/'backend/apps/capture/agent').exists()
print('Boundaries and contract checksums: OK')
