import importlib.util
from pathlib import Path
import pytest


def test_private_runtime_refuses_previous_wheel_when_current_release_is_absent(tmp_path,monkeypatch):
    script=Path(__file__).resolve().parents[1]/'scripts/prepare_desktop_runtime.py'
    spec=importlib.util.spec_from_file_location('desktop_prepare',script)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.__file__=str(tmp_path/'scripts/prepare_desktop_runtime.py')
    runtime=tmp_path/'.work/desktop-python';runtime.mkdir(parents=True)
    (runtime/'python.exe').write_bytes(b'')
    (tmp_path/'pyproject.toml').write_text('[project]\nversion="0.5.0"\n')
    dist=tmp_path/'dist';dist.mkdir();(dist/'contract_driven_ai_flow-0.4.0-py3-none-any.whl').write_bytes(b'old')
    monkeypatch.setattr(module.subprocess,'check_output',lambda *a,**k:str(runtime))
    calls=[]
    def install(*a,**k):calls.append(a);raise AssertionError('Previous wheel must never be installed')
    monkeypatch.setattr(module.subprocess,'run',install)
    with pytest.raises(SystemExit,match='0.5.0|current|build'):
        module.main()
    assert not calls
