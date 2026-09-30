#! python 3
"""
Cut a polysurface at the point where a cylindrical "meter" section meets a
diffuser body, delete the meter section, and cap the diffuser back into a
closed solid. Can find that cutting plane automatically, or fall back to
defining it by hand -- 3 points on the surface, or a single planar curve.
Every finished result is moved onto its own layer (PROCESSED_LAYER_NAME)
so processed diffusers are easy to find and filter later.

WORKFLOW
--------
1. User selects one or more polysurfaces (or surfaces) to work on.

   Selecting MORE THAN ONE switches straight to BATCH MODE: auto-detection
   only, no prompts at all. Anything that isn't a clean, confident
   detection (or doesn't split into exactly 2 pieces the way expected) is
   left completely untouched rather than guessed at or stopped on -- its
   display color is inverted so it's visually obvious in the viewport, and
   it's reported, selected, and zoomed to at the end so you can re-run this
   tool on just those, one at a time, using the interactive flow below.

   Selecting exactly one runs the interactive flow:

   Single-feature (interactive) mode is a straight, simple 4-step
   sequence:

2. Finding the cutting plane:

   AUTO is always attempted first, straight away, with no prompt to
   choose Auto vs Manual. It scans the part along its own rotational axis
   looking for a run of cross-sections that are round and hold a constant
   radius -- i.e. a clean cylinder -- then finds where that run stops
   being clean (see AUTO-DETECTION below).
     - Confident result: used immediately, no prompt.
     - Low-confidence result: the candidate split line is previewed in
       red, and you're asked a single either/or -- Use this plane, or
       define it manually? (Escape backs out entirely.)
     - No candidate found at all: there's no plane to offer using, so it
       falls straight to manual, no prompt.

   MANUAL (reached automatically whenever AUTO doesn't produce a plane
   you've accepted -- never chosen up front): defaults straight to
   picking a curve, no prompt -- select a single planar curve (a free-
   standing curve object, or an edge directly on the polysurface) and its
   own plane is used directly. If what you pick isn't planar (or isn't
   usable some other way), it falls back automatically to the original
   3-point pick instead (constrained to lie ON the object's surface).
   Cancelling the curve pick itself cancels the whole manual step, rather
   than falling through to points.

3. The polysurface is split by that plane. The plane's own location and
   orientation are never altered -- the rectangle used to cut with is
   auto-sized by projecting the object's bounding box onto that exact
   plane, so it always extends past the object in every direction (and
   cuts all the way through) without ever shifting off-plane. This
   oversized cutter is only used for the split math; it is never added to
   the document.

4. Which piece to delete: an attempt is always made to identify the
   meter piece and delete it automatically, no prompt -- if that
   succeeds, you're told which piece was deleted and which was kept
   (Undo/Ctrl+Z if it guessed backwards), and the kept piece goes
   straight to capping.
     - When a confident AUTO plane was used, this identification comes
       from the actual detected cylindrical run -- the trustworthy case.
     - Otherwise (a manually-picked plane, or a low-confidence AUTO plane
       you chose to use), there's no detected run to lean on, so a
       weaker guess is used instead: whichever side of the plane has
       less of the part beyond it along the part's own rotational axis
       is guessed as the meter's free end.
   Only when identification isn't possible at all -- more than two
   pieces came out of the split, or the two pieces couldn't be told
   apart either way -- do you pick the piece(s) to DELETE by hand
   instead, the same way manual picking always worked here. (Batch mode
   is the separate, deliberately fully-automatic, no-fallback path -- see
   WORKFLOW step 1.)

5. Each kept piece gets capped: its naked (open) edges at the cut are
   collected, joined into closed loop(s), and turned into a new planar
   surface exactly matching that opening -- then joined back onto the piece
   to close it into a solid again. Either way (capped or left open because
   capping wasn't possible), the result is moved onto PROCESSED_LAYER_NAME
   so it's easy to find later, separate from anything skipped or untouched.

AUTO-DETECTION
---------------
The part is assumed to be roughly axisymmetric (true for a diffuser body).
The rotational axis is estimated by PCA (principal component analysis) on
points sampled across all the polysurface's faces -- no numpy dependency,
just a hand-rolled covariance + power-iteration eigensolve, seeded with the
bounding-box diagonal direction for fast convergence, since that's all a
3x3 symmetric matrix needs.

The polysurface is then sliced by SLICE_COUNT planes perpendicular to that
axis, evenly spaced along its length. Each slice is classified: does it
intersect the part in exactly one closed curve, and is that curve round
(CIRC_TOLERANCE)? Consecutive round slices are grouped into runs, and a run
only counts as "cylindrical" if its radius stays constant across the whole
run (RADIUS_SPREAD_TOLERANCE) -- this tells a straight tube apart from a
cone, since a cone's individual cross-sections are round too, they just
aren't the same radius as their neighbors.

Circularity + constant radius alone is NOT enough to pick out the meter,
though: the diffuser body can present its own round, constant-radius run
somewhere along its length too (real parts aren't perfectly conical). What
actually identifies the meter is that it sits at a free/open end of the
part -- but that end is almost never the very last round slice, because
real parts are usually cut or chamfered at an ANGLE right at the tip, not
perpendicular to the axis, so the round cross-sections stop a bit short of
the true physical end (an angled face makes the cross-section skewed, not
round, so it fails the roundness test even though it's genuinely close to
the tip).

So instead of checking "is this run's boundary within a small margin of
the scanned range's extreme," each end of every run is scored by its
STUB -- how much more of the part lies beyond that end, out to the
scanned range's edge on that side. The meter's real free end should only
have a small stub past it (a chamfer, a bit of fitting geometry, or
nothing) before the part truly ends; the transition end always has a lot
more part beyond it -- the whole diffuser body. Whichever run (and side of
it) has the smallest stub, out of every round run found anywhere on the
part, is taken as the meter's free end -- a relative comparison, not a
fixed distance, so it isn't thrown off by how big the chamfer happens to
be.

- If one run's stub is clearly the smallest of all, that's the meter, high
  confidence.
- If more than one run's stub is in the same ballpark (within
  STUB_TIE_RATIO of the smallest), the narrowest-radius one among them is
  picked, since the meter is the metering tube and the diffuser flares out
  from it -- flagged as low confidence either way, you're asked to
  confirm.
- If only one round run exists and it has a small stub on BOTH sides
  (BARE_CYLINDER_STUB_RADII), the whole part is scanning as a single
  cylinder with no transition anywhere -- nothing to cut, reported as
  failed.
- If nothing round is found at all, detection fails outright and falls
  back to manual picking.

Whichever end of the winning run is the free one is left alone; the other
end is bisected down to a precise transition point between the two
adjacent slices, which becomes the cutting plane.

This is a heuristic, not an exact geometric query, so:
- It expects the meter section to be a genuinely round, constant-radius
  run of some length, with one end noticeably closer to a free/open end of
  the part than the other.
- Whenever detection fails or comes back low-confidence, it prints every
  candidate run it found (radius, length, stub distance on each side) so
  you can tell whether the problem is "no round cross-section was found at
  all" (CIRC_TOLERANCE / RADIUS_SPREAD_TOLERANCE too tight for your part's
  actual surface noise) or "a run was found but rejected/misclassified"
  (the stub-distance logic itself) -- worth reading before re-tuning
  blind.
- The tolerances below are starting points, not calibrated against your
  actual parts yet -- expect to tune them once you've run this on a real
  diffuser or two.

Run this from Rhino 8's Script Editor (auto-detection needs the Python 3
engine), or from a toolbar button macro:
    ! _-ScriptEditor _R "full\\path\\to\\cut_cap_polysurface.py"

VERSION HISTORY
----------------
v18 (2026-09-25) - Simplified single-feature mode: "manual behavior is
    chaotic now." The v15/v16 "suggest, pre-select, and let Enter accept
    it" dance around the piece-to-delete prompt added real complexity
    (auto_info vs the axis-guess, suggestion_note wording, pre-select-
    then-prompt) for a case that, on reflection, didn't need a prompt at
    all. Reworked step 4 to a plain either/or: identify_meter_fragment
    (new, factored out of the old inline classification block) is always
    tried first, and when it succeeds the meter piece is just deleted --
    no prompt -- with a printed note on what was deleted/kept and a
    reminder that Undo/Ctrl+Z is right there if it guessed backwards.
    Manual piece-selection (the old rs.GetObjects prompt, unchanged
    otherwise) is now ONLY reached when identification genuinely can't be
    done -- more than two split pieces, or the two couldn't be told
    apart -- rather than always. Also trimmed the low-confidence Use-or-
    Manual prompt from three options down to two (dropped the explicit
    "Cancel" entry; Escape still backs out and returns None same as
    before) to match. The overall single-feature sequence is now exactly:
    (1) attempt auto, (2) if low confidence, Use-or-Manual, (3) if
    manual, curve then 3-point-fallback-if-non-planar (unchanged), (4)
    attempt to identify and delete the meter piece automatically,
    otherwise pick the polysurface(s) to delete by hand.
v17 - Fixed a crash: "ValueError: <guid> does not exist in
    ObjectTable" from rs.ObjectLayer, right after a split, in single-
    feature mode. Root cause: doc.Objects.AddBrep doesn't raise on a
    degenerate/invalid fragment (a sliver, self-intersecting geometry,
    etc.) -- it just returns System.Guid.Empty -- and the code immediately
    after it (setting the fragment's layer) assumed every add had
    succeeded and wasn't checking for that. Now each AddBrep result is
    checked; a failed fragment is skipped and reported instead of trusted,
    and the piece-to-delete/classification logic only ever sees fragments
    that actually made it into the document. Applied the same guard
    everywhere else in the file that calls AddBrep without checking (the
    cap surface(s) in cap_and_join, and the diffuser fragment in
    run_batch_mode) since they share the same latent risk, even though
    only the single-feature-mode case had actually been hit and reported.
v16 - The meter-piece suggestion added in v15 was hard to
    act on: matching a printed object id against unlabeled geometry in
    the viewport is slow, and confirming it still took a click. Now,
    whenever a suggestion is made (either kind, v15's confident or rough-
    guess case), that piece is pre-selected (highlighted) in the viewport
    before the piece-to-delete prompt appears, so it's visually obvious
    which piece the suggestion means -- and the prompt uses preselect=True
    instead of False, so hitting Enter with no further clicking accepts
    that pre-selected piece as the one to delete. Clicking the pre-
    selected piece drops it from the selection (keeps both), and clicking
    the other piece instead selects that one instead -- ordinary Rhino
    click-to-change behavior, nothing new there. When no suggestion could
    be made, the prompt and Enter-keeps-everything behavior are unchanged
    from v15 and earlier.
v15 - "After manual selection of cutting plane, attempt
    auto identification of diffuser": the "suggested meter piece to
    delete" hint used to only appear when a fully confident AUTO plane
    was used (it needs a detected cylindrical run's axis/boundary/free-
    end info to classify the split pieces) -- any manually-picked plane
    (points or curve), or a low-confidence AUTO plane accepted via "Use
    anyway", got no suggestion at all, just the bare piece-picking prompt.
    Added classify_fragments_by_axis: a fallback classifier that reuses
    the same "the shorter stub is the free/meter end" idea auto-detection
    itself relies on, but applied directly to the CHOSEN plane's position
    along the part's own rotational axis (re-deriving that axis via PCA
    if it wasn't already known) rather than requiring a detected
    cylindrical run -- weaker evidence (no roundness/constant-radius
    check at all, just axial position), so it's labeled a "rough guess"
    in the printed suggestion rather than "auto-classified", to set the
    right expectation. auto_find_cutting_plane now also returns axis_pt/
    axis_dir whenever PCA succeeded, even on an otherwise-failed result
    (no cylindrical run found), so this fallback can reuse that axis
    instead of recomputing PCA from scratch when one's already available.
    Factored the axial bounding-box-extent projection (previously inlined
    in auto_find_cutting_plane) out into its own axis_extent helper so
    both places that need it share the same code.
v14 - Cleanup pass, prompted by "unify the view-centering
    settings, they seem to go to slightly different positions/zoom
    levels": the three snap_view_to call sites in single-feature mode
    were computing their radius three different ways. The low-confidence
    preview call always used the real detected radius (result["radius"]),
    but the later piece-to-delete-prompt call only reused that real value
    when a CONFIDENT auto plane was used (via auto_info) -- for the "Use
    anyway" low-confidence path, auto_info is deliberately left unset (see
    v11), so that call silently fell back to a generic bounding-box-
    fraction estimate instead, even for the exact same feature point,
    producing a visibly different zoom between two consecutive snaps of
    the same spot. Fixed by tracking a single feature_radius local: set
    once from the real detected radius whenever auto-detection returns a
    result at all (confident or not), reused by every snap_view_to call
    for the rest of that run, and reset to None only if the user goes on
    to pick a fresh manual plane (which could be an unrelated location/
    scale). The two remaining magic numbers this touched (bbox diagonal /
    2.0 for the whole-part fallback zoom, and * 0.15 for the no-radius-
    known feature fallback) are now named constants,
    WHOLE_PART_ZOOM_FRACTION and FEATURE_ZOOM_FALLBACK_FRACTION, with the
    same values as before (no behavior change to either of those two
    cases by itself). Rest of the file reviewed; no other issues found.
v13 - Found the actual root cause of the premature layer
    move (v11/v12 fixed real but secondary issues in the classification
    logic, not this): doc.Objects.AddBrep gives a new object whatever
    layer is currently ACTIVE in Rhino, not the layer of the object it
    came from. Since the split fragments are added to the document before
    the "select piece(s) to DELETE" prompt even appears, if
    PROCESSED_LAYER_NAME happened to be the active layer (e.g. from
    browsing it to sort through results, which is exactly the workflow
    this layer is for), brand-new undecided fragments would land there
    immediately -- and hiding that layer to review processed results
    would hide them too, before you'd picked anything. Fixed by capturing
    the original object's layer before deleting it and pinning both new
    fragments there explicitly, so nothing about fragment placement
    depends on Rhino's active-layer state anymore. cap_and_join's explicit
    move to PROCESSED_LAYER_NAME afterward is the only thing that ever
    changes a result's layer now.
v12 - v11 only fixed the low-confidence "Use anyway" path;
    a fully CONFIDENT auto-detection still auto-classified, auto-deleted,
    auto-capped, and moved the diffuser to the processed layer with no
    prompt at all -- so layer movement could still happen before you ever
    got to pick a piece, just via a different path than v11 covered.
    Removed that fast path entirely: single-feature mode now ALWAYS shows
    the "select piece(s) to DELETE" prompt, regardless of confidence.
    When classification succeeded, the likely meter piece is printed as a
    suggestion first so it's still quick to confirm, but nothing is ever
    deleted/capped/layer-moved without you picking. Batch mode is
    unaffected -- it's deliberately the one fully-automatic, no-prompt
    path, and stays that way.
v11 - Fixed: choosing "Use anyway" on a low-confidence plane
    still let the SAME shaky detection auto-classify which split fragment
    was the meter and auto-delete + cap + move it to the processed layer,
    with no piece-selection prompt at all -- so the layer move (and the
    deletion decision) could happen before you ever got a say, right after
    you'd only confirmed the plane's location, not which side was which.
    Now "Use anyway" no longer triggers auto-classification -- it falls
    through to the normal "select piece(s) to DELETE" prompt like any
    other manually-confirmed plane, and the layer move only happens once
    that choice is made, at the very end.
v10 - The low-confidence "use this plane anyway?" prompt now
    previews the actual split line before asking: the real curve(s) where
    the candidate plane intersects the polysurface are added to the
    document in bright red for the duration of the prompt, so you can see
    exactly where it would cut instead of judging it from the printed
    radius/message alone. Removed automatically the moment the prompt is
    answered, whatever the answer.
v9 - Single-feature (interactive) mode no longer prompts
    "Find the cutting plane how: Auto/Manual" -- it always attempts
    auto-detection first, immediately, same as it already did once you
    hit Enter on that prompt. Manual is still reached automatically on
    detection failure or low confidence, exactly as before; there's just
    no upfront choice to make (or Enter to hit) when Auto is what you
    always want tried first anyway.
v8 - Manual plane definition no longer prompts Points vs
    Curve -- it goes straight to curve/edge picking by default (usually
    quicker than placing 3 points), and falls back automatically to the
    3-point method only if what got picked isn't a usable planar curve.
    Cancelling the curve pick itself still cancels the whole manual step,
    it doesn't fall through to points.
v7 - Fixed curve selection for the Curve manual-plane option:
    it used rs.GetObject with a curve filter, which only accepts free-
    standing curve objects, not edges of a solid -- so picking the natural
    thing (an edge right on the polysurface) wasn't possible at all.
    Switched to the lower-level GetObject class directly, with
    GeometryFilter + SubObjectSelect set explicitly, and ObjRef.Curve() to
    resolve either a standalone curve or a picked edge into real curve
    geometry -- now both work.
v6 - Every finished result (capped or left open because
    capping wasn't possible) is now moved onto its own layer,
    PROCESSED_LAYER_NAME ("Processed Diffusers" by default, created if it
    doesn't exist) -- applies uniformly across the interactive flow and
    batch mode, since it's done inside cap_and_join itself. Manual plane
    definition now offers a choice of Points (the original 3-point pick)
    or Curve (select a single planar curve anywhere in the document and
    use its own plane directly) -- available everywhere manual picking
    was, including the auto-detection failure/low-confidence fallbacks.
v5 - Batch mode now inverts the display color (255-R, 255-G,
    255-B of whatever the object currently resolves to, explicit or by-
    layer) of anything it skips, in addition to reporting/selecting/
    zooming to it -- makes skipped diffusers visually obvious in the
    viewport at a glance, not just in the console/selection. Part of the
    same undo record as the rest of the batch.
v4 - v3's end-anchoring check (is a run's boundary within a
    small margin of the scanned range's extreme?) turned out to almost
    never fire on real parts, because the meter's actual free end is
    usually cut at an angle -- not perpendicular to the axis -- so the
    round, constant-radius run stops a bit short of the true tip instead
    of running right up to it. Replaced with a relative "stub distance"
    comparison: each run's two ends are scored by how much more part lies
    beyond them out to the scanned range's edge, and whichever run/side
    has the smallest stub of everything found on the part wins, regardless
    of the exact chamfer/bevel length. END_MARGIN_FRACTION and
    END_MARGIN_SLICES are gone (no longer meaningful); added
    STUB_TIE_RATIO (how close two stubs have to be to count as "both look
    free") and BARE_CYLINDER_STUB_RADII (both sides have a tiny stub ->
    the whole part is just one cylinder, nothing to cut).
v3 - Reworked detection after real-part testing showed the
    tool was generally failing to find meters. The old selection logic
    picked the LONGEST round/constant-radius run and only used "does it
    touch a free end" as a soft confidence flag -- so a coincidentally
    long, clean run anywhere on the diffuser could win over the actual
    (possibly shorter) meter run, or a genuine meter run could lose to a
    longer diffuser run and get flagged/skipped instead of chosen. Now
    ONLY runs that touch a free/open end of the part are ever considered
    candidates at all, since the meter is always anchored to an end; the
    old length-based "ambiguity margin" is gone, replaced by "if more than
    one end looks circular, pick the narrower one" (the meter is the
    narrow tube the diffuser flares out from). MIN_RUN_LENGTH_RADII is
    now a confidence flag instead of a hard filter, so a short-but-real
    end-anchored run is still used (flagged), not thrown away.
    CIRC_TOLERANCE and RADIUS_SPREAD_TOLERANCE loosened (0.003->0.01,
    0.006->0.015) since real surfaces are noisier than a perfect analytic
    cylinder. Added run-by-run diagnostics printed on any failure/low-
    confidence result, so the next tuning pass has actual evidence instead
    of guessing again.
v2.3 - MIN_RUN_LENGTH_RADII lowered again (0.2 radii, was 0.5)
    to allow shorter meter sections, with SLICE_COUNT raised (600, was
    400) so those shorter runs still get enough samples to be measured
    reliably. Added batch mode: selecting more than one polysurface at
    the initial prompt runs the fully-automatic path over all of them
    with no per-object prompts, skipping (and reporting/selecting) any
    that aren't a clean, confident detection rather than guessing or
    interrupting the batch to ask.
v2.2 - Whenever the tool pauses for input (the low-confidence
    confirm prompt, a manual-picking fallback, or the piece-to-delete
    prompt), the view now snaps to whatever's relevant at that moment and
    re-centers the rotation pivot there, so you're not hunting around a
    larger model for where it's asking about. Not yet checked against a
    live Rhino session -- flag it if ViewCameraTarget's behavior doesn't
    match what's expected.
v2.1 - Tuned for shorter meter sections after first real-part
    testing: MIN_RUN_LENGTH_RADII lowered (0.5 diameters instead of 1.5
    radii ~ 0.75 diameters) so shorter cylindrical runs still qualify;
    SLICE_COUNT doubled so short runs still get enough samples to measure
    reliably; RADIUS_SPREAD_TOLERANCE tightened so the cylinder-to-diffuser
    transition is flagged as soon as the radius genuinely starts changing,
    instead of drifting a little way into the flare first (which was
    eating into short sections and skewing their measured length); the
    free-end margin now scales with SLICE_COUNT instead of being a fixed
    slice count, so it stays proportionally right as SLICE_COUNT changes.
v2 / RC1 - Added automatic meter-section detection (PCA axis + cross-
    section scan + confidence gating) and automatic piece classification,
    so the 3-point pick is no longer required for the normal case. Manual
    3-point picking is kept as the fallback path.
v1 - Original manual 3-point-plane cut/cap tool, with the plane-shift bug
    fixed (never re-center the picked plane; project the bounding box onto
    it instead). Proven in production use.
"""

