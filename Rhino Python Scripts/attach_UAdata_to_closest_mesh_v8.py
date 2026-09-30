#! python 3
"""
Attach CSV vector data (I, J, K) to the closest mesh object in the Rhino document.

CSV format expected (header row required):
    ID, X, Y, Z, I, J, K

Example:
    ID,X,Y,Z,I,J,K
    A101,0,0,0,1,0,0
    B202,5,0,0,0,1,0
    C303,0,5,0,0,0,1

WHAT THIS SCRIPT DOES
----------------------
1. Prompts for a max match distance, prefilled with the doc-unit equivalent
   of 1 mm. Press Enter to accept it, type a different number to override,
   type 0 for no limit, or Esc to cancel the whole run. Rows further than
   the tolerance from every mesh are treated as unmatched rather than being
   force-matched to whatever mesh happens to be nearest.

2. Clears out any points/vectors/labels left over from a previous run of
   this script (see CLEANUP below), so re-running on an updated CSV doesn't
   pile up duplicates.

3. For every row, adds a point at (X, Y, Z) and a unit-length line in the
   direction of (I, J, K), both on a "CSV Points+Vectors" layer (created
   automatically). Each point/line is named after its row's ID. Rows with a
   zero-length IJK vector get a point only.

4. For each row, finds the closest VISIBLE mesh (hidden meshes and meshes on
   hidden layers are skipped; locked-but-visible meshes are still included)
   to the point (X, Y, Z), using an RTree-accelerated nearest-neighbor search
   (see PERFORMANCE below) instead of checking every mesh individually.
   Stores ID, X, Y, Z, I, J, K as user text on the matched mesh, renames the
   mesh to that row's ID, and drops a text dot label at the point showing
   the ID, on a separate "CSV Match Labels" layer. If more than one CSV row
   is closest to the same mesh, only the row with the smallest distance is
   kept (a console note is printed when this happens).

5. Prints a summary: how many meshes were tagged, which meshes had more
   than one competing row, and a list of any CSV row IDs that were not
   applied to a mesh of their own (because a closer row claimed the same
   mesh, because no mesh matched, or because every candidate was beyond the
   distance tolerance).

The whole run is wrapped in a single Undo record, so one Ctrl+Z undoes
everything the script did (points, vectors, labels, tags, and renames).

PERFORMANCE (RTree)
--------------------
Instead of comparing every CSV point against every mesh (which gets slow
with many meshes), this script uses Rhino's RTree spatial index to quickly
narrow each point down to its K_NEIGHBORS nearest mesh bounding-box centers,
then only runs the exact (and more expensive) mesh.ClosestPoint() check
against those candidates. This is an approximation: in rare cases involving
very unevenly sized or overlapping meshes, the true closest mesh could fall
just outside the K_NEIGHBORS shortlist. Raise K_NEIGHBORS below for more
confidence at the cost of some speed, or set it to a number >= your mesh
count to make it exactly equivalent to a full brute-force search. If the
RTree query fails for any reason, the script automatically falls back to
checking every mesh directly.

CLEANUP
-------
Each run deletes every object currently on the "CSV Points+Vectors" and
"CSV Match Labels" layers before adding new ones. It does NOT undo user
text or renames applied to meshes by a previous run — if a mesh matched
a different row last time and no longer matches anything this time, its
old tags/name are left as-is.

Run this from Rhino's Python script editor (EditPythonScript / _RunPythonScript).
Works in Rhino 7 and 8 (rhinoscriptsyntax + RhinoCommon).
"""

import rhinoscriptsyntax as rs
import Rhino
import Rhino.Geometry as rg
import csv

POINTS_LAYER = "CSV Points+Vectors"
LABELS_LAYER = "CSV Match Labels"
K_NEIGHBORS = 12   # candidate meshes checked per point via RTree; see PERFORMANCE note above


def select_csv_file():
    """Opens a file-selection dialog box and returns the chosen CSV path, or None if cancelled."""
    dlg = Rhino.UI.OpenFileDialog()
    dlg.Title = "Select CSV file"
    dlg.Filter = "CSV Files (*.csv)|*.csv|All Files (*.*)|*.*"
    if dlg.ShowOpenDialog():
        return dlg.FileName
    return None


