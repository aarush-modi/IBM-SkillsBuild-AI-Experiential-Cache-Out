# PyInstaller spec for FocusBand (DESIGN §4 Packaging). Build with: python scripts/build_app.py
# One-folder build (fast start-up), windowed. On macOS it is wrapped in FocusBand.app with a
# camera usage description, which macOS requires before it will show the camera prompt.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).parent

datas = [
    (str(ROOT / "models"), "models"),                         # MediaPipe .task files and yolo26n.pt
    (str(ROOT / "app" / "alerts" / "sounds"), "app/alerts/sounds"),
    (str(ROOT / "app" / "ui" / "icons"), "app/ui/icons"),
]
datas += collect_data_files("mediapipe")
datas += collect_data_files("desktop_notifier")
# MediaPipe loads libmediapipe from mediapipe/tasks/c via importlib.resources, so keep that path.
binaries = collect_dynamic_libs("mediapipe")
# torchvision >= 0.29 names its compiled ops _C_stable / image_stable, which the PyInstaller hook
# doesn't know; without them YOLO's NMS op is missing. torchvision finds them next to its .py files.
import torchvision  # noqa: E402

TV = Path(torchvision.__file__).parent
binaries += [(str(p), "torchvision") for p in TV.glob("*_stable.*") if p.suffix in (".so", ".pyd")]
binaries += collect_dynamic_libs("torchvision")
hiddenimports = ["mediapipe.tasks.c"]
hiddenimports += collect_submodules("mediapipe.tasks.python")
hiddenimports += collect_submodules("desktop_notifier")

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "IPython", "pytest", "mypy", "tests", "scripts"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="FocusBand",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="FocusBand", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="FocusBand.app",
        bundle_identifier="local.focusband.app",
        info_plist={
            "CFBundleName": "FocusBand",
            "CFBundleDisplayName": "FocusBand",
            "CFBundleShortVersionString": "0.1.0",
            "NSCameraUsageDescription": (
                "FocusBand uses the camera during a session to notice distraction and posture. "
                "Video is processed on this Mac and never saved or sent anywhere."
            ),
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "13.0",
        },
    )
