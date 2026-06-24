(* main.ml — GeoCAML Change Detection CLI
 *
 * Usage:
 *   village_lulc_analytics_cli \
 *     --lulc y1.tif y2.tif ... yN.tif   (annual LULC rasters, chronological)
 *     --watersheds watersheds.geojson    (MWS boundary FeatureCollection)
 *     --outdir ./output                  (directory for output files)
 *     [--no-raster]                      (skip writing transition TIFFs)
 *     [--no-vector]                      (skip writing vectorised GeoJSONs)
 *
 * Output files in --outdir:
 *   <outdir>/change_Urbanization.tif
 *   <outdir>/change_Degradation.tif
 *   <outdir>/change_Deforestation.tif
 *   <outdir>/change_Afforestation.tif
 *   <outdir>/change_CropIntensity.tif
 *   <outdir>/change_vector_Urbanization.geojson
 *   <outdir>/change_vector_Degradation.geojson
 *   <outdir>/change_vector_Deforestation.geojson
 *   <outdir>/change_vector_Afforestation.geojson
 *   <outdir>/change_vector_CropIntensity.geojson
 *
 * All raster codes and vector attribute names match the GEE output exactly.
 *)

open Village_lulc_analytics_lib

(* ================================================================== *)
(* CLI argument parsing (stdlib Arg module)                           *)
(* ================================================================== *)

let lulc_paths  : string list ref = ref []
let ws_path     : string ref      = ref ""
let outdir      : string ref      = ref "./output"
let no_raster   : bool ref        = ref false
let no_vector   : bool ref        = ref false

let add_lulc p = lulc_paths := !lulc_paths @ [p]

let spec =
  [ "--lulc",       Arg.String add_lulc,
      "<path>  Annual LULC GeoTIFF (repeat for each year, chronological)";
    "--watersheds", Arg.Set_string ws_path,
      "<path>  GeoJSON FeatureCollection of micro-watershed polygons";
    "--outdir",     Arg.Set_string outdir,
      "<path>  Output directory (default: ./output)";
    "--no-raster",  Arg.Set no_raster,
      " Skip writing transition GeoTIFF outputs";
    "--no-vector",  Arg.Set no_vector,
      " Skip writing vectorised GeoJSON outputs";
  ]

let usage =
  "Usage: village_lulc_analytics_cli --lulc y1.tif y2.tif ... --watersheds ws.geojson [--outdir ./out]"

(* ================================================================== *)
(* GeoJSON watershed parser                                           *)
(* ================================================================== *)

(** Parse a GeoJSON FeatureCollection of polygons into watershed records.
    Only outer rings (first ring of each Polygon) are used. *)
