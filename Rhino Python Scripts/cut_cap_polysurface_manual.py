#! python 3
"""
Cut a polysurface at a cutting plane YOU define by hand, delete the
piece(s) you pick, and cap what's left back into a closed solid.

This is the fully-manual sibling of cut_cap_polysurface.py -- no auto-
detection at all, for the "really tough" parts where auto-detection either
doesn't apply or isn't worth attempting (no clean cylindrical meter
section, noisy/faceted surfaces, a one-off oddball part, etc.). Every step
is a deliberate choice: which method defines the plane, and which piece(s)
get deleted. Nothing is guessed or auto-classified anywhere in this tool.

Single feature only -- there's no batch mode here. For scanning many parts
automatically, use cut_cap_polysurface.py instead (its auto-detection with
manual fallback, or its dedicated batch mode).

WORKFLOW
--------
1. Select exactly one polysurface (or surface) to work on.

2. Define the cutting plane -- always asks which method, no auto-fallback
   tried first:
     - Curve: select a single planar curve (a free-standing curve object,
       or an edge directly on the polysurface) and its own plane is used
       directly. If what you pick isn't planar or otherwise unusable, it
       falls back to the 3-point method below rather than failing
       outright.
     - Points: pick 3 points directly on the polysurface's own faces.

3. The polysurface is split by that plane. The plane's own location and
   orientation are never altered -- the rectangle used to cut with is
   auto-sized by projecting the object's bounding box onto that exact
   plane, so it always extends past the object in every direction (and
   cuts all the way through) without ever shifting off-plane. This
   oversized cutter is only used for the split math; it is never added to
   the document.

4. You pick the piece(s) to DELETE yourself, always -- no suggestion, no
   auto-identification attempted. Nothing gets deleted, capped, or moved
   until you've confirmed this.

5. Each kept piece gets capped: its naked (open) edges at the cut are
   collected, joined into closed loop(s), and turned into a new planar
   surface exactly matching that opening -- then joined back onto the
   piece to close it into a solid again. Either way (capped or left open
   because capping wasn't possible), the result is moved onto its own
   layer (PROCESSED_LAYER_NAME -- the same one cut_cap_polysurface.py
   uses, so results from either tool sort together) so it's easy to find
   later, separate from anything untouched.

Run this from Rhino 8's Script Editor, or from a toolbar button macro:
    ! _-ScriptEditor _R "full\\path\\to\\cut_cap_polysurface_manual.py"

VERSION HISTORY
----------------
v1 / RC1 (2026-09-25) - Split out of cut_cap_polysurface.py as a
    dedicated fully-manual tool: "make a new tool that is just for single
    feature with manual selection of cutting plane (option for curve or
    3-point) and manual selection of piece to delete (for the really
    tough ones)." Unlike the main tool's manual fallback (which tries
    Curve first and only falls back to Points automatically), this always
    asks which method up front, since the whole point of this tool is
    deliberate manual control rather than a default being tried for you.
    Piece-to-delete is likewise always a manual pick here -- no
    identification is attempted at all, confident or otherwise. Reuses
    the same well-tested plane-picking (get_point_on_brep,
    get_cutting_plane, get_cutting_plane_from_curve -- including the v7
    fix that lets you pick an edge on the polysurface, not just a free-
    standing curve), cutting (build_oversized_cutter), capping
    (cap_and_join), view-centering (snap_view_to), and active-layer-
    inheritance fix (pinning new fragments to the original object's layer
    right after they're added, rather than trusting Rhino's currently
    active layer -- see cut_cap_polysurface.py's v13 notes for why that
    matters) from cut_cap_polysurface.py, as of its v18.
"""

import System
import rhinoscriptsyntax as rs
import Rhino
import Rhino.Geometry as rg

SCRIPT_VERSION = "v1 / RC1"

PROCESSED_LAYER_NAME = "Processed Diffusers"  # same layer cut_cap_polysurface.py uses, so results from either tool sort together
SNAP_VIEW_ZOOM_FACTOR = 1.3           # half-width of the snap_view_to framing box, as a multiple of the given radius -- lower = tighter zoom
WHOLE_PART_ZOOM_FRACTION = 0.5        # snap_view_to radius when framing the WHOLE part (before a plane is picked), as a fraction of its bounding-box diagonal
FEATURE_ZOOM_FALLBACK_FRACTION = 0.15 # snap_view_to radius once a plane is picked (no detected feature size to go by here), as a fraction of the part's bounding-box diagonal


