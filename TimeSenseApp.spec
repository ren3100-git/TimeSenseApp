# -*- mode: python ; coding: utf-8 -*-
import subprocess
from pathlib import Path
from PyInstaller.config import CONF


a = Analysis(
    ['launcher_v7.py'],
    pathex=[],
    binaries=[],
    datas=[('templates', 'templates'), ('static', 'static'), ('config', 'config')],
    hiddenimports=['server_v2', 'stats_v5'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# Remove the builder's home directory from Python build metadata.
# Keep the analysis code cache for all other modules (including hook changes).
for index, (module_name, source_path, type_code) in enumerate(a.pure):
    if module_name.startswith('_sysconfigdata') and source_path:
        public_source = Path(CONF['workpath']) / (module_name + '_public.py')
        text = Path(source_path).read_text(encoding='utf-8')
        public_text = text.replace(str(Path.home()), '/opt/buildroot')
        if not public_source.exists() or public_source.read_text(encoding='utf-8') != public_text:
            public_source.write_text(public_text, encoding='utf-8')
        a.pure[index] = (module_name, str(public_source), type_code)
        code_cache = CONF['code_cache'].get(id(a.pure))
        if code_cache is not None:
            code_cache.pop(module_name, None)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TimeSenseApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['TSE.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TimeSenseApp',
)
app = BUNDLE(
    coll,
    name='TimeSenseApp.app',
    icon='TSE.icns',
    bundle_identifier='io.github.ren3100-git.TimeSenseApp',
    version='1.0.0',
    info_plist={'CFBundleShortVersionString': '1.0.0', 'CFBundleVersion': '1.0.0'},
)

# Python's shared library can retain its original installation prefix.
# Redact only the builder's home prefix, preserving binary offsets, then sign.
home_prefix = str(Path.home()).encode('utf-8')
public_prefix = b'/build' + b'_' * (len(home_prefix) - len(b'/build'))
assert len(public_prefix) == len(home_prefix)
modified = False
for library in (Path(app.name) / 'Contents' / 'Frameworks').glob('libpython*.dylib'):
    if library.is_symlink():
        continue
    contents = library.read_bytes()
    if home_prefix not in contents:
        continue
    library.write_bytes(contents.replace(home_prefix, public_prefix))
    subprocess.run(['codesign', '--force', '--sign', '-', str(library)], check=True)
    modified = True
if modified:
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', app.name], check=True)
subprocess.run(['codesign', '--verify', '--deep', '--strict', app.name], check=True)