import math
import System
import rhinoscriptsyntax as rs
import Rhino
import Rhino.Geometry as rg
from Rhino.Geometry.Intersect import Intersection

SCRIPT_VERSION = "v18"

PROCESSED_LAYER_NAME = "Processed Diffusers"  # every capped/closed (or left-open) result is moved here
SNAP_VIEW_ZOOM_FACTOR = 1.3     # half-width of the snap_view_to framing box, as a multiple of the feature's radius -- lower = tighter zoom
WHOLE_PART_ZOOM_FRACTION = 0.5        # snap_view_to radius when framing the WHOLE part (no feature radius known yet), as a fraction of its bounding-box diagonal
FEATURE_ZOOM_FALLBACK_FRACTION = 0.15 # snap_view_to radius for a feature when no real detected radius is available, as a fraction of the part's bounding-box diagonal

# ---- tunable constants for auto-detection -----------------------------
AXIS_SAMPLE_GRID = 10           # per-face u,v sample grid density for the PCA axis fit
SLICE_COUNT = 600               # number of cross-sections scanned along the axis
CIRC_TOLERANCE = 0.01           # max (max-min)/mean radius WITHIN one slice, to count as round
RADIUS_SPREAD_TOLERANCE = 0.015 # max (max-min)/mean radius ACROSS a run, to count as constant-radius
MIN_RUN_LENGTH_RADII = 0.2      # below this, the winning run is still used but flagged low confidence
STUB_TIE_RATIO = 3.0            # a run's stub within this factor of the smallest stub is also treated as "could be free"
BARE_CYLINDER_STUB_RADII = 2.0  # a lone run with < this many radii of stub on BOTH sides -> no transition, nothing to cut
BISECTION_ITERS = 25


