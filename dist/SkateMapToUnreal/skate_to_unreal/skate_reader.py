"""SKATE14 binary reader (geometry, materials, textures).

Based on the SK8-ENGINE skate-3-rust-engine map_writer layout.
Light / irradiance data is parsed only enough to skip it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import struct
import zlib
from typing import Optional

import numpy as np


@dataclass
class Texture:
    name: str
    width: int
    height: int
    faces: int
    rgba: bytes  # raw RGBA8, top-down as stored in the package


@dataclass
class MaterialRole:
    role: str
    texture_id: int  # 1-based into textures list; 0 = none
    uv_set: int
    clamp_u: int
    clamp_v: int


@dataclass
class Material:
    name: str
    albedo_id: int
    lightmap_id: int
    normal_id: int
    alpha_mode: int  # 0 opaque, 1 mask, 2 blend
    alpha_cutoff: float
    depth_layer: int
    base_color: tuple[float, float, float]
    roughness: float
    shader_name: str = ""
    roles: list[MaterialRole] = field(default_factory=list)
    params: dict = field(default_factory=dict)


@dataclass
class SkateMap:
    name: str
    spawn: tuple[float, float, float]
    heading: float
    materials: list[Material]
    textures: list[Texture]
    # interleaved vertex buffer (dtype below)
    positions: np.ndarray  # (N, 3) float32 Y-up metres
    normals: np.ndarray
    uvs: np.ndarray  # UV0
    lightmap_uvs: np.ndarray
    material_ids: np.ndarray  # 1-based material index per vertex
    decal_uvs: np.ndarray
    tangent_frame: np.ndarray  # (N, 4) int8 binormal xyz + handedness
    indices: np.ndarray  # uint32 triangle list
    rails_raw: bytes = b""
    extensions: dict = field(default_factory=dict)


VERTEX_DTYPE = np.dtype(
    [
        ("p", "<f4", (3,)),
        ("n", "<f4", (3,)),
        ("uv", "<f4", (2,)),
        ("lm", "<f4", (2,)),
        ("mat", "<u4"),
        ("decal", "<f4", (2,)),
        ("frame", "i1", (4,)),
    ]
)


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.off = 0

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.data, self.off)[0]
        self.off += 4
        return v

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.data, self.off)[0]
        self.off += 4
        return v

    def f32(self) -> float:
        v = struct.unpack_from("<f", self.data, self.off)[0]
        self.off += 4
        return v

    def string(self) -> str:
        n = self.u32()
        s = self.data[self.off : self.off + n]
        self.off += n
        return s.decode("utf-8", errors="replace")

    def stored(self) -> bytes:
        method = self.u32()
        n = self.u32()
        blob = self.data[self.off : self.off + n]
        self.off += n
        if method == 1:
            return zlib.decompress(blob)
        if method == 0:
            return blob
        raise ValueError(f"Unknown storage method {method}")


def read_skate(path: Path | str) -> SkateMap:
    path = Path(path)
    data = path.read_bytes()
    if data[:7] != b"SKATE14":
        raise ValueError(f"Not a SKATE14 file (got {data[:8]!r})")

    r = _Reader(data)
    r.off = 8
    endian = r.u32()
    if endian != 0x12345678:
        raise ValueError(f"Unexpected endian marker {endian:#x}")

    name = r.string()
    spawn = (r.f32(), r.f32(), r.f32())
    heading = r.f32()
    for _ in range(45):  # environment / sky block — intentionally ignored for UE lighting
        r.f32()

    n_mats = r.u32()
    n_tex = r.u32()
    n_verts = r.u32()
    n_indices = r.u32()
    _ = r.u32()  # reserved
    n_rails = r.u32()
    for _ in range(3):
        r.u32()

    materials: list[Material] = []
    for _ in range(n_mats):
        mname = r.string()
        _layer = r.u32()
        floats7 = [r.f32() for _ in range(7)]
        # floats7: roughness?, pad, base_r, base_g, base_b, roughness2?, pad
        base = (floats7[2], floats7[3], floats7[4])
        roughness = floats7[0]
        albedo = r.u32()
        light = r.u32()
        _light_scale = r.f32()
        normal = r.u32()
        r.u32()
        r.u32()
        alpha_mode = r.u32()
        alpha_cutoff = r.f32()
        r.u32()
        r.u32()
        r.u32()
        depth = r.u32()
        has_shader = r.u32()
        shader_name = ""
        roles: list[MaterialRole] = []
        params: dict = {}
        if has_shader:
            r.off += 16  # guid Q + handle I + group i
            shader_name = r.string()
            _family = r.u32()
            _flags = r.u32()
            nroles = r.u32()
            for _ in range(nroles):
                role = r.string()
                tid, uv, c0, c1 = r.u32(), r.u32(), r.u32(), r.u32()
                roles.append(MaterialRole(role, tid, uv, c0, c1))
            nparams = r.u32()
            for _ in range(nparams):
                pname = r.string()
                nvals = r.u32()
                params[pname] = [r.string() for _ in range(nvals)]
            _meta = r.string()
        materials.append(
            Material(
                name=mname,
                albedo_id=albedo,
                lightmap_id=light,
                normal_id=normal,
                alpha_mode=alpha_mode,
                alpha_cutoff=alpha_cutoff,
                depth_layer=depth,
                base_color=base,
                roughness=roughness,
                shader_name=shader_name,
                roles=roles,
                params=params,
            )
        )

    textures: list[Texture] = []
    for _ in range(n_tex):
        tname = r.string()
        w, h, faces = r.u32(), r.u32(), r.u32()
        rgba = r.stored()
        expected = w * h * 4 * max(faces, 1)
        if len(rgba) != expected and faces == 1:
            # tolerate minor padding differences
            pass
        textures.append(Texture(tname, w, h, faces, rgba))

    verts_blob = r.stored()
    idx_blob = r.stored()
    _collision_portable = r.stored()  # empty in current writer

    expected_v = n_verts * VERTEX_DTYPE.itemsize
    if len(verts_blob) != expected_v:
        raise ValueError(f"Vertex buffer size mismatch: {len(verts_blob)} vs {expected_v}")
    verts = np.frombuffer(verts_blob, dtype=VERTEX_DTYPE)
    indices = np.frombuffer(idx_blob, dtype="<u4").copy()
    if len(indices) != n_indices:
        raise ValueError("Index count mismatch")

    # Skip rails (not needed for UE mesh import)
    for _ in range(n_rails):
        _ = r.string()
        closed = r.u32()
        _kind = r.u32()
        r.off += 16  # two Q
        _flags = r.u32()
        _trail = r.u32()
        seg_count = r.u32()
        r.off += seg_count * 120

    extensions: dict = {}
    if r.off + 4 <= len(data):
        n_ext = r.u32()
        for _ in range(n_ext):
            tag = data[r.off : r.off + 4]
            r.off += 4
            schema = r.u32()
            size = r.u32()
            payload = r.stored()
            extensions[tag.decode("ascii", errors="replace")] = {
                "schema": schema,
                "size": size,
                "payload_len": len(payload),
            }

    return SkateMap(
        name=name,
        spawn=spawn,
        heading=heading,
        materials=materials,
        textures=textures,
        positions=verts["p"].copy(),
        normals=verts["n"].copy(),
        uvs=verts["uv"].copy(),
        lightmap_uvs=verts["lm"].copy(),
        material_ids=verts["mat"].copy(),
        decal_uvs=verts["decal"].copy(),
        tangent_frame=verts["frame"].copy(),
        indices=indices,
        extensions=extensions,
    )
