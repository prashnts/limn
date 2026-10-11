# Adding a camera

A camera of the plot tool's Scan tab is an entry of the pen library (`plot/profiles/pens.toml`, `kind = "camera"`), named by a tag like a pen. Its URL alone gives a live view; a scan also needs its optics, or it takes the defaults (a 16 × 9 mm shot, turn 0, no offset, focus at Z7.5): tiles too far apart or overlapping, a mosaic turned or scaled wrong, positions off from where a pen draws.

What an entry says (`Camera` in `plot/tools.py`):

| Key | What | Found by |
|---|---|---|
| `webcam` | `http://host:port/capture.jpg` for a camera with its own server (limn_picam, the endoscope), or a Moonraker webcam's name | its server |
| `fov` | mm one shot covers at `focus_z`, across and down (its px/mm) | Calibrate |
| `turn` | degrees machine +X makes in the picture | Calibrate |
| `center` | mm from the tool point to the picture's middle: positions are the middle's, so a scan lines up with what a pen draws at the same x, y | Calibrate, on the cross |
| `focus_z` | machine Z (no mesh, no tag dz) where the paper is sharpest | Calibrate (or *Find focus*) |
| `clear_z`, `z_min` | sideways only at `clear_z` or higher; never under `z_min` (the lens, its tube) | by hand: measure them |
| `settle` | s still before a shot | by eye: shots blurred by the move |

Not modelled: a mirrored picture (`turn` can't say it: flip it at the camera, limn_picam's `hflip`/`vflip` in its settings, the endoscope's `?flip=1`), and lens distortion (one px/mm over the whole picture: a wide lens's mosaic doesn't meet at its edges; more `overlap` hides some of it).

**A Pi camera** (`limn_endoscope/picam`, docked by hand: holder 90, `DOCK_MANUAL`):
1. Its server on the Pi (`picam/README.md`); `http://<host>:4250/capture.jpg` should give a full-size still.
2. Its entry: the library's `[picam]`, or a new one (a key of up to 8 of a-z 0-9 - _ .: it goes on the tag) with `kind = "camera"`, `webcam`, `clear_z`, `z_min`. Give it a rough `center` if the lens is more than a few mm from the tool point (a ruler): the calibration has to find its cross in the first shot.
3. Its tag names that key (`PEN=<key>`, written like any tool's tag, before it is docked): docking it by hand (`DOCK_MANUAL`, the tag to the reader) makes it the Scan tab's camera *manual*.
4. **Before it goes on**, with a pen: the Scan tab's *Calibration cross* puts a 12 mm cross (the drawing `camera-mark`) at the middle of the region; plot it like any drawing. Once the camera is on, the dock is out of reach (no tool changes) until it is taken off and `DOCK_CLEAR`.
5. Dock the camera by hand. *Calibrate* (about a minute, over the cross): the focus sweep, moves of 0.5 mm in X and in Y then of a quarter of a shot (the picture's shift by phase correlation, the two measures agreeing within 8%), the cross found in the picture (straightened by the turn) for `center`, then a look with that center: the cross should be in the middle (its *residual*). The shots are a capture (*calibrate*, ⊕).
6. Check what it found (the Scan tab shows the old values beside it), then *Save to <key>*: `fov`, `turn`, `focus_z` and `center` go into its entry, the file's comments kept. Nothing is written before.
7. A small scan over the cross: no gaps between tiles (`fov` too big) and no doubled edges (too small). Calibrate again after the camera, its lens or its tag's offsets change: `center` includes the tag's dx/dy.

It says when it can't: no cross in sight (a rough `center`), a picture that hardly moves (nothing to see there), two measures that don't agree (the bed mat's regular grid and glare fool the correlation: plain paper and the cross), a mirrored picture.

**A camera picked up from a holder** (the U20, a tag in its holder) is the same, but the job picks it up first, and the cross is plotted any time before. Without a cross (*Calibrate* on the region's middle, over something with texture) it measures all but `center`.

Behind the buttons: `POST /api/camera/mark {x, y}`, `POST /api/camera/calibrate` (on the cross, else `{x, y}`), `POST /api/camera/calibration` (save); `Job.calibrate` in `limn_cam/scan.py`.
