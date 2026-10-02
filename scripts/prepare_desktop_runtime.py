"""Update only the repository's copied, relocatable desktop Python runtime."""
from pathlib import Path
import hashlib
import json
import subprocess
import zipfile


def main():
    root = Path(__file__).resolve().parents[1]
    runtime = (root / '.work/desktop-python').resolve()
    if not runtime.is_relative_to(root / '.work'):
        raise SystemExit('Desktop runtime must remain inside the repository .work directory')
    python = runtime / 'python.exe'
    if not python.is_file():
        raise SystemExit('Copy a relocatable Windows Python distribution to .work/desktop-python first')
    prefix = subprocess.check_output([str(python), '-I', '-c', 'import sys;print(sys.prefix)'], text=True).strip()
    if Path(prefix).resolve() != runtime:
        raise SystemExit('Refusing to modify a Python installation outside the private desktop copy')
    wheel = sorted((root / 'dist').glob('contract_driven_ai_flow-*.whl'))[-1]
    # The copied uv runtime retains its PEP 668 marker. The override targets
    # only this checked private copy, never the source/user installation.
    install = [str(python), '-I', '-m', 'pip', '--isolated', 'install', '--no-user', '--break-system-packages']
    # A local candidate can be rebuilt at the same version. --upgrade alone
    # retains old package bytes; reinstall the exact wheel without churning deps.
    subprocess.run([*install, '--force-reinstall', '--no-deps', str(wheel)], cwd=root, check=True)
    subprocess.run([*install, '--upgrade', str(wheel) + '[research,tables,views]'], cwd=root, check=True)
    data = json.loads(subprocess.check_output([str(python), '-I', '-c', 'import json,importlib.metadata as m,contract_driven_ai_flow as p;print(json.dumps({"version":p.__version__,"package":p.__file__,"tools":{k:m.version(k) for k in ("matplotlib","seaborn","plotly","altair")}}))'], text=True))
    if not Path(data['package']).resolve().is_relative_to(runtime):
        raise SystemExit('Desktop package unexpectedly resolves outside the private runtime')
    matched = 0
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.startswith('contract_driven_ai_flow/') and not name.endswith('/'):
                if (Path(data['package']).parent.parent / name).read_bytes() != archive.read(name):
                    raise SystemExit('Private runtime differs from the selected wheel: ' + name)
                matched += 1
    data['matched_package_files'] = matched
    data.update(wheel=wheel.name, wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(), private_runtime=str(runtime), result='passed')
    (root / '.work/desktop-runtime-validation.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    print(json.dumps(data, indent=2))


if __name__ == '__main__':
    main()
