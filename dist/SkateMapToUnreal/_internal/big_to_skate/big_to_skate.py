#!/usr/bin/env python3
"""
Convert a Skate 3 world map archive (.big) into a SKATE14 (.skate) package.

This is a thin driver around the public SK8-ENGINE pipeline:

  https://github.com/SK8-ENGINE/skate-3-rust-engine

It reuses that repo's:
  - tools/owned_game/big.py          (EA .big reader)
  - tools/asset_pipeline/map_writer.py
  - tools/asset_pipeline/install.convert_map
  - vendored university extractors under tools/vendor/

Requirements
------------
  • Python 3.10+
  • A local checkout of skate-3-rust-engine (see --engine)
  • Dependencies used by that pipeline (numpy, Pillow, …).
    Install with:
      pip install -r <engine>/tools/requirements-setup.txt
    or at least:  pip install numpy Pillow

  • The input must be a district archive named like:
      worldDIST_University.big
      worldDIST_BlackBoxPark.big
    (stem after "world" becomes the district id, e.g. DIST_University)

  • Optional: path to skate3rust.exe for post-conversion load check
    (--game-exe). Without it, validation is skipped.

Usage
-----
  python big_to_skate.py worldDIST_BlackBoxPark.big -o ./out \\
      --engine /path/to/skate-3-rust-engine

  python big_to_skate.py map.big -o ./out --engine ./skate-3-rust-engine \\
      --game-exe /path/to/skate3rust.exe

Notes
-----
  Conversion needs the engine's vendored map tools under
  tools/vendor/university/. If those are missing from your checkout
  (LFS / incomplete clone), the prepare step will fail with a clear error.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _die(msg: str, code: int = 1) -> None:
    print(f"[big_to_skate] error: {msg}", file=sys.stderr)
    raise SystemExit(code)


ENGINE_REPO = "https://github.com/SK8-ENGINE/skate-3-rust-engine.git"


def _looks_like_engine(root: Path) -> bool:
    return (root / "tools" / "asset_pipeline" / "install.py").is_file()


def resolve_engine(engine: Path | None, *, auto_clone: bool = True) -> Path:
    if engine is not None:
        root = engine.expanduser().resolve()
        if not root.is_dir():
            _die(f"--engine is not a directory: {root}")
        if not _looks_like_engine(root):
            _die(
                f"--engine does not look like skate-3-rust-engine "
                f"(missing tools/asset_pipeline/install.py):\n  {root}"
            )
        return root

    here = Path(__file__).resolve().parent
    search_bases = [
        here,
        Path.cwd(),
        *list(here.parents)[:4],
        *list(Path.cwd().parents)[:4],
    ]
    for base in search_bases:
        for cand in (base, base / "skate-3-rust-engine"):
            try:
                if _looks_like_engine(cand):
                    print(f"[big_to_skate] using engine: {cand.resolve()}")
                    return cand.resolve()
            except OSError:
                continue

    dest = here / "skate-3-rust-engine"
    if _looks_like_engine(dest):
        return dest.resolve()

    if not auto_clone:
        _die(
            "Could not find skate-3-rust-engine.\n"
            "  Pass --engine C:\\path\\to\\skate-3-rust-engine\n"
            f"  Or: git clone {ENGINE_REPO}"
        )

    print(f"[big_to_skate] engine not found — cloning into:\n  {dest}")
    print(f"[big_to_skate] {ENGINE_REPO}")
    import subprocess

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", ENGINE_REPO, str(dest)],
            check=True,
        )
    except FileNotFoundError:
        _die(
            "git is not installed or not on PATH.\n"
            f"  Install Git, or clone manually:\n    git clone {ENGINE_REPO}\n"
            "  then:  --engine path\\to\\skate-3-rust-engine"
        )
    except subprocess.CalledProcessError as e:
        _die(f"git clone failed: {e}")

    if not _looks_like_engine(dest):
        _die(f"Clone finished but install.py is missing under {dest}")
    print(f"[big_to_skate] using engine: {dest.resolve()}")
    return dest.resolve()


def ensure_engine_on_path(engine: Path) -> None:
    # Repo root must be importable as the parent of `tools`
    root = str(engine)
    if root not in sys.path:
        sys.path.insert(0, root)

    # Vendored university tools (prepare_hawaiian_dream, collision, …)
    uni = engine / "tools" / "vendor" / "university" / "tools"
    vanilla = uni / "vanilla_map_extraction" / "tools"
    for p in (uni, vanilla, uni / "vanilla_map_extraction" / "blender"):
        if p.is_dir() and str(p) not in sys.path:
            sys.path.insert(0, str(p))


def check_prereqs(engine: Path, archive: Path) -> None:
    if not archive.is_file():
        _die(f"Input not found: {archive}")
    if archive.suffix.lower() != ".big":
        print(f"[big_to_skate] warning: expected a .big file, got {archive.suffix!r}")

    install = engine / "tools" / "asset_pipeline" / "install.py"
    writer = engine / "tools" / "asset_pipeline" / "map_writer.py"
    big = engine / "tools" / "owned_game" / "big.py"
    for p in (install, writer, big):
        if not p.is_file():
            _die(f"Engine checkout looks incomplete (missing {p})")

    # Soft-check vendor tree (hard failure happens inside prepare if absent)
    stream_tools = (
        engine
        / "tools"
        / "vendor"
        / "university"
        / "tools"
        / "vanilla_map_extraction"
        / "tools"
    )
    if not stream_tools.is_dir():
        print(
            "[big_to_skate] warning: vendored university tools not found at\n"
            f"  {stream_tools}\n"
            "  prepare_hawaiian_dream / collision extractors may fail.\n"
            "  Ensure the engine repo clone includes tools/vendor/ "
            "(submodules / LFS if applicable)."
        )


def convert_one(
    archive: Path,
    output_dir: Path,
    engine: Path,
    game_exe: Path | None,
    work_root: Path | None,
    skip_validate: bool,
) -> Path:
    ensure_engine_on_path(engine)
    check_prereqs(engine, archive)

    from tools.asset_pipeline.install import convert_map

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    work = (work_root or (output_dir / "_work")).expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    maps_dir = output_dir  # final .skate lands here
    stage = work / "stage"
    stage.mkdir(parents=True, exist_ok=True)
    # convert_map writes props under stage/assets/private/…
    (stage / "assets" / "private" / "native-props").mkdir(parents=True, exist_ok=True)

    # Dummy game exe when validation is skipped: convert_map always calls run().
    # We patch a no-op by pointing at a script that exits 0, or skip via monkeypatch.
    log_path = work / f"{archive.stem}-convert.log"

    def report(msg: str) -> None:
        print(f"[big_to_skate] {msg}", flush=True)

    # Validation uses the game binary; optional.
    if game_exe is None or skip_validate:
        # Monkey-patch install.run so missing game_exe does not fail the job.
        import tools.asset_pipeline.install as install_mod

        def _noop_run(args, log, report_fn):
            report("skipping runtime validation (no --game-exe / --skip-validate)")
            log.write("validation skipped by big_to_skate.py\n")

        install_mod.run = _noop_run  # type: ignore[assignment]
        game_exe = Path(sys.executable)  # placeholder, never invoked
    else:
        game_exe = game_exe.expanduser().resolve()
        if not game_exe.is_file():
            _die(f"--game-exe not found: {game_exe}")

    report(f"engine : {engine}")
    report(f"input  : {archive}")
    report(f"output : {output_dir}")
    report(f"work   : {work}")

    t0 = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log:
        try:
            entry = convert_map(
                archive.resolve(),
                work / "conversion",
                maps_dir,
                stage,
                game_exe,
                log,
                report,
            )
        except ModuleNotFoundError as e:
            _die(
                f"Missing Python module or vendor tool: {e}\n"
                "  Install engine setup deps:\n"
                f"    pip install -r {engine / 'tools' / 'requirements-setup.txt'}\n"
                "  And ensure tools/vendor/university is present in the engine repo."
            )
        except Exception as e:
            log.write(f"\nFATAL: {e!r}\n")
            _die(f"Conversion failed: {e}\n  See log: {log_path}")

    elapsed = time.perf_counter() - t0
    skate_name = entry.get("path") or entry.get("name", "")
    # entry['path'] is like 'maps/BlackBoxPark.skate' relative to stage; we wrote maps_dir=output
    candidates = list(output_dir.glob("*.skate"))
    label = archive.stem.removeprefix("world").removeprefix("DIST_")
    preferred = output_dir / f"{label}.skate"
    if not preferred.is_file():
        # convert_map uses label from district after stripping DIST_
        district = archive.stem.removeprefix("world")
        label2 = district.removeprefix("DIST_")
        preferred = output_dir / f"{label2}.skate"

    result = preferred if preferred.is_file() else (candidates[0] if candidates else None)
    meta = {
        "input": str(archive),
        "engine": str(engine),
        "entry": entry,
        "seconds": round(elapsed, 3),
        "log": str(log_path),
        "skate": str(result) if result else None,
    }
    (output_dir / f"{archive.stem}.convert.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )

    if result is None:
        _die(f"No .skate written under {output_dir}. Check log: {log_path}")

    report(f"done in {elapsed:.1f}s → {result}")
    report(f"log: {log_path}")
    return result


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Convert Skate 3 worldDIST_*.big maps to SKATE14 .skate "
        "(via SK8-ENGINE/skate-3-rust-engine).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "big",
        type=Path,
        help="Input map archive (e.g. worldDIST_BlackBoxPark.big)",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("./skate_out"),
        help="Directory for the .skate and logs (default: ./skate_out)",
    )
    ap.add_argument(
        "--engine",
        type=Path,
        default=None,
        help="Path to skate-3-rust-engine checkout "
        "(default: search nearby / ./skate-3-rust-engine)",
    )
    ap.add_argument(
        "--game-exe",
        type=Path,
        default=None,
        help="Optional skate3rust.exe for post-convert load check",
    )
    ap.add_argument(
        "--skip-validate",
        action="store_true",
        help="Do not run the game binary load check",
    )
    ap.add_argument(
        "--work",
        type=Path,
        default=None,
        help="Scratch directory for intermediates (default: <output>/_work)",
    )
    args = ap.parse_args(argv)

    engine = resolve_engine(args.engine)
    convert_one(
        archive=args.big,
        output_dir=args.output,
        engine=engine,
        game_exe=args.game_exe,
        work_root=args.work,
        skip_validate=args.skip_validate or args.game_exe is None,
    )


if __name__ == "__main__":
    main()
