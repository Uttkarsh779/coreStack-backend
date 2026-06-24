(* Library entry point — re-exports all public modules. *)

(* Exposed modules (accessible as Village_lulc_analytics_lib.Raster, etc.):
   - Raster                    (Phase 0 — core primitives)
   - Change_detection          (Phases 1-5 — transition rasters)
   - Change_detection_vector   (Phase 6 — vectorisation)
*)

module Raster = Raster
module Change_detection = Change_detection
module Change_detection_vector = Change_detection_vector
module Tiff_reader = Tiff_reader