def get_target_polysurfaces():
    """User selects one or more polysurfaces (or surfaces) to work on.
    A single selection runs the normal interactive flow; more than one
    switches to batch mode (see run_batch_mode). Returns a list of
    (object_id, Brep) pairs, skipping anything that doesn't coerce to a
    Brep (with a warning), or [] if cancelled."""
    obj_ids = rs.GetObjects(
        "Select the polysurface(s) to cut (select more than one for batch mode)",
        filter=rs.filter.surface | rs.filter.polysurface,
        preselect=True)
    if not obj_ids:
        return []

    pairs = []
    for obj_id in obj_ids:
        brep = rs.coercebrep(obj_id)
        if brep is None:
            print("Skipping {} -- not a surface or polysurface.".format(obj_id))
            continue
        pairs.append((obj_id, brep))
    return pairs


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
    """Manual fallback: user picks 3 points on the polysurface; returns a
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
    """Manual fallback: user picks a single planar curve -- a free-standing
    curve object, OR an edge on the polysurface (or any other object) in
    the document -- and its own plane becomes the cutting plane.

    Uses the lower-level GetObject class directly (same reason
    get_point_on_brep does, rather than the rs.GetObject wrapper):
    rs.GetObject's curve filter only accepts free-standing curve objects,
    not edges of a solid -- but an edge is often exactly what you want to
    click (e.g. the naked edge right at a meter/diffuser transition), so
    GeometryFilter + SubObjectSelect are set directly to allow picking
    either kind, and ObjRef.Curve() resolves whichever was picked into
    actual curve geometry either way.

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
        print("That wasn't a valid curve -- falling back to picking 3 points instead.")
        return "invalid", None

    ok, plane = curve.TryGetPlane(tolerance)
    if not ok:
        print("That curve isn't planar -- falling back to picking 3 points instead.")
        return "invalid", None
    if not plane.IsValid:
        print("That curve's plane came back invalid -- falling back to picking 3 points instead.")
        return "invalid", None
    return "ok", plane


