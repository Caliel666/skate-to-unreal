# Skate 3 Map → Unreal (GUI)

One-page app that walks you from an **Xbox 360 Skate 3 ISO** to an **Unreal-ready map folder**.

## Folder layout

Keep these three folders together:

```text
parent/
  skate_map_gui/          ← this app (run.bat)
  big_to_skate/           ← .big → .skate
  skate_to_unreal/        ← .skate → UE export
```

## Run

```bat
cd skate_map_gui
run.bat
```

First launch creates a `.venv` and installs `numpy` / `Pillow`.

## What the app does

| Step | Action |
|------|--------|
| 1 | Downloads the **latest** [extract-xiso](https://github.com/XboxDev/extract-xiso/releases) Win64 build at runtime |
| 2 | Extracts your **Xbox 360** Skate 3 `.iso` |
| 3 | Lists `worldDIST_*.big` maps under `data/content` |
| 4 | Clones [skate-3-rust-engine](https://github.com/SK8-ENGINE/skate-3-rust-engine) into `runtime/` (first convert only) |
| 5 | Converts selected map `.big` → `.skate` |
| 6 | Builds Unreal export (mesh, textures, `import_to_unreal.py`) |
| 7 | Optionally copies the export into your UE `Content` folder |

## After conversion

In Unreal Engine 5.4:

1. Enable **Python Editor Script Plugin**
2. **Tools → Execute Python Script…** (or File → Execute Python Script)
3. Select `import_to_unreal.py` inside the exported map folder

Or Output Log (forward slashes):

```text
py "C:/Users/You/Documents/Unreal Projects/MyGame/Content/BlackBoxPark/import_to_unreal.py"
```

## Requirements

- Windows
- Python 3.10+
- Git (for cloning the engine on first convert)
- Internet (extract-xiso download + git clone)
- Your own Xbox 360 Skate 3 ISO

## Runtime cache

```text
skate_map_gui/runtime/
  tools/extract-xiso/     downloaded extractor
  skate-3-rust-engine/    cloned engine
  extracted/              default ISO extract location
  skate_out/              .skate files
  ue_export/              Unreal export folders
```
