#! python 3
"""
Build a laser job file (.sp extension, CSV content: Active, ID|S, X, Y, Z,
B, C, Pen, L3D|S, plus any custom columns you want) by matching a CSV (ID,
X, Y, Z, I, J, K -- the same format used by attach_UAdata_to_closest_mesh.py)
against a .MACH file exported by the Rhino CAM, pulling each matched row's
motion coordinates (X, Y, Z, B, C), its .l3d slicing filename, and the laser
"pen" (the P value of the most recent M111 line above that row).

WHAT A .MACH FILE LOOKS LIKE (see MACH FILE FORMAT below for the full story)
-----------------------------------------------------------------------------
    // Strategy: PT-S Group: 3 Slicing 1-80
    M111 P2
    G00.1 R4 T1 H0 X22.5 Y0.7648 Z290.0 B62.1 C-54.5 S0
    *po=0,0,0 aw=1 pangle=0 lr=0.1,"FullOutput1_PT-S_g3_p1_1.l3d"*

Each such block is one "processing row": a Group comment, an optional M111
pen-select line, the G00.1 motion line carrying X/Y/Z/B/C, and a *po=...*
line carrying the .l3d filename in quotes.

OUTPUT FILE
------------
Written with a .sp extension (not .csv) -- the content is still plain CSV,
just saved under the extension the downstream job expects. One row per
input CSV row, always -- nothing is silently dropped. Columns:

    Active | ID|S | X | Y | Z | B | C | Pen | L3D|S | <your custom columns>

  ID and L3D carry a "|S" suffix on their header to mark them as
  string-typed columns (every other column here is numeric and needs no
  suffix) -- this is the downstream job format's own type-tagging
  convention, not something this script invents.

  - Active is 1 for a row that was successfully matched to a .MACH
    processing row (within tolerance, and not lost to a closer competing
    row). It's 0 for anything that wasn't -- bad/missing X,Y,Z in the
    source CSV, no .MACH row close enough, or it lost a tie-break -- with
    X/Y/Z/B/C/Pen/L3D|S left blank on that row. The point is that a row
    that couldn't be matched still shows up in the file, flagged off,
    rather than just disappearing -- see WHAT THIS SCRIPT DOES step 6.
  - X, Y, Z, B, C, Pen, L3D|S all come from the matched .MACH processing
    row, NOT from the source CSV (the source CSV's own X/Y/Z are only used
    to find the match -- see MATCHING AND MATCH_AXES -- and aren't carried
    into the output).
  - Any names listed in CUSTOM_COLUMNS below are appended after L3D|S, always
    filled with 0, for values that have to be typed in by hand afterward.

WHAT THIS SCRIPT DOES
----------------------
1. Prompts you to select the CSV file (ID, X, Y, Z required; I, J, K and any
   other columns are read but not carried into the output -- see OUTPUT FILE).
2. Prompts you to select the .MACH file.
3. Parses every processing row out of the .MACH file (see MACH FILE FORMAT).
4. Prompts for a max match distance (0 = no limit, which is the default --
   see MATCHING AND MATCH_AXES below for why there's no natural default
   here the way there is for the mesh-matching tools).
5. For every CSV row, finds the closest .MACH processing row by position
   (see MATCHING AND MATCH_AXES). If two CSV rows are both closest to the
   same .MACH row, the closer one wins and the other counts as unmatched
   (same closest-wins convention as attach_UAdata_to_closest_mesh.py) --
   each .MACH processing row is physically a single laser job step, so it
   should only ever end up attached to one part feature.
6. Writes one output row per CSV row (see OUTPUT FILE) and appends every
   column listed in CUSTOM_COLUMNS, filled with 0.
7. Prompts for where to save the job file, as .sp (your original CSV file
   is never modified).
8. Prints a full summary: how many rows were matched (i.e. came out
   Active=1), the resulting match-distance range (READ THIS -- see MATCHING
   AND MATCH_AXES), any .MACH processing rows that were never claimed, and
   every CSV row that came out Active=0 (and why).

MACH FILE FORMAT
-----------------
Header lines (O0001, G95 R5, ...) before the first Group comment are
ignored. From there, the file is a sequence of blocks, each block being:
  - a comment line containing "Group: <n>" -- this starts a new block and
    is where the group number comes from.
  - optionally, a line "M111 P<n>" -- sets the current pen value. This is
    NOT required in every block: if a block has no M111 of its own, it
    inherits whatever pen value was most recently set by an M111 line
    ABOVE IT, however many blocks back that was (in the sample file, only
    blocks 1, 3, and 4 have their own M111 line; blocks 2 and 5 inherit
    pen=1 and pen=1 respectively from the M111 lines above them).
  - a motion line carrying the X/Y/Z/B/C values, detected by looking for an
    "X<number>" token rather than by matching "G00.1" literally, so small
    G-code variations between jobs don't break the parser. Whatever pen
    value is current AT THIS LINE (not at the block's comment line, in case
    an M111 appears in between) is frozen onto this block.
  - a "*po=...,"<filename>.l3d"*" line, which supplies the .l3d filename and
    closes out the block.
A block missing its motion line or its .l3d line when the next Group
comment (or the end of the file) is reached is discarded and reported as a
warning rather than silently guessed at.

MATCHING AND MATCH_AXES
-------------------------
The .MACH file has no ID field of its own, so CSV rows are matched to
.MACH processing rows by closest position -- the CSV row's (X, Y, Z) versus
each processing row's motion (X, Y, Z), using plain brute-force distance
(there's no RTree acceleration here on purpose: the row counts involved are
small enough that it isn't needed, and it keeps this script's matching core
pure Python and unit-testable without RhinoCommon).

IMPORTANT CAVEAT: the .MACH file's X/Y/Z/B/C are motion-system coordinates
from the CAM output, which may or may not share an origin/frame with your
CSV's X/Y/Z (which usually come from the Rhino model). If they don't share
a frame, the closest-position match can come out wrong, and a common tell
is every matched row's distance being suspiciously large and similar in
size. ALWAYS check the printed match-distance range after running this the
first time on a new CSV/.MACH pair. If it looks wrong, set MATCH_AXES to
"XY" below and re-run -- this ignores Z entirely, which is the more likely
axis to disagree between the two coordinate systems (a laser head's Z is
often a large near-constant standoff/focus distance rather than a
part-local height).

Run this from Rhino's Python script editor (EditPythonScript / _RunPythonScript),
or from a toolbar button macro:
    ! _-ScriptEditor _R "full\\path\\to\\augment_csv_with_mach_data.py"
Works in Rhino 7 and 8 (rhinoscriptsyntax + RhinoCommon). No Rhino document
or geometry is actually touched -- this only reads/writes files -- so it
could equally be run outside Rhino with the file-dialog calls swapped out,
but it's kept as a Rhino script for a consistent workflow with the rest of
this toolset.

VERSION HISTORY
----------------
RC4 (2026-09-30) - ID and L3D output column headers now carry a "|S" suffix
    (ID|S, L3D|S) to mark them as string-typed, per the downstream job
    format's convention. New COL_ID constant added alongside the existing
    COL_L3D (now "L3D|S"); no other column, matching, or Active-flag logic
    changed. build_output_row's tests updated and re-passed (34 checks) to
    confirm the new keys.
RC3 (2026-09-30) - Output file is now saved with a .sp extension instead of
    .csv (content is unchanged -- still plain CSV, Active/ID/X/Y/Z/B/C/Pen/
    L3D). Only the save dialog's default filename/extension and filter
    changed; no content or matching logic was touched.
RC2 (2026-09-30) - Simplified output to a fixed job-CSV header (Active, ID,
    X, Y, Z, B, C, Pen, L3D, + custom columns) instead of appending MACH_*
    columns onto a copy of the source CSV. Every source CSV row now always
    produces exactly one output row: Active=1 with the matched .MACH data
    for a genuine match, Active=0 with blank fields for anything that
    wasn't matched (bad source data, no close-enough .MACH row, or lost a
    tie-break) -- so a row that couldn't be matched shows up flagged off
    rather than disappearing. MACH_Group and Match_Distance are no longer
    written to the CSV; the match-distance range and per-row unmatch
    reasons are still printed to the console. New build_output_row()
    function unit-tested (10 additional checks) before being wired in.
RC1 (2026-09-29) - First release. .MACH parsing (Group/M111-carry-forward/
    motion-line/.l3d-line block model), closest-position matching with
    configurable MATCH_AXES, closest-wins tie-break, zero-filled custom
    columns, full match/unmatch summary reporting. Matching core validated
    against the sample .MACH file supplied for this tool plus synthetic
    tie-break/no-data/coordinate-offset test cases (23 checks) before being
    wired up to the file dialogs below.
"""