def pick_manual_plane(target_brep, tolerance):
    """Defines the cutting plane by hand. Defaults straight to picking a
    curve or edge, no prompt -- there's usually already a curve or edge
    marking the cut, and it's quicker than placing 3 points individually.
    If that pick isn't a usable planar curve, falls back automatically to
    the original 3-point method instead. An outright cancel of the curve
    pick cancels the whole manual step rather than falling through to
    points -- that's a deliberate "never mind" from the user, not a bad
    pick.

    Used everywhere manual plane picking happens: the top-level Manual
    mode, and both auto-detection fallback paths. Returns a
    Rhino.Geometry.Plane, or None if cancelled."""
    status, plane = get_cutting_plane_from_curve(tolerance)
    if status == "ok":
        return plane
    if status == "cancelled":
        return None
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
    layer(s) the original polysurfaces were on."""
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


# ---- auto-detection ------------------------------------------------------

def pca_axis(brep):
    """Rough rotational axis of brep via PCA on a sampled point cloud from
    all its faces. Returns (axis_point, axis_direction) or None."""
    pts = []
    for face in brep.Faces:
        u0, u1 = face.Domain(0).T0, face.Domain(0).T1
        v0, v1 = face.Domain(1).T0, face.Domain(1).T1
        for iu in range(AXIS_SAMPLE_GRID):
            u = u0 + (u1 - u0) * iu / float(AXIS_SAMPLE_GRID - 1)
            for iv in range(AXIS_SAMPLE_GRID):
                v = v0 + (v1 - v0) * iv / float(AXIS_SAMPLE_GRID - 1)
                if face.IsPointOnFace(u, v) == rg.PointFaceRelation.Exterior:
                    continue
                pts.append(face.PointAt(u, v))

    if len(pts) < 10:
        return None

    n = len(pts)
    cx = sum(p.X for p in pts) / n
    cy = sum(p.Y for p in pts) / n
    cz = sum(p.Z for p in pts) / n

    sxx = syy = szz = sxy = sxz = syz = 0.0
    for p in pts:
        dx, dy, dz = p.X - cx, p.Y - cy, p.Z - cz
        sxx += dx * dx
        syy += dy * dy
        szz += dz * dz
        sxy += dx * dy
        sxz += dx * dz
        syz += dy * dz
    sxx /= n; syy /= n; szz /= n; sxy /= n; sxz /= n; syz /= n

    # Power iteration for the dominant eigenvector of the covariance matrix
    # -- all that's needed is the longest axis, seeded with the bounding
    # box diagonal (already close to the true axis for an elongated part,
    # so this converges in a handful of steps; no numpy required).
    bbox = brep.GetBoundingBox(True)
    seed = bbox.Max - bbox.Min
    if seed.Length < 1e-9:
        seed = rg.Vector3d(1, 0, 0)
    vx, vy, vz = seed.X, seed.Y, seed.Z

    for _ in range(60):
        nx = sxx * vx + sxy * vy + sxz * vz
        ny = sxy * vx + syy * vy + syz * vz
        nz = sxz * vx + syz * vy + szz * vz
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if length < 1e-12:
            return None
        vx, vy, vz = nx / length, ny / length, nz / length

    axis_dir = rg.Vector3d(vx, vy, vz)
    axis_dir.Unitize()
    axis_pt = rg.Point3d(cx, cy, cz)
    return axis_pt, axis_dir


class _Slice(object):
    __slots__ = ("t", "valid", "radius", "dev")

    def __init__(self, t):
        self.t = t
        self.valid = False
        self.radius = None
        self.dev = None


def scan_cross_section(brep, axis_pt, axis_dir, t, tolerance):
    """Intersects brep with the plane perpendicular to axis_dir at
    axis_pt + t*axis_dir. Valid only if exactly one closed curve results."""
    slc = _Slice(t)
    plane = rg.Plane(axis_pt + axis_dir * t, axis_dir)
    ok, curves, _pts = Intersection.BrepPlane(brep, plane, tolerance)
    if not ok or not curves or len(curves) != 1:
        return slc
    curve = curves[0]
    if not curve.IsClosed:
        return slc

    amp = rg.AreaMassProperties.Compute(curve)
    if amp is None:
        return slc
    center = amp.Centroid

    sample_n = 24
    t0, t1 = curve.Domain.T0, curve.Domain.T1
    dists = []
    for k in range(sample_n):
        tp = t0 + (t1 - t0) * k / float(sample_n)
        dists.append(curve.PointAt(tp).DistanceTo(center))
    mean_r = sum(dists) / len(dists)
    if mean_r < 1e-9:
        return slc

    slc.valid = True
    slc.radius = mean_r
    slc.dev = (max(dists) - min(dists)) / mean_r
    return slc


def find_cylinder_runs(slices):
    """Greedy grouping of contiguous slices into round, constant-radius runs.
    Returns a list of (start_index, end_index, mean_radius) tuples."""
    runs = []
    n = len(slices)
    i = 0
    while i < n:
        s = slices[i]
        if not s.valid or s.dev > CIRC_TOLERANCE:
            i += 1
            continue
        j = i
        radii = [s.radius]
        while j + 1 < n:
            nxt = slices[j + 1]
            if not nxt.valid or nxt.dev > CIRC_TOLERANCE:
                break
            trial = radii + [nxt.radius]
            spread = (max(trial) - min(trial)) / (sum(trial) / len(trial))
            if spread > RADIUS_SPREAD_TOLERANCE:
                break
            radii = trial
            j += 1
        runs.append((i, j, sum(radii) / len(radii)))
        i = j + 1
    return runs


def evaluate_runs(slices, runs, t_min, t_max):
    """Picks the meter candidate among round, constant-radius runs.

    Circularity + constant radius are necessary but NOT sufficient -- the
    diffuser itself can produce a run like that somewhere along its length.
    What actually identifies the meter is that one end of it sits at a
    free/open end of the part -- but real parts are usually cut at an
    angle right at that tip, not perpendicular to the axis, so the round
    run stops a bit short of the true physical end instead of running
    right up to it. So rather than checking proximity to the scanned
    range's extreme, each run's two ends are scored by their STUB -- how
    much more of the part lies beyond that end, out to the scanned range's
    edge on that side. The true free end should only have a small stub
    (a chamfer, a bit of fitting geometry, or nothing) before the part
    truly ends; the transition end always has a lot more part beyond it --
    the whole diffuser body. Whichever run/side has the smallest stub of
    everything found on the part is taken as the meter's free end -- a
    relative comparison across all runs, not a fixed distance, so it isn't
    thrown off by how long the chamfer happens to be.

    Returns (best_run, at_start, confident, message, run_summaries).
    run_summaries lists every run found (including non-winners) for
    diagnostic printing on failure/low confidence."""
    run_summaries = []
    candidates = []
    for (i, j, mean_r) in runs:
        length = slices[j].t - slices[i].t
        before = slices[i].t - t_min   # stub distance if the free end is the low-t side
        after = t_max - slices[j].t    # stub distance if the free end is the high-t side
        run_summaries.append({
            "t_start": slices[i].t, "t_end": slices[j].t,
            "length": length, "radius": mean_r,
            "before": before, "after": after,
        })
        if mean_r > 0:
            candidates.append((i, j, mean_r, length, before, after))

    if not candidates:
        return None, None, False, "no round cross-section found anywhere along the axis", run_summaries

    # a lone run with only a tiny stub on BOTH sides means the whole part
    # reads as one constant-radius cylinder end-to-end -- no diffuser
    # transition anywhere, nothing to cut
    if len(candidates) == 1:
        _i, _j, mean_r, _length, before, after = candidates[0]
        if before <= BARE_CYLINDER_STUB_RADII * mean_r and after <= BARE_CYLINDER_STUB_RADII * mean_r:
            return None, None, False, "the whole part scans as one constant-radius cylinder -- no meter/diffuser transition found", run_summaries

    # each run's smaller-stub side is its candidate free end
    scored = []
    for (i, j, mean_r, length, before, after) in candidates:
        if before <= after:
            scored.append((before, True, i, j, mean_r, length))   # free end is the low-t side
        else:
            scored.append((after, False, i, j, mean_r, length))   # free end is the high-t side
    scored.sort(key=lambda s: s[0])  # smallest stub first

    stub, at_start, i, j, mean_r, length = scored[0]

    reasons = []
    if len(scored) > 1 and scored[1][0] <= STUB_TIE_RATIO * stub + 1e-9:
        near_ties = [s for s in scored if s[0] <= STUB_TIE_RATIO * stub + 1e-9]
        near_ties.sort(key=lambda s: s[4])  # narrowest radius first
        stub, at_start, i, j, mean_r, length = near_ties[0]
        reasons.append("{} ends looked like they could be free -- picked the narrowest as the meter (diffuser flares out from it)".format(len(near_ties)))

    if length < MIN_RUN_LENGTH_RADII * mean_r:
        reasons.append("run is shorter than the usual minimum ({:.2f} vs {:.2f} radii)".format(length / mean_r if mean_r else 0.0, MIN_RUN_LENGTH_RADII))

    confident = not reasons
    message = "; ".join(reasons) if reasons else "single clear candidate, anchored to the {} end (stub past it: {:.3f})".format("start" if at_start else "far", stub)
    return (i, j, mean_r, length), at_start, confident, message, run_summaries


def describe_runs(run_summaries):
    """Human-readable dump of every candidate run found, for diagnosing a
    failed or low-confidence detection -- tells you whether the problem is
    'nothing round was found at all' vs 'something was found but not
    picked as the meter'."""
    if not run_summaries:
        return "  (no round cross-section found anywhere along the axis)"
    lines = []
    for r in run_summaries:
        lines.append("  - radius~{:.3f} over length {:.3f} (stub before: {:.3f}, stub after: {:.3f})".format(
            r["radius"], r["length"], r["before"], r["after"]))
    return "\n".join(lines)


