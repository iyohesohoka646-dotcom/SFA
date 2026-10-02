"""Update only the repository's copied, relocatable desktop Python runtime."""

from pathlib import Path
import hashlib
import json
import subprocess
import zipfile
import tomllib
import shutil


def main():
    root = Path(__file__).resolve().parents[1]
    runtime = (root / ".work/desktop-python").resolve()
    if not runtime.is_relative_to(root / ".work"):
        raise SystemExit(
            "Desktop runtime must remain inside the repository .work directory"
        )
    python = runtime / "python.exe"
    if not python.is_file():
        raise SystemExit(
            "Copy a relocatable Windows Python distribution to .work/desktop-python first"
        )
    prefix = subprocess.check_output(
        [str(python), "-I", "-c", "import sys;print(sys.prefix)"], text=True
    ).strip()
    if Path(prefix).resolve() != runtime:
        raise SystemExit(
            "Refusing to modify a Python installation outside the private desktop copy"
        )
    version=tomllib.loads((root/"pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    wheel=root/"dist"/f"contract_driven_ai_flow-{version}-py3-none-any.whl"
    if not wheel.is_file():
        raise SystemExit("Build the current release wheel first: "+version)
    # Target the verified private site explicitly, preserving PEP 668 protections.
    site = (runtime / "Lib/site-packages").resolve()
    if not site.is_relative_to(runtime):
        raise SystemExit("Private package target escapes the copied runtime")
    install = [
        str(python),
        "-I",
        "-m",
        "pip",
        "--isolated",
        "install",
        "--no-user",
        "--target",
        str(site),
        "--upgrade",
    ]
    # A local candidate can be rebuilt at the same version. --upgrade alone
    # retains old package bytes; reinstall the exact wheel without churning deps.
    subprocess.run(
        [*install, "--force-reinstall", "--no-deps", str(wheel)], cwd=root, check=True
    )
    subprocess.run(
        [*install, "--upgrade", str(wheel) + "[research,tables,views]"],
        cwd=root,
        check=True,
    )
    quarantine=root/'.work/desktop-prior-metadata'
    for previous in site.glob('contract_driven_ai_flow-*.dist-info'):
        if previous.name!=f'contract_driven_ai_flow-{version}.dist-info':
            destination=quarantine/previous.name
            if destination.exists():raise SystemExit('Prior metadata backup already exists: '+str(destination))
            quarantine.mkdir(exist_ok=True)
            shutil.move(str(previous),str(destination))
    data = json.loads(
        subprocess.check_output(
            [
                str(python),
                "-I",
                "-c",
                'import json,importlib.metadata as m,contract_driven_ai_flow as p;print(json.dumps({"version":p.__version__,"package":p.__file__,"tools":{k:m.version(k) for k in ("matplotlib","seaborn","plotly","altair")}}))',
            ],
            text=True,
        )
    )
    if not Path(data["package"]).resolve().is_relative_to(runtime):
        raise SystemExit(
            "Desktop package unexpectedly resolves outside the private runtime"
        )
    if data["version"]!=version:
        raise SystemExit("Private runtime release identity differs from the current wheel")
    matched = 0
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.startswith("contract_driven_ai_flow/") and not name.endswith("/"):
                if (
                    Path(data["package"]).parent.parent / name
                ).read_bytes() != archive.read(name):
                    raise SystemExit(
                        "Private runtime differs from the selected wheel: " + name
                    )
                matched += 1
    data["matched_package_files"] = matched
    data.update(
        wheel=wheel.name,
        wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
        private_runtime=str(runtime),
        result="passed",
    )
    (root / ".work/desktop-runtime-validation.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
