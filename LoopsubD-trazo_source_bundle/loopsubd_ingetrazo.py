# SPDX-License-Identifier: GPL-3.0-or-later
"""LoopsubD — experimental extension for IngeTrazo 0.5.9–0.5.11, with crease support and Cage wireframe overlay.

Creates and updates a subdivided COPY of a selected source group. The original
Control Cage remains independent. Supports native face triangulation, Crease
metadata, material/face attributes, and source edge flags where topology permits.
During Cage editing, the linked subdivision surface remains visible while the
Control Cage is edited. The surface is temporarily locked to avoid accidental
selection; its prior lock state is restored when editing ends.
"""
from __future__ import annotations

import copy

from PySide6.QtGui import QVector3D, QColor, QPen, QBrush, QPolygonF
from PySide6.QtCore import Qt, QPointF, QTimer, QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QSpinBox, QPushButton, QCheckBox, QMessageBox, QInputDialog

EXTENSION_KEY = "loopsubd_ingetrazo"


def _xyz(p):
    return (float(p.x()), float(p.y()), float(p.z()))


def _add(a, b): return (a[0]+b[0], a[1]+b[1], a[2]+b[2])
def _sub(a, b): return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def _mul(a, k): return (a[0]*k, a[1]*k, a[2]*k)
def _avg(points):
    n=len(points)
    return tuple(sum(p[i] for p in points)/n for i in range(3))


def _loop_subdivide(vertices, triangles, edge_flags=None, crease_edges=None):
    """One Loop step. Returns new vertex tuples and triangle index tuples."""
    crease_edges = set(crease_edges or ())
    edge_faces = {}
    vertex_neighbors = [set() for _ in vertices]
    vertex_faces = [[] for _ in vertices]
    for fi, tri in enumerate(triangles):
        if len(tri) != 3: raise ValueError("Internal error: non-triangle input")
        for v in tri: vertex_faces[v].append(fi)
        for i in range(3):
            a,b=tri[i],tri[(i+1)%3]
            key=(a,b) if a<b else (b,a)
            edge_faces.setdefault(key, []).append(fi)
            vertex_neighbors[a].add(b); vertex_neighbors[b].add(a)
    for e, fs in edge_faces.items():
        if len(fs)>2:
            raise ValueError("A malha não é manifold: há uma aresta compartilhada por mais de duas faces.")
    # Reject isolated vertices and non-manifold boundary fans.
    for vi, ns in enumerate(vertex_neighbors):
        if not ns: raise ValueError("A malha contém vértices isolados; limpe a geometria antes de subdividir.")
        boundary_ns=[]
        for e, fs in edge_faces.items():
            if len(fs)==1 and vi in e: boundary_ns.append(e[1] if e[0]==vi else e[0])
        if len(boundary_ns) not in (0,2):
            raise ValueError("A malha tem uma borda não manifold ou um vértice de borda irregular.")
    newv=[]
    # Even (old) vertices
    for vi,p in enumerate(vertices):
        boundary_ns=[]
        for e, fs in edge_faces.items():
            if len(fs)==1 and vi in e: boundary_ns.append(e[1] if e[0]==vi else e[0])
        crease_ns=[]
        for e in crease_edges:
            if vi in e:
                crease_ns.append(e[1] if e[0] == vi else e[0])
        crease_ns=sorted(set(crease_ns))
        if len(crease_ns) >= 3:
            q=p
        elif len(crease_ns) == 2:
            q=_add(_mul(p,0.75), _mul(_add(vertices[crease_ns[0]],vertices[crease_ns[1]]),0.125))
        elif boundary_ns:
            q=_add(_mul(p,0.75), _mul(_add(vertices[boundary_ns[0]],vertices[boundary_ns[1]]),0.125))
        else:
            n=len(vertex_neighbors[vi])
            if n<3: raise ValueError("Vértice interior com valência menor que 3.")
            beta=(3/16) if n==3 else 3/(8*n)
            q=_add(_mul(p,1-n*beta), _mul(tuple(sum(vertices[j][k] for j in vertex_neighbors[vi]) for k in range(3)),beta))
        newv.append(q)
    # Odd (edge) vertices
    edge_new={}
    for e, fs in edge_faces.items():
        a,b=e
        if e in crease_edges:
            q=_mul(_add(vertices[a],vertices[b]),0.5)
        elif len(fs)==2:
            opposites=[]
            for fi in fs: opposites.extend(v for v in triangles[fi] if v not in e)
            q=_add(_mul(_add(vertices[a],vertices[b]),3/8),_mul(_add(vertices[opposites[0]],vertices[opposites[1]]),1/8))
        else:
            q=_mul(_add(vertices[a],vertices[b]),0.5)
        edge_new[e]=len(newv); newv.append(q)
    out=[]
    for a,b,c in triangles:
        ab=edge_new[(a,b) if a<b else (b,a)]
        bc=edge_new[(b,c) if b<c else (c,b)]
        ca=edge_new[(c,a) if c<a else (a,c)]
        out.extend(((a,ab,ca),(b,bc,ab),(c,ca,bc),(ab,bc,ca)))
    # Carry visual edge flags down each split source edge. Flags are keyed by
    # sorted vertex-index pairs and are inherited by both child segments.
    new_flags = {}
    for e, flags in (edge_flags or {}).items():
        mid = edge_new.get(e)
        if mid is None:
            continue
        a, b = e
        new_flags[(a, mid) if a < mid else (mid, a)] = flags
        new_flags[(b, mid) if b < mid else (mid, b)] = flags
    new_creases=set()
    for e in crease_edges:
        mid=edge_new.get(e)
        if mid is not None:
            a,b=e
            new_creases.add(tuple(sorted((a,mid))))
            new_creases.add(tuple(sorted((b,mid))))
    return newv,out,new_flags,new_creases


def _extract(mesh):
    """Triangulate each source face using IngeTrazo's native triangulator.

    The host triangulator supports concave n-gons and faces with inner loops.
    Triangles are mapped back to the original mesh vertices, so the resulting
    topology retains the hole boundary instead of filling it with a fan.
    """
    vertices=[]; index_by_id={}; index_by_position={}; triangles=[]; source_attrs=[]; edge_flags={}
    def index(v):
        k=id(v)
        if k not in index_by_id:
            p=_xyz(v.position)
            index_by_id[k]=len(vertices)
            # Position fallback maps triangulator-returned QVector3D values back
            # to the source vertex index. The host triangulator returns original
            # loop positions, not newly interpolated points.
            index_by_position.setdefault(p, index_by_id[k])
            vertices.append(p)
        return index_by_id[k]
    if not mesh.faces:
        raise ValueError("Não encontrei faces na malha ativa. Selecione/abra um objeto com geometria e tente novamente.")
    # Source edge visual flags are copied to the indexed topology. The host
    # API currently exposes soft/hidden/curve/layer, but no native crease weight.
    for edge in getattr(mesh, "edges", []):
        ia=index(edge.v0); ib=index(edge.v1)
        key=(ia,ib) if ia<ib else (ib,ia)
        flags=(bool(getattr(edge,"soft",False)), getattr(edge,"curve",None),
               getattr(edge,"layer",None), bool(getattr(edge,"hidden",False)))
        if flags != (False,None,None,False):
            edge_flags[key]=flags
    for face in mesh.faces:
        # Register outer and hole-loop vertices before triangulation.
        for v in face.loop:
            index(v)
        for hole in face.hole_loops:
            for v in hole:
                index(v)
        try:
            face_triangles = face.triangulate()
        except Exception as exc:
            raise ValueError(f"Não foi possível triangular uma face ({len(face.loop)} vértices; {len(face.hole_loops)} furos): {exc}") from exc
        if not face_triangles:
            raise ValueError(f"A triangulação não produziu triângulos para uma face com {len(face.loop)} vértices.")
        attrs=dict(getattr(face,'attrs',{}) or {})
        for tri in face_triangles:
            try:
                tri_idx=tuple(index_by_position[_xyz(p)] for p in tri)
            except KeyError as exc:
                raise ValueError("A triangulação gerou um ponto que não corresponde a um vértice original; a operação foi cancelada para evitar alterar a forma da malha.") from exc
            if len(set(tri_idx)) != 3:
                raise ValueError("A triangulação produziu um triângulo degenerado com vértices repetidos.")
            triangles.append(tri_idx)
            source_attrs.append(attrs.copy())
    # Creases are stored as endpoint-coordinate pairs in the source group's
    # extension metadata, so they survive save/reopen and do not depend on edge IDs.
    return vertices,triangles,source_attrs,edge_flags