def refine_transition(brep, axis_pt, axis_dir, slices, run, at_start, tolerance):
    """Bisects between the last good sample and the first bad one at the
    non-free end of run to find a precise transition axial parameter t."""
    i, j, mean_r, _length = run
    n = len(slices)

    if at_start:
        lo_t, hi_t = slices[j].t, slices[min(j + 1, n - 1)].t
    else:
        lo_t, hi_t = slices[max(i - 1, 0)].t, slices[i].t

    for _ in range(BISECTION_ITERS):
        mid_t = (lo_t + hi_t) / 2.0
        slc = scan_cross_section(brep, axis_pt, axis_dir, mid_t, tolerance)
        good = (slc.valid and slc.dev <= CIRC_TOLERANCE
                and abs(slc.radius - mean_r) / mean_r <= RADIUS_SPREAD_TOLERANCE)
        if at_start:
            if good:
                lo_t = mid_t
            else:
                hi_t = mid_t
        else:
            if good:
                hi_t = mid_t
            else:
                lo_t = mid_t

    return (lo_t + hi_t) / 2.0


def axis_extent(brep, axis_pt, axis_dir):
    """Returns (t_min, t_max): brep's bounding-box corners' axial
    positions, projected onto axis_dir from axis_pt -- i.e. how far the
    part's bounding box reaches to either side along that axis. No margin
    is added here; callers that need one (e.g. for slice scanning near
    the true ends) add it themselves."""
    bbox = brep.GetBoundingBox(True)
    ts = [(c - axis_pt) * axis_dir for c in bbox.GetCorners()]
    return min(ts), max(ts)


