# v5.6 - reviewer viewer redesign (research software; expert review required)

Only the browser reviewer changed (`scripts/review_web.html`, small additions to `scripts/review_web.py`). The detector,
scoring, calls files and reports are unchanged.

## Viewer
- ONE large MRI image, whole slice at fit, never auto-zoomed to the candidate (the candidate is outlined, with an arrow and
  label). Zoom / pan yourself; "Candidate" (F) centres and zooms on it on request. Moving to another candidate keeps your zoom.
- Layouts 1x1 (default), 1x2, 2x2 (`\`); each image has its own plane and sequence; all follow one crosshair.
- Left tool palette (Pan, Zoom, Window, Scroll, Ruler, Probe, Lens, Missed), plane / layout / Fit / 1:1 / Candidate toolbar,
  slice bar on each image, corner text + scale bar (P toggles), orientation letters, per-sequence window/level.
- Mouse: wheel = slices, Ctrl/Cmd+wheel / pinch = zoom to the pointer, right-drag or Shift+drag = contrast/brightness,
  middle-drag = pan, right-click (no move) = menu.

## Right panel
- Resizable (grip on the left edge, width remembered); Hide button / Space / click on the active tab hides it.
- Hidden: vertical rail buttons (Viewer, Candidates, Calls summary, AI meter, Decision + green dot) appear; click opens the
  panel on that tab; pin symbol pins it again. "Auto-hide panel" checkbox (also in right-click, View and Settings menus):
  the panel slides over the image only while the pointer is on the rail or panel. Last tab is reopened.

## Menus
- Icons beside the text in the menu bar and right-click menu (lens = Magnifier, half-dark circle = Darkness probe, ...).

## Snapshots
- Take snapshot (Ctrl/Cmd+S) and Save snapshot as... (Shift+Ctrl/Cmd+S): PNG/JPEG named with study, candidate, voxel x y z,
  plane, e.g. `M04_cand12_x082_y162_z099_axial.png`. Default folder set -> saves at once; none (or "always ask") -> Save-as
  window (folder, name, "use as default"; Choose... where the browser has a native picker). Existing files are never
  overwritten (`_2`, `_3`...). Toast with path + Open folder.
- Settings -> Snapshot settings...: view / all images, corner text, scale bar, outline, crosshair, arrow, format, 1x/2x,
  default folder (`{study}` allowed), always ask, file-name parts with live preview, optional sidecar .txt (voxel + mm xyz,
  call, AI meter), optional clipboard copy. Study code only in names.

## Server
- `/api/snapshot`, `/api/openfolder`, `meta` gains `snapdir`, `acq`, `cands[].vox`.
- POSTs now need the `X-CSS: 1` header and a localhost Host header (blocks cross-site requests); filenames are sanitised.
- Tests: `tests/check_review_web.py` covers snapshot save / sanitising / no-overwrite / sidecar / guards; the browser behaviour
  (zoom stays 1, layouts, panel hide / auto-hide / pin / resize, menu, snapshot flows) was checked with Playwright.

## v5.6.1 - narrow tool strip, R badge, mirror
- Left tool strip is 34 px wide, icons only (names as tooltips) with an "auto" tick box at the bottom: ticked = the strip folds
  into a thin "tools" tab and slides out while the pointer is on it (remembered).
- A small round **R** badge (labelled RIGHT) marks the side of the patient's right on every axial / coronal image (not sagittal);
  no L badge. It follows the image header: it moves to the other side when the image is mirrored. Settings > "Show R badge".
- **Mirror left-right** (Shift+H, View / Settings / right-click menus) flips all axial/coronal images of the layout, with a
  "Mirrored" tag; remembered per study; snapshots keep it (file name `-mirrored`, sidecar says so). Voxel x y z are never flipped.
- **Side check**: the server compares the FreeSurfer hemisphere label of each candidate with its side of the image
  (canonical RAS: higher x = patient right) and the viewer warns in the banner when fewer than 30 % agree (View > Side check...
  shows the numbers).

## v5.6.2
- Crosshair is hidden by default (Settings / View > Crosshair turns it on) and much fainter when shown (old saved setting ignored).
- Right-panel rail buttons: only Viewer, Candidates, Calls summary (+ the pin symbol); the green dot (current candidate has a call) is on Viewer.
- New `scripts/midline_probe.py` (read-only): measures how much each detector object looks like the interhemispheric fissure
  (mid_local_frac, both3_frac, equi_med_mm, hug_med_mm, plane distance, sheet orientation) next to the reader's calls and tests
  candidate rules for "cSS calls lost"; used to set the occipital-midline exclusion on real data before any rule is added.
