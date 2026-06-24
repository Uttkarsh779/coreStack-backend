(* tiff_reader.ml — Phase 7: GeoTIFF Reader and Writer
 *
 * Implements loading/saving uncompressed GeoTIFFs using the ocaml-tiff library.
 *)

open Bigarray

(** [read_raster_from_tiff path] reads an uncompressed GeoTIFF file at [path] and
    constructs a [Raster.t] representation including spatial metadata (resolution, tiepoints). *)
let read_raster_from_tiff (path : string) : Raster.t =
  Tiff_unix.with_open_in path (fun file_ro ->
    let header = Tiff.Ifd.read_header file_ro in
    let ifd = Tiff.Ifd.v ~file_offset:header.offset header file_ro in
    let width = Tiff.Ifd.width ifd in
    let height = Tiff.Ifd.height ifd in
    
    (* Read BitsPerSample to determine data kind (default 8) *)
    let bits =
      try
        match Tiff.Ifd.bits_per_sample ifd with
        | [] -> 8
        | b :: _ -> b
      with _ -> 8
    in

    (* Read GeoTIFF ModelPixelScaleTag *)
    let scale =
      try Tiff.Ifd.pixel_scale ifd
      with _ -> [| 1.0; 1.0; 0.0 |]
    in

    (* Read GeoTIFF ModelTiepointTag *)
    let tiepoint =
      try Tiff.Ifd.tiepoint ifd
      with _ -> [| 0.0; 0.0; 0.0; 0.0; 0.0; 0.0 |]
    in

    let x_res = if Array.length scale > 0 then scale.(0) else 10.0 in
    let y_res = if Array.length scale > 1 then scale.(1) else 10.0 in
    let origin_x = if Array.length tiepoint > 3 then tiepoint.(3) else 0.0 in
    let origin_y = if Array.length tiepoint > 4 then tiepoint.(4) else 0.0 in

    let meta : Raster.metadata = {
      width;
      height;
      x_res;
      y_res;
      origin_x;
      origin_y;
    } in

    let pixels =
      if bits <= 8 then
        let t = Tiff.from_file Tiff.Uint8 file_ro in
        let d = Tiff.data t file_ro in
        let dims = Genarray.dims d in
        let arr = Array.make (width * height) 0 in
        if Array.length dims = 2 then
          for r = 0 to height - 1 do
            for c = 0 to width - 1 do
              arr.(r * width + c) <- Genarray.get d [| r; c |]
            done
          done
        else if Array.length dims = 3 then
          for r = 0 to height - 1 do
            for c = 0 to width - 1 do
              arr.(r * width + c) <- Genarray.get d [| 0; r; c |]
            done
          done;
        arr
      else if bits <= 16 then
        let t = Tiff.from_file Tiff.Uint16 file_ro in
        let d = Tiff.data t file_ro in
        let dims = Genarray.dims d in
        let arr = Array.make (width * height) 0 in
        if Array.length dims = 2 then
          for r = 0 to height - 1 do
            for c = 0 to width - 1 do
              arr.(r * width + c) <- Genarray.get d [| r; c |]
            done
          done
        else if Array.length dims = 3 then
          for r = 0 to height - 1 do
            for c = 0 to width - 1 do
              arr.(r * width + c) <- Genarray.get d [| 0; r; c |]
            done
          done;
        arr
      else
        let t = Tiff.from_file Tiff.Int32 file_ro in
        let d = Tiff.data t file_ro in
        let dims = Genarray.dims d in
        let arr = Array.make (width * height) 0 in
        if Array.length dims = 2 then
          for r = 0 to height - 1 do
            for c = 0 to width - 1 do
              arr.(r * width + c) <- Int32.to_int (Genarray.get d [| r; c |])
            done
          done
        else if Array.length dims = 3 then
          for r = 0 to height - 1 do
            for c = 0 to width - 1 do
              arr.(r * width + c) <- Int32.to_int (Genarray.get d [| 0; r; c |])
            done
          done;
        arr
    in
    Raster.create meta pixels
  )

(** [write_raster_to_tiff raster path] writes [raster] to an uncompressed 8-bit TIFF file at [path]. *)
let write_raster_to_tiff (raster : Raster.t) (path : string) : unit =
  let meta = raster.Raster.meta in
  let width = meta.Raster.width in
  let height = meta.Raster.height in
  let arr = Genarray.create int8_unsigned c_layout [| height; width |] in
  for r = 0 to height - 1 do
    for c = 0 to width - 1 do
      Genarray.set arr [| r; c |] (Raster.get raster r c)
    done
  done;
  let tiff = Tiff.make arr in
  Tiff_unix.with_open_out path (fun file_wo ->
    Tiff.to_file tiff file_wo
  )
