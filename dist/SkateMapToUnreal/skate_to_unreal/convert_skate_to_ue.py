#!/usr/bin/env python3
"""Convert SKATE14 (.skate) maps to Unreal-friendly assets.

Exports:
  <out>/<map_name>/
    mesh.glb                 – geometry + UV0 + normals (Y-up metres)
    textures/*.png           – albedo / normal maps (lightmaps skipped)
    materials.json           – material → texture slot mapping
    import_to_unreal.py      – UE Editor Python script to import & build materials

Light / irradiance / lightmap data is intentionally not converted so you can
light the map inside Unreal.

Usage:
  python convert_skate_to_ue.py BlackBoxPark.skate -o ./export
  python convert_skate_to_ue.py BlackBoxPark.skate -o ./export --split-by-material
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from skate_reader import Material, SkateMap, Texture, read_skate


def safe_name(s: str) -> str:
    s = re.sub(r"[^\w\-.]+", "_", s.strip())
    return s[:120] or "unnamed"


def is_lightmap_texture(tex: Texture, materials: list[Material]) -> bool:
    """Heuristic: only used as lightmap role / lightmap_id and never as albedo/normal."""
    idx = None
    return False  # decided per-material below


def texture_usage(m: SkateMap) -> dict[int, set[str]]:
    """texture_id (1-based) -> set of roles used."""
    usage: dict[int, set[str]] = {}
    for mat in m.materials:
        for role, tid in (
            ("albedo", mat.albedo_id),
            ("lightmap", mat.lightmap_id),
            ("normal", mat.normal_id),
        ):
            if tid:
                usage.setdefault(tid, set()).add(role)
        for r in mat.roles:
            if r.texture_id:
                usage.setdefault(r.texture_id, set()).add(r.role)
    return usage


def export_textures(m: SkateMap, tex_dir: Path, skip_lightmaps: bool = True) -> dict[int, str]:
    """Write PNGs. Returns 1-based texture id -> relative path (or empty if skipped)."""
    tex_dir.mkdir(parents=True, exist_ok=True)
    usage = texture_usage(m)
    id_to_rel: dict[int, str] = {}

    for i, tex in enumerate(m.textures, start=1):
        roles = usage.get(i, set())
        # Skip pure lightmap-only textures when requested
        if skip_lightmaps and roles and roles <= {"lightmap", "chromaticity"}:
            continue
        # Cube faces: export first face only as 2D
        w, h = tex.width, tex.height
        rgba = tex.rgba
        face_bytes = w * h * 4
        if tex.faces > 1 and len(rgba) >= face_bytes:
            rgba = rgba[:face_bytes]
        if len(rgba) < face_bytes:
            print(f"  warn: texture {tex.name} truncated ({len(rgba)} < {face_bytes})", file=sys.stderr)
            continue
        arr = np.frombuffer(rgba[:face_bytes], dtype=np.uint8).reshape(h, w, 4)
        # Package stores top-down for non-cubes already flipped in writer for OpenGL-style;
        # PIL expects top-down — keep as-is.
        name = safe_name(tex.name) + ".png"
        path = tex_dir / name
        Image.fromarray(arr, "RGBA").save(path)
        id_to_rel[i] = f"textures/{name}"
    return id_to_rel


def build_materials_json(m: SkateMap, id_to_rel: dict[int, str]) -> list[dict]:
    out = []
    for i, mat in enumerate(m.materials):
        entry = {
            "index": i + 1,  # matches vertex material_ids
            "name": mat.name,
            "shader": mat.shader_name,
            "alpha_mode": {0: "opaque", 1: "mask", 2: "blend"}.get(mat.alpha_mode, "opaque"),
            "alpha_cutoff": mat.alpha_cutoff,
            "base_color": list(mat.base_color),
            "roughness": mat.roughness,
            "albedo": id_to_rel.get(mat.albedo_id),
            "normal": id_to_rel.get(mat.normal_id),
            # lightmap intentionally omitted
        }
        # Prefer role-based albedo/normal if present
        for r in mat.roles:
            if r.role in ("albedo", "diffuse", "color") and r.texture_id in id_to_rel:
                entry["albedo"] = id_to_rel[r.texture_id]
            if r.role == "normal" and r.texture_id in id_to_rel:
                entry["normal"] = id_to_rel[r.texture_id]
        out.append(entry)
    return out


def _glb_from_parts(
    positions: np.ndarray,
    normals: np.ndarray,
    uvs: np.ndarray,
    indices: np.ndarray,
    material_slots: list[dict],
    primitives: list[tuple[int, int, int]],  # (index_byte_offset, index_count, material_index)
) -> bytes:
    """Minimal glTF 2.0 binary (GLB) writer, one mesh, multiple primitives by material."""
    # Buffers: POSITION, NORMAL, TEXCOORD_0, INDICES
    pos = np.ascontiguousarray(positions, dtype=np.float32)
    nor = np.ascontiguousarray(normals, dtype=np.float32)
    uv = np.ascontiguousarray(uvs, dtype=np.float32)
    idx = np.ascontiguousarray(indices, dtype=np.uint32)

    blobs = [pos.tobytes(), nor.tobytes(), uv.tobytes(), idx.tobytes()]
    # Align each to 4 bytes
    aligned = []
    offsets = []
    cursor = 0
    for b in blobs:
        pad = (4 - (len(b) % 4)) % 4
        offsets.append(cursor)
        aligned.append(b + b"\x00" * pad)
        cursor += len(b) + pad
    bin_blob = b"".join(aligned)

    accessors = [
        {
            "bufferView": 0,
            "componentType": 5126,
            "count": len(pos),
            "type": "VEC3",
            "max": pos.max(axis=0).tolist(),
            "min": pos.min(axis=0).tolist(),
        },
        {
            "bufferView": 1,
            "componentType": 5126,
            "count": len(nor),
            "type": "VEC3",
        },
        {
            "bufferView": 2,
            "componentType": 5126,
            "count": len(uv),
            "type": "VEC2",
        },
        {
            "bufferView": 3,
            "componentType": 5125,
            "count": len(idx),
            "type": "SCALAR",
        },
    ]
    buffer_views = [
        {"buffer": 0, "byteOffset": offsets[0], "byteLength": len(pos.tobytes()), "target": 34962},
        {"buffer": 0, "byteOffset": offsets[1], "byteLength": len(nor.tobytes()), "target": 34962},
        {"buffer": 0, "byteOffset": offsets[2], "byteLength": len(uv.tobytes()), "target": 34962},
        {"buffer": 0, "byteOffset": offsets[3], "byteLength": len(idx.tobytes()), "target": 34963},
    ]

    prims = []
    for index_byte_offset, index_count, mat_i in primitives:
        # index accessor per primitive
        acc_i = len(accessors)
        accessors.append(
            {
                "bufferView": 3,
                "byteOffset": index_byte_offset,
                "componentType": 5125,
                "count": index_count,
                "type": "SCALAR",
            }
        )
        prims.append(
            {
                "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                "indices": acc_i,
                "material": mat_i,
                "mode": 4,
            }
        )

    materials_gltf = []
    for slot in material_slots:
        mat = {
            "name": slot["name"],
            "pbrMetallicRoughness": {
                "baseColorFactor": slot.get("base_color", [0.8, 0.8, 0.8]) + [1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": float(slot.get("roughness", 0.8)),
            },
            "doubleSided": True,
        }
        am = slot.get("alpha_mode", "opaque")
        if am == "mask":
            mat["alphaMode"] = "MASK"
            mat["alphaCutoff"] = float(slot.get("alpha_cutoff", 0.5))
        elif am == "blend":
            mat["alphaMode"] = "BLEND"
        materials_gltf.append(mat)

    gltf = {
        "asset": {"version": "2.0", "generator": "skate_to_ue"},
        "buffers": [{"byteLength": len(bin_blob)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "materials": materials_gltf,
        "meshes": [{"name": "SkateMap", "primitives": prims}],
        "nodes": [{"name": "SkateMapRoot", "mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    # Note: textures are external; UE import script wires them. Embedding would
    # require image buffers + samplers; external PNGs are clearer for UE.

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_pad = (4 - (len(json_bytes) % 4)) % 4
    json_bytes += b" " * json_pad

    total = 12 + 8 + len(json_bytes) + 8 + len(bin_blob)
    header = struct.pack("<4sII", b"glTF", 2, total)
    json_chunk = struct.pack("<I4s", len(json_bytes), b"JSON") + json_bytes
    bin_chunk = struct.pack("<I4s", len(bin_blob), b"BIN\x00") + bin_blob
    return header + json_chunk + bin_chunk


def split_by_material(m: SkateMap) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[tuple[int, int, int]], list[dict]]:
    """Rebuild index buffer grouped by material id; one glTF material per used mat."""
    faces = m.indices.reshape(-1, 3)
    # material of a face = material of first vertex (writer assigns same mat per mesh island)
    face_mat = m.material_ids[faces[:, 0]]
    used = sorted(set(int(x) for x in face_mat if x > 0))
    mat_to_slot = {mid: i for i, mid in enumerate(used)}

    new_indices = []
    primitives = []
    cursor = 0
    for mid in used:
        mask = face_mat == mid
        part = faces[mask].reshape(-1)
        byte_off = cursor * 4
        count = len(part)
        new_indices.append(part)
        primitives.append((byte_off, count, mat_to_slot[mid]))
        cursor += count

    if not new_indices:
        # fallback single primitive
        idx = m.indices.copy()
        slots = [{"name": "Default", "base_color": [0.8, 0.8, 0.8], "roughness": 0.8, "alpha_mode": "opaque"}]
        return m.positions, m.normals, m.uvs, idx, [(0, len(idx), 0)], slots

    idx = np.concatenate(new_indices).astype(np.uint32)
    slots = []
    for mid in used:
        mat = m.materials[mid - 1]
        slots.append(
            {
                "name": safe_name(mat.name) or f"Mat_{mid}",
                "base_color": list(mat.base_color),
                "roughness": mat.roughness,
                "alpha_mode": {0: "opaque", 1: "mask", 2: "blend"}.get(mat.alpha_mode, "opaque"),
                "alpha_cutoff": mat.alpha_cutoff,
                "source_index": mid,
            }
        )
    return m.positions, m.normals, m.uvs, idx, primitives, slots


def write_ue_import_script(out_dir: Path, map_name: str, materials: list[dict]) -> None:
    """Generate a UE 5.4-compatible Editor Python importer.

    Creates a master material (BaseColor + Normal + Roughness), imports textures
    with correct sRGB/normal settings, builds Material Instance Constants, imports
    the glTF mesh, and assigns materials to slots automatically.
    """
    script = out_dir / "import_to_unreal.py"
    # Embed as a Python literal — JSON null/true/false are not valid Python names.
    mats_json = json.dumps(materials, indent=2)
    mats_json = (
        mats_json.replace(": null", ": None")
        .replace(": true", ": True")
        .replace(": false", ": False")
    )
    content = f'''# -*- coding: utf-8 -*-
"""
Unreal Engine 5.4.x — automatic .skate map importer