def _find_existing_copy(app, source_group):
    """Find the copy by stable source uid metadata, not by its visible name."""
    from core.group import Group
    key = EXTENSION_KEY
    for group in app.scene.groups:
        if not isinstance(group, Group) or group is source_group:
            continue
        data = getattr(group, "ext", None) or {}
        record = data.get(key) if isinstance(data, dict) else None
        if isinstance(record, dict) and record.get("source_uid") == source_group.uid:
            return group
    return None


def _find_source_for_copy(app, copy_group):
    """Resolve the original Cage from a selected LoopsubD surface copy."""
    from core.group import Group
    data = getattr(copy_group, "ext", None) or {}
    record = data.get(EXTENSION_KEY) if isinstance(data, dict) else None
    source_uid = record.get("source_uid") if isinstance(record, dict) else None
    if source_uid is None:
        return None
    return next((g for g in app.scene.groups
                 if isinstance(g, Group) and g is not copy_group
                 and getattr(g, "uid", None) == source_uid), None)


class _CreateSubdivisionCopyCommand:
    """Undoable insertion; metadata lives on the generated copy."""
    def __init__(self, group):
        self.group = group
        self.owner = None

    def do(self, scene):
        from core.history import InsertGroupCommand
        # Use the application's own insertion semantics (including edit context).
        self._insert = InsertGroupCommand(self.group)
        self._insert.do(scene)
        self.owner = self._insert._owner

    def undo(self, scene):
        self._insert.undo(scene)


class _UpdateSubdivisionCopyCommand:
    """Swap the generated mesh as one undoable action."""
    def __init__(self, group, new_mesh, new_name, new_ext, new_material=None, new_layer=None, new_hidden=False, preserve_selection=False):
        self.group = group
        self.new_mesh = new_mesh
        self.new_name = new_name
        self.new_ext = new_ext
        self.new_material = copy.deepcopy(new_material)
        self.new_layer = new_layer
        self.new_hidden = new_hidden
        self.preserve_selection = bool(preserve_selection)
        self.old_mesh = None
        self.old_name = None
        self.old_ext = None
        self.old_material = None
        self.old_layer = None
        self.old_hidden = None

    def do(self, scene):
        if self.old_mesh is None:
            self.old_mesh = self.group.mesh
            self.old_name = self.group.name
            self.old_ext = self.group.ext
            self.old_material = copy.deepcopy(getattr(self.group,"material",None))
            self.old_layer = getattr(self.group,"layer",None)
            self.old_hidden = getattr(self.group,"hidden",False)
        self.group.mesh = self.new_mesh
        self.group.name = self.new_name
        self.group.ext = self.new_ext
        self.group.material = copy.deepcopy(self.new_material)
        self.group.layer = self.new_layer
        self.group.hidden = self.new_hidden
        if not self.preserve_selection:
            scene.selection.clear()
            scene.selection.add(self.group)
        scene.version += 1

    def undo(self, scene):
        self.group.mesh = self.old_mesh
        self.group.name = self.old_name
        self.group.ext = self.old_ext
        self.group.material = copy.deepcopy(self.old_material)
        self.group.layer = self.old_layer
        self.group.hidden = self.old_hidden
        if not self.preserve_selection:
            scene.selection.clear()
            scene.selection.add(self.group)
        scene.version += 1


