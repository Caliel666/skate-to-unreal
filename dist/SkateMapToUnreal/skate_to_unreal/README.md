# skate → Unreal Engine converter

Converts **SKATE14** `.skate` maps (from [SK8-ENGINE/skate-3-rust-engine](https://github.com/SK8-ENGINE/skate-3-rust-engine)) into assets for **Unreal Engine 5.4.x**.

**Included:** mesh geometry, UV0, normals, albedo + normal textures, material metadata.  
**Excluded (by design):** lightmaps, irradiance, sky/environment light data — light the map inside Unreal.

## Requirements

```bash
pip install numpy pillow
```

Python 3.10+ recommended.

## Usage

```bash
python convert_skate_to_ue.py /path/to/BlackBoxPark.skate -o ./export
```

Optional: also dump lightmap textures (still not assigned to materials):

```bash
python convert_skate_to_ue.py map.skate -o ./export --keep-lightmaps
```

### Output layout

```
export/BlackBoxPark/
  mesh.glb              # static mesh (Y-up metres, one primitive per material)
  textures/*.png        # albedo / normal (lightmaps skipped by default)
  materials.json        # slot → texture mapping
  map_meta.json         # spawn point + notes
  import_to_unreal.py   # UE 5.4 Editor automation (auto materials)
```

## Import into Unreal Engine 5.4.4

**Embedding textures in the glTF is not required.** External PNGs + the import script give correct sRGB / normal-map compression and fully automatic material setup.

1. Copy the map folder under your project’s `Content/` directory, e.g.  
   `Content/BlackBoxPark/` or `Content/SkateMaps/BlackBoxPark/`
2. Enable **Python Editor Script Plugin** (Edit → Plugins). Restart if prompted.
3. Run with **one** of these:

   **A) Recommended** — File → **Execute Python Script** → select `import_to_unreal.py`

   **B) Output Log** — `py` command with **forward slashes** (required on Windows):

   ```text
   py "C:/Users/You/Documents/Unreal Projects/MyProject/Content/BlackBoxPark/import_to_unreal.py"
   ```

   Avoid these (they fail on UE 5.4 / Windows):

   ```text
   exec(open(r"C:\Users\...").read())     ← deprecated
   python "C:\Users\..."                  ← \U in \Users is a unicode escape error
   ```

### What the script does automatically

| Step | Result |
|------|--------|
| Master material | Creates `/Game/SkateMaps/_Shared/M_Skate_Master` once (params: `BaseColor`, `Normal`, `Roughness`, `UseNormal`, `Opacity`) |
| Textures | Imports PNGs; albedo = sRGB, normals = `TC_Normalmap` (linear) |
| Materials | One `MaterialInstanceConstant` per material with textures assigned |
| Mesh | Imports `mesh.glb` and assigns material instances to slots in order |

No manual drag-and-drop of textures onto materials is required.

## Coordinates & scale

| Source (`.skate`) | Unreal (typical after glTF import) |
|-------------------|--------------------------------------|
| Y-up, metres      | Z-up, centimetres                    |

Most Unreal glTF/Interchange importers convert Y-up → Z-up and scale ×100. After import, confirm map size, floor orientation, and optionally use the spawn from `map_meta.json`.

## Format notes

- Header magic: `SKATE14`
- Vertex stride 56 bytes: position, normal, UV0, lightmap UV, material id, decal UV, packed tangent frame
- Textures are RGBA8, optionally zlib-stored inside the package
- Material texture ids are **1-based** indexes into the texture table
- Collision (`RWCM`) and grind rails are not exported (mesh is visual geometry only)

## Tested with

- `BlackBoxPark.skate` (~10 MB) — 15 670 verts, 12 978 tris, 132 materials, 78 textures → 67 non-lightmap PNGs exported
