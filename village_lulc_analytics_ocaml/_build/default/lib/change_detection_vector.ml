(* change_detection_vector.ml — Phase 6: Vectorisation
 *
 * Replicates the logic of generate_vector() in
 *   computing/change_detection/change_detection_vector.py
 *
 * For each transition-code raster and a list of watershed polygons:
 *   1. For every (code, label) pair, build a binary mask of matching pixels.
 *   2. Count pixels inside each watershed using a bounding-box + ray-cast PIP
 *      algorithm (replacing GEE's reduceRegions + ee.Reducer.sum()).
 *   3. Convert pixel count → area (m²) → area (ha) using the pixel resolution.
 *   4. Attach the resulting float value to the watershed as a named attribute.
 *
 * All attribute names match the GEE output exactly so that downstream
 * GeoServer / PostGIS consumers see identical field names.
 *)

(* ================================================================== *)
(* Types                                                               *)
(* ================================================================== *)

(** WGS-84 (longitude, latitude) coordinate pair. *)
type coord = float * float

(** A closed polygon ring stored as an array of (lon, lat) coordinates.
    The ring does NOT need to repeat the first vertex at the end;
    the PIP algorithm handles both open and closed conventions. *)
type ring = coord array

(** A watershed (micro-watershed) feature. *)
type watershed = {
  uid      : string;   (** Unique identifier from the GEE asset. *)
  geometry : ring;     (** Outer boundary ring of the watershed. *)
}

(* -- Per-parameter attribute records -- *)

(** Urbanization vector attributes.
    total_urb excludes stable built-up (bu_bu). *)
type urb_attrs = {
  bu_bu     : float;
  w_bu      : float;
  tr_bu     : float;
  b_bu      : float;
  total_urb : float;   (* = w_bu + tr_bu + b_bu *)
}

(** Degradation (farmland) vector attributes.
    "f_" prefix = Farmland, not Forest.
    total_deg excludes stable farmland (f_f). *)
type deg_attrs = {
  f_f       : float;
  f_bu      : float;
  f_ba      : float;
  f_sc      : float;
  total_deg : float;   (* = f_bu + f_ba + f_sc *)
}

(** Deforestation vector attributes.
    total_def excludes stable forest (fo_fo). *)
type def_attrs = {
  fo_fo     : float;
  fo_bu     : float;
  fo_fa     : float;
  fo_ba     : float;
  fo_sc     : float;
  total_def : float;   (* = fo_bu + fo_fa + fo_ba + fo_sc *)
}

(** Afforestation vector attributes.
    total_aff excludes stable forest (fo_fo). *)
type aff_attrs = {
  fo_fo_aff : float;   (** Stable forest (afforestation context). *)
  bu_fo     : float;
  fa_fo     : float;
  ba_fo     : float;
  sc_fo     : float;
  total_aff : float;   (* = bu_fo + fa_fo + ba_fo + sc_fo *)
}

(** Crop Intensity vector attributes.
    total_change = sum of all directional transitions (excludes stable). *)
type crop_attrs = {
  do_si        : float;
  tr_si        : float;
  tr_do        : float;
  si_do        : float;
  si_tr        : float;
  do_tr        : float;
  si_si        : float;
  do_do        : float;
  tr_tr        : float;
  total_change : float;   (* = do_si+tr_si+tr_do+si_do+si_tr+do_tr *)
}

(** Combined statistics for one watershed across all five parameters. *)
type watershed_stats = {
  uid            : string;
  geometry       : ring;
  urbanization   : urb_attrs;
  degradation    : deg_attrs;
  deforestation  : def_attrs;
  afforestation  : aff_attrs;
  crop_intensity : crop_attrs;
}

(* ================================================================== *)
(* Spatial helpers                                                     *)
(* ================================================================== *)

(** [pixel_area_ha meta] returns the area of one pixel in hectares.
    Assumes [x_res] and [y_res] are in metres (true for projected 10 m data).
    GEE equivalent: ee.Image.pixelArea() * 0.0001 *)
let pixel_area_ha (meta : Raster.metadata) =
  meta.Raster.x_res *. meta.Raster.y_res *. 1e-4

(** [bounding_box ring] returns (min_lon, min_lat, max_lon, max_lat). *)
let bounding_box ring =
  Array.fold_left
    (fun (mnx, mny, mxx, mxy) (x, y) ->
       (Float.min mnx x, Float.min mny y,
        Float.max mxx x, Float.max mxy y))
    (Float.infinity, Float.infinity,
     Float.neg_infinity, Float.neg_infinity)
    ring

(** [is_point_in_polygon (px, py) ring] uses the ray-casting algorithm to
    determine whether point [p] lies inside [ring].
    Returns [true] for interior points and most boundary points. *)
let is_point_in_polygon (px, py) ring =
  let n      = Array.length ring in
  if n < 3 then false
  else begin
    let inside = ref false in
    let j      = ref (n - 1) in
    for i = 0 to n - 1 do
      let (xi, yi) = ring.(i) in
      let (xj, yj) = ring.(!j) in
      if ((yi > py) <> (yj > py)) &&
         (px < (xj -. xi) *. (py -. yi) /. (yj -. yi) +. xi)
      then inside := not !inside;
      j := i
    done;
    !inside
  end

(* ================================================================== *)
(* Core area computation                                               *)
(* ================================================================== *)

(** [compute_area_ha raster ring target_codes] returns the total area in
    hectares of all pixels inside [ring] whose value is in [target_codes].
    [target_codes] corresponds to arg["value"] in the GEE generate_vector().
    May be a single value [v] or a union [v1; v2; …] for "total_*" fields.

    Algorithm:
      1. Compute geographic bounding box of [ring].
      2. Convert bbox to pixel row/col ranges (clamped to raster extent).
      3. For each pixel in the bbox window:
           a. Compute pixel-centre (lon, lat).
           b. Point-in-polygon test against [ring].
           c. If inside and pixel value ∈ [target_codes], accumulate area.  *)
let compute_area_ha (raster : Raster.t) (ring : ring) (target_codes : int list) =
  let meta = raster.Raster.meta in
  let pa   = pixel_area_ha meta in

  (* Geographic bbox of the watershed polygon *)
  let (min_lon, min_lat, max_lon, max_lat) = bounding_box ring in

  (* Convert lon/lat bbox → pixel row/col range
     origin_x = left edge of col 0,  origin_y = top edge of row 0.
     col  = floor((lon - origin_x) / x_res)
     row  = floor((origin_y - lat) / y_res)           *)
  let col_lo = max 0 (Float.to_int
      ((min_lon -. meta.Raster.origin_x) /. meta.Raster.x_res)) in
  let col_hi = min (meta.Raster.width - 1) (Float.to_int
      ((max_lon -. meta.Raster.origin_x) /. meta.Raster.x_res)) in
  let row_lo = max 0 (Float.to_int
      ((meta.Raster.origin_y -. max_lat) /. meta.Raster.y_res)) in
  let row_hi = min (meta.Raster.height - 1) (Float.to_int
      ((meta.Raster.origin_y -. min_lat) /. meta.Raster.y_res)) in

  let total = ref 0.0 in
  for row = row_lo to row_hi do
    for col = col_lo to col_hi do
      let centre = Raster.pixel_lat_lon meta row col in
      if is_point_in_polygon centre ring then begin
        let v = Raster.get raster row col in
        if List.mem v target_codes then
          total := !total +. pa
      end
    done
  done;
  !total

(* ================================================================== *)
(* Per-parameter vectorisation                                         *)
(* ================================================================== *)

let vectorise_urbanization raster (ws : watershed) =
  let area codes = compute_area_ha raster ws.geometry codes in
  let bu_bu  = area [1] in
  let w_bu   = area [2] in
  let tr_bu  = area [3] in
  let b_bu   = area [4] in
  { bu_bu; w_bu; tr_bu; b_bu;
    total_urb = w_bu +. tr_bu +. b_bu }

let vectorise_degradation raster (ws : watershed) =
  let area codes = compute_area_ha raster ws.geometry codes in
  let f_f    = area [1] in
  let f_bu   = area [2] in
  let f_ba   = area [3] in
  let f_sc   = area [4] in
  { f_f; f_bu; f_ba; f_sc;
    total_deg = f_bu +. f_ba +. f_sc }

let vectorise_deforestation raster (ws : watershed) =
  let area codes = compute_area_ha raster ws.geometry codes in
  let fo_fo  = area [1] in
  let fo_bu  = area [2] in
  let fo_fa  = area [3] in
  let fo_ba  = area [4] in
  let fo_sc  = area [5] in
  { fo_fo; fo_bu; fo_fa; fo_ba; fo_sc;
    total_def = fo_bu +. fo_fa +. fo_ba +. fo_sc }

let vectorise_afforestation raster (ws : watershed) =
  let area codes = compute_area_ha raster ws.geometry codes in
  let fo_fo_aff = area [1] in
  let bu_fo  = area [2] in
  let fa_fo  = area [3] in
  let ba_fo  = area [4] in
  let sc_fo  = area [5] in
  { fo_fo_aff; bu_fo; fa_fo; ba_fo; sc_fo;
    total_aff = bu_fo +. fa_fo +. ba_fo +. sc_fo }

let vectorise_crop_intensity raster (ws : watershed) =
  let area codes = compute_area_ha raster ws.geometry codes in
  let do_si = area [1] in
  let tr_si = area [2] in
  let tr_do = area [3] in
  let si_do = area [4] in
  let si_tr = area [5] in
  let do_tr = area [6] in
  let si_si = area [7] in
  let do_do = area [8] in
  let tr_tr = area [9] in
  { do_si; tr_si; tr_do; si_do; si_tr; do_tr; si_si; do_do; tr_tr;
    total_change = do_si +. tr_si +. tr_do +. si_do +. si_tr +. do_tr }

(* ================================================================== *)
(* Top-level driver                                                    *)
(* ================================================================== *)

(** [vectorise_all ~urb_raster ~deg_raster ~def_raster ~aff_raster
    ~crop_raster ~watersheds] computes all five change parameters for
    every watershed in [watersheds] and returns one [watershed_stats]
    record per watershed. *)
let vectorise_all
    ~urb_raster
    ~deg_raster
    ~def_raster
    ~aff_raster
    ~crop_raster
    ~watersheds
  =
  List.map (fun (ws : watershed) ->
    { uid            = ws.uid;
      geometry       = ws.geometry;
      urbanization   = vectorise_urbanization  urb_raster  ws;
      degradation    = vectorise_degradation   deg_raster  ws;
      deforestation  = vectorise_deforestation def_raster  ws;
      afforestation  = vectorise_afforestation aff_raster  ws;
      crop_intensity = vectorise_crop_intensity crop_raster ws;
    }
  ) watersheds