def read_csv(path):
    rows = []
    with open(path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rid = row['ID']
                x = float(row['X'])
                y = float(row['Y'])
                z = float(row['Z'])
                i = float(row['I'])
                j = float(row['J'])
                k = float(row['K'])
            except (KeyError, ValueError, TypeError):
                continue  # skip malformed or blank rows
            rows.append((rid, x, y, z, i, j, k))
    return rows


def ask_tolerance():
    """Prompts for a max match distance, prefilled with the doc-unit equivalent
    of 1 mm. Press Enter to accept the default, type a different number to
    override it, type 0 for no limit, or press Esc to cancel the whole run.
    Returns (tolerance_or_None, cancelled_bool)."""
    doc = Rhino.RhinoDoc.ActiveDoc
    mm_to_doc_units = Rhino.RhinoMath.UnitScale(Rhino.UnitSystem.Millimeters, doc.ModelUnitSystem)
    default_tol = 1.0 * mm_to_doc_units

    val = rs.GetReal("Maximum match distance, in document units (0 = no limit)", default_tol)
    if val is None:
        return None, True   # user pressed Esc
    if val <= 0:
        return None, False  # explicit no-limit
    return val, False


def ensure_layer(name):
    """Creates the layer if it doesn't already exist; returns its name."""
    if not rs.IsLayer(name):
        rs.AddLayer(name)
    return name


def clear_layer_objects(layer_name):
    """Deletes every object currently on layer_name, if the layer exists."""
    if not rs.IsLayer(layer_name):
        return
    ids = rs.ObjectsByLayer(layer_name)
    if ids:
        rs.DeleteObjects(ids)


def add_points_and_vectors(data, layer_name):
    """For every CSV row, adds a point at (X,Y,Z) and a unit-length line in the
    direction of (I,J,K), both on layer_name. Rows with a zero-length IJK
    vector get a point only (a unit vector can't be derived from (0,0,0))."""
    ensure_layer(layer_name)
    skipped = []
    for (rid, x, y, z, i, j, k) in data:
        pt = rg.Point3d(x, y, z)
        pt_id = rs.AddPoint(pt)
        rs.ObjectLayer(pt_id, layer_name)
        rs.ObjectName(pt_id, rid)

        vec = rg.Vector3d(i, j, k)
        if vec.Unitize():  # normalizes in place; False if the vector is zero-length
            end_pt = pt + vec
            line_id = rs.AddLine(pt, end_pt)
            rs.ObjectLayer(line_id, layer_name)
            rs.ObjectName(line_id, "{}_vec".format(rid))
        else:
            skipped.append(rid)

    if skipped:
        print("NOTE: {} row(s) had a zero-length IJK vector, so only a point was added (no vector line):".format(len(skipped)))
        for rid in skipped:
            print("  - {}".format(rid))


def get_mesh_objects():
    """Returns mesh object ids that are visible: not hidden, and not on a hidden layer.
    (Locked meshes are still included, since locked objects remain visible on screen.)"""
    all_meshes = rs.ObjectsByType(rs.filter.mesh)
    if not all_meshes:
        return []

    visible = []
    for obj_id in all_meshes:
        if rs.IsObjectHidden(obj_id):
            continue
        layer = rs.ObjectLayer(obj_id)
        if layer and not rs.IsLayerVisible(layer):
            continue
        visible.append(obj_id)
    return visible


def build_neighbor_lists(mesh_cache, needle_points):
    """Returns a list (one entry per needle point) of candidate mesh_cache indices
    to check, using RTree nearest-neighbor search on mesh bounding-box centers.
    Falls back to "check every mesh" if the RTree query fails for any reason."""
    try:
        centers = [mesh.GetBoundingBox(True).Center for _, mesh in mesh_cache]
        k = min(K_NEIGHBORS, len(mesh_cache))
        results = rg.RTree.Point3dKNeighbors(centers, needle_points, k)
        return [list(idxs) for idxs in results], True
    except Exception:
        all_indices = list(range(len(mesh_cache)))
        return [all_indices for _ in needle_points], False


def closest_mesh_among(point, candidates):
    """candidates is a list of (id, Mesh) tuples. Returns (best_id, best_dist)."""
    pt = rg.Point3d(point[0], point[1], point[2])
    best_id = None
    best_dist = None
    for mid, mesh in candidates:
        cp = mesh.ClosestPoint(pt)   # returns closest Point3d on the mesh
        dist = pt.DistanceTo(cp)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_id = mid
    return best_id, best_dist


def process(data, tolerance):
    add_points_and_vectors(data, POINTS_LAYER)

    mesh_ids = get_mesh_objects()
    if not mesh_ids:
        print("No visible meshes found in the document.")
        return

    mesh_cache = [(mid, rs.coercemesh(mid)) for mid in mesh_ids]
    mesh_cache = [(mid, m) for mid, m in mesh_cache if m is not None]

    ensure_layer(LABELS_LAYER)

    needle_points = [rg.Point3d(x, y, z) for (_, x, y, z, _, _, _) in data]
    neighbor_lists, used_rtree = build_neighbor_lists(mesh_cache, needle_points)
    print("Using {} nearest-mesh search ({} mesh(es) in scene).".format(
        "RTree-accelerated" if used_rtree else "brute-force fallback", len(mesh_cache)))

    match_count = {}    # mesh_id -> number of CSV rows that targeted it
    best_dist = {}       # mesh_id -> distance of the closest row kept so far
    winner_rid = {}       # mesh_id -> ID of the row currently kept for it
    label_ids = {}         # mesh_id -> text dot object id for the current winner
    all_ids = []
    too_far_ids = []
    tagged = 0

    for idx, (rid, x, y, z, i, j, k) in enumerate(data):
        all_ids.append(rid)
        candidates = [mesh_cache[j] for j in neighbor_lists[idx]]
        mesh_id, dist = closest_mesh_among((x, y, z), candidates)
        if mesh_id is None:
            continue

        if tolerance is not None and dist > tolerance:
            too_far_ids.append(rid)
            continue

        match_count[mesh_id] = match_count.get(mesh_id, 0) + 1

        if mesh_id in best_dist and dist >= best_dist[mesh_id]:
            continue  # a closer row already claimed this mesh; skip this one

        best_dist[mesh_id] = dist
        winner_rid[mesh_id] = rid

        rs.SetUserText(mesh_id, "ID", rid)
        rs.SetUserText(mesh_id, "X", str(x))
        rs.SetUserText(mesh_id, "Y", str(y))
        rs.SetUserText(mesh_id, "Z", str(z))
        rs.SetUserText(mesh_id, "I", str(i))
        rs.SetUserText(mesh_id, "J", str(j))
        rs.SetUserText(mesh_id, "K", str(k))
        rs.ObjectName(mesh_id, rid)

        if mesh_id in label_ids:
            rs.DeleteObject(label_ids[mesh_id])
        dot_id = rs.AddTextDot(rid, rg.Point3d(x, y, z))
        rs.ObjectLayer(dot_id, LABELS_LAYER)
        label_ids[mesh_id] = dot_id

        tagged += 1

    winners = set(winner_rid.values())
    unmatched_ids = [rid for rid in all_ids if rid not in winners]

    print("Tagged {} mesh(es) with vector data (from {} CSV rows).".format(len(match_count), len(data)))
    for mesh_id, n in match_count.items():
        if n > 1:
            print("  NOTE: mesh {} was targeted by {} CSV rows; kept the closest one (ID {}).".format(
                mesh_id, n, winner_rid[mesh_id]))

    if too_far_ids:
        print("")
        print("{} row(s) exceeded the {} unit distance tolerance and were not matched:".format(
            len(too_far_ids), tolerance))
        for rid in too_far_ids:
            print("  - {}".format(rid))

    print("")
    if not unmatched_ids:
        print("All CSV rows were matched to their own mesh.")
    else:
        print("{} CSV row(s) were NOT applied to a mesh of their own:".format(len(unmatched_ids)))
        for rid in unmatched_ids:
            print("  - {}".format(rid))


def main():
    csv_path = select_csv_file()
    if not csv_path:
        print("No CSV file selected.")
        return

    data = read_csv(csv_path)
    if not data:
        print("No valid rows found in CSV.")
        return

    tolerance, cancelled = ask_tolerance()
    if cancelled:
        print("Cancelled.")
        return

    clear_layer_objects(POINTS_LAYER)
    clear_layer_objects(LABELS_LAYER)

    doc = Rhino.RhinoDoc.ActiveDoc
    undo_serial = doc.BeginUndoRecord("Tag meshes from CSV")
    rs.EnableRedraw(False)
    try:
        process(data, tolerance)
    finally:
        rs.EnableRedraw(True)
        doc.EndUndoRecord(undo_serial)
        rs.Redraw()


if __name__ == "__main__":
    main()
