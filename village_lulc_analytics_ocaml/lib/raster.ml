(* raster.ml — Phase 0: Core raster primitives
 *
 * A raster is represented as a flat, row-major [int array] together with
 * a lightweight [metadata] record that describes its spatial extent.
 *
 * Index of pixel at (row, col) = row * meta.width + col
 * Row 0 is the topmost row (north), col 0 is the leftmost column (west).
 *)

(** Spatial metadata for a single raster layer. *)
type metadata = {
  width    : int;    (** Number of pixel columns. *)
  height   : int;    (** Number of pixel rows. *)
  x_res    : float;  (** Pixel width  in the CRS unit (metres or degrees). *)
  y_res    : float;  (** Pixel height in the CRS unit (positive value). *)
  origin_x : float;  (** X coordinate of the top-left pixel corner. *)
  origin_y : float;  (** Y coordinate of the top-left pixel corner. *)
}

(** A single raster band: spatial metadata + flat pixel array. *)
type t = {
  meta   : metadata;
  pixels : int array;
}

(* ------------------------------------------------------------------ *)
(* Constructors                                                        *)
(* ------------------------------------------------------------------ *)

(** [create meta pixels] wraps [pixels] in a raster.
    Raises [Invalid_argument] when [Array.length pixels <> width * height]. *)
let create meta pixels =
  let expected = meta.width * meta.height in
  if Array.length pixels <> expected then
    invalid_arg
      (Printf.sprintf
         "Raster.create: pixels length %d <> width*height (%d*%d=%d)"
         (Array.length pixels) meta.width meta.height expected);
  { meta; pixels }

(** [of_array2d rows ~x_res ~y_res ~origin_x ~origin_y] constructs a raster
    from a 2-D int array (outer index = row).  Each row must have equal length. *)
let of_array2d rows ~x_res ~y_res ~origin_x ~origin_y =
  let height = Array.length rows in
  let width  = if height = 0 then 0 else Array.length rows.(0) in
  let pixels = Array.concat (Array.to_list rows) in
  let meta   = { width; height; x_res; y_res; origin_x; origin_y } in
  create meta pixels

(* ------------------------------------------------------------------ *)
(* Pixel access                                                        *)
(* ------------------------------------------------------------------ *)

(** [get r row col] returns the integer value of pixel (row, col). *)
let get r row col =
  if row < 0 || row >= r.meta.height || col < 0 || col >= r.meta.width then
    invalid_arg
      (Printf.sprintf "Raster.get: (%d,%d) out of %dx%d bounds"
         row col r.meta.height r.meta.width);
  r.pixels.(row * r.meta.width + col)

(* ------------------------------------------------------------------ *)
(* Pixel-wise transforms (all return new rasters; inputs are immutable) *)
(* ------------------------------------------------------------------ *)

(** [map f r] applies [f] to every pixel value, preserving metadata. *)
let map f r =
  { r with pixels = Array.map f r.pixels }

(** [map2 f a b] applies [f] pixel-wise over two rasters.
    Raises [Invalid_argument] when their dimensions differ. *)
let map2 f a b =
  if a.meta.width  <> b.meta.width ||
     a.meta.height <> b.meta.height then
    invalid_arg
      (Printf.sprintf "Raster.map2: dimension mismatch %dx%d vs %dx%d"
         a.meta.height a.meta.width b.meta.height b.meta.width);
  { a with
    pixels = Array.init (Array.length a.pixels)
               (fun i -> f a.pixels.(i) b.pixels.(i)) }

(** [remap f r] is an alias for [map f r], documenting intent to reclassify. *)
let remap f r = map f r

(* ------------------------------------------------------------------ *)
(* Mode helpers                                                        *)
(* ------------------------------------------------------------------ *)

(** [mode3 v0 v1 v2] returns the most frequent value among three integers.
    Ties resolve to [v0] (mirrors GEE's ImageCollection.mode() tie-breaking). *)
let mode3 v0 v1 v2 =
  if v0 = v1 || v0 = v2 then v0
  else if v1 = v2 then v1
  else v0  (* all different — fall back to first *)

(** [mode_list xs] returns the mode of a non-empty list.
    When multiple values share the maximum frequency, the one encountered
    first in the list is returned (leftmost-wins, mirrors GEE). *)
let mode_list = function
  | [] -> invalid_arg "Raster.mode_list: empty list"
  | [x] -> x
  | first :: _ as xs ->
    let tbl = Hashtbl.create 8 in
    List.iter (fun v ->
      Hashtbl.replace tbl v (1 + (try Hashtbl.find tbl v with Not_found -> 0))
    ) xs;
    let best_v = ref first in
    let best_c = ref 0 in
    Hashtbl.iter (fun v c ->
      if c > !best_c then begin best_v := v; best_c := c end
    ) tbl;
    !best_v

(* ------------------------------------------------------------------ *)
(* Stack operations                                                    *)
(* ------------------------------------------------------------------ *)

(** [mode_stack rasters] computes the pixel-wise mode across a list of rasters.
    All rasters must share the same width * height.
    Raises [Invalid_argument] if the list is empty or dimensions differ. *)
let mode_stack = function
  | []      -> invalid_arg "Raster.mode_stack: empty list"
  | [r]     -> r
  | first :: rest as all ->
    let n = Array.length first.pixels in
    List.iter (fun r ->
      if Array.length r.pixels <> n then
        invalid_arg
          (Printf.sprintf
             "Raster.mode_stack: dimension mismatch (expected %d pixels, got %d)"
             n (Array.length r.pixels))
    ) rest;
    let pixels = Array.init n (fun i ->
      mode_list (List.map (fun r -> r.pixels.(i)) all)
    ) in
    { first with pixels }

(** [slice rasters ~start ~stop] returns the sub-list [rasters[start..stop)].
    Indices are clamped to valid bounds. *)
let slice rasters ~start ~stop =
  let arr = Array.of_list rasters in
  let len = Array.length arr in
  let s = max 0 start in
  let e = min len stop in
  if e <= s then []
  else Array.to_list (Array.sub arr s (e - s))

(* ------------------------------------------------------------------ *)
(* Coordinate helpers                                                  *)
(* ------------------------------------------------------------------ *)

(** [pixel_lat_lon meta row col] returns the (longitude, latitude) of the
    centre of pixel (row, col).
    Assumes [origin_x / origin_y] is the top-left corner and y increases
    northward (i.e. row 0 is the topmost, highest-latitude row). *)
let pixel_lat_lon meta row col =
  let lon = meta.origin_x +. (Float.of_int col +. 0.5) *. meta.x_res in
  let lat = meta.origin_y -. (Float.of_int row +. 0.5) *. meta.y_res in
  (lon, lat)
