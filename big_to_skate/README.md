# big → skate converter

Python driver that converts Skate 3 **world map** `.big` archives into **SKATE14** `.skate` files by calling the real pipeline from:

[SK8-ENGINE/skate-3-rust-engine](https://github.com/SK8-ENGINE/skate-3-rust-engine)

It does **not** re-implement the format. It imports and runs:

- `tools/owned_game/big.py` — extract the `.big`
- vendored university preparers — models, textures, rails
- `tools/asset_pipeline/map_writer.py` — write the `.skate`

## Setup

```bash
# 1) Engine checkout (required)
git clone https://github.com/SK8-ENGINE/skate-3-rust-engine.git

# 2) Python deps
pip install -r requirements.txt
# better, if present:
pip install -r skate-3-rust-engine/tools/requirements-setup.txt
```

Ensure `skate-3-rust-engine/tools/vendor/university/` is present (submodules / full clone). Without it, the prepare step fails.

## Usage

```bash
python big_to_skate.py worldDIST_BlackBoxPark.big -o ./skate_out \
  --engine ./skate-3-rust-engine

# Windows
run.bat worldDIST_BlackBoxPark.big -o .\skate_out --engine C:\src\skate-3-rust-engine
```

| Argument | Meaning |
|----------|---------|
| `big` | Input `worldDIST_*.big` |
| `-o` | Output directory for `.skate` + logs |
| `--engine` | Path to skate-3-rust-engine |
| `--game-exe` | Optional `skate3rust.exe` for load check |
| `--skip-validate` | Skip runtime check (default if no `--game-exe`) |
| `--work` | Scratch dir for intermediates |

## Naming

Archives are expected to look like:

```text
worldDIST_University.big   →  University.skate
worldDIST_BlackBoxPark.big →  BlackBoxPark.skate
```

The district stream path inside the archive is:

```text
data/content/world/stream/DIST_<Name>/
```

## Output

```text
skate_out/
  BlackBoxPark.skate
  BlackBoxPark.irradiance          (if the pipeline writes it)
  worldDIST_BlackBoxPark.convert.json
  _work/                           (intermediates + log)
```

## Next step (Unreal)

Feed the `.skate` into the separate tool under `../skate_to_unreal/`:

```bash
python ../skate_to_unreal/convert_skate_to_ue.py skate_out/BlackBoxPark.skate -o ./ue_export
```

## Limitations

- Needs a **legal** copy of the game data (your own `.big` from a disc/ISO you own).
- Full district conversion can take time and RAM (large maps).
- This is not affiliated with EA; it only wraps the open-source engine tools.