def auto_find_cutting_plane(brep, tolerance):
    """Returns a dict describing the result:
      status: "ok" | "failed"
      plane, t_boundary, free_end_t, radius: (if ok)
      axis_pt, axis_dir: known whenever PCA succeeded, which includes
          some "failed" results (only the run-finding failed) -- None
          only when PCA itself couldn't find an axis at all. Callers that
          want to reuse the axis without recomputing PCA (e.g.
          classify_fragments_by_axis after a manual plane pick) should
          check these rather than assuming they're only present on "ok".
      confident (bool), message (str), all_runs (list, for diagnostics)
    """
    axis = pca_axis(brep)
    if axis is None:
        return {"status": "failed",
                "message": "could not determine a rotational axis (too few sample points, or a degenerate shape)",
                "all_runs": [], "axis_pt": None, "axis_dir": None}
    axis_pt, axis_dir = axis

    t_min, t_max = axis_extent(brep, axis_pt, axis_dir)
    margin = (t_max - t_min) * 0.02
    t_min -= margin
    t_max += margin

    slices = [scan_cross_section(brep, axis_pt, axis_dir,
                                  t_min + (t_max - t_min) * k / float(SLICE_COUNT - 1),
                                  tolerance)
              for k in range(SLICE_COUNT)]

    runs = find_cylinder_runs(slices)
    best, at_start, confident, message, run_summaries = evaluate_runs(slices, runs, t_min, t_max)
    if best is None:
        return {"status": "failed", "message": message, "all_runs": run_summaries,
                "axis_pt": axis_pt, "axis_dir": axis_dir}

    i, j, mean_r, _length = best
    t_boundary = refine_transition(brep, axis_pt, axis_dir, slices, best, at_start, tolerance)
    free_end_t = t_min if at_start else t_max

    plane = rg.Plane(axis_pt + axis_dir * t_boundary, axis_dir)
    return {
        "status": "ok",
        "plane": plane,
        "axis_pt": axis_pt,
        "axis_dir": axis_dir,
        "t_boundary": t_boundary,
        "free_end_t": free_end_t,
        "radius": mean_r,
        "confident": confident,
        "message": message,
        "all_runs": run_summaries,
    }


def classify_fragment_is_meter(frag_brep, axis_pt, axis_dir, t_boundary, free_end_t):
    """True if frag_brep lies mostly on the free/open (meter) side of t_boundary."""
    center = frag_brep.GetBoundingBox(True).Center
    t = (center - axis_pt) * axis_dir
    return (t < t_boundary) if free_end_t < t_boundary else (t > t_boundary)


def classify_fragments_by_axis(target_brep, plane, fragments, axis_pt=None, axis_dir=None):
    """Best-effort guess at which of the two split fragments is the meter,
    for whenever there's no confident auto-detected run to lean on
    already -- i.e. after any manually-picked plane (points or curve), or
    after accepting a low-confidence auto plane via "Use anyway". Reuses
    auto-detection's own "the shorter stub is the free/meter end" idea,
    just applied directly to THIS plane's position along the part's
    rotational axis instead of a detected cylindrical run: whichever side
    of the plane has less of the whole part beyond it is taken as the
    meter's free end. This is a weaker signal than a real detected run
    (no roundness/constant-radius check at all, just axial position), so
    callers should present it as a rougher guess, not a confident one.

    Pass axis_pt/axis_dir if already known (e.g. from the
    auto_find_cutting_plane call that ran before manual picking took
    over) to skip recomputing PCA; otherwise it's derived fresh from
    target_brep. Returns the index (0 or 1) of the guessed meter fragment
    in fragments, or None if no axis could be determined at all, or the
    plane sits about in the middle (the two sides look about the same,
    too close to call)."""
    if axis_pt is None or axis_dir is None:
        axis = pca_axis(target_brep)
        if axis is None:
            return None
        axis_pt, axis_dir = axis

    t_min, t_max = axis_extent(target_brep, axis_pt, axis_dir)
    t_boundary = (plane.Origin - axis_pt) * axis_dir
    before, after = t_boundary - t_min, t_max - t_boundary
    free_end_t = t_min if before <= after else t_max

    flags = [classify_fragment_is_meter(frag, axis_pt, axis_dir, t_boundary, free_end_t) for frag in fragments]
    if flags[0] == flags[1]:
        return None
    return 0 if flags[0] else 1


