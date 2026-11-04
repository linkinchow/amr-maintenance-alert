"""Repository checks, run by GitHub Actions and usable locally.

  python scripts/build_templates.py
  az bicep build -f main.bicep --outfile /tmp/built.json
  python scripts/ci_check.py /tmp/built.json

1. Every tracked *.json file parses.
2. azuredeploy.json matches a fresh build of main.bicep (ignoring metadata._generator).
3. modules/workflow.json matches scripts/build_templates.py (also covered by the unit tests, which CI runs separately).
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from build_templates import build_workflow  # noqa: E402

errors = []


def load(path):
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))


def strip_generator(node):
    if isinstance(node, dict):
        return {k: strip_generator(v) for k, v in node.items() if k != '_generator'}
    if isinstance(node, list):
        return [strip_generator(v) for v in node]
    return node


files = subprocess.check_output(['git', 'ls-files', '*.json'], cwd=ROOT, text=True).split()
for f in files:
    try:
        load(ROOT / f)
    except Exception as e:  # noqa: BLE001
        errors.append(f'{f}: invalid JSON ({e})')

if len(sys.argv) > 1:
    if strip_generator(load(sys.argv[1])) != strip_generator(load(ROOT / 'azuredeploy.json')):
        errors.append('azuredeploy.json is out of date: run  az bicep build -f main.bicep --outfile azuredeploy.json')
else:
    print('skip: no freshly built template given, azuredeploy.json not compared')

if load(ROOT / 'modules' / 'workflow.json') != build_workflow():
    errors.append('modules/workflow.json is out of date: run  python scripts/build_templates.py')

for e in errors:
    print('ERROR', e)
print(f'{len(files)} JSON files checked, {len(errors)} error(s)')
sys.exit(1 if errors else 0)