import rhinoscriptsyntax as rs
import Rhino
import csv
import os
import re
import math

SCRIPT_VERSION = "RC4"

# ---------------------------------------------------------------------------
# Extra columns appended to the output CSV, always filled with 0. Add or
# remove names here whenever the downstream job needs a different set --
# nothing else in this script needs to change.
#     CUSTOM_COLUMNS = ["Power", "Frequency", "Speed"]
# ---------------------------------------------------------------------------
CUSTOM_COLUMNS = []

# Which coordinates to use when finding each CSV row's closest .MACH
# processing row. See MATCHING AND MATCH_AXES in the docstring above before
# trusting the default of "XYZ" on a new CSV/.MACH pair.
MATCH_AXES = "XYZ"   # "XYZ" or "XY"

# Output column names. ID and L3D carry a "|S" suffix to mark them as
# string-typed columns, per the downstream job format's convention (every
# other output column here is numeric and needs no suffix).
COL_ACTIVE = "Active"
COL_ID = "ID|S"
COL_B = "B"
COL_C = "C"
COL_L3D = "L3D|S"
COL_PEN = "Pen"

GROUP_RE = re.compile(r'Group:\s*(\d+)')
M111_RE = re.compile(r'^M111\s+P(\d+)', re.IGNORECASE)
FILENAME_RE = re.compile(r'"([^"]+)"')
AXIS_TOKEN_RE = re.compile(r'^([XYZBC])(-?\d+(?:\.\d+)?)$', re.IGNORECASE)
MOTION_HINT_RE = re.compile(r'\bX-?\d', re.IGNORECASE)