def identify_meter_fragment(target_brep, plane, frag_breps, frag_ids, auto_info, axis_pt, axis_dir):
    """Best-effort automatic identification of which of exactly two split
    fragments is the meter (the piece single-feature mode should delete
    without asking). Prefers a confident auto-detected cylindrical run
    (auto_info) when available, via classify_fragment_is_meter -- the
    trustworthy case -- and falls back to the weaker axis-position guess
    (classify_fragments_by_axis) otherwise, reusing axis_pt/axis_dir if
    already known rather than recomputing PCA. Returns the meter
    fragment's object id, or None if there aren't exactly two fragments,
    or the two couldn't be told apart -- the caller's cue to fall back to
    manual selection instead."""
    if len(frag_breps) != 2:
        return None

    if auto_info is not None:
        flags = [
            classify_fragment_is_meter(frag, auto_info["axis_pt"], auto_info["axis_dir"],
                                        auto_info["t_boundary"], auto_info["free_end_t"])
            for frag in frag_breps
        ]
        if flags[0] == flags[1]:
            return None
        return frag_ids[0] if flags[0] else frag_ids[1]

    idx = classify_fragments_by_axis(target_brep, plane, frag_breps, axis_pt, axis_dir)
    return frag_ids[idx] if idx is not None else None


def snap_view_to(center_pt, radius):
    """Zooms the active viewport to frame center_pt (sized off radius) and
    re-centers the view's target there too, so it becomes the rotation
    pivot -- called right before any prompt that needs you to look at (or
    orbit around) a specific spot, instead of leaving you to go hunt for it
    on a possibly much larger model. Best-effort: a view-API hiccup here
    should never block the actual geometry operation, so failures are
    swallowed with a short printed note.

    NOTE: this hasn't been checked against a live Rhino session -- if
    ViewCameraTarget's exact call signature doesn't match what's below,
    flag it and this is a quick fix.
    """
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


def preview_split_curves(brep, plane, tolerance):
    """Adds the actual curve(s) where plane intersects brep to the
    document, in a bright, distinct color, as a temporary visual -- so a
    low-confidence plane can be SEEN (exactly where the split line will
    land) before deciding whether to use it, instead of judging it from
    the printed radius/message alone. Returns the list of added object
    ids (possibly empty on failure) for the caller to remove afterward
    with clear_preview, regardless of what gets decided. Best-effort: a
    failed preview should never block the real operation."""
    try:
        ok, curves, _pts = Intersection.BrepPlane(brep, plane, tolerance)
        if not ok or not curves:
            return []
        doc = Rhino.RhinoDoc.ActiveDoc
        ids = []
        for curve in curves:
            cid = doc.Objects.AddCurve(curve)
            if cid != System.Guid.Empty:
                rs.ObjectColor(cid, (255, 40, 40))
                rs.ObjectName(cid, "cutting plane preview -- not part of the model")
                ids.append(cid)
        rs.Redraw()
        return ids
    except Exception as ex:
        print("  (couldn't preview the split line: {})".format(ex))
        return []


def clear_preview(preview_ids):
    """Deletes temporary preview objects added by preview_split_curves.
    Best-effort, always safe to call even with an empty list."""
    for pid in preview_ids:
        try:
            rs.DeleteObject(pid)
        except Exception:
            pass
    if preview_ids:
        rs.Redraw()


def invert_object_color(obj_id):
    """Inverts obj_id's current display color (whatever it resolves to --
    an explicit object color, by-layer, by-parent, etc.) and sets it
    explicitly on the object, so a skipped item visually stands out in the
    viewport no matter what color its layer happens to be. Best-effort:
    a failure here should never block the batch, so it's swallowed with a
    short printed note."""
    try:
        current = rs.ObjectColor(obj_id)  # already resolved to the effective display color
        inverted = (255 - current.R, 255 - current.G, 255 - current.B)
        rs.ObjectColor(obj_id, inverted)
    except Exception as ex:
        print("  (couldn't invert color on {}: {})".format(obj_id, ex))


def run_batch_mode(targets, tolerance):
    """Runs the fully-automatic detect -> split -> delete meter -> cap
    diffuser pipeline over several polysurfaces with no per-object prompts.
    Anything that isn't a clean, confident auto-detection (or that doesn't
    split the way expected) is left completely untouched, with its display
    color inverted for visual identification, rather than risking a wrong
    automatic guess or stopping mid-batch to ask -- it's reported and
    selected at the end too, for you to run through the normal single-
    object flow one at a time."""
    doc = Rhino.RhinoDoc.ActiveDoc
    print("Batch mode: {} polysurface(s) selected. Auto-detection only -- "
          "anything not clean and confident is left untouched (and its "
          "color inverted).".format(len(targets)))

    done, skipped = [], []

    undo_serial = doc.BeginUndoRecord("Batch cut and cap polysurfaces")
    try:
        for obj_id, brep in targets:
            result = auto_find_cutting_plane(brep, tolerance)
            if result["status"] == "failed":
                skipped.append((obj_id, "no candidate cylinder found ({})".format(result["message"]), result["all_runs"]))
                continue
            if not result["confident"]:
                skipped.append((obj_id, "low confidence ({})".format(result["message"]), result["all_runs"]))
                continue

            cutter_brep = build_oversized_cutter(result["plane"], brep)
            fragments = brep.Split(cutter_brep, tolerance)
            if not fragments or len(fragments) != 2:
                n = len(fragments) if fragments else 0
                skipped.append((obj_id, "split produced {} piece(s), expected 2".format(n), []))
                continue

            flags = [
                classify_fragment_is_meter(frag, result["axis_pt"], result["axis_dir"],
                                            result["t_boundary"], result["free_end_t"])
                for frag in fragments
            ]
            if flags[0] == flags[1]:
                skipped.append((obj_id, "could not tell the two split pieces apart", []))
                continue

            diffuser_frag = fragments[1] if flags[0] else fragments[0]
            # the meter-side fragment is simply never added to the document

            rs.DeleteObject(obj_id)
            diffuser_id = doc.Objects.AddBrep(diffuser_frag)
            if diffuser_id == System.Guid.Empty:
                # AddBrep failed on the diffuser fragment (degenerate
                # geometry) -- the original is already deleted and the
                # meter side was never added on purpose, so there's
                # nothing left in the document for this one. Reported so
                # it's visible rather than silently vanishing; the whole
                # batch's undo record (below) can still get the original
                # back if needed.
                skipped.append((obj_id, "the diffuser fragment could not be added to the document after splitting (invalid geometry) -- original already removed, use Undo to recover it", []))
                continue
            result_id = cap_and_join(diffuser_id, tolerance)
            done.append((obj_id, result_id))

        # inverting colors here too, before the undo record closes, so one
        # Ctrl+Z reverts the whole batch -- geometry changes and coloring
        # together
        for obj_id, _reason, _all_runs in skipped:
            invert_object_color(obj_id)
    finally:
        doc.EndUndoRecord(undo_serial)
        rs.Redraw()

    print("")
    print("Batch done: {} processed, {} skipped.".format(len(done), len(skipped)))
    if skipped:
        print("Skipped (left untouched but color-inverted for visual ID -- re-run this "
              "tool on just these, one at a time, to resolve via the manual/confirm flow):")
        skipped_ids = []
        for obj_id, reason, all_runs in skipped:
            print("  - {}: {}".format(obj_id, reason))
            if all_runs:
                print(describe_runs(all_runs))
            skipped_ids.append(obj_id)
        try:
            rs.UnselectAllObjects()
            rs.SelectObjects(skipped_ids)
            rs.ZoomSelected()
        except Exception as ex:
            print("  (couldn't select/zoom the skipped pieces: {})".format(ex))


