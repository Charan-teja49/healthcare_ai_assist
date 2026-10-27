"""Package portable source without local data, credentials or dependencies."""
from pathlib import Path
import os
import zipfile

root=Path(__file__).resolve().parents[1]
archive=root.parent/'MediAssist-AI-v0.2.1-Login-Fixed.zip'
excluded_dirs={'.python','.venv','node_modules','__pycache__','.git','dist','.pytest_cache','.pio','.npm-cache'}
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as target:
    for folder,dirs,files in os.walk(root,followlinks=False):
        dirs[:]=[name for name in dirs if name not in excluded_dirs]
        for name in files:
            file=Path(folder)/name
            relative=file.relative_to(root).as_posix()
            if name in ('.env','secrets.h') or name.endswith(('.db','.db-wal','.db-shm','.db-journal','.jwt-secret','.pyc','.log')) or relative=='tools/update_frontend.py':
                continue
            target.write(file,'mediassist/'+relative)
with zipfile.ZipFile(archive) as check:
    assert check.testzip() is None
    names=check.namelist()
    assert 'mediassist/frontend/package-lock.json' in names
    assert 'mediassist/backend/requirements-lock.txt' in names
    assert not any('/node_modules/' in name or name.endswith(('.db','.jwt-secret','/secrets.h')) for name in names)
    print(f'Verified {len(names)} files; {archive.stat().st_size:,} bytes')
    print(archive)