def parse_mach_lines(lines):
    """Parses the lines of a .MACH file into a list of process-row dicts:
        {"group": int, "pen": int or None,
         "x", "y", "z", "b", "c": float or None,
         "l3d": str or None, "line_no": int}
    in file order, plus a list of warning strings for anything that looked
    incomplete or out of place."""
    blocks = []
    warnings = []
    current_pen = None
    pending = None

    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue

        if line.startswith("//"):
            m = GROUP_RE.search(line)
            if m is None:
                continue  # an unrelated comment line
            if pending is not None:
                warnings.append(
                    "Group {} (line {}) never got a motion/.l3d line before "
                    "Group {} started -- discarded.".format(
                        pending["group"], pending["line_no"], m.group(1)))
            pending = {"group": int(m.group(1)), "pen": None,
                       "x": None, "y": None, "z": None, "b": None, "c": None,
                       "l3d": None, "line_no": line_no}
            continue

        m111 = M111_RE.match(line)
        if m111:
            current_pen = int(m111.group(1))
            continue

        if line.startswith("*po="):
            if pending is None:
                warnings.append(
                    "Line {}: .l3d line with no preceding Group comment -- skipped.".format(line_no))
                continue
            fm = FILENAME_RE.search(line)
            pending["l3d"] = fm.group(1) if fm else None
            if pending["x"] is None or pending["y"] is None or pending["z"] is None:
                warnings.append(
                    "Group {} (line {}) is missing X/Y/Z position data -- discarded.".format(
                        pending["group"], pending["line_no"]))
            else:
                blocks.append(pending)
            pending = None
            continue

        if pending is not None and MOTION_HINT_RE.search(line):
            for token in line.split():
                am = AXIS_TOKEN_RE.match(token)
                if am:
                    axis = am.group(1).upper()
                    value = float(am.group(2))
                    if axis == "X":
                        pending["x"] = value
                    elif axis == "Y":
                        pending["y"] = value
                    elif axis == "Z":
                        pending["z"] = value
                    elif axis == "B":
                        pending["b"] = value
                    elif axis == "C":
                        pending["c"] = value
            pending["pen"] = current_pen
            continue

        # anything else (O0001, G95 R5, etc.) is intentionally ignored

    if pending is not None:
        warnings.append(
            "Group {} (line {}) never got a .l3d line before the file ended -- discarded.".format(
                pending["group"], pending["line_no"]))

    return blocks, warnings


