"""Backend steps for the Skate 3 → Unreal map pipeline."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

LogFn = Callable[[str], None]


def _log(log: LogFn, msg: str) -> None:
    log(msg)


def app_runtime_dir() -> Path:
    """Persistent runtime folder next to the app (tools, clones, downloads).

    When frozen as an .exe, uses a folder beside the executable so downloads
    survive and do not write into a temp _MEIPASS tree.
    """
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent / "runtime"
    else:
        base = Path(__file__).resolve().parent / "runtime"
    base.mkdir(parents=True, exist_ok=True)
    return base


def tools_dir() -> Path:
    d = app_runtime_dir() / "tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# extract-xiso (always resolve latest from GitHub releases)
# ---------------------------------------------------------------------------

EXTRACT_XISO_REPO = "XboxDev/extract-xiso"
EXTRACT_XISO_ASSET_RE = re.compile(r"extract-xiso-Win64.*\.zip$", re.I)


def fetch_latest_extract_xiso_url(log: LogFn) -> tuple[str, str]:
    """Return (download_url, tag_or_name) for the latest Win64 release zip."""
    api = f"https://api.github.com/repos/{EXTRACT_XISO_REPO}/releases/latest"
    _log(log, "Checking GitHub for latest extract-xiso release…")
    req = urllib.request.Request(
        api,
        headers={"User-Agent": "SkateMapGUI/1.0", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    tag = data.get("tag_name") or data.get("name") or "latest"
    assets = data.get("assets") or []
    for asset in assets:
        name = asset.get("name") or ""
        if EXTRACT_XISO_ASSET_RE.search(name):
            url = asset.get("browser_download_url")
            if url:
                _log(log, f"Latest extract-xiso: {tag} → {name}")
                return url, tag
    # Fallback: known recent build if API shape changes
    fallback = (
        "https://github.com/XboxDev/extract-xiso/releases/download/"
        "build-202609111233/extract-xiso-Win64_Release.zip"
    )
    _log(log, "No matching asset on latest release; using known Win64 build URL")
    return fallback, tag


def download_file(url: str, dest: Path, log: LogFn) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    _log(log, f"Downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "SkateMapGUI/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
        shutil.copyfileobj(resp, out, 1024 * 256)
    tmp.replace(dest)
    _log(log, f"Saved {dest.name} ({dest.stat().st_size // 1024} KB)")


def ensure_extract_xiso(log: LogFn) -> Path:
    """Download latest extract-xiso zip, extract, return path to extract-xiso.exe."""
    tdir = tools_dir() / "extract-xiso"
    tdir.mkdir(parents=True, exist_ok=True)
    marker = tdir / "version.txt"
    url, tag = fetch_latest_extract_xiso_url(log)

    need_download = True
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == tag:
        exe = next(tdir.rglob("extract-xiso.exe"), None)
        if exe and exe.is_file():
            _log(log, f"extract-xiso already up to date ({tag})")
            need_download = False
            return exe

    if need_download:
        zip_path = tdir / "extract-xiso-Win64.zip"
        download_file(url, zip_path, log)
        # Clear old extract (keep zip)
        for child in tdir.iterdir():
            if child.name in {"extract-xiso-Win64.zip", "version.txt"}:
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except OSError:
                    pass
        _log(log, "Extracting extract-xiso…")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tdir)
        marker.write_text(tag, encoding="utf-8")

    exe = next(tdir.rglob("extract-xiso.exe"), None)
    if not exe:
        raise FileNotFoundError("extract-xiso.exe not found after download")
    _log(log, f"Ready: {exe}")
    return exe


def _is_game_root(path: Path) -> bool:
    return (path / "default.xex").is_file() or (path / "data" / "content").is_dir()


def find_game_root(*roots: Path, log: LogFn | None = None) -> Path | None:
    """Locate a Skate 3 game folder under the given roots (and a few fallbacks)."""
    seen: set[Path] = set()
    search: list[Path] = []
    for r in roots:
        if r is None:
            continue
        try:
            r = r.expanduser().resolve()
        except OSError:
            continue
        if r not in seen:
            seen.add(r)
            search.append(r)

    # Common accidental extract locations (cwd / next to the app)
    app_dir = Path(__file__).resolve().parent
    for extra in (app_dir, app_dir / "Skate_3", Path.cwd(), Path.cwd() / "Skate_3"):
        try:
            extra = extra.resolve()
        except OSError:
            continue
        if extra not in seen:
            seen.add(extra)
            search.append(extra)

    for base in search:
        if not base.exists():
            continue
        if _is_game_root(base):
            if log:
                _log(log, f"Game folder: {base}")
            return base
        # One level down
        if base.is_dir():
            try:
                for child in base.iterdir():
                    if child.is_dir() and _is_game_root(child):
                        if log:
                            _log(log, f"Game folder: {child}")
                        return child
            except OSError:
                pass
        # Deeper: default.xex (limit depth via rglob on likely names)
        if base.is_dir():
            try:
                for xex in base.rglob("default.xex"):
                    if log:
                        _log(log, f"Game folder: {xex.parent}")
                    return xex.parent
            except OSError:
                pass
            try:
                for content in base.rglob("data/content"):
                    parent = content.parent.parent
                    if log:
                        _log(log, f"Game folder: {parent}")
                    return parent
            except OSError:
                pass
    return None


def extract_iso(iso: Path, output_dir: Path, log: LogFn) -> Path:
    """Run extract-xiso; return folder that contains default.xex / data/."""
    iso = iso.expanduser().resolve()
    if not iso.is_file():
        raise FileNotFoundError(f"ISO not found: {iso}")
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    exe = ensure_extract_xiso(log)
    # Official usage: extract-xiso <iso> -d <dir>  (also accept -x for explicit extract)
    # Run with cwd=output_dir so if -d is ignored, files still land here.
    cmd = [str(exe), "-x", str(iso), "-d", str(output_dir)]
    _log(log, "Running: " + " ".join(cmd))
    _log(log, f"Working directory: {output_dir}")
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(output_dir),
    )
    if proc.stdout:
        for line in proc.stdout.splitlines()[-40:]:
            _log(log, line)
    if proc.stderr:
        for line in proc.stderr.splitlines()[-20:]:
            _log(log, line)

    # Prefer finding the game even if extract-xiso returned a non-zero code
    # (some builds warn but still extract) or wrote next to the app by mistake.
    found = find_game_root(output_dir, Path(__file__).resolve().parent, log=log)
    if found is not None:
        if proc.returncode != 0:
            _log(
                log,
                f"extract-xiso exit code {proc.returncode}, but game data was found — continuing.",
            )
        return found

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"extract-xiso failed (code {proc.returncode}): {err[:500]}")

    raise FileNotFoundError(
        f"Extraction finished but no default.xex / data/content found.\n"
        f"  Looked under: {output_dir}\n"
        f"  and next to the app. Try Refresh map list if files appeared elsewhere."
    )


# ---------------------------------------------------------------------------
# Map discovery
# ---------------------------------------------------------------------------

def list_map_bigs(game_root: Path) -> list[Path]:
    content = game_root / "data" / "content"
    if not content.is_dir():
        return []
    maps = sorted(content.glob("worldDIST_*.big"))
    if not maps:
        maps = sorted(content.glob("world*.big"))
    return maps


def map_display_name(big: Path) -> str:
    stem = big.stem
    for prefix in ("worldDIST_", "world"):
        if stem.startswith(prefix):
            return stem[len(prefix) :]
    return stem


# ---------------------------------------------------------------------------
# Engine clone + big_to_skate + skate_to_unreal
# ---------------------------------------------------------------------------

ENGINE_REPO = "https://github.com/SK8-ENGINE/skate-3-rust-engine.git"
GIT_DOWNLOAD_URL = "https://git-scm.com/download/win"


def find_git() -> str | None:
    """Return path to git.exe if available on PATH (or common install dirs)."""
    which = shutil.which("git")
    if which:
        return which
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Git"
        / "cmd"
        / "git.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Git"
        / "cmd"
        / "git.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "cmd" / "git.exe",
    ]
    for c in candidates:
        try:
            if c.is_file():
                return str(c)
        except OSError:
            continue
    return None


def git_version(git_path: str | None = None) -> str | None:
    git = git_path or find_git()
    if not git:
        return None
    try:
        proc = subprocess.run(
            [git, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if proc.returncode == 0:
            return (proc.stdout or proc.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def ensure_python_deps(log: LogFn) -> None:
    """Ensure numpy/Pillow are importable.

    When frozen as an .exe, deps must already be bundled — never call pip
    via sys.executable (that would relaunch the GUI).
    """
    try:
        import numpy  # noqa: F401
        import PIL  # noqa: F401
        return
    except ImportError:
        pass
    if getattr(sys, "frozen", False):
        raise RuntimeError(
            "numpy/Pillow are missing from the packaged app. Rebuild with build.bat "
            "(it collects numpy and Pillow into the exe folder)."
        )
    _log(log, "Installing numpy + Pillow…")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "numpy", "Pillow"],
        check=True,
    )


def ensure_engine(log: LogFn) -> Path:
    dest = app_runtime_dir() / "skate-3-rust-engine"
    marker = dest / "tools" / "asset_pipeline" / "install.py"
    if marker.is_file():
        _log(log, f"Engine ready: {dest}")
        return dest
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)

    git = find_git()
    if not git:
        raise RuntimeError(
            "Git is required to download the map converter engine, but it was not found.\n"
            f"Install Git for Windows from:\n  {GIT_DOWNLOAD_URL}\n"
            "Then restart this app and try again."
        )

    _log(log, f"Cloning {ENGINE_REPO} …")
    _log(log, f"  git={git}")
    _log(log, f"  → {dest}")
    try:
        subprocess.run(
            [git, "clone", "--depth", "1", ENGINE_REPO, str(dest)],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Git is not installed or not on PATH. Install Git for Windows, then try again.\n"
            f"  {GIT_DOWNLOAD_URL}"
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"git clone failed: {e.stderr or e}")
    if not marker.is_file():
        raise RuntimeError("Clone completed but engine tools are missing")
    _log(log, "Engine clone complete")
    return dest


def _bundle_roots() -> list[Path]:
    """Search roots for sibling tools (dev layout + PyInstaller bundle)."""
    roots: list[Path] = []
    here = Path(__file__).resolve().parent
    roots.append(here)
    roots.append(here.parent)
    # PyInstaller onefile/onedir
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(Path(meipass))
        roots.append(Path(sys.executable).resolve().parent)
    return roots


def find_sibling_tool(name: str) -> Path | None:
    """Locate big_to_skate.py or convert_skate_to_ue.py next to this package."""
    for root in _bundle_roots():
        candidates = [
            root / "big_to_skate" / name,
            root / "skate_to_unreal" / name,
            root / name,
            root / "big_to_skate" / "big_to_skate.py" if name == "big_to_skate.py" else None,
            root / "skate_to_unreal" / "convert_skate_to_ue.py"
            if name == "convert_skate_to_ue.py"
            else None,
        ]
        for c in candidates:
            if c is not None and c.is_file() and c.name == name:
                return c
        # recursive under root (one level of folders)
        try:
            for c in root.rglob(name):
                if c.is_file():
                    return c
        except OSError:
            pass
    return None


def _import_tool_module(script: Path, module_name: str):
    """Load a sibling .py tool as a module (works when frozen — no subprocess)."""
    import importlib.util

    # Ensure the tool's directory is on path (for local imports like skate_reader)
    tool_dir = str(script.parent)
    if tool_dir not in sys.path:
        sys.path.insert(0, tool_dir)
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {script}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _pick_skate(output_dir: Path, big: Path, log: LogFn) -> Path:
    skates = list(output_dir.glob("*.skate"))
    if not skates:
        raise FileNotFoundError(f"No .skate produced in {output_dir}")
    label = map_display_name(big)
    for s in skates:
        if s.stem.lower() == label.lower() or label.lower() in s.stem.lower():
            _log(log, f"Created {s}")
            return s
    _log(log, f"Created {skates[0]}")
    return skates[0]


def _block_gui_relaunch() -> None:
    """Prevent any code from spawning this frozen .exe as if it were Python."""
    if not getattr(sys, "frozen", False):
        return
    self_exe = Path(sys.executable).resolve()
    real_run = subprocess.run
    real_popen = subprocess.Popen

    def _bad(cmd) -> bool:
        if not cmd:
            return False
        try:
            return Path(str(cmd[0])).resolve() == self_exe
        except OSError:
            return False

    def guarded_run(cmd, *a, **kw):
        if _bad(cmd):
            raise RuntimeError(
                "Blocked attempt to relaunch the GUI as a Python interpreter:\n"
                f"  {cmd}\n"
                "This is an internal bug — conversion must stay in-process."
            )
        return real_run(cmd, *a, **kw)

    def guarded_popen(cmd, *a, **kw):
        if _bad(cmd):
            raise RuntimeError(
                "Blocked attempt to relaunch the GUI as a Python interpreter:\n"
                f"  {cmd}"
            )
        return real_popen(cmd, *a, **kw)

    subprocess.run = guarded_run  # type: ignore[assignment]
    subprocess.Popen = guarded_popen  # type: ignore[assignment]


def convert_big_to_skate(
    big: Path,
    output_dir: Path,
    engine: Path,
    log: LogFn,
) -> Path:
    """Convert worldDIST_*.big → .skate entirely in-process (no new GUI window)."""
    ensure_python_deps(log)
    _block_gui_relaunch()

    frozen = getattr(sys, "frozen", False)
    _log(log, "Converting .big → .skate (in-process)…")
    _log(log, f"  frozen={frozen}  executable={sys.executable}")
    _log(log, f"  engine={engine}")

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    work = output_dir / "_work"
    work.mkdir(parents=True, exist_ok=True)
    stage = work / "stage"
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "assets" / "private" / "native-props").mkdir(parents=True, exist_ok=True)

    # Import engine modules (same path logic as big_to_skate)
    engine = engine.resolve()
    if str(engine) not in sys.path:
        sys.path.insert(0, str(engine))
    uni = engine / "tools" / "vendor" / "university" / "tools"
    for p in (
        uni,
        uni / "vanilla_map_extraction" / "tools",
        uni / "vanilla_map_extraction" / "blender",
    ):
        if p.is_dir() and str(p) not in sys.path:
            sys.path.insert(0, str(p))

    try:
        from tools.asset_pipeline import install as install_mod
        from tools.asset_pipeline.install import convert_map
    except ImportError as e:
        raise RuntimeError(
            f"Cannot import engine convert_map: {e}\n"
            f"Engine path: {engine}\n"
            "Make sure git clone of skate-3-rust-engine completed."
        ) from e

    # Never run the game binary / never use this exe as a stand-in
    def _noop_run(args, log_f, report_fn):
        msg = "skipping runtime validation (in-process GUI convert)"
        report_fn(msg)
        log_f.write(msg + "\n")

    install_mod.run = _noop_run  # type: ignore[assignment]

    log_path = work / f"{big.stem}-convert.log"
    t0 = __import__("time").perf_counter()

    def report(msg: str) -> None:
        _log(log, msg)

    _log(log, f"  input={big}")
    with log_path.open("w", encoding="utf-8") as log_f:
        try:
            entry = convert_map(
                big.resolve(),
                work / "conversion",
                output_dir,
                stage,
                Path("validation-skipped"),  # not used; run() is no-op
                log_f,
                report,
            )
        except Exception as e:
            log_f.write(f"\nFATAL: {e!r}\n")
            raise RuntimeError(
                f"Conversion failed: {e}\n  See log: {log_path}"
            ) from e

    elapsed = __import__("time").perf_counter() - t0
    _log(log, f"  convert_map finished in {elapsed:.1f}s  entry={entry!r}")
    _log(log, f"  log: {log_path}")
    return _pick_skate(output_dir, big, log)


def convert_skate_to_unreal(skate: Path, output_dir: Path, log: LogFn) -> Path:
    """Convert .skate → Unreal export folder in-process."""
    ensure_python_deps(log)
    _block_gui_relaunch()

    script = find_sibling_tool("convert_skate_to_ue.py")
    if script is None:
        raise FileNotFoundError(
            "convert_skate_to_ue.py not found. Keep skate_to_unreal next to the app."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    _log(log, "Converting .skate → Unreal export (in-process)…")
    _log(log, f"  frozen={getattr(sys, 'frozen', False)}  tool={script}")

    mod = _import_tool_module(script, "skate_to_ue_tool")
    if not hasattr(mod, "convert"):
        raise RuntimeError("convert_skate_to_ue.py is missing convert()")

    export_folder = mod.convert(
        Path(skate).resolve(),
        Path(output_dir).resolve(),
        skip_lightmaps=True,
    )
    export_folder = Path(export_folder)
    if (export_folder / "import_to_unreal.py").is_file():
        _log(log, f"Unreal export: {export_folder}")
        return export_folder
    subdirs = [
        p
        for p in output_dir.iterdir()
        if p.is_dir() and (p / "import_to_unreal.py").is_file()
    ]
    if subdirs:
        _log(log, f"Unreal export: {subdirs[0]}")
        return subdirs[0]
    raise FileNotFoundError(f"Unreal export folder not found under {output_dir}")


def copy_to_ue_content(export_folder: Path, content_dir: Path, log: LogFn) -> Path:
    content_dir = content_dir.expanduser().resolve()
    if not content_dir.is_dir():
        raise NotADirectoryError(f"UE Content folder not found: {content_dir}")
    dest = content_dir / export_folder.name
    if dest.exists():
        _log(log, f"Removing previous {dest}")
        shutil.rmtree(dest)
    _log(log, f"Copying export → {dest}")
    shutil.copytree(export_folder, dest)
    return dest