def get_single_target():
    """User selects exactly one polysurface (or surface) to work on.
    Returns (object_id, Brep), or None if cancelled or not a valid
    surface/polysurface."""
    obj_id = rs.GetObject(
        "Select the polysurface to cut",
        filter=rs.filter.surface | rs.filter.polysurface,
        preselect=True)
    if obj_id is None:
        return None
    brep = rs.coercebrep(obj_id)
    if brep is None:
        print("That's not a surface or polysurface.")
        return None
    return obj_id, brep


def get_point_on_brep(brep, prompt):
    """Prompts for a single point, constrained to lie on brep's surface(s)."""
    gp = Rhino.Input.Custom.GetPoint()
    gp.SetCommandPrompt(prompt)
    gp.Constrain(brep, -1, -1, False)  # -1,-1 = constrain to the whole brep, any face
    gp.Get()
    if gp.CommandResult() != Rhino.Commands.Result.Success:
        return None
    return gp.Point()


def get_cutting_plane(brep):
    """User picks 3 points on the polysurface; returns a
    Rhino.Geometry.Plane, or None if cancelled or the points are invalid."""
    labels = ("first", "second", "third")
    pts = []
    for label in labels:
        pt = get_point_on_brep(brep, "Pick the {} point on the polysurface for the cutting plane".format(label))
        if pt is None:
            print("Point selection cancelled.")
            return None
        pts.append(pt)

    plane = rg.Plane(pts[0], pts[1], pts[2])
    if not plane.IsValid:
        print("Those three points don't define a valid plane (they may be collinear, or two coincide).")
        return None
    return plane


def get_cutting_plane_from_curve(tolerance):
    """User picks a single planar curve -- a free-standing curve object,
    OR an edge on the polysurface (or any other object) in the document --
    and its own plane becomes the cutting plane.

    Uses the lower-level GetObject class directly rather than the
    rs.GetObject wrapper: rs.GetObject's curve filter only accepts free-
    standing curve objects, not edges of a solid -- but an edge is often
    exactly what you want to click (e.g. a naked edge right at a feature
    boundary), so GeometryFilter + SubObjectSelect are set directly to
    allow picking either kind, and ObjRef.Curve() resolves whichever was
    picked into actual curve geometry either way.

    Returns (status, plane):
      status: "ok" (plane is a valid Rhino.Geometry.Plane) |
              "cancelled" (user backed out of the pick itself) |
              "invalid" (picked something, but it's not a usable planar
              curve -- caller's cue to fall back to point-picking)."""
    go = Rhino.Input.Custom.GetObject()
    go.SetCommandPrompt("Select a planar curve, or an edge on an object, to define the cutting plane")
    go.GeometryFilter = Rhino.DocObjects.ObjectType.Curve
    go.SubObjectSelect = True
    go.Get()
    if go.CommandResult() != Rhino.Commands.Result.Success:
        print("Curve selection cancelled.")
        return "cancelled", None

    objref = go.Object(0)
    curve = objref.Curve()
    if curve is None:
        print("That wasn't a valid curve.")
        return "invalid", None

    ok, plane = curve.TryGetPlane(tolerance)
    if not ok:
        print("That curve isn't planar.")
        return "invalid", None
    if not plane.IsValid:
        print("That curve's plane came back invalid.")
        return "invalid", None
    return "ok", plane


def pick_manual_plane(target_brep, tolerance):
    """Defines the cutting plane by hand -- always asks which method to
    use, no auto-fallback tried first (that's the whole point of this
    tool: a deliberate choice for the tough cases, rather than one method
    being tried for you). If Curve is chosen but what got picked isn't a
    usable planar curve, falls back to the 3-point method automatically
    rather than failing outright -- but the initial choice is always
    yours. Returns a Rhino.Geometry.Plane, or None if cancelled."""
    choice = rs.GetString(
        "Define the cutting plane using a Curve or 3 Points?",
        "Curve", ["Curve", "Points"])
    if choice is None:
        print("Cancelled.")
        return None

    if choice.lower().startswith("p"):
        return get_cutting_plane(target_brep)

    status, plane = get_cutting_plane_from_curve(tolerance)
    if status == "ok":
        return plane
    if status == "cancelled":
        return None
    print("Falling back to picking 3 points instead.")
    return get_cutting_plane(target_brep)