def read_csv_rows(path):
    """Returns (fieldnames, rows) where rows is a list of plain dicts,
    preserving every column already in the CSV and the original row order."""
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(r) for r in reader]
    return fieldnames, rows


def match_csv_to_mach(csv_rows, mach_blocks, axes="XYZ"):
    """csv_rows: list of dicts with numeric-parseable 'X','Y','Z' values.
    mach_blocks: list of dicts as returned by parse_mach_lines.
    Returns (matches, unmatched_csv, unused_blocks):
      matches       -- list of (csv_row, mach_block, distance) tuples
      unmatched_csv -- list of (csv_row, reason_str) tuples
      unused_blocks -- mach_blocks never claimed by any csv row (closest-wins
                       tie-break: each .MACH row is claimed by at most one
                       CSV row, the closest one)
    """
    def dist(pt, block):
        dx = pt[0] - block["x"]
        dy = pt[1] - block["y"]
        if axes == "XY":
            return math.sqrt(dx * dx + dy * dy)
        dz = pt[2] - block["z"]
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    candidate_for_row = {}   # id(row) -> (block, distance)
    for row in csv_rows:
        pt = (float(row["X"]), float(row["Y"]), float(row["Z"]))
        best_block = None
        best_dist = None
        for block in mach_blocks:
            d = dist(pt, block)
            if best_dist is None or d < best_dist:
                best_dist = d
                best_block = block
        if best_block is not None:
            candidate_for_row[id(row)] = (best_block, best_dist)

    best_for_block = {}   # id(block) -> (row, distance)
    for row in csv_rows:
        cand = candidate_for_row.get(id(row))
        if cand is None:
            continue
        block, d = cand
        key = id(block)
        current = best_for_block.get(key)
        if current is None or d < current[1]:
            best_for_block[key] = (row, d)

    matches = []
    unmatched_csv = []
    claimed_block_ids = set()
    for row in csv_rows:
        cand = candidate_for_row.get(id(row))
        if cand is None:
            unmatched_csv.append((row, "no MACH processing rows available to match against"))
            continue
        block, d = cand
        winner_row, _ = best_for_block[id(block)]
        if winner_row is row:
            matches.append((row, block, d))
            claimed_block_ids.add(id(block))
        else:
            unmatched_csv.append((row, "lost the tie-break to a closer row for the same MACH group"))

    unused_blocks = [b for b in mach_blocks if id(b) not in claimed_block_ids]
    return matches, unmatched_csv, unused_blocks


