"""Portable onedir Windows application with the local Vite build bundled."""

from pathlib import Path


PROJECT_ROOT = Path(SPEC).resolve().parent.parent
WEB_DIST = PROJECT_ROOT / "web" / "dist"
if not (WEB_DIST / "index.html").is_file():
    raise SystemExit("web/dist/index.html is missing; run npm run build before packaging.")

frontend_files = []
for source in WEB_DIST.rglob("*"):
    if source.is_file():
        relative_parent = source.relative_to(WEB_DIST).parent
        destination = Path("web") / "dist" / relative_parent
        frontend_files.append((str(source), str(destination)))

a = Analysis(
    [str(PROJECT_ROOT / "launcher.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=frontend_files,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GridShift",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="GridShift",
)