def ensure_layer(name):
    """Returns name, creating that layer first if it doesn't already
    exist. Leaves an existing layer's color/state/parent alone."""
    if not rs.IsLayer(name):
        rs.AddLayer(name)
    return name


def build_oversized_cutter(plane, target_brep):
    """Builds a planar cutter Brep ON THE EXACT PLANE given -- that plane's
    origin and normal are never altered -- sized so its rectangle fully
    covers target_brep's bounding box no matter where the plane's origin
    sits relative to the object."""
    bbox = target_brep.GetBoundingBox(True)
    corners = bbox.GetCorners()

    us, vs = [], []
    for corner in corners:
        success, u, v = plane.ClosestParameter(corner)
        if success:
            us.append(u)
            vs.append(v)

    if not us:
        half = bbox.Diagonal.Length or 1000.0
        u_min, u_max, v_min, v_max = -half, half, -half, half
    else:
        pad = bbox.Diagonal.Length * 0.1 + 1.0  # margin past the object's projected extent
        u_min, u_max = min(us) - pad, max(us) + pad
        v_min, v_max = min(vs) - pad, max(vs) + pad

    x_extents = rg.Interval(u_min, u_max)
    y_extents = rg.Interval(v_min, v_max)
    plane_surface = rg.PlaneSurface(plane, x_extents, y_extents)
    return plane_surface.ToBrep()


def cap_and_join(fragment_id, tolerance):
    """Caps fragment_id's naked edges with a matching planar surface and
    joins it back on. Returns the id of the final (hopefully closed)
    result, or fragment_id unchanged if capping wasn't possible. Either
    way, the returned object is moved onto PROCESSED_LAYER_NAME (created
    if needed) before returning, so every finished result -- capped or
    left open -- ends up somewhere easy to find, separate from whatever
    layer the original polysurface was on."""
    result_id = fragment_id
    brep = rs.coercebrep(fragment_id)
    naked = brep.DuplicateNakedEdgeCurves(True, True)

    if naked:
        loops = rg.Curve.JoinCurves(naked, tolerance)
        if not loops:
            print("  Could not join the naked edges into closed loop(s) on {} -- left open for manual cleanup.".format(fragment_id))
        else:
            caps = rg.Brep.CreatePlanarBreps(loops, tolerance)
            if not caps:
                print("  Could not build a planar cap on {} -- left open for manual cleanup.".format(fragment_id))
            else:
                doc = Rhino.RhinoDoc.ActiveDoc
                # AddBrep returns System.Guid.Empty (rather than raising)
                # on a degenerate cap -- filtered out here so a bad cap
                # can't get passed into JoinSurfaces, which would raise
                # trying to look up an id that was never actually added.
                cap_ids = [cid for cid in (doc.Objects.AddBrep(cap) for cap in caps) if cid != System.Guid.Empty]
                if not cap_ids:
                    print("  Could not add the cap surface(s) to the document on {} -- left open for manual cleanup.".format(fragment_id))
                else:
                    joined = rs.JoinSurfaces([fragment_id] + cap_ids, delete_input=True)
                    if not joined:
                        print("  Join failed on {} -- the cap piece(s) were added separately instead.".format(fragment_id))
                    else:
                        result_id = joined
    # else: already closed somehow; nothing to cap, just move it to the layer

    try:
        rs.ObjectLayer(result_id, ensure_layer(PROCESSED_LAYER_NAME))
    except Exception as ex:
        print("  (couldn't move {} to the '{}' layer: {})".format(result_id, PROCESSED_LAYER_NAME, ex))

    return result_id