def build_output_row(row, match, custom_columns):
    """Builds one output-CSV row dict (keys: Active, ID|S, X, Y, Z, B, C,
    Pen, L3D|S, plus every name in custom_columns). ID and L3D carry a "|S"
    suffix on their header to mark them as string-typed columns, per the
    downstream job format's convention (every other column here is numeric).

    row: the original CSV row dict (must have an 'ID' key -- the SOURCE
        CSV's own column is still plain "ID", unsuffixed; only the output
        header changes).
    match: (mach_block, distance) tuple if this row was matched and kept, or
        None if it wasn't (no numeric X/Y/Z in the source CSV, no MACH block
        close enough, or it lost a tie-break to a closer row).

    Every CSV row produces exactly one output row -- nothing is silently
    dropped. Active is 1 only for a genuinely matched row; every other case
    (bad source data, no match, too far, lost tie-break) comes out as
    Active=0 with the MACH-derived fields left blank, so a human has to
    consciously turn a row back on rather than a bad row just vanishing."""
    out = {COL_ID: row.get("ID", "")}
    if match is not None:
        block, _dist = match
        out[COL_ACTIVE] = 1
        out["X"] = block["x"]
        out["Y"] = block["y"]
        out["Z"] = block["z"]
        out[COL_B] = block["b"] if block["b"] is not None else ""
        out[COL_C] = block["c"] if block["c"] is not None else ""
        out[COL_PEN] = block["pen"] if block["pen"] is not None else ""
        out[COL_L3D] = block["l3d"] if block["l3d"] else ""
    else:
        out[COL_ACTIVE] = 0
        out["X"] = ""
        out["Y"] = ""
        out["Z"] = ""
        out[COL_B] = ""
        out[COL_C] = ""
        out[COL_PEN] = ""
        out[COL_L3D] = ""
    for col in custom_columns:
        out[col] = 0
    return out


def select_open_file(title, file_filter):
    dlg = Rhino.UI.OpenFileDialog()
    dlg.Title = title
    dlg.Filter = file_filter
    if dlg.ShowOpenDialog():
        return dlg.FileName
    return None


def select_save_file(title, file_filter, default_name):
    dlg = Rhino.UI.SaveFileDialog()
    dlg.Title = title
    dlg.Filter = file_filter
    dlg.FileName = default_name
    if dlg.ShowSaveDialog():
        return dlg.FileName
    return None


def ask_tolerance():
    """Prompts for a max match distance. Unlike the mesh-matching tools,
    there's no natural small default here (a CSV point isn't expected to
    sit ON the .MACH motion coordinate the way it sits on a mesh surface),
    so this defaults to 0 (no limit) until you've seen real match distances
    and can judge what's reasonable for your own data.
    Returns (tolerance_or_None, cancelled_bool)."""
    val = rs.GetReal("Maximum match distance, same units as both files (0 = no limit)", 0)
    if val is None:
        return None, True   # user pressed Esc
    if val <= 0:
        return None, False  # explicit no-limit
    return val, False