def _build_copy(app, level, source_group=None, preserve_selection=False):
    from core.mesh import Mesh
    from core.group import Group
    from core.history import InsertGroupCommand
    if source_group is None:
        selected = [entity for entity in app.scene.selection if isinstance(entity, Group)]
        if len(selected) != 1:
            raise ValueError(
                "Selecione exatamente um objeto (grupo) antes de subdividir. "
                f"Grupos selecionados: {len(selected)}."
            )
        source_group = selected[0]
    elif not isinstance(source_group, Group):
        raise ValueError("A Control Cage vinculada não está disponível.")
    if source_group.xform is not None:
        raise ValueError(
            "O objeto selecionado é uma instância de componente com transformação. "
            "Esta versão ainda não processa instâncias; use um grupo convencional."
        )
    source = source_group.mesh
    verts,tris,attrs,edge_flags=_extract(source)
    if len(verts)<3 or not tris: raise ValueError("A malha não contém uma superfície válida.")
    # Resolve persistent crease endpoint coordinates to the current indexed mesh.
    source_ext = getattr(source_group, "ext", None) or {}
    crease_records = source_ext.get(EXTENSION_KEY, {}) if isinstance(source_ext, dict) else {}
    crease_coords = crease_records.get("creases", []) if isinstance(crease_records, dict) else []
    pos_index = {tuple(round(c, 7) for c in p): i for i,p in enumerate(verts)}
    crease_edges=set()
    for pair in crease_coords:
        try:
            a=pos_index[tuple(round(float(c),7) for c in pair[0])]
            b=pos_index[tuple(round(float(c),7) for c in pair[1])]
            crease_edges.add(tuple(sorted((a,b))))
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    face_attrs=attrs
    for _ in range(level):
        verts,tris,edge_flags,crease_edges=_loop_subdivide(verts,tris,edge_flags,crease_edges)
        face_attrs=[face_attrs[i//4].copy() for i in range(len(tris))]
    result=Mesh()
    for i,tri in enumerate(tris):
        pts=[QVector3D(*verts[j]) for j in tri]
        f=result.add_face(pts)
        if i < len(face_attrs): f.attrs=face_attrs[i].copy()

    # Restore supported edge styling by matching output edge endpoint positions.
    # Only flagged segments are touched; newly introduced internal edges remain default.
    out_vertex_index={p:i for i,p in enumerate(verts)}
    for edge in result.edges:
        ia=out_vertex_index.get(_xyz(edge.v0.position)); ib=out_vertex_index.get(_xyz(edge.v1.position))
        if ia is None or ib is None: continue
        key=(ia,ib) if ia<ib else (ib,ia)
        flags=edge_flags.get(key)
        if flags:
            edge.soft,edge.curve,edge.layer,edge.hidden=flags

    # The relation uses the source's persistent uid. Re-running updates this same group.
    existing = _find_existing_copy(app, source_group)
    record = {"source_uid": source_group.uid, "level": int(level), "version": "0.3.0-experimental"}
    if existing is not None:
        ext = dict(getattr(existing, "ext", None) or {})
        ext[EXTENSION_KEY] = record
        app.viewport.history.execute(
            _UpdateSubdivisionCopyCommand(
                existing, result, f"{source_group.name} — LoopsubD nível {level}", ext,
                getattr(source_group,"material",None), getattr(source_group,"layer",None),
                getattr(source_group,"hidden",False), preserve_selection=preserve_selection
            )
        )
        action = "atualizada"
    else:
        if preserve_selection:
            raise RuntimeError("A cópia LoopsubD vinculada não foi encontrada; atualização automática cancelada.")
        group=Group(result, name=f"{source_group.name} — LoopsubD nível {level}")
        # Container-level paint is the fallback for faces without their own paint.
        group.material=copy.deepcopy(getattr(source_group,"material",None))
        group.layer=getattr(source_group,"layer",None)
        group.hidden=getattr(source_group,"hidden",False)
        group.ext = {EXTENSION_KEY: record}
        app.viewport.history.execute(InsertGroupCommand(group))
        action = "criada"
    if getattr(app.viewport.history,'last_error',None):
        raise RuntimeError(app.viewport.history.last_error)
    notify=getattr(app.viewport,'notify_scene_changed',None)
    if callable(notify): notify()
    app.viewport.update()
    return len(verts),len(tris),action


def _mark_selected_edges_crease(app, remove=False):
    """Mark selected mesh edges on the currently edited source group.

    In IngeTrazo, entering group edit mode clears the group selection and makes
    ``scene.edit_group`` the authoritative editing context. Edges are then the
    entities in ``scene.selection``; requiring the group to remain selected is
    incorrect and caused the 0.1.7 prototype error.
    """
    from core.group import Group
    scene=app.scene
    group=getattr(scene, "edit_group", None)
    selected_edges=[e for e in scene.selection if hasattr(e,"v0") and hasattr(e,"v1")]
    if not isinstance(group, Group):
        raise ValueError("Entre no modo de edição do grupo original antes de marcar arestas como Crease.")
    if not selected_edges:
        raise ValueError("Nenhuma aresta selecionada foi encontrada. Entre na edição do grupo original e selecione uma ou mais arestas.")
    # Guard against accidentally marking a generated subdivision copy.
    group_ext=getattr(group, "ext", None) or {}
    copy_record=group_ext.get(EXTENSION_KEY) if isinstance(group_ext, dict) else None
    if (isinstance(copy_record, dict) and copy_record.get("source_uid")
            and "level" in copy_record and "creases" not in copy_record):
        raise ValueError("As arestas Crease devem ser marcadas no grupo original, não na cópia subdividida.")
    ext=copy.deepcopy(group_ext)
    record=ext.get(EXTENSION_KEY,{})
    if not isinstance(record,dict): record={}
    records=list(record.get("creases",[]))
    for edge in selected_edges:
        pair=[list(_xyz(edge.v0.position)),list(_xyz(edge.v1.position))]
        canon=sorted(pair)
        found=next((x for x in records if sorted(x)==canon),None)
        if remove:
            if found is not None: records.remove(found)
        elif found is None:
            records.append(pair)
    # Source crease metadata must not carry the generated-copy source_uid marker.
    # Otherwise _find_existing_copy could mistake the original for its own copy.
    record.pop("source_uid", None)
    record.pop("level", None)
    record.pop("version", None)
    record["creases"]=records
    ext[EXTENSION_KEY]=record
    group.ext=ext
    scene.version += 1
    notify=getattr(app.viewport,"notify_scene_changed",None)
    if callable(notify): notify()
    app.viewport.update()
    return len(selected_edges),len(records)


def _draw_cage_overlay(app, viewport, painter, enabled=True, selected_vertex_indices=None, selected_edge_index=None, selected_edge_indices=None, selected_face_indices=None):
    """Draw a high-contrast, screen-space wireframe for the active Cage.

    This is a visual-only overlay: it does not alter face materials, opacity,
    mesh topology, selection, or the generated subdivision surface.
    """
    if not enabled:
        return
    from core.group import Group
    group = getattr(app.scene, "edit_group", None)
    if not isinstance(group, Group):
        return
    mesh = getattr(group, "mesh", None)
    if mesh is None:
        return

    record = (getattr(group, "ext", None) or {}).get(EXTENSION_KEY, {})
    crease_pairs = record.get("creases", []) if isinstance(record, dict) else []
    crease_keys = set()
    for pair in crease_pairs:
        try:
            a = tuple(round(float(v), 7) for v in pair[0])
            b = tuple(round(float(v), 7) for v in pair[1])
            crease_keys.add(tuple(sorted((a, b))))
        except (TypeError, ValueError, IndexError):
            continue

    selected = set(app.scene.selection)
    selected_edge_indices = set(selected_edge_indices or ())
    selected_face_indices = set(selected_face_indices or ())
    if selected_edge_index is not None:
        selected_edge_indices.add(selected_edge_index)
    # A dark under-stroke keeps the Cage legible over both light and dark
    # materials. The colored stroke on top distinguishes ordinary/Crease/
    # selected edges. Cosmetic widths remain constant while zooming.
    halo = QPen(QColor(12, 20, 32, 225), 4.2)
    halo.setCosmetic(True)
    halo.setCapStyle(Qt.PenCapStyle.RoundCap)
    halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    ordinary = QPen(QColor(35, 190, 235, 255), 2.25)
    ordinary.setCosmetic(True)
    ordinary.setCapStyle(Qt.PenCapStyle.RoundCap)
    ordinary.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    crease = QPen(QColor(255, 125, 25, 255), 3.4)
    crease.setCosmetic(True)
    crease.setCapStyle(Qt.PenCapStyle.RoundCap)
    crease.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    selected_pen = QPen(QColor(255, 225, 35, 255), 3.8)
    selected_pen.setCosmetic(True)
    selected_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    selected_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

    projected = {}
    def pixel(vertex):
        key = id(vertex)
        if key not in projected:
            projected[key] = viewport.world_to_pixel(vertex.position)
        return projected[key]

    # Selected Cage faces are filled with a translucent amber overlay.
    # The fill is visual-only and is drawn before the wireframe.
    faces = list(getattr(mesh, "faces", ()))
    for face_index in sorted(selected_face_indices):
        if not (0 <= face_index < len(faces)):
            continue
        try:
            face = faces[face_index]
            loop = list(face.loop)
            pts = [pixel(v) for v in loop]
            if len(pts) >= 3 and all(p is not None for p in pts):
                polygon = QPolygonF([QPointF(*p) for p in pts])
                painter.setPen(QPen(QColor(255, 190, 35, 235), 2.0))
                painter.setBrush(QBrush(QColor(255, 185, 25, 75)))
                painter.drawPolygon(polygon)
        except (AttributeError, TypeError, ValueError):
            continue

    for edge_index, edge in enumerate(getattr(mesh, "edges", ())):
        try:
            pa, pb = pixel(edge.v0), pixel(edge.v1)
            if pa is None or pb is None:
                continue
            akey = tuple(round(v, 7) for v in _xyz(edge.v0.position))
            bkey = tuple(round(v, 7) for v in _xyz(edge.v1.position))
            is_crease = tuple(sorted((akey, bkey))) in crease_keys
            extension_selected = edge_index in selected_edge_indices
            color_pen = (selected_pen if extension_selected or edge in selected else
                         crease if is_crease else ordinary)
            painter.setPen(halo)
            painter.drawLine(QPointF(*pa), QPointF(*pb))
            painter.setPen(color_pen)
            painter.drawLine(QPointF(*pa), QPointF(*pb))
        except (AttributeError, TypeError, ValueError):
            continue

    # Vertex dots have a dark border and bright fill, so cage topology remains
    # readable over a dense subdivided surface. Multiple selected vertices are
    # highlighted independently, including vertices with no connecting edge.
    selected_vertex_indices = set(selected_vertex_indices or ())
    for vertex_index, vertex in enumerate(getattr(mesh, "vertices", ())):
        try:
            p = pixel(vertex)
            if p is None:
                continue
            point = QPointF(*p)
            if vertex_index in selected_vertex_indices:
                painter.setPen(QPen(QColor(20, 20, 20, 245), 1.8))
                painter.setBrush(QColor(255, 225, 35, 255))
                painter.drawEllipse(point, 7.0, 7.0)
                painter.setPen(QPen(QColor(255, 255, 255, 255), 1.0))
                painter.setBrush(QColor(255, 170, 20, 255))
                painter.drawEllipse(point, 4.0, 4.0)
            else:
                painter.setPen(QPen(QColor(12, 20, 32, 235), 1.4))
                painter.setBrush(QColor(225, 250, 255, 255))
                painter.drawEllipse(point, 3.4, 3.4)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(25, 145, 205, 255))
                painter.drawEllipse(point, 1.8, 1.8)
        except (AttributeError, TypeError, ValueError):
            continue


class _MoveCageVerticesCommand:
    """One undoable translation of a set of vertices in the active Cage."""
    keeps_paint = True

    def __init__(self, vertices, before_positions, after_positions):
        self.vertices = list(vertices)
        self.before = [QVector3D(p) for p in before_positions]
        self.after = [QVector3D(p) for p in after_positions]

    def _place(self, scene, positions):
        mesh = scene.mesh
        for vertex, position in zip(self.vertices, positions):
            mesh.place_vertex(vertex, position)
        scene.version += 1

    def do(self, scene):
        self._place(scene, self.after)

    def undo(self, scene):
        self._place(scene, self.before)


class _CageDragFilter(QObject):
    """Directly drag selected Cage vertices without changing native selection."""
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel

    def eventFilter(self, obj, ev):
        try:
            kind = ev.type()
            if kind == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                if self.panel.edge_pick_checkbox.isChecked():
                    return bool(self.panel._edge_drag_press(ev))
                return bool(self.panel._vertex_drag_press(ev))
            if kind == QEvent.Type.MouseMove:
                return bool(self.panel._vertex_drag_move(ev))
            if kind == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton:
                return bool(self.panel._vertex_drag_release(ev))
            if kind == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Escape:
                return bool(self.panel._cancel_vertex_drag())
        except Exception as exc:
            self.panel._cancel_vertex_drag()
            self.panel.vertex_pick_status.setText(f"Falha na movimentação: {exc}")
        return False


class LoopsubDPanel(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app=app
        layout=QVBoxLayout(self)
        intro=QLabel("Cria uma cópia subdividida independente. Ao executar novamente no original, atualiza a mesma cópia; a malha original permanece intacta.")
        intro.setWordWrap(True); layout.addWidget(intro)
        layout.addWidget(QLabel("Nível de subdivisão:"))
        self.level=QSpinBox(); self.level.setRange(1,4); self.level.setValue(1)
        self.level.setToolTip("Cada nível gera quatro triângulos por triângulo de entrada.")
        layout.addWidget(self.level)
        self.run_button=QPushButton("Subdividir / atualizar cópia")
        self.run_button.clicked.connect(self.run)
        layout.addWidget(self.run_button)
        self.auto_update_checkbox=QCheckBox("Atualizar superfície automaticamente")
        self.auto_update_checkbox.setChecked(False)
        self.auto_update_checkbox.setToolTip("Atualiza a cópia vinculada após uma pausa na edição da Control Cage.")
        layout.addWidget(self.auto_update_checkbox)
        self.auto_status=QLabel("Atualização automática desligada.")
        self.auto_status.setWordWrap(True)
        layout.addWidget(self.auto_status)
        self.cage_faces_visible_checkbox=QCheckBox("Exibir faces da Cage durante a edição")
        self.cage_faces_visible_checkbox.setChecked(False)
        self.cage_faces_visible_checkbox.setToolTip("Desativado: oculta somente as faces da Cage durante a edição, mantendo o wireframe, vértices e Creases visíveis. Ative para restaurar as faces.")
        self.cage_faces_visible_checkbox.toggled.connect(self._cage_faces_visibility_toggled)
        layout.addWidget(self.cage_faces_visible_checkbox)
        self.crease_button=QPushButton("Marcar arestas selecionadas como Crease")
        self.crease_button.clicked.connect(self.mark_creases)
        layout.addWidget(self.crease_button)
        self.uncrease_button=QPushButton("Remover Crease das arestas selecionadas")
        self.uncrease_button.clicked.connect(self.remove_creases)
        layout.addWidget(self.uncrease_button)
        self.edit_cage_button=QPushButton("Editar Cage (superfície visível)")
        self.edit_cage_button.clicked.connect(self.toggle_cage_edit)
        layout.addWidget(self.edit_cage_button)
        self.wireframe_checkbox=QCheckBox("Destacar Cage em wireframe")
        self.wireframe_checkbox.setChecked(True)
        self.wireframe_checkbox.setToolTip("Desenha arestas e vértices da Cage sobre a viewport, sem alterar materiais ou opacidade.")
        layout.addWidget(self.wireframe_checkbox)
        self.vertex_pick_checkbox=QCheckBox("Selecionar vértices da Cage na viewport")
        self.vertex_pick_checkbox.setChecked(True)
        self.vertex_pick_checkbox.setToolTip("Na edição da Cage, permite selecionar seus vértices clicando diretamente nos pontos do wireframe.")
        layout.addWidget(self.vertex_pick_checkbox)
        self.vertex_pick_status=QLabel("Seleção de vértices: entre na edição da Cage e clique em um ponto.")
        self.vertex_pick_status.setWordWrap(True)
        layout.addWidget(self.vertex_pick_status)
        self.edge_pick_checkbox=QCheckBox("Selecionar arestas da Cage na viewport")
        self.edge_pick_checkbox.setChecked(False)
        self.edge_pick_checkbox.setToolTip("Na edição da Cage, permite selecionar uma aresta clicando diretamente sobre o wireframe. A seleção é independente do estado Crease.")
        layout.addWidget(self.edge_pick_checkbox)
        self.edge_pick_status=QLabel("Seleção de arestas: desativada.")
        self.edge_pick_status.setWordWrap(True)
        layout.addWidget(self.edge_pick_status)
        self.face_pick_checkbox=QCheckBox("Selecionar faces da Cage na viewport")
        self.face_pick_checkbox.setChecked(False)
        self.face_pick_checkbox.setToolTip("Na edição da Cage, permite selecionar faces clicando dentro de seus polígonos. Ctrl adiciona e Shift alterna a seleção.")
        layout.addWidget(self.face_pick_checkbox)
        self.face_pick_status=QLabel("Seleção de faces: desativada.")
        self.face_pick_status.setWordWrap(True)
        layout.addWidget(self.face_pick_status)
        self._picked_vertex_index=None
        self._picked_vertex_indices=set()
        self._picked_edge_index=None
        self._picked_edge_indices=set()
        self._picked_face_indices=set()
        self.vertex_pick_checkbox.toggled.connect(self._vertex_pick_toggled)
        self.edge_pick_checkbox.toggled.connect(self._edge_pick_toggled)
        self.face_pick_checkbox.toggled.connect(self._face_pick_toggled)
        note=QLabel("Na edição da Cage, a superfície subdividida permanece visível e bloqueada para evitar seleção acidental. A Cage pode receber destaque wireframe; arestas Crease aparecem em laranja e arestas selecionadas em amarelo. Com a atualização automática ligada, a superfície é recalculada após uma pausa de aproximadamente 450 ms.")
        note.setWordWrap(True); layout.addWidget(note)
        self._editing_source=None
        self._editing_surface=None
        self._surface_locked_before=False
        self._source_hidden_before=False
        self._vertex_drag=None
        self._dragging_vertices=False
        self._edit_starting=False
        self._auto_updating=False
        self._last_auto_source_version=None
        self._auto_update_timer=QTimer(self)
        self._auto_update_timer.setSingleShot(True)
        self._auto_update_timer.setInterval(450)
        self._auto_update_timer.timeout.connect(self._run_auto_update)
        self.auto_update_checkbox.toggled.connect(self._auto_update_toggled)
        self.app.on_document_changed(self._on_document_changed)
        self._sync_edit_state()

    def _notify_visibility_change(self):
        scene=self.app.scene
        scene.version += 1
        notify=getattr(self.app.viewport,"notify_scene_changed",None)
        if callable(notify): notify()
        self.app.viewport.update()

    def _set_cage_faces_suppressed(self, source, suppress):
        """Hide only the active Cage faces through IngeTrazo's viewport pass.

        The mesh, face materials and generated subdivision group remain untouched.
        """
        setter=getattr(self.app.viewport, "set_suppressed_faces", None)
        if not callable(setter):
            raise RuntimeError("Esta versão do IngeTrazo não oferece o controle de ocultação temporária de faces necessário.")
        faces=set(getattr(getattr(source, "mesh", None), "faces", ())) if suppress and source is not None else set()
        setter(faces)

    def _cage_faces_visibility_toggled(self, visible):
        source=self._editing_source
        if source is None or self.app.scene.edit_group is not source:
            return
        try:
            self._set_cage_faces_suppressed(source, not visible)
        except Exception as exc:
            self.cage_faces_visible_checkbox.blockSignals(True)
            self.cage_faces_visible_checkbox.setChecked(not visible)
            self.cage_faces_visible_checkbox.blockSignals(False)
            QMessageBox.warning(self, "LoopsubD — visibilidade da Cage", str(exc))

    def _restore_surface_lock(self):
        self._cancel_vertex_drag()
        self._auto_update_timer.stop()
        surface=self._editing_surface
        source=self._editing_source
        locked_before=self._surface_locked_before
        # Always restore the normal face pass before leaving Cage edit mode.
        try:
            self._set_cage_faces_suppressed(source, False)
        except Exception:
            pass
        # Normal object mode shows only the generated subdivision surface.
        # The original Cage is revealed again when the user re-enters editing.
        if source is not None:
            source.hidden = True
        self._editing_source=None
        self._editing_surface=None
        self._picked_vertex_index=None
        self._picked_vertex_indices=set()
        self._picked_edge_index=None
        self._picked_edge_indices=set()
        self._picked_face_indices=set()
        clear_pick=getattr(self.app.viewport, "clear_extension_pick", None)
        if callable(clear_pick):
            clear_pick()
        self.vertex_pick_status.setText("Seleção de vértices: entre na edição da Cage e clique em um ponto.")
        self.edge_pick_status.setText("Seleção de arestas: entre na edição da Cage e ative a opção.")
        self.edit_cage_button.setText("Editar Cage (superfície visível)")
        if surface is not None:
            surface.locked=locked_before
            self._notify_visibility_change()

    def _active_select_tool(self):
        return getattr(getattr(self.app.viewport, "active_tool", None), "name", "") == "Select"

    def _apply_vertex_pick(self, index, modifiers):
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if shift:
            if index in self._picked_vertex_indices:
                self._picked_vertex_indices.remove(index)
            else:
                self._picked_vertex_indices.add(index)
        elif ctrl:
            self._picked_vertex_indices.add(index)
        else:
            self._picked_vertex_indices = {index}
        self._picked_vertex_index = index if index in self._picked_vertex_indices else None
        count = len(self._picked_vertex_indices)
        if count == 0:
            self.vertex_pick_status.setText("Nenhum vértice selecionado.")
        elif count == 1:
            self.vertex_pick_status.setText(f"Vértice da Cage selecionado: {next(iter(self._picked_vertex_indices)) + 1}")
        else:
            self.vertex_pick_status.setText(f"Vértices da Cage selecionados: {count}")
        self.app.viewport.update()

    def _vertex_drag_press(self, ev):
        if (not self.vertex_pick_checkbox.isChecked() or self.edge_pick_checkbox.isChecked()
                or self._editing_source is None or self.app.scene.edit_group is not self._editing_source
                or not self._active_select_tool()):
            return False
        pos = ev.position()
        item = self._pick_cage_vertex(self.app.viewport, pos.x(), pos.y())
        if not (isinstance(item, tuple) and len(item) == 2 and item[0] == "loopsubd_cage_vertex"):
            return False
        index = int(item[1])
        modifiers = ev.modifiers()
        was_selected = index in self._picked_vertex_indices
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)

        # Preserve an existing multi-selection when the user starts dragging
        # from any vertex that is already part of it. A plain click on an
        # unselected vertex still replaces the previous selection.
        if shift:
            self._apply_vertex_pick(index, modifiers)
            # Shift-click on an already selected vertex removes it; do not
            # immediately start dragging the remaining selection.
            if was_selected:
                self._vertex_drag = None
                return True
        elif ctrl:
            self._apply_vertex_pick(index, modifiers)
        elif was_selected:
            # Clicking an already selected vertex begins a group drag; keep
            # all selected vertices instead of collapsing to this one.
            self._picked_vertex_index = index
            count = len(self._picked_vertex_indices)
            self.vertex_pick_status.setText(
                f"Vértices da Cage selecionados: {count}" if count > 1
                else f"Vértice da Cage selecionado: {index + 1}"
            )
            self.app.viewport.update()
        else:
            self._apply_vertex_pick(index, modifiers)
        mesh = self._editing_source.mesh
        vertices = list(getattr(mesh, "vertices", ()))
        selected = sorted(i for i in self._picked_vertex_indices if 0 <= i < len(vertices))
        if not selected:
            self._vertex_drag = None
            return True
        moving = [vertices[i] for i in selected]
        before = [QVector3D(v.position) for v in moving]
        pivot = QVector3D(
            sum(p.x() for p in before) / len(before),
            sum(p.y() for p in before) / len(before),
            sum(p.z() for p in before) / len(before))
        vp = self.app.viewport
        origin, ray = vp._pixel_to_ray(pos.x(), pos.y())
        _center_origin, view = vp._pixel_to_ray(vp.width() / 2, vp.height() / 2)
        if origin is None or ray is None or view is None:
            self._vertex_drag = None
            return True
        start = vp._ray_plane(origin, ray, pivot, view)
        if start is None:
            self._vertex_drag = None
            return True
        self._vertex_drag = {
            "mesh": mesh, "vertices": moving, "before": before,
            "press": (float(pos.x()), float(pos.y())),
            "pivot": pivot, "view": view, "start": start,
            "started": False, "last": before,
        }
        return True

    def _vertex_drag_move(self, ev):
        drag = self._vertex_drag
        if drag is None:
            return False
        if not (ev.buttons() & Qt.MouseButton.LeftButton):
            self._cancel_vertex_drag()
            return False
        pos = ev.position()
        if not drag["started"] and ((pos.x() - drag["press"][0]) ** 2 + (pos.y() - drag["press"][1]) ** 2) ** 0.5 < 4.0:
            return True
        vp = self.app.viewport
        origin, ray = vp._pixel_to_ray(pos.x(), pos.y())
        if origin is None or ray is None:
            return True
        target = vp._ray_plane(origin, ray, drag["pivot"], drag["view"])
        if target is None:
            return True
        delta = target - drag["start"]
        mesh = drag["mesh"]
        for vertex, original in zip(drag["vertices"], drag["before"]):
            mesh.place_vertex(vertex, original + delta)
        drag["last"] = [QVector3D(v.position) for v in drag["vertices"]]
        drag["started"] = True
        self._dragging_vertices = True
        self.app.scene.version += 1
        vp.update()
        return True

    def _finish_vertex_drag(self, commit):
        drag = self._vertex_drag
        self._vertex_drag = None
        self._dragging_vertices = False
        if drag is None:
            return False
        if not drag["started"]:
            self.app.viewport.update()
            return True
        after = [QVector3D(v.position) for v in drag["vertices"]]
        before = drag["before"]
        mesh = drag["mesh"]
        # Restore the preview first; History then records one clean command.
        for vertex, position in zip(drag["vertices"], before):
            mesh.place_vertex(vertex, position)
        self.app.scene.version += 1
        if commit and any((a - b).length() > 1e-8 for a, b in zip(after, before)):
            self.app.viewport.history.execute(
                _MoveCageVerticesCommand(drag["vertices"], before, after))
            err = getattr(self.app.viewport.history, "last_error", None)
            if err:
                (self.edge_pick_status if drag.get("kind") == "edges" else self.vertex_pick_status).setText(
                    f"Movimentação não registrada: {err}")
            else:
                status = (f"{len(after)} vértice(s) movimentado(s) a partir da seleção de arestas. Uma operação de Undo."
                          if drag.get("kind") == "edges" else
                          f"{len(after)} vértice(s) movimentado(s). Uma operação de Undo.")
                (self.edge_pick_status if drag.get("kind") == "edges" else self.vertex_pick_status).setText(status)
        self.app.viewport.update()
        return True

    def _vertex_drag_release(self, ev):
        if self._vertex_drag is None:
            return False
        return self._finish_vertex_drag(True)

    def _cancel_vertex_drag(self):
        if self._vertex_drag is None:
            return False
        return self._finish_vertex_drag(False)

    def _auto_update_toggled(self, enabled):
        if not enabled:
            self._auto_update_timer.stop()
            self.auto_status.setText("Atualização automática desligada.")
        elif self._editing_source is None:
            self.auto_status.setText("Ative a edição da Cage para usar a atualização automática.")
        else:
            self._last_auto_source_version=self.app.scene.version
            self.auto_status.setText("Atualização automática ligada — aguardando alterações na Cage.")

    def _on_document_changed(self):
        self._sync_edit_state()
        if self._dragging_vertices:
            return
        if self._auto_updating or not self.auto_update_checkbox.isChecked():
            return
        source=self._editing_source
        if source is None or self.app.scene.edit_group is not source:
            return
        version=self.app.scene.version
        if version == self._last_auto_source_version:
            return
        self._auto_update_timer.start(450)

    def _run_auto_update(self):
        source=self._editing_source
        if (not self.auto_update_checkbox.isChecked() or source is None
                or self.app.scene.edit_group is not source or self._auto_updating):
            return
        version=self.app.scene.version
        if version == self._last_auto_source_version:
            return
        self._auto_updating=True
        try:
            nv,nf,action=_build_copy(
                self.app, self.level.value(), source_group=source,
                preserve_selection=True
            )
            self._last_auto_source_version=self.app.scene.version
            self.auto_status.setText(
                f"Superfície atualizada automaticamente — {nf} triângulos."
            )
        except Exception as exc:
            self.auto_status.setText(f"Falha na atualização automática: {exc}")
        finally:
            self._auto_updating=False

    def _sync_edit_state(self):
        if self._edit_starting:
            return
        # The IngeTrazo viewport owns group-edit entry/exit. Observe its
        # authoritative state so Esc, click-outside and the app's own
        # Finalizar/exit commands all restore the linked surface.
        if self._editing_source is not None:
            if self.app.scene.edit_group is not self._editing_source:
                self._restore_surface_lock()
            else:
                self.edit_cage_button.setText("Finalizar edição da Cage")

    def toggle_cage_edit(self):
        scene=self.app.scene
        vp=self.app.viewport
        if self._editing_source is not None and scene.edit_group is self._editing_source:
            vp.end_group_edit()
            self._sync_edit_state()
            return
        if scene.edit_group is not None:
            QMessageBox.warning(self,"LoopsubD", "Saia do modo de edição atual antes de iniciar a edição da Cage LoopsubD.")
            return
        from core.group import Group
        selected=[e for e in scene.selection if isinstance(e,Group)]
        if len(selected)!=1:
            QMessageBox.warning(self,"LoopsubD", "Selecione exatamente a superfície subdividida ou a Control Cage vinculada para iniciar a edição.")
            return
        selected_group=selected[0]
        # Accept either the generated surface (the normal object-mode target)
        # or the original Cage for backward-compatible workflows.
        selected_record=(getattr(selected_group,"ext",None) or {}).get(EXTENSION_KEY,{})
        if isinstance(selected_record,dict) and selected_record.get("source_uid"):
            surface=selected_group
            source=_find_source_for_copy(self.app,surface)
        else:
            source=selected_group
            surface=_find_existing_copy(self.app,source)
        if source is None or surface is None:
            QMessageBox.warning(self,"LoopsubD", "Não encontrei o vínculo entre a superfície subdividida e sua Control Cage. Crie ou atualize a subdivisão primeiro.")
            return
        previous_locked=bool(getattr(surface,"locked",False))
        previous_source_hidden=bool(getattr(source,"hidden",False))
        # Keep the subdivided result visible as a visual reference. Locking it
        # is intended to prevent accidental group/face selection while the
        # original Control Cage is the active edit context.
        surface.locked=True
        source.hidden=False
        self._editing_source=source
        self._editing_surface=surface
        self._surface_locked_before=previous_locked
        self._source_hidden_before=previous_source_hidden
        self._edit_starting=True
        self._notify_visibility_change()
        try:
            vp.begin_group_edit(source)
        except Exception:
            surface.locked=previous_locked
            source.hidden=previous_source_hidden
            self._editing_source=None
            self._editing_surface=None
            self._edit_starting=False
            self._notify_visibility_change()
            raise
        self._edit_starting=False
        if scene.edit_group is not source:
            surface.locked=previous_locked
            source.hidden=previous_source_hidden
            self._editing_source=None
            self._editing_surface=None
            self._notify_visibility_change()
            QMessageBox.warning(self,"LoopsubD", "O IngeTrazo não conseguiu entrar na edição da Cage. O bloqueio da superfície foi restaurado.")
            return
        self.edit_cage_button.setText("Finalizar edição da Cage")
        try:
            self._set_cage_faces_suppressed(source, not self.cage_faces_visible_checkbox.isChecked())
        except Exception as exc:
            # Roll back the edit entry rather than leave the surface in an
            # ambiguous visual state on unsupported host builds.
            vp.end_group_edit()
            self._restore_surface_lock()
            QMessageBox.warning(self, "LoopsubD — visibilidade da Cage", str(exc))
            return
        self._last_auto_source_version=scene.version
        if self.auto_update_checkbox.isChecked():
            self.auto_status.setText("Atualização automática ligada — aguardando alterações na Cage.")

    def _clear_extension_selection(self):
        self._picked_vertex_index=None
        self._picked_vertex_indices=set()
        self._picked_edge_index=None
        self._picked_edge_indices=set()
        self._picked_face_indices=set()
        clear_pick=getattr(self.app.viewport, "clear_extension_pick", None)
        if callable(clear_pick):
            clear_pick()
        self.app.viewport.update()

    def _vertex_pick_toggled(self, enabled):
        if enabled and self.face_pick_checkbox.isChecked():
            self.face_pick_checkbox.blockSignals(True)
            self.face_pick_checkbox.setChecked(False)
            self.face_pick_checkbox.blockSignals(False)
            self.face_pick_status.setText("Seleção de faces: desativada.")
        if enabled and self.edge_pick_checkbox.isChecked():
            self.edge_pick_checkbox.blockSignals(True)
            self.edge_pick_checkbox.setChecked(False)
            self.edge_pick_checkbox.blockSignals(False)
            self.edge_pick_status.setText("Seleção de arestas: desativada.")
        self._clear_extension_selection()
        self._picked_edge_indices.clear()
        self._picked_edge_index=None
        self.vertex_pick_status.setText(
            "Seleção de vértices ativada." if enabled else "Seleção de vértices desativada."
        )

    def _edge_pick_toggled(self, enabled):
        if enabled and self.face_pick_checkbox.isChecked():
            self.face_pick_checkbox.blockSignals(True)
            self.face_pick_checkbox.setChecked(False)
            self.face_pick_checkbox.blockSignals(False)
            self.face_pick_status.setText("Seleção de faces: desativada.")
        if enabled and self.vertex_pick_checkbox.isChecked():
            self.vertex_pick_checkbox.blockSignals(True)
            self.vertex_pick_checkbox.setChecked(False)
            self.vertex_pick_checkbox.blockSignals(False)
            self.vertex_pick_status.setText("Seleção de vértices desativada.")
        self._clear_extension_selection()
        self._picked_edge_indices.clear()
        self._picked_edge_index=None
        self.edge_pick_status.setText(
            "Seleção de arestas ativada — clique sobre uma aresta da Cage." if enabled
            else "Seleção de arestas desativada."
        )

    def _face_pick_toggled(self, enabled):
        if enabled:
            for checkbox, status in ((self.vertex_pick_checkbox, self.vertex_pick_status),
                                     (self.edge_pick_checkbox, self.edge_pick_status)):
                if checkbox.isChecked():
                    checkbox.blockSignals(True)
                    checkbox.setChecked(False)
                    checkbox.blockSignals(False)
                    status.setText("Seleção desativada.")
        self._clear_extension_selection()
        self._picked_face_indices.clear()
        self.face_pick_status.setText(
            "Seleção de faces ativada — clique dentro de uma face da Cage." if enabled
            else "Seleção de faces desativada.")

    @staticmethod
    def _point_in_polygon(px, py, points):
        inside = False
        n = len(points)
        j = n - 1
        for i in range(n):
            xi, yi = points[i]
            xj, yj = points[j]
            if ((yi > py) != (yj > py)):
                cross = (xj - xi) * (py - yi) / ((yj - yi) or 1e-12) + xi
                if px < cross:
                    inside = not inside
            j = i
        return inside

    def _pick_cage_face(self, viewport, px, py):
        """Pick a Cage face by testing the cursor against projected outer/hole loops."""
        if not self.face_pick_checkbox.isChecked():
            return None
        group = self.app.scene.edit_group
        if group is None or group is not self._editing_source:
            return None
        mesh = getattr(group, "mesh", None)
        faces = list(getattr(mesh, "faces", ())) if mesh is not None else []
        best = None
        # Later faces win ties, matching the overlay's painter order.
        for face_index, face in enumerate(faces):
            try:
                loops = [list(face.loop)] + [list(h) for h in getattr(face, "hole_loops", ())]
                projected_loops = []
                valid = True
                for loop in loops:
                    coords = [_xyz(v.position) for v in loop]
                    xs, ys, front = self.app.world_to_pixels(coords)
                    if len(xs) < 3 or not all(bool(v) for v in front):
                        valid = False
                        break
                    projected_loops.append([(float(x), float(y)) for x, y in zip(xs, ys)])
                if not valid:
                    continue
                if self._point_in_polygon(float(px), float(py), projected_loops[0]):
                    # A cursor inside a hole is not inside the face.
                    if any(self._point_in_polygon(float(px), float(py), hole) for hole in projected_loops[1:]):
                        continue
                    best = face_index
            except (AttributeError, TypeError, ValueError):
                continue
        return ("loopsubd_cage_face", int(best)) if best is not None else None

    def _apply_face_pick(self, index, modifiers):
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if shift:
            if index in self._picked_face_indices:
                self._picked_face_indices.remove(index)
            else:
                self._picked_face_indices.add(index)
        elif ctrl:
            self._picked_face_indices.add(index)
        else:
            self._picked_face_indices = {index}
        count = len(self._picked_face_indices)
        if count == 0:
            self.face_pick_status.setText("Nenhuma face selecionada.")
        elif count == 1:
            self.face_pick_status.setText(f"Face da Cage selecionada: {index + 1}")
        else:
            self.face_pick_status.setText(f"Faces da Cage selecionadas: {count}")
        self.app.viewport.update()

    def _pick_cage_edge(self, viewport, px, py):
        """Return an extension-pick ID for the nearest visible Cage edge."""
        if not self.edge_pick_checkbox.isChecked():
            return None
        group=self.app.scene.edit_group
        if group is None or group is not self._editing_source:
            return None
        mesh=getattr(group, "mesh", None)
        edges=list(getattr(mesh, "edges", ())) if mesh is not None else []
        if not edges:
            return None
        try:
            points=[]
            for edge in edges:
                points.append(_xyz(edge.v0.position))
                points.append(_xyz(edge.v1.position))
            xs,ys,front=self.app.world_to_pixels(points)
        except Exception:
            return None
        best_index=None
        best_distance=7.5
        for i in range(len(edges)):
            j=2*i
            if not (bool(front[j]) and bool(front[j+1])):
                continue
            ax,ay=float(xs[j]),float(ys[j])
            bx,by=float(xs[j+1]),float(ys[j+1])
            dx,dy=bx-ax,by-ay
            denom=dx*dx+dy*dy
            if denom <= 1e-12:
                t=0.0
            else:
                t=max(0.0,min(1.0,((float(px)-ax)*dx+(float(py)-ay)*dy)/denom))
            qx,qy=ax+t*dx,ay+t*dy
            distance=((float(px)-qx)**2+(float(py)-qy)**2)**0.5
            if distance <= best_distance:
                best_index=i
                best_distance=distance
        if best_index is None:
            return None
        return ("loopsubd_cage_edge", int(best_index))

    def _pick_cage_vertex(self, viewport, px, py):
        """Return an extension-pick id for a Cage vertex near the cursor.

        The host keeps extension picks separate from scene.selection, so a
        LoopsubD vertex can be selected without inserting foreign IDs into the
        model's native selection collection.
        """
        if not self.vertex_pick_checkbox.isChecked() or self.edge_pick_checkbox.isChecked():
            return None
        group=self.app.scene.edit_group
        if group is None or group is not self._editing_source:
            return None
        mesh=getattr(group, "mesh", None)
        vertices=list(getattr(mesh, "vertices", ())) if mesh is not None else []
        if not vertices:
            return None
        try:
            points=[_xyz(v.position) for v in vertices]
            xs,ys,front=self.app.world_to_pixels(points)
        except Exception:
            return None
        best_index=None
        best_distance=10.0
        for i,(x,y,is_front) in enumerate(zip(xs,ys,front)):
            if not bool(is_front):
                continue
            distance=((float(x)-float(px))**2+(float(y)-float(py))**2)**0.5
            if distance <= best_distance:
                best_index=i
                best_distance=distance
        if best_index is None:
            return None
        return ("loopsubd_cage_vertex", int(best_index))

    def _selection_modifiers(self):
        """Read modifiers during the host's synchronous extension-pick callback."""
        try:
            return QApplication.keyboardModifiers()
        except Exception:
            return Qt.KeyboardModifier.NoModifier


    def _apply_edge_pick(self, index, modifiers):
        """Apply SketchUp-like single/add/toggle selection to Cage edges."""
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if shift:
            if index in self._picked_edge_indices:
                self._picked_edge_indices.remove(index)
            else:
                self._picked_edge_indices.add(index)
        elif ctrl:
            self._picked_edge_indices.add(index)
        else:
            self._picked_edge_indices = {index}
        self._picked_edge_index = index if index in self._picked_edge_indices else None
        self._picked_vertex_indices.clear()
        self._picked_vertex_index = None
        self._picked_face_indices.clear()
        count = len(self._picked_edge_indices)
        if count == 0:
            self.edge_pick_status.setText("Nenhuma aresta selecionada.")
        elif count == 1:
            self.edge_pick_status.setText(f"Aresta da Cage selecionada: {index + 1}")
        else:
            self.edge_pick_status.setText(f"Arestas da Cage selecionadas: {count}")
        self.app.viewport.update()

    def _edge_drag_press(self, ev):
        """Select and, when dragging, move the unique vertices of selected edges."""
        if (not self.edge_pick_checkbox.isChecked()
                or self._editing_source is None
                or self.app.scene.edit_group is not self._editing_source
                or not self._active_select_tool()):
            return False
        pos = ev.position()
        item = self._pick_cage_edge(self.app.viewport, pos.x(), pos.y())
        if not (isinstance(item, tuple) and len(item) == 2 and item[0] == "loopsubd_cage_edge"):
            return False
        index = int(item[1])
        modifiers = ev.modifiers()
        was_selected = index in self._picked_edge_indices
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

        if shift:
            self._apply_edge_pick(index, modifiers)
            # Shift-click on an already selected edge removes it, not drag it.
            if was_selected:
                self._vertex_drag = None
                return True
        elif modifiers & Qt.KeyboardModifier.ControlModifier:
            self._apply_edge_pick(index, modifiers)
        elif was_selected:
            self._picked_edge_index = index
            count = len(self._picked_edge_indices)
            self.edge_pick_status.setText(f"Arestas da Cage selecionadas: {count}" if count > 1
                                          else f"Aresta da Cage selecionada: {index + 1}")
            self.app.viewport.update()
        else:
            self._apply_edge_pick(index, modifiers)

        mesh = self._editing_source.mesh
        edges = list(getattr(mesh, "edges", ()))
        selected_edges = sorted(i for i in self._picked_edge_indices if 0 <= i < len(edges))
        if not selected_edges:
            self._vertex_drag = None
            return True

        # Deduplicate endpoints: shared vertices must be translated exactly once.
        moving = []
        seen = set()
        for edge_index in selected_edges:
            edge = edges[edge_index]
            for vertex in (edge.v0, edge.v1):
                key = id(vertex)
                if key not in seen:
                    seen.add(key)
                    moving.append(vertex)
        before = [QVector3D(v.position) for v in moving]
        pivot = QVector3D(
            sum(p.x() for p in before) / len(before),
            sum(p.y() for p in before) / len(before),
            sum(p.z() for p in before) / len(before))
        vp = self.app.viewport
        origin, ray = vp._pixel_to_ray(pos.x(), pos.y())
        _center_origin, view = vp._pixel_to_ray(vp.width() / 2, vp.height() / 2)
        if origin is None or ray is None or view is None:
            self._vertex_drag = None
            return True
        start = vp._ray_plane(origin, ray, pivot, view)
        if start is None:
            self._vertex_drag = None
            return True
        self._vertex_drag = {
            "mesh": mesh, "vertices": moving, "before": before,
            "press": (float(pos.x()), float(pos.y())),
            "pivot": pivot, "view": view, "start": start,
            "started": False, "last": before, "kind": "edges",
        }
        return True

    def _on_cage_vertex_selected(self, item):
        modifiers=self._selection_modifiers()
        ctrl=bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift=bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

        if item is None:
            # set_extension_pick() first releases the previous single host pick
            # before notifying us about the new one. Keep our own multi-selection
            # while Ctrl/Shift is held; a plain click/Esc clears it.
            if not (ctrl or shift):
                self._picked_vertex_indices.clear()
                self._picked_vertex_index=None
                self._picked_edge_index=None
                self._picked_edge_indices.clear()
                self._picked_face_indices.clear()
                self.vertex_pick_status.setText("Nenhum elemento selecionado.")
        elif isinstance(item, tuple) and len(item)==2 and item[0]=="loopsubd_cage_vertex":
            index=int(item[1])
            self._picked_edge_index=None
            self._picked_edge_indices.clear()
            if shift:
                if index in self._picked_vertex_indices:
                    self._picked_vertex_indices.remove(index)
                else:
                    self._picked_vertex_indices.add(index)
            elif ctrl:
                self._picked_vertex_indices.add(index)
            else:
                self._picked_vertex_indices={index}
            self._picked_vertex_index=index if index in self._picked_vertex_indices else None
            count=len(self._picked_vertex_indices)
            if count == 0:
                self.vertex_pick_status.setText("Nenhum vértice selecionado.")
            elif count == 1:
                only=next(iter(self._picked_vertex_indices))
                self.vertex_pick_status.setText(f"Vértice da Cage selecionado: {only + 1}")
            else:
                self.vertex_pick_status.setText(f"Vértices da Cage selecionados: {count}")
        elif isinstance(item, tuple) and len(item)==2 and item[0]=="loopsubd_cage_edge":
            self._apply_edge_pick(int(item[1]), modifiers)
        elif isinstance(item, tuple) and len(item)==2 and item[0]=="loopsubd_cage_face":
            self._picked_vertex_indices.clear()
            self._picked_vertex_index=None
            self._picked_edge_indices.clear()
            self._picked_edge_index=None
            self._apply_face_pick(int(item[1]), modifiers)
        self.app.viewport.update()

    def mark_creases(self):
        try:
            n,total=_mark_selected_edges_crease(self.app,False)
            QMessageBox.information(self,"LoopsubD — Crease",f"Arestas processadas: {n}\nCreases armazenados: {total}")
        except Exception as exc:
            QMessageBox.warning(self,"LoopsubD — Crease",str(exc))

    def remove_creases(self):
        try:
            n,total=_mark_selected_edges_crease(self.app,True)
            QMessageBox.information(self,"LoopsubD — Crease",f"Arestas processadas: {n}\nCreases restantes: {total}")
        except Exception as exc:
            QMessageBox.warning(self,"LoopsubD — Crease",str(exc))

    def run(self):
        self.run_button.setEnabled(False)
        try:
            level=self.level.value()
            nv,nf,action=_build_copy(self.app,level)
            verb = "atualizada" if action == "atualizada" else "criada"
            QMessageBox.information(self,"LoopsubD",f"Cópia {verb}.\nNível: {level}\nVértices: {nv}\nTriângulos: {nf}\n\nUse Desfazer para reverter esta operação.")
        except Exception as exc:
            QMessageBox.warning(self,"LoopsubD — não foi possível subdividir",str(exc))
        finally:
            self.run_button.setEnabled(True)


def _run_with_level_dialog(app):
    level, ok = QInputDialog.getInt(
        None,
        "LoopsubD — nível de subdivisão",
        "Escolha o nível (1 a 4):",
        1, 1, 4, 1
    )
    if not ok:
        return
    try:
        nv, nf, action = _build_copy(app, level)
        verb = "atualizada" if action == "atualizada" else "criada"
        QMessageBox.information(
            None, "LoopsubD",
            f"Cópia {verb}.\nNível: {level}\nVértices: {nv}\n"
            f"Triângulos: {nf}\n\nUse Desfazer para reverter esta operação."
        )
    except Exception as exc:
        QMessageBox.warning(None, "LoopsubD — não foi possível subdividir", str(exc))


def setup(app):
    panel=LoopsubDPanel(app)
    app.add_panel("LoopsubD",panel)
    app.add_overlay(lambda viewport, painter: _draw_cage_overlay(
        app, viewport, painter, panel.wireframe_checkbox.isChecked(),
        panel._picked_vertex_indices,
        panel._picked_edge_index, panel._picked_edge_indices, panel._picked_face_indices
    ))
    # Viewport extension-picking is supported by IngeTrazo 0.5.9+ and keeps
    # plugin-owned IDs separate from the native scene selection.
    def _pick_cage_element(viewport, px, py):
        if panel.face_pick_checkbox.isChecked():
            return panel._pick_cage_face(viewport, px, py)
        if panel.edge_pick_checkbox.isChecked():
            return panel._pick_cage_edge(viewport, px, py)
        return panel._pick_cage_vertex(viewport, px, py)
    app.add_pickable(_pick_cage_element, on_select=panel._on_cage_vertex_selected)
    # Direct vertex dragging is scoped to Cage edit mode and the native Select tool.
    panel._drag_filter = _CageDragFilter(panel)
    app.viewport.installEventFilter(panel._drag_filter)
    # The menu command asks for the level explicitly, even if the dock panel is hidden.
    app.add_menu_action("LoopsubD: subdividir / atualizar cópia",lambda: _run_with_level_dialog(app),
                        tip="Escolhe o nível e cria ou atualiza a cópia subdividida do grupo selecionado.")
