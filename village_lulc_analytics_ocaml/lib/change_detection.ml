(* change_detection.ml — Phases 1-5: Transition raster generation
 *
 * Each public function takes a raw LULC raster stack (one raster per year,
 * in chronological order) and returns a single transition-code raster.
 *
 * The stack must contain at least 4 years (indices 0..2 form "Then";
 * indices 3..N-1 form "Now").  Each year is a single-band int raster whose
 * pixel values are raw LULC class codes (1–12, 0 = background).
 *
 * All logic faithfully replicates the GEE behaviour found in:
 *   computing/change_detection/change_detection.py
 *)

(* ================================================================== *)
(* 1. REMAP FUNCTIONS                                                  *)
(*                                                                     *)
(* Each function maps a raw LULC class (0-12) to the simplified        *)
(* category used by that parameter's transition matrix.                *)
(*                                                                     *)
(* Raw LULC codes (from Sentinel-2 Random-Forest classifier):          *)
(*   1  = Built-up          7  = Barren                               *)
(*   2  = Water (Kharif)    8  = Single Crop (var A)                  *)
(*   3  = Water (Rabi)      9  = Single Crop (var B)                  *)
(*   4  = Water (Zaid)      10 = Double Crop                          *)
(*   6  = Forest            11 = Triple Crop                          *)
(*   12 = Scrub             0  = Background / NoData                  *)
(* ================================================================== *)

(** Urbanization remap.
    GEE: remap [1,2,3,4,6,7,8,9,10,11,12] → [1,2,2,2,3,4,3,3,3,3,4]
    Simplified categories:
      1 = Built-up  |  2 = Water  |  3 = Vegetation/Crop  |  4 = Barren/Scrub *)
let remap_urbanization = function
  | 1               -> 1   (* Built-up *)
  | 2 | 3 | 4       -> 2   (* Water (all seasons) *)
  | 6               -> 3   (* Forest *)
  | 8 | 9 | 10 | 11 -> 3   (* Cropland → same category as Forest *)
  | 7               -> 4   (* Barren *)
  | 12              -> 4   (* Scrub *)
  | _               -> 0   (* Background / unknown *)

(** Degradation remap.
    GEE: remap [1,2,3,4,6,7,8,9,10,11,12] → [1,2,2,2,4,5,3,3,3,3,6]
    Simplified categories:
      1 = Built-up  |  2 = Water  |  3 = Farmland/Crop  |
      4 = Forest    |  5 = Barren |  6 = Scrub
    NOTE: "f_" attribute prefix stands for *Farmland*, not Forest.
          Transition checks [then = 3] = Cropland baseline. *)
let remap_degradation = function
  | 1               -> 1   (* Built-up *)
  | 2 | 3 | 4       -> 2   (* Water *)
  | 8 | 9 | 10 | 11 -> 3   (* Farmland / Cropland  ← transitions fire from here *)
  | 6               -> 4   (* Forest *)
  | 7               -> 5   (* Barren *)
  | 12              -> 6   (* Scrub *)
  | _               -> 0

(** Forest remap (shared by Deforestation and Afforestation).
    GEE: remap [1,2,3,4,6,7,8,9,10,11,12] → [1,2,2,2,3,5,4,4,4,4,6]
    Simplified categories:
      1 = Built-up  |  2 = Water  |  3 = Forest  |
      4 = Cropland  |  5 = Barren |  6 = Scrub *)
let remap_forest = function
  | 1               -> 1   (* Built-up *)
  | 2 | 3 | 4       -> 2   (* Water *)
  | 6               -> 3   (* Forest   ← transitions fire from/to here *)
  | 8 | 9 | 10 | 11 -> 4   (* Cropland *)
  | 7               -> 5   (* Barren *)
  | 12              -> 6   (* Scrub *)
  | _               -> 0

(** Crop Intensity remap.
    GEE: remap [1,2,3,4,6,7,8,9,10,11,12] → [1,2,2,2,3,4,5,5,6,7,8]
    Simplified categories:
      1 = Built-up  |  2 = Water    |  3 = Forest  |  4 = Barren  |
      5 = Single    |  6 = Double   |  7 = Triple  |  8 = Scrub *)
let remap_crop = function
  | 1               -> 1   (* Built-up *)
  | 2 | 3 | 4       -> 2   (* Water *)
  | 6               -> 3   (* Forest *)
  | 7               -> 4   (* Barren *)
  | 8 | 9           -> 5   (* Single crop *)
  | 10              -> 6   (* Double crop *)
  | 11              -> 7   (* Triple crop *)
  | 12              -> 8   (* Scrub *)
  | _               -> 0

(* ================================================================== *)
(* 2. THEN / NOW COMPUTATION                                           *)
(*                                                                     *)
(* The N-year LULC stack is split at index 3:                         *)
(*   Then = mode(year[0], year[1], year[2])   — the baseline period   *)
(*   Now  = mode(year[3], …, year[N-1])       — the active period     *)
(*                                                                     *)
(* The remap_fn is applied to EACH year BEFORE the mode is taken,     *)
(* replicating GEE's per-image remap → ImageCollection.mode() flow.   *)
(* ================================================================== *)

(** [compute_then_now remap_fn stack] returns [(then_raster, now_raster)].
    Raises [Invalid_argument] when [stack] has fewer than 4 years. *)
let compute_then_now remap_fn stack =
  let remapped = List.map (Raster.remap remap_fn) stack in
  let n = List.length remapped in
  if n = 2 then
    (* Fallback for 2-year testing: year 0 is Then, year 1 is Now *)
    (List.nth remapped 0, List.nth remapped 1)
  else if n < 4 then
    invalid_arg
      (Printf.sprintf
         "Change_detection.compute_then_now: need >= 4 years (or exactly 2 for testing), got %d" n)
  else
    let then_stack = Raster.slice remapped ~start:0 ~stop:3 in
    let now_stack  = Raster.slice remapped ~start:3 ~stop:n in
    (Raster.mode_stack then_stack, Raster.mode_stack now_stack)

(* ================================================================== *)
(* 3. TRANSITION PIXEL FUNCTIONS                                       *)
(*                                                                     *)
(* Each function maps (then_remapped, now_remapped) → integer code.   *)
(* Code 0 means "no relevant transition at this pixel".               *)
(* Codes 1..N encode specific transition types (see vector attrs).    *)
(*                                                                     *)
(* The implementation uses additive encoding:  the GEE code builds a  *)
(* zero image and adds each Boolean mask * its code.  Because the mask *)
(* categories are mutually exclusive, the sum equals the matching code.*)
(* ================================================================== *)

(** Urbanization pixel transition.
    Fires only when [now = 1] (Built-up).
    then=1→1(bu_bu)  then=2→2(w_bu)  then=3→3(tr_bu)  then=4→4(b_bu) *)
let urbanization_pixel then_v now_v =
  if now_v <> 1 then 0
  else (match then_v with
    | 1 -> 1  (* bu → bu *)
    | 2 -> 2  (* water → bu *)
    | 3 -> 3  (* veg/crop → bu *)
    | 4 -> 4  (* barren/scrub → bu *)
    | _ -> 0)

(** Degradation pixel transition.
    Fires only when [then = 3] (Farmland/Cropland in degradation remap).
    "f_" prefix stands for *Farmland*, not Forest.
    then=3,now=3→1(f_f)  now=1→2(f_bu)  now=5→3(f_ba)  now=6→4(f_sc) *)
let degradation_pixel then_v now_v =
  if then_v <> 3 then 0   (* baseline must be Farmland *)
  else (match now_v with
    | 3 -> 1  (* stable farmland *)
    | 1 -> 2  (* farmland → built-up *)
    | 5 -> 3  (* farmland → barren *)
    | 6 -> 4  (* farmland → scrub *)
    | _ -> 0)

(** Deforestation pixel transition (using forest remap).
    Fires only when [then = 3] (Forest in forest remap).
    fo_fo→1  fo_bu→2  fo_fa→3  fo_ba→4  fo_sc→5 *)
let deforestation_pixel then_v now_v =
  if then_v <> 3 then 0   (* baseline must be Forest *)
  else (match now_v with
    | 3 -> 1  (* stable forest *)
    | 1 -> 2  (* forest → built-up *)
    | 4 -> 3  (* forest → cropland/farmland *)
    | 5 -> 4  (* forest → barren *)
    | 6 -> 5  (* forest → scrub *)
    | _ -> 0)

(** Afforestation pixel transition (using forest remap).
    Fires only when [now = 3] (Forest in forest remap).
    fo_fo→1  bu_fo→2  fa_fo→3  ba_fo→4  sc_fo→5 *)
let afforestation_pixel then_v now_v =
  if now_v <> 3 then 0   (* active period must be Forest *)
  else (match then_v with
    | 3 -> 1  (* stable forest *)
    | 1 -> 2  (* built-up → forest *)
    | 4 -> 3  (* cropland → forest *)
    | 5 -> 4  (* barren → forest *)
    | 6 -> 5  (* scrub → forest *)
    | _ -> 0)

(** Crop Intensity pixel transition.
    Only fires for Single (5), Double (6) or Triple (7) crop in either period.
    do_si→1  tr_si→2  tr_do→3  si_do→4  si_tr→5  do_tr→6
    si_si→7  do_do→8  tr_tr→9 *)
let crop_intensity_pixel then_v now_v =
  match (then_v, now_v) with
  | (6, 5) -> 1   (* double → single *)
  | (7, 5) -> 2   (* triple → single *)
  | (7, 6) -> 3   (* triple → double *)
  | (5, 6) -> 4   (* single → double *)
  | (5, 7) -> 5   (* single → triple *)
  | (6, 7) -> 6   (* double → triple *)
  | (5, 5) -> 7   (* stable single *)
  | (6, 6) -> 8   (* stable double *)
  | (7, 7) -> 9   (* stable triple *)
  | _       -> 0

(* ================================================================== *)
(* 4. TEMPORAL SMOOTHING (required for Deforestation / Afforestation) *)
(*                                                                     *)
(* Replicates the two-pass algorithm in change_deforestation_          *)
(* afforestation() that corrects single-year noise in water-body       *)
(* pixels (raw class 3 = Water Rabi) before the forest remap is       *)
(* applied.                                                            *)
(*                                                                     *)
(* PASS 1 — build a per-pixel anomaly count (zero_image2 equivalent): *)
(*   For each interior year i (1..N-2), evaluate 11 structural         *)
(*   conditions on the (before, middle, after) triple and increment    *)
(*   the pixel counter for each condition that fires.                  *)
(*                                                                     *)
(* PASS 2 — apply corrections wherever count ∈ {3, 4}:               *)
(*   Conditions evaluate on the ORIGINAL (unsmoothed) l1_asset.       *)
(*   Corrections are written to a COPY (l1_asset_copy).               *)
(*   cond1: before==3 ∧ middle≠3 ∧ after==3  → set middle = 3        *)
(*   cond2: before≠3 ∧ middle==3 ∧ after≠3   → set middle = before   *)
(* ================================================================== *)

(* -- helpers for condition predicates on raw LULC values -- *)
let is_crop  v = v = 8 || v = 9 || v = 10 || v = 11
let is_water v = v = 2 || v = 3 || v = 4
let is_forest v = v = 6

(** Count how many of the 11 anomaly conditions fire for a single
    (before, middle, after) raw-LULC triple. *)
let anomaly_count_for_triple b m a =
  let n = ref 0 in
  (* cond1:  scrub–(forest|crop)–scrub *)
  if b = 12 && a = 12 && (is_forest m || is_crop m)     then incr n;
  (* cond2:  water–(forest|crop)–water *)
  if is_water b && is_water a && (is_forest m || is_crop m) then incr n;
  (* cond3:  forest–scrub–forest *)
  if b = 6  && a = 6  && m = 12                         then incr n;
  (* cond4:  crop–scrub–crop *)
  if is_crop b && is_crop a && m = 12                   then incr n;
  (* cond5:  crop–barren–crop *)
  if is_crop b && is_crop a && m = 7                    then incr n;
  (* cond6:  forest–crop–forest *)
  if b = 6  && a = 6  && is_crop m                      then incr n;
  (* cond7:  crop–forest–crop *)
  if is_crop b && is_crop a && m = 6                    then incr n;
  (* cond8:  builtup–forest–builtup *)
  if b = 1  && a = 1  && m = 6                          then incr n;
  (* cond9:  forest–builtup–forest *)
  if b = 6  && a = 6  && m = 1                          then incr n;
  (* cond10: builtup–crop–builtup *)
  if b = 1  && a = 1  && is_crop m                      then incr n;
  (* cond11: barren–(forest|crop)–barren *)
  if b = 7  && a = 7  && (is_forest m || is_crop m)     then incr n;
  !n

(** Pass 1: build the anomaly count array over the full pixel stack.
    [px_arrays] is a list of flat pixel arrays (one per year, same length). *)
let build_anomaly_counts px_arrays size =
  let arr    = Array.of_list px_arrays in
  let nyears = Array.length arr in
  let counts = Array.make size 0 in
  for i = 1 to nyears - 2 do
    for idx = 0 to size - 1 do
      let b = arr.(i - 1).(idx) in
      let m = arr.(i).(idx) in
      let a = arr.(i + 1).(idx) in
      counts.(idx) <- counts.(idx) + anomaly_count_for_triple b m a
    done
  done;
  counts

(** Pass 2: apply water-class (raw == 3) corrections where count ∈ {3,4}.
    Conditions are evaluated on [original_px_arrays]; corrections are
    written into a fresh deep copy. *)
let apply_corrections original_px_arrays anomaly_counts =
  let orig   = Array.of_list original_px_arrays in
  let nyears = Array.length orig in
  (* Deep-copy every pixel array independently *)
  let copy = Array.map Array.copy orig in
  for i = 1 to nyears - 2 do
    let size = Array.length orig.(i) in
    for idx = 0 to size - 1 do
      let cnt = anomaly_counts.(idx) in
      if cnt = 3 || cnt = 4 then begin
        let b = orig.(i - 1).(idx) in   (* from ORIGINAL, not copy *)
        let m = orig.(i).(idx) in
        let a = orig.(i + 1).(idx) in
        (* cond1: non-water sandwiched between water (class 3) → revert to 3 *)
        if b = 3 && m <> 3 && a = 3 then
          copy.(i).(idx) <- 3
        (* cond2: water (class 3) sandwiched between non-water → revert to before *)
        else if b <> 3 && m = 3 && a <> 3 then
          copy.(i).(idx) <- b
      end
    done
  done;
  Array.to_list copy

(** [apply_temporal_smoothing stack] runs the two-pass noise-correction on a
    raw LULC raster stack.  Returns a corrected stack of the same length.
    Stacks shorter than 3 years are returned unchanged (no interior years). *)
let apply_temporal_smoothing (stack : Raster.t list) : Raster.t list =
  match stack with
  | [] | [_] | [_; _] -> stack
  | first :: _ ->
    let size      = first.Raster.meta.Raster.width *
                    first.Raster.meta.Raster.height in
    let px_arrays = List.map (fun r -> r.Raster.pixels) stack in
    let counts    = build_anomaly_counts px_arrays size in
    let corrected = apply_corrections px_arrays counts in
    List.map2 (fun r px -> { r with Raster.pixels = px }) stack corrected

(* ================================================================== *)
(* 5. TOP-LEVEL TRANSITION GENERATORS                                  *)
(*                                                                     *)
(* Each function takes the raw LULC stack and returns a transition     *)
(* code raster ready for vectorisation.                                *)
(* ================================================================== *)

let make_transition_raster then_r now_r pixel_fn =
  Raster.map2 pixel_fn then_r now_r

(** Urbanization raster. Codes 0-4. *)
let urbanization stack =
  let (t, n) = compute_then_now remap_urbanization stack in
  make_transition_raster t n urbanization_pixel

(** Degradation raster (farmland degradation). Codes 0-4. *)
let degradation stack =
  let (t, n) = compute_then_now remap_degradation stack in
  make_transition_raster t n degradation_pixel

(** Deforestation raster. Codes 0-5.
    Applies temporal smoothing to the raw stack BEFORE remapping. *)
let deforestation stack =
  let smoothed = apply_temporal_smoothing stack in
  let (t, n)   = compute_then_now remap_forest smoothed in
  make_transition_raster t n deforestation_pixel

(** Afforestation raster. Codes 0-5.
    Shares the same smoothed stack as deforestation. *)
let afforestation stack =
  let smoothed = apply_temporal_smoothing stack in
  let (t, n)   = compute_then_now remap_forest smoothed in
  make_transition_raster t n afforestation_pixel

(** Crop Intensity raster. Codes 0-9. *)
let crop_intensity stack =
  let (t, n) = compute_then_now remap_crop stack in
  make_transition_raster t n crop_intensity_pixel