def snap_view_to(center_pt, radius):
    """Zooms the active viewport to frame center_pt (sized off radius) and
    re-centers the view's target there too, so it becomes the rotation
    pivot -- called right before any prompt that needs you to look at (or
    orbit around) a specific spot, instead of leaving you to go hunt for it
    on a possibly much larger model. Best-effort: a view-API hiccup here
    should never block the actual geometry operation, so failures are
    swallowed with a short printed note."""
    try:
        half = max(radius, 1.0) * SNAP_VIEW_ZOOM_FACTOR
        bbox = rg.BoundingBox(
            rg.Point3d(center_pt.X - half, center_pt.Y - half, center_pt.Z - half),
            rg.Point3d(center_pt.X + half, center_pt.Y + half, center_pt.Z + half))
        view = rs.CurrentView()
        rs.ZoomBoundingBox(bbox, view=view)
        cam, tgt = rs.ViewCameraTarget(view)
        offset = cam - tgt
        rs.ViewCameraTarget(view, center_pt + offset, center_pt)
        rs.Redraw()
    except Exception as ex:
        print("  (couldn't snap the view: {})".format(ex))


def main():
    print("cut_cap_polysurface_manual.py - {}".format(SCRIPT_VERSION))

    doc = Rhino.RhinoDoc.ActiveDoc
    tolerance = doc.ModelAbsoluteTolerance

    target = get_single_target()
    if target is None:
        return
    target_id, target_brep = target

    bbox = target_brep.GetBoundingBox(True)
    snap_view_to(bbox.Center, bbox.Diagonal.Length * WHOLE_PART_ZOOM_FRACTION)

    plane = pick_manual_plane(target_brep, tolerance)
    if plane is None:
        return

    cutter_brep = build_oversized_cutter(plane, target_brep)

    undo_serial = doc.BeginUndoRecord("Cut and cap polysurface (manual)")
    try:
        fragments = target_brep.Split(cutter_brep, tolerance)
        if not fragments or len(fragments) < 2:
            print("The plane didn't split the polysurface into more than one piece. Nothing was changed.")
            return

        # capture the original object's layer BEFORE deleting it, so the
        # new split fragments can be pinned there explicitly -- otherwise
        # doc.Objects.AddBrep puts them on whatever layer is currently
        # ACTIVE in Rhino, which has nothing to do with the original part
        # and could easily be PROCESSED_LAYER_NAME itself (e.g. if that's
        # what you were browsing) -- landing brand-new, still-undecided
        # fragments on the processed layer before you've picked anything,
        # and hiding it to sort through results would hide them too.
        original_layer = rs.ObjectLayer(target_id)
        rs.DeleteObject(target_id)

        # doc.Objects.AddBrep can fail on a degenerate/invalid split
        # fragment (a sliver, self-intersecting geometry, etc.) and
        # returns System.Guid.Empty rather than raising -- calling
        # rs.ObjectLayer (or anything else) on that empty id blows up with
        # "does not exist in ObjectTable", so each add is checked and a
        # failed fragment is skipped (and reported) rather than trusted.
        frag_ids = []
        for frag in fragments:
            fid = doc.Objects.AddBrep(frag)
            if fid == System.Guid.Empty:
                print("  Warning: a split fragment could not be added to the document (invalid geometry) -- skipped.")
                continue
            rs.ObjectLayer(fid, original_layer)
            frag_ids.append(fid)
        rs.Redraw()

        if not frag_ids:
            print("None of the split pieces could be added to the document. Nothing was changed.")
            return

        radius_hint = target_brep.GetBoundingBox(True).Diagonal.Length * FEATURE_ZOOM_FALLBACK_FRACTION
        snap_view_to(plane.Origin, radius_hint)

        # Always a manual pick here -- no suggestion, no auto-
        # identification attempted anywhere in this tool. Nothing gets
        # deleted, capped, or moved to PROCESSED_LAYER_NAME until you've
        # confirmed this.
        to_delete = rs.GetObjects(
            "Select the polysurface(s) to DELETE (Enter with none selected keeps everything)",
            preselect=False, objects=frag_ids, minimum_count=0)
        if to_delete is None:
            print("Selection cancelled. The split pieces remain in the document, unjoined, for you to finish manually.")
            return

        remaining_ids = [fid for fid in frag_ids if fid not in to_delete]
        if to_delete:
            rs.DeleteObjects(to_delete)
        if not remaining_ids:
            print("All pieces were selected for deletion; nothing left to cap.")
            return

        results = [cap_and_join(fid, tolerance) for fid in remaining_ids]
        print("Done. {} piece(s) kept and processed: {}".format(len(results), ", ".join(str(r) for r in results)))

    finally:
        doc.EndUndoRecord(undo_serial)
        rs.Redraw()


if __name__ == "__main__":
    main()