let parse_watersheds_geojson path =
  let ic   = open_in path in
  let len  = in_channel_length ic in
  let buf  = Bytes.create len in
  really_input ic buf 0 len;
  close_in ic;
  let json_str = Bytes.to_string buf in
  let json = Ezjsonm.from_string json_str in

  (* Navigate: {"type":"FeatureCollection","features":[...]} *)
  let features =
    match Ezjsonm.find json ["features"] with
    | `A fs -> fs
    | _ -> failwith "parse_watersheds: no 'features' array"
  in

  List.filter_map (fun feat ->
    let uid_opt =
      try
        match Ezjsonm.find feat ["properties"; "uid"] with
        | `String s -> Some s
        | `Float f  -> Some (Printf.sprintf "%.0f" f)
        | _         -> None
      with Not_found ->
        try
          match Ezjsonm.find feat ["id"] with
          | `String s -> Some s
          | `Float f  -> Some (Printf.sprintf "%.0f" f)
          | _         -> None
        with Not_found -> Some "unknown"
    in
    let uid = match uid_opt with Some u -> u | None -> "unknown" in

    let geom_type =
      try
        match Ezjsonm.find feat ["geometry"; "type"] with
        | `String t -> t
        | _ -> ""
      with Not_found -> ""
    in

    let ring_opt =
      try
        if geom_type = "Polygon" then
          match Ezjsonm.find feat ["geometry"; "coordinates"] with
          | `A (outer_ring :: _) ->
            (match outer_ring with
             | `A pts ->
               let coords = List.filter_map (fun pt ->
                 match pt with
                 | `A [`Float lon; `Float lat] -> Some (lon, lat)
                 | `A [`Float lon; `Float lat; `Float _] -> Some (lon, lat)
                 | _ -> None
               ) pts in
               Some (Array.of_list coords)
             | _ -> None)
          | _ -> None
        else if geom_type = "MultiPolygon" then
          (* Take first polygon, first ring *)
          match Ezjsonm.find feat ["geometry"; "coordinates"] with
          | `A (first_poly :: _) ->
            (match first_poly with
             | `A (outer_ring :: _) ->
               (match outer_ring with
                | `A pts ->
                  let coords = List.filter_map (fun pt ->
                    match pt with
                    | `A [`Float lon; `Float lat] -> Some (lon, lat)
                    | `A [`Float lon; `Float lat; `Float _] -> Some (lon, lat)
                    | _ -> None
                  ) pts in
                  Some (Array.of_list coords)
                | _ -> None)
             | _ -> None)
          | _ -> None
        else
          None
      with Not_found -> None
    in
    match ring_opt with
    | Some ring when Array.length ring >= 3 ->
      Some { Change_detection_vector.uid; geometry = ring }
    | _ -> None
  ) features

(* ================================================================== *)
(* GeoJSON serialiser for watershed_stats                             *)
(* ================================================================== *)

let float_json f = `Float f

let urb_props (a : Change_detection_vector.urb_attrs) =
  [ ("bu_bu",     float_json a.bu_bu);
    ("w_bu",      float_json a.w_bu);
    ("tr_bu",     float_json a.tr_bu);
    ("b_bu",      float_json a.b_bu);
    ("total_urb", float_json a.total_urb); ]

let deg_props (a : Change_detection_vector.deg_attrs) =
  [ ("f_f",       float_json a.f_f);
    ("f_bu",      float_json a.f_bu);
    ("f_ba",      float_json a.f_ba);
    ("f_sc",      float_json a.f_sc);
    ("total_deg", float_json a.total_deg); ]

let def_props (a : Change_detection_vector.def_attrs) =
  [ ("fo_fo",     float_json a.fo_fo);
    ("fo_bu",     float_json a.fo_bu);
    ("fo_fa",     float_json a.fo_fa);
    ("fo_ba",     float_json a.fo_ba);
    ("fo_sc",     float_json a.fo_sc);
    ("total_def", float_json a.total_def); ]

let aff_props (a : Change_detection_vector.aff_attrs) =
  [ ("fo_fo",     float_json a.fo_fo_aff);
    ("bu_fo",     float_json a.bu_fo);
    ("fa_fo",     float_json a.fa_fo);
    ("ba_fo",     float_json a.ba_fo);
    ("sc_fo",     float_json a.sc_fo);
    ("total_aff", float_json a.total_aff); ]

let crop_props (a : Change_detection_vector.crop_attrs) =
  [ ("do_si",        float_json a.do_si);
    ("tr_si",        float_json a.tr_si);
    ("tr_do",        float_json a.tr_do);
    ("si_do",        float_json a.si_do);
    ("si_tr",        float_json a.si_tr);
    ("do_tr",        float_json a.do_tr);
    ("si_si",        float_json a.si_si);
    ("do_do",        float_json a.do_do);
    ("tr_tr",        float_json a.tr_tr);
    ("total_change", float_json a.total_change); ]

(** Serialise a ring to a GeoJSON coordinate array. *)
let ring_to_json ring =
  let pts = Array.to_list (Array.map (fun (lon, lat) ->
    `A [`Float lon; `Float lat]
  ) ring) in
  `A pts

(** Build one GeoJSON Feature from a watershed_stats and a property extractor. *)
let to_feature (ws : Change_detection_vector.watershed_stats)
    (extra_props : (string * Ezjsonm.value) list) =
  let geom =
    `O [ ("type",        `String "Polygon");
         ("coordinates", `A [ ring_to_json ws.geometry ]); ]
  in
  let props =
    `O ([ ("uid", `String ws.uid) ] @ extra_props)
  in
  `O [ ("type",       `String "Feature");
       ("geometry",   geom);
       ("properties", props); ]

(** Write a GeoJSON FeatureCollection to [path]. *)
let write_geojson path features =
  let fc =
    `O [ ("type",     `String "FeatureCollection");
         ("features", `A features); ]
  in
  let oc = open_out path in
  output_string oc (Ezjsonm.to_string fc);
  close_out oc

(** Serialise all five parameters to their own GeoJSON files. *)
let write_vector_outputs outdir stats =
  let base n = Filename.concat outdir n in

  let make_features extractor =
    List.map (fun ws -> to_feature ws (extractor ws)) stats
  in

  write_geojson (base "change_vector_Urbanization.geojson")
    (make_features (fun ws -> urb_props  ws.Change_detection_vector.urbanization));
  write_geojson (base "change_vector_Degradation.geojson")
    (make_features (fun ws -> deg_props  ws.Change_detection_vector.degradation));
  write_geojson (base "change_vector_Deforestation.geojson")
    (make_features (fun ws -> def_props  ws.Change_detection_vector.deforestation));
  write_geojson (base "change_vector_Afforestation.geojson")
    (make_features (fun ws -> aff_props  ws.Change_detection_vector.afforestation));
  write_geojson (base "change_vector_CropIntensity.geojson")
    (make_features (fun ws -> crop_props ws.Change_detection_vector.crop_intensity));

  Printf.printf "[vector] wrote 5 GeoJSON files to %s\n%!" outdir

(* ================================================================== *)
(* Main                                                               *)
(* ================================================================== *)

let () =
  Arg.parse spec (fun _ -> ()) usage;

  (* Validate inputs *)
  let paths = !lulc_paths in
  let n = List.length paths in
  if n <> 2 && n < 4 then begin
    Printf.eprintf "Error: need exactly 2 years (for testing) or >= 4 annual LULC rasters (got %d)\n" n;
    exit 1
  end;
  if not !no_vector && !ws_path = "" then begin
    Printf.eprintf "Error: --watersheds is required for vector output (or use --no-vector)\n";
    exit 1
  end;

  (* Create output directory *)
  (try Unix.mkdir !outdir 0o755
   with Unix.Unix_error (Unix.EEXIST, _, _) -> ());

  (* Load LULC rasters *)
  Printf.printf "[load] loading %d LULC rasters...\n%!" (List.length paths);
  let lulc_stack = List.mapi (fun i p ->
    Printf.printf "  [%d] %s\n%!" i p;
    Tiff_reader.read_raster_from_tiff p
  ) paths in

  (* Run change detection *)
  Printf.printf "[compute] running change detection...\n%!";

  let urb_raster  = Change_detection.urbanization  lulc_stack in
  Printf.printf "  urbanization done\n%!";
  let deg_raster  = Change_detection.degradation   lulc_stack in
  Printf.printf "  degradation done\n%!";
  let def_raster  = Change_detection.deforestation lulc_stack in
  Printf.printf "  deforestation done\n%!";
  let aff_raster  = Change_detection.afforestation lulc_stack in
  Printf.printf "  afforestation done\n%!";
  let crop_raster = Change_detection.crop_intensity lulc_stack in
  Printf.printf "  crop intensity done\n%!";

  (* Write transition TIFFs *)
  if not !no_raster then begin
    Printf.printf "[raster] writing transition TIFFs...\n%!";
    let write name raster =
      let p = Filename.concat !outdir (Printf.sprintf "change_%s.tif" name) in
      Tiff_reader.write_raster_to_tiff raster p;
      Printf.printf "  wrote %s\n%!" p
    in
    write "Urbanization"  urb_raster;
    write "Degradation"   deg_raster;
    write "Deforestation" def_raster;
    write "Afforestation" aff_raster;
    write "CropIntensity" crop_raster
  end;

  (* Vectorise *)
  if not !no_vector then begin
    Printf.printf "[vector] parsing watersheds from %s...\n%!" !ws_path;
    let watersheds = parse_watersheds_geojson !ws_path in
    Printf.printf "[vector] %d watersheds loaded\n%!" (List.length watersheds);

    Printf.printf "[vector] computing zonal statistics...\n%!";
    let stats = Change_detection_vector.vectorise_all
      ~urb_raster
      ~deg_raster
      ~def_raster
      ~aff_raster
      ~crop_raster
      ~watersheds
    in
    Printf.printf "[vector] vectorised %d watersheds\n%!" (List.length stats);

    write_vector_outputs !outdir stats
  end;

  Printf.printf "[done]\n%!"