def main():
    print("augment_csv_with_mach_data.py - {}".format(SCRIPT_VERSION))

    csv_path = select_open_file("Select the CSV file", "CSV Files (*.csv)|*.csv|All Files (*.*)|*.*")
    if not csv_path:
        print("No CSV file selected.")
        return

    mach_path = select_open_file("Select the .MACH file", "MACH Files (*.mach)|*.mach|All Files (*.*)|*.*")
    if not mach_path:
        print("No .MACH file selected.")
        return

    fieldnames, csv_rows = read_csv_rows(csv_path)
    missing_cols = [c for c in ("ID", "X", "Y", "Z") if c not in fieldnames]
    if missing_cols:
        print("CSV is missing required column(s): {}".format(", ".join(missing_cols)))
        return

    usable_rows = []
    bad_row_entries = []   # (row, reason) for rows with non-numeric/missing X, Y, or Z
    for row in csv_rows:
        try:
            float(row["X"])
            float(row["Y"])
            float(row["Z"])
        except (TypeError, ValueError):
            bad_row_entries.append((row, "non-numeric or missing X/Y/Z in the source CSV"))
            continue
        usable_rows.append(row)
    if bad_row_entries:
        print("NOTE: {} CSV row(s) have non-numeric/missing X/Y/Z -- they'll be written "
              "Active=0: {}".format(len(bad_row_entries),
                                     ", ".join(str(r.get("ID", "<no ID>")) for r, _ in bad_row_entries)))

    with open(mach_path, "r", encoding="utf-8", errors="replace") as f:
        mach_lines = f.readlines()

    mach_blocks, parse_warnings = parse_mach_lines(mach_lines)
    if parse_warnings:
        print("")
        print("NOTE: {} issue(s) while reading the .MACH file:".format(len(parse_warnings)))
        for w in parse_warnings:
            print("  - {}".format(w))

    if not mach_blocks:
        print("No usable processing rows found in the .MACH file -- every output row will be Active=0.")

    tolerance, cancelled = ask_tolerance()
    if cancelled:
        print("Cancelled.")
        return

    matches, unmatched_csv, unused_blocks = match_csv_to_mach(usable_rows, mach_blocks, MATCH_AXES)

    if tolerance is not None:
        kept = [(r, b, d) for (r, b, d) in matches if d <= tolerance]
        pushed_out_matches = [(r, b, d) for (r, b, d) in matches if d > tolerance]
        pushed_out = [(r, "closest MACH row was {:.4g} units away, beyond the {} unit tolerance".format(d, tolerance))
                      for (r, b, d) in pushed_out_matches]
        unused_blocks = unused_blocks + [b for (_, b, _) in pushed_out_matches]
        matches = kept
        unmatched_csv = unmatched_csv + pushed_out

    # merge in the rows that couldn't even be attempted (bad source X/Y/Z),
    # so the printed Active=0 list and count always match the file exactly
    unmatched_csv = bad_row_entries + unmatched_csv

    match_lookup = {id(row): (block, d) for row, block, d in matches}

    out_fieldnames = [COL_ACTIVE, COL_ID, "X", "Y", "Z", COL_B, COL_C, COL_PEN, COL_L3D] + list(CUSTOM_COLUMNS)

    out_rows = []
    for row in csv_rows:
        cand = match_lookup.get(id(row))
        out_rows.append(build_output_row(row, cand, CUSTOM_COLUMNS))

    base, _ext = os.path.splitext(os.path.basename(csv_path))
    default_name = base + "_job.sp"
    save_path = select_save_file("Save job file as", "SP Files (*.sp)|*.sp|All Files (*.*)|*.*", default_name)
    if not save_path:
        print("No output file chosen -- nothing written.")
        return

    with open(save_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=out_fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    active_count = sum(1 for r in out_rows if r[COL_ACTIVE] == 1)
    inactive_count = len(out_rows) - active_count

    print("")
    print("Wrote {} row(s) to {}".format(len(out_rows), save_path))
    print("  {} row(s) written Active=1 (matched).".format(active_count))
    print("  {} row(s) written Active=0 (unmatched -- see below).".format(inactive_count))

    if matches:
        dists = [d for _, _, d in matches]
        print("  Match distance range: {:.4g} to {:.4g} (same units as your input files).".format(
            min(dists), max(dists)))
        print("  Sanity-check this range against what you'd expect for real matches -- if it's "
              "suspiciously large or uniform across every row, MATCH_AXES = \"{}\" may be comparing "
              "coordinates that don't share a frame; try \"XY\" near the top of the script.".format(MATCH_AXES))

    if unused_blocks:
        print("")
        print("{} MACH processing row(s) were never the closest match for any CSV row:".format(len(unused_blocks)))
        for b in unused_blocks:
            print("  - Group {} ({})".format(b["group"], b["l3d"] or "no filename"))

    if unmatched_csv:
        print("")
        print("{} CSV row(s) came out Active=0:".format(len(unmatched_csv)))
        for row, reason in unmatched_csv:
            print("  - {}: {}".format(row.get("ID", "<no ID>"), reason))


if __name__ == "__main__":
    main()