def main():
    print("cut_cap_polysurface.py - {}".format(SCRIPT_VERSION))

    doc = Rhino.RhinoDoc.ActiveDoc
    tolerance = doc.ModelAbsoluteTolerance

    targets = get_target_polysurfaces()
    if not targets:
        return

    if len(targets) > 1:
        run_batch_mode(targets, tolerance)
        return

    target_id, target_brep = targets[0]

    plane = None
    auto_info = None
    # the real detected feature radius, once known -- reused by every
    # snap_view_to call below for this run so the zoom level stays
    # consistent for the same spot instead of each call site computing its
    # own differently-scaled estimate. Reset to None if the user ends up
    # picking a fresh manual plane, since that could be an unrelated
    # location/scale that the old detected radius has nothing to do with.
    feature_radius = None

    # single-feature mode always attempts auto-detection first, straight
    # away -- no "Auto or Manual" prompt to hit Enter through. Manual is
    # still reached automatically on failure or low confidence below.
    result = auto_find_cutting_plane(target_brep, tolerance)
    if result["status"] == "failed":
        print("Auto-detection failed ({}) -- falling back to manual picking.".format(result["message"]))
        if result["all_runs"]:
            print(describe_runs(result["all_runs"]))
        bbox = target_brep.GetBoundingBox(True)
        snap_view_to(bbox.Center, bbox.Diagonal.Length * WHOLE_PART_ZOOM_FRACTION)
        plane = pick_manual_plane(target_brep, tolerance)
        if plane is None:
            return
    else:
        print("Auto-detected cylindrical section: radius ~{:.3f}, {}.".format(result["radius"], result["message"]))
        feature_radius = result["radius"]
        if not result["confident"]:
            print(describe_runs(result["all_runs"]))
            feature_pt = result["axis_pt"] + result["axis_dir"] * result["t_boundary"]
            snap_view_to(feature_pt, feature_radius)
            preview_ids = preview_split_curves(target_brep, result["plane"], tolerance)
            try:
                # Two options: use it, or take over manually. Escape still
                # backs out entirely (choice comes back None) without a
                # separate "Cancel" entry cluttering the list.
                choice = rs.GetString(
                    "Detection confidence is low (split line previewed in red). Use this plane, "
                    "or define it manually?",
                    "Use", ["Use", "Manual"])
            finally:
                clear_preview(preview_ids)
            if choice is None:
                print("Cancelled.")
                return
            if choice.lower().startswith("m"):
                plane = pick_manual_plane(target_brep, tolerance)
                if plane is None:
                    return
                feature_radius = None
            else:
                # Plane confirmed, but auto_info stays unset -- the same
                # shaky detection that made this plane low-confidence
                # isn't trustworthy for classifying the pieces either, so
                # it's treated like a manual plane from here on (the
                # weaker axis-position guess below, not the confident
                # classifier). feature_radius IS kept, though -- the
                # plane's location is confirmed either way.
                plane = result["plane"]
        else:
            plane = result["plane"]
            auto_info = result

    cutter_brep = build_oversized_cutter(plane, target_brep)

    undo_serial = doc.BeginUndoRecord("Cut and cap polysurface")
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
        # frag_breps/frag_ids are kept in lock-step so every fragment used
        # below actually exists in the document.
        frag_breps, frag_ids = [], []
        for frag in fragments:
            fid = doc.Objects.AddBrep(frag)
            if fid == System.Guid.Empty:
                print("  Warning: a split fragment could not be added to the document (invalid geometry) -- skipped.")
                continue
            rs.ObjectLayer(fid, original_layer)
            frag_breps.append(frag)
            frag_ids.append(fid)
        rs.Redraw()

        if not frag_ids:
            print("None of the split pieces could be added to the document. Nothing was changed.")
            return

        radius_hint = feature_radius if feature_radius is not None else target_brep.GetBoundingBox(True).Diagonal.Length * FEATURE_ZOOM_FALLBACK_FRACTION
        snap_view_to(plane.Origin, radius_hint)

        # Step 4: try to identify the meter piece and delete it
        # automatically -- prefers the confident auto-detected classifier
        # when a trustworthy run backs it (auto_info), otherwise the
        # weaker axis-position guess (see identify_meter_fragment). Only
        # when that identification isn't possible at all -- more than two
        # pieces came out of the split, or the two pieces couldn't be told
        # apart -- do you pick by hand instead. (Batch mode is the
        # separate, deliberately fully-automatic, no-fallback path -- see
        # run_batch_mode.)
        meter_id = identify_meter_fragment(target_brep, plane, frag_breps, frag_ids, auto_info,
                                            result.get("axis_pt"), result.get("axis_dir"))

        if meter_id is not None:
            keep_id = frag_ids[1] if frag_ids[0] == meter_id else frag_ids[0]
            rs.DeleteObject(meter_id)
            print("Identified and deleted the meter piece ({}); kept {} -- Undo (Ctrl+Z) if that's "
                  "backwards.".format(meter_id, keep_id))
            result_id = cap_and_join(keep_id, tolerance)
            print("Done. Piece kept and processed: {}".format(result_id))
        else:
            if len(frag_breps) == 2:
                print("Could not tell the two pieces apart automatically -- pick by hand below.")
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