What this does (no manual material wiring):
  1. Creates master material  /Game/SkateMaps/_Shared/M_Skate_Master
       parameters: BaseColor (texture), Normal (texture), Roughness (scalar),
                   UseNormal (static switch), Opacity (scalar for translucent)
  2. Imports every PNG under textures/ as Texture2D (sRGB for albedo, TC_Normalmap for normals)
  3. Creates one MaterialInstanceConstant per material and assigns textures
  4. Imports mesh.glb and assigns material instances to mesh slots in order

Setup:
  1. Edit → Plugins → enable "Python Editor Script Plugin" (restart if needed)
  2. Copy this whole folder under Content/, e.g.
       <Project>/Content/BlackBoxPark/
       or <Project>/Content/SkateMaps/BlackBoxPark/
  3. Run the script with ONE of these (do NOT use exec(open(...)) — deprecated):

       A) File → Execute Python Script → pick import_to_unreal.py

       B) Output Log — use FORWARD SLASHES only (Windows backslashes break the path):
            py "C:/Users/You/Documents/Unreal Projects/MyProject/Content/BlackBoxPark/import_to_unreal.py"

Tested target: Unreal Engine 5.4.4
Lightmaps / irradiance are intentionally not used — light the map in UE.
"""
from __future__ import annotations

import unreal
from pathlib import Path

MAP_NAME = {map_name!r}
MATERIALS = {mats_json}
DEST = f"/Game/SkateMaps/{{MAP_NAME}}"
SHARED = "/Game/SkateMaps/_Shared"
MASTER_PATH = f"{{SHARED}}/M_Skate_Master"

# Optional override if auto-discovery fails (FORWARD SLASHES on Windows):
# SOURCE_DIR = "C:/Users/You/Documents/Unreal Projects/MyProject/Content/BlackBoxPark"
SOURCE_DIR = None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ensure_dir(package_path: str) -> None:
    if not unreal.EditorAssetLibrary.does_directory_exist(package_path):
        unreal.EditorAssetLibrary.make_directory(package_path)


def _find_source_folder() -> Path:
    """Locate folder that contains mesh.glb + textures/.

    Works with:
      - File → Execute Python Script
      - Console:  py "C:/full/path/import_to_unreal.py"
    Avoid exec(open(...).read()) — deprecated in UE 5.4 and leaves __file__ unset.
    """
    candidates = []
    if SOURCE_DIR:
        candidates.append(Path(SOURCE_DIR))
    try:
        candidates.append(Path(__file__).resolve().parent)
    except NameError:
        pass
    content = Path(unreal.Paths.project_content_dir())
    candidates.append(content / "SkateMaps" / MAP_NAME)
    candidates.append(content / MAP_NAME)
    candidates.append(content / "SkateMaps" / MAP_NAME / MAP_NAME)
    candidates.append(content / MAP_NAME / MAP_NAME)

    tried = []
    for c in candidates:
        try:
            p = c.resolve()
        except Exception:
            p = c
        tried.append(str(p))
        if (p / "mesh.glb").is_file():
            unreal.log(f"[skate] Source folder: {{p}}")
            return p

    raise FileNotFoundError(
        "mesh.glb not found. Tried:\\n  - "
        + "\\n  - ".join(tried)
        + "\\nSet SOURCE_DIR at the top of this script "
        "(forward slashes, e.g. C:/Users/.../Content/BlackBoxPark)."
    )


def _import_file(src: Path, dest_path: str):
    """Import a single file; return first imported object path or None."""
    task = unreal.AssetImportTask()
    task.filename = str(src)
    task.destination_path = dest_path
    task.automated = True
    task.replace_existing = True
    task.save = True
    # Prefer Interchange for glTF on UE5.4 when available; AssetImportTask still works.
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    paths = list(task.imported_object_paths) if task.imported_object_paths else []
    return paths[0] if paths else None


def _save(asset) -> None:
    if asset:
        unreal.EditorAssetLibrary.save_loaded_asset(asset)


# ---------------------------------------------------------------------------
# 1) Master material (created once, shared across maps)
# ---------------------------------------------------------------------------

def ensure_master_material():
    """Build M_Skate_Master with BaseColor, Normal, Roughness, UseNormal, Opacity.

    Always rebuilds so sampler-type / default-texture fixes apply after updates.
    """
    _ensure_dir(SHARED)
    if unreal.EditorAssetLibrary.does_asset_exist(MASTER_PATH):
        unreal.EditorAssetLibrary.delete_asset(MASTER_PATH)
        unreal.log(f"[skate] Removed old master material {{MASTER_PATH}}")

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.MaterialFactoryNew()
    mat = asset_tools.create_asset("M_Skate_Master", SHARED, unreal.Material, factory)
    if mat is None:
        raise RuntimeError("Failed to create master material")

    MEL = unreal.MaterialEditingLibrary

    # Engine defaults with matching sampler types (avoids SM6 "should be Color/Normal" errors)
    default_color = unreal.load_asset("/Engine/EngineResources/DefaultTexture")
    default_normal = unreal.load_asset("/Engine/EngineMaterials/DefaultNormal")
    if default_normal is None:
        default_normal = unreal.load_asset("/Engine/EngineResources/DefaultTexture_N")

    tex_base = MEL.create_material_expression(
        mat, unreal.MaterialExpressionTextureSampleParameter2D, -600, -200
    )
    tex_base.set_editor_property("parameter_name", "BaseColor")
    tex_base.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
    if default_color:
        tex_base.set_editor_property("texture", default_color)

    tex_norm = MEL.create_material_expression(
        mat, unreal.MaterialExpressionTextureSampleParameter2D, -600, 200
    )
    tex_norm.set_editor_property("parameter_name", "Normal")
    tex_norm.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    if default_normal:
        tex_norm.set_editor_property("texture", default_normal)

    rough = MEL.create_material_expression(
        mat, unreal.MaterialExpressionScalarParameter, -400, 50
    )
    rough.set_editor_property("parameter_name", "Roughness")
    rough.set_editor_property("default_value", 0.75)

    opacity = MEL.create_material_expression(
        mat, unreal.MaterialExpressionScalarParameter, -400, 350
    )
    opacity.set_editor_property("parameter_name", "Opacity")
    opacity.set_editor_property("default_value", 1.0)

    # Default OFF so instances without a normal map do not sample a bad default
    use_n = MEL.create_material_expression(
        mat, unreal.MaterialExpressionStaticSwitchParameter, -350, 200
    )
    use_n.set_editor_property("parameter_name", "UseNormal")
    use_n.set_editor_property("default_value", False)

    flat_n = MEL.create_material_expression(
        mat, unreal.MaterialExpressionConstant3Vector, -600, 450
    )
    flat_n.set_editor_property("constant", unreal.LinearColor(0.0, 0.0, 1.0, 0.0))

    MEL.connect_material_expressions(tex_norm, "RGB", use_n, "True")
    MEL.connect_material_expressions(flat_n, "", use_n, "False")

    MEL.connect_material_property(tex_base, "RGB", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(use_n, "", unreal.MaterialProperty.MP_NORMAL)
    MEL.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.connect_material_property(opacity, "", unreal.MaterialProperty.MP_OPACITY)

    metal = MEL.create_material_expression(
        mat, unreal.MaterialExpressionConstant, -200, 100
    )
    metal.set_editor_property("r", 0.0)
    MEL.connect_material_property(metal, "", unreal.MaterialProperty.MP_METALLIC)

    mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_OPAQUE)
    mat.set_editor_property("two_sided", True)
    MEL.layout_material_expressions(mat)
    MEL.recompile_material(mat)
    _save(mat)
    unreal.log(f"[skate] Created master material {{MASTER_PATH}}")
    return mat


def _resolve_texture(tex_map: dict, rel_or_name):
    """Look up an imported texture by relative path or by filename stem."""
    if not rel_or_name:
        return None
    if rel_or_name in tex_map:
        return unreal.load_asset(tex_map[rel_or_name])
    stem = Path(rel_or_name).stem
    if stem in tex_map:
        return unreal.load_asset(tex_map[stem])
    # Last resort: asset already under DEST/Textures
    guess = f"{{DEST}}/Textures/{{stem}}"
    if unreal.EditorAssetLibrary.does_asset_exist(guess):
        return unreal.load_asset(guess)
    return None


# ---------------------------------------------------------------------------
# 2) Textures
# ---------------------------------------------------------------------------

def import_textures(src: Path, materials: list) -> dict:
    """Import PNGs; return maps keyed by relative path AND by stem for lookup."""
    _ensure_dir(f"{{DEST}}/Textures")
    needed = set()
    for e in materials:
        if e.get("albedo"):
            needed.add(e["albedo"])
        if e.get("normal"):
            needed.add(e["normal"])

    normal_set = {{e["normal"] for e in materials if e.get("normal")}}
    tex_map = {{}}
    tex_dir = src / "textures"
    if not tex_dir.is_dir():
        unreal.log_warning(f"[skate] No textures folder at {{tex_dir}}")
        return tex_map

    pngs = sorted(tex_dir.glob("*.png"))
    unreal.log(f"[skate] Found {{len(pngs)}} PNGs under {{tex_dir}}")

    for png in pngs:
        rel = f"textures/{{png.name}}"
        if needed and rel not in needed:
            continue

        dest_folder = f"{{DEST}}/Textures"
        path = _import_file(png, dest_folder)
        if not path:
            path = f"{{dest_folder}}/{{png.stem}}"
            if not unreal.EditorAssetLibrary.does_asset_exist(path):
                # Interchange sometimes nests or renames — search the folder
                found = None
                for a in unreal.EditorAssetLibrary.list_assets(dest_folder, recursive=True):
                    if a.rsplit("/", 1)[-1] == png.stem or a.endswith("/" + png.stem):
                        found = a
                        break
                if found:
                    path = found
                else:
                    unreal.log_warning(f"[skate] Failed to import {{png.name}}")
                    continue

        tex_map[rel] = path
        tex_map[png.stem] = path  # also key by stem for robust lookup

        tex = unreal.load_asset(path)
        if not isinstance(tex, unreal.Texture2D):
            unreal.log_warning(f"[skate] Not a Texture2D: {{path}}")
            continue

        if rel in normal_set:
            tex.set_editor_property("srgb", False)
            try:
                tex.set_editor_property(
                    "compression_settings",
                    unreal.TextureCompressionSettings.TC_NORMALMAP,
                )
            except Exception:
                pass
            try:
                tex.set_editor_property(
                    "lod_group",
                    unreal.TextureGroup.TEXTUREGROUP_WORLDNORMALMAP,
                )
            except Exception:
                pass
        else:
            tex.set_editor_property("srgb", True)
        _save(tex)
        unreal.log(f"[skate] texture {{png.name}} -> {{path}}")

    unreal.log(f"[skate] Imported {{len(pngs) and len(set(tex_map.values()))}} unique textures")
    return tex_map


# ---------------------------------------------------------------------------
# 3) Material instances
# ---------------------------------------------------------------------------

def create_material_instances(master, tex_map: dict, materials: list) -> dict:
    """index -> MaterialInstanceConstant path."""
    _ensure_dir(f"{{DEST}}/Materials")
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    MEL = unreal.MaterialEditingLibrary
    result = {{}}
    assigned_albedo = 0
    assigned_normal = 0

    for entry in materials:
        name = entry["name"]
        # Keep asset names filesystem-safe
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:100]
        asset_name = f"MI_{{safe}}"
        package = f"{{DEST}}/Materials"
        full = f"{{package}}/{{asset_name}}"

        if unreal.EditorAssetLibrary.does_asset_exist(full):
            mat = unreal.load_asset(full)
        else:
            factory = unreal.MaterialInstanceConstantFactoryNew()
            mat = asset_tools.create_asset(
                asset_name, package, unreal.MaterialInstanceConstant, factory
            )
        if mat is None:
            unreal.log_warning(f"[skate] Could not create {{asset_name}}")
            continue

        mat.set_editor_property("parent", master)

        albedo_tex = _resolve_texture(tex_map, entry.get("albedo"))
        normal_tex = _resolve_texture(tex_map, entry.get("normal"))

        if albedo_tex:
            MEL.set_material_instance_texture_parameter_value(mat, "BaseColor", albedo_tex)
            assigned_albedo += 1
        else:
            if entry.get("albedo"):
                unreal.log_warning(
                    f"[skate] Missing albedo for {{asset_name}}: {{entry.get('albedo')}}"
                )

        if normal_tex:
            MEL.set_material_instance_texture_parameter_value(mat, "Normal", normal_tex)
            MEL.set_material_instance_static_switch_parameter_value(mat, "UseNormal", True)
            assigned_normal += 1
        else:
            MEL.set_material_instance_static_switch_parameter_value(mat, "UseNormal", False)

        MEL.set_material_instance_scalar_parameter_value(
            mat, "Roughness", float(entry.get("roughness", 0.75))
        )
        if entry.get("alpha_mode") == "blend":
            MEL.set_material_instance_scalar_parameter_value(mat, "Opacity", 0.85)

        _save(mat)
        result[entry["index"]] = mat.get_path_name()

    unreal.log(
        f"[skate] Materials: {{len(result)}}  "
        f"albedo assigned: {{assigned_albedo}}  normal assigned: {{assigned_normal}}"
    )
    return result


# ---------------------------------------------------------------------------
# 4) Mesh + slot assignment
# ---------------------------------------------------------------------------

def import_mesh_and_assign(src: Path, mat_assets: dict, materials: list):
    _ensure_dir(f"{{DEST}}/Meshes")
    glb = src / "mesh.glb"
    if not glb.is_file():
        unreal.log_error("[skate] mesh.glb missing")
        return None

    mesh_path = _import_file(glb, f"{{DEST}}/Meshes")
    if not mesh_path:
        # try common name
        for cand in (f"{{DEST}}/Meshes/mesh", f"{{DEST}}/Meshes/SkateMap", f"{{DEST}}/Meshes/{{MAP_NAME}}"):
            if unreal.EditorAssetLibrary.does_asset_exist(cand):
                mesh_path = cand
                break
    if not mesh_path:
        unreal.log_error("[skate] glTF import produced no mesh path")
        return None

    mesh = unreal.load_asset(mesh_path)
    if not isinstance(mesh, unreal.StaticMesh):
        # Interchange sometimes nests; search for StaticMesh in the package
        assets = unreal.EditorAssetLibrary.list_assets(f"{{DEST}}/Meshes", recursive=True)
        for a in assets:
            obj = unreal.load_asset(a)
            if isinstance(obj, unreal.StaticMesh):
                mesh = obj
                mesh_path = a
                break
    if not isinstance(mesh, unreal.StaticMesh):
        unreal.log_error(f"[skate] No StaticMesh at {{mesh_path}}")
        return None

    # Slot order matches glTF primitive / MATERIALS order
    ordered_paths = [mat_assets[e["index"]] for e in materials if e["index"] in mat_assets]
    if not ordered_paths:
        unreal.log_warning("[skate] No materials to assign")
        return mesh

    new_mats = []
    for i, p in enumerate(ordered_paths):
        mi = unreal.StaticMaterial()
        iface = unreal.load_asset(p)
        mi.set_editor_property("material_interface", iface)
        mi.set_editor_property("material_slot_name", f"slot_{{i}}_{{Path(p).name}}")
        new_mats.append(mi)

    try:
        mesh.set_editor_property("static_materials", new_mats)
    except Exception as e:
        unreal.log_warning(f"[skate] static_materials set failed ({{e}}); trying per-slot API")
        try:
            for i, p in enumerate(ordered_paths):
                iface = unreal.load_asset(p)
                unreal.StaticMeshEditorSubsystem().set_material(mesh, i, iface)
        except Exception as e2:
            unreal.log_warning(f"[skate] Per-slot assign failed: {{e2}}")

    # Collision: use complex (per-triangle) as simple so the player can stand on the map.
    # glTF import ships with no collision primitives by default.
    try:
        body = mesh.get_editor_property("body_setup")
        if body is None:
            # Force a body setup to exist
            try:
                unreal.EditorStaticMeshLibrary.add_simple_box_collision(mesh)
                body = mesh.get_editor_property("body_setup")
            except Exception:
                pass
        if body is not None:
            body.set_editor_property(
                "collision_trace_flag",
                unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE,
            )
            unreal.log("[skate] Collision set to Use Complex Collision As Simple")
        # Ensure mesh is marked to generate collision data
        try:
            mesh.set_editor_property("b_generate_mesh_distance_field", False)
        except Exception:
            pass
        # Notify the mesh editor so collision is rebuilt
        try:
            unreal.StaticMeshEditorSubsystem().build_collision(mesh)
        except Exception:
            try:
                # Older API name variations
                subsystem = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
                if subsystem:
                    subsystem.build_collision(mesh)
            except Exception as e3:
                unreal.log_warning(f"[skate] build_collision skipped: {{e3}}")
    except Exception as e:
        unreal.log_warning(f"[skate] Collision setup failed (set it manually on the mesh): {{e}}")

    _save(mesh)
    unreal.log(f"[skate] mesh {{mesh_path}}  ({{len(new_mats)}} material slots)")
    return mesh


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------

def run():
    unreal.log(f"[skate] === Import {{MAP_NAME}} (UE 5.4 auto materials) ===")
    src = _find_source_folder()
    _ensure_dir(DEST)

    master = ensure_master_material()
    tex_map = import_textures(src, MATERIALS)
    mat_assets = create_material_instances(master, tex_map, MATERIALS)
    import_mesh_and_assign(src, mat_assets, MATERIALS)

    unreal.log("[skate] Done. Drop the static mesh into a level and light it in Unreal.")
    unreal.log(f"[skate] Assets under {{DEST}}")


if __name__ == "__main__":
    run()
'''
    script.write_text(content, encoding="utf-8")


def convert(skate_path: Path, out_root: Path, skip_lightmaps: bool = True) -> Path:
    print(f"Reading {skate_path} ...")
    m = read_skate(skate_path)
    print(
        f"  map={m.name}  verts={len(m.positions)}  tris={len(m.indices)//3}  "
        f"materials={len(m.materials)}  textures={len(m.textures)}"
    )

    out_dir = out_root / safe_name(m.name)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Exporting textures ...")
    id_to_rel = export_textures(m, out_dir / "textures", skip_lightmaps=skip_lightmaps)
    print(f"  wrote {len(id_to_rel)} textures (lightmaps skipped={skip_lightmaps})")

    mats_json = build_materials_json(m, id_to_rel)
    (out_dir / "materials.json").write_text(json.dumps(mats_json, indent=2), encoding="utf-8")

    print("Building mesh (split by material) ...")
    pos, nor, uv, idx, prims, slots = split_by_material(m)
    # Align slot list with materials.json indices for UE script
    # Rebuild slots to carry albedo/normal paths
    slot_by_source = {s["source_index"]: s for s in slots}
    ue_mats = []
    for entry in mats_json:
        mid = entry["index"]
        if mid not in slot_by_source:
            continue
        ue_mats.append(entry)

    glb = _glb_from_parts(pos, nor, uv, idx, slots, prims)
    (out_dir / "mesh.glb").write_bytes(glb)
    print(f"  mesh.glb ({len(glb)} bytes), {len(prims)} material sections")

    # Sidecar with spawn for convenience
    meta = {
        "name": m.name,
        "spawn_y_up_metres": list(m.spawn),
        "heading": m.heading,
        "note": "Coordinates are Y-up metres (same as Skate 3 / the .skate package). "
        "Unreal is Z-up cm — the glTF importer usually converts; verify scale (×100) and axis.",
        "extensions_present": list(m.extensions.keys()),
    }
    (out_dir / "map_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    write_ue_import_script(out_dir, safe_name(m.name), ue_mats)
    print(f"Done → {out_dir}")
    return out_dir


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("skate", type=Path, help="Input .skate file")
    ap.add_argument("-o", "--output", type=Path, default=Path("export"), help="Output directory")
    ap.add_argument(
        "--keep-lightmaps",
        action="store_true",
        help="Also export lightmap textures (still not wired into materials)",
    )
    args = ap.parse_args()
    if not args.skate.is_file():
        sys.exit(f"File not found: {args.skate}")
    convert(args.skate, args.output, skip_lightmaps=not args.keep_lightmaps)


if __name__ == "__main__":
    main()
