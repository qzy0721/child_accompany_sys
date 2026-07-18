# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder specification for the desktop companion app."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs


PROJECT_ROOT = Path(SPECPATH).resolve().parent
FRONTEND_DIST = PROJECT_ROOT / "web" / "dist"
DEFAULT_AUDIO = PROJECT_ROOT / "reference_audio" / "default.wav"

if not FRONTEND_DIST.is_dir():
    raise SystemExit(
        f"未找到 {FRONTEND_DIST}；请先执行 npm run build "
        "或运行 scripts/build_package.ps1"
    )
if not DEFAULT_AUDIO.is_file():
    raise SystemExit("未找到 reference_audio/default.wav，无法生成默认角色")

datas = [
    (str(FRONTEND_DIST), "web/dist"),
    (str(PROJECT_ROOT / "prompts"), "prompts"),
    (str(DEFAULT_AUDIO), "reference_audio"),
    (str(PROJECT_ROOT / ".env.example"), "."),
]

hiddenimports = [
    "MemoryGenerate",
    "PromptOptimizer",
    "api",
    "fetch_baidu",
    "oss_client",
    "tts",
    "dashscope.audio.tts_v2",
    "h11",
    "uvicorn.lifespan.off",
    "uvicorn.lifespan.on",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.websockets_impl",
    "websockets",
    "pydantic_core",
    "pydantic_core._pydantic_core",
]

a = Analysis(
    [str(PROJECT_ROOT / "app_launcher.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=collect_dynamic_libs("curl_cffi"),
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "IPython",
        "PIL",
        "cv2",
        "gradio",
        "librosa",
        "matplotlib",
        "numba",
        "numpy",
        "pandas",
        "pydub",
        "pynput",
        "scipy",
        "sklearn",
        "sounddevice",
        "soundfile",
        "sympy",
        "tensorflow",
        "torch",
        "torchaudio",
        "torchvision",
        "transformers",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VirtualCompanion.Server",
    icon=str(PROJECT_ROOT / "web" / "public" / "favicon.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="VirtualCompanion.Server",
    upx=False,
)
