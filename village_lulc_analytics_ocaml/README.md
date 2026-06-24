# village_lulc_analytics_ocaml

A standalone OCaml proof-of-concept using the GeoCAML ecosystem to compute
village-level LULC area statistics from GeoTIFF rasters exported by GEE.

> Status: Scaffolding only. No business logic implemented yet.

## Quick Start
    dune build
    dune test
    dune exec village_lulc_analytics_cli

## Milestones
| # | Goal                        |
|---|-----------------------------|
| 1 | Project builds successfully |
| 2 | Load and parse GeoJSON      |
| 3 | Read TIFF file metadata     |
| 4 | Read TIFF pixel values      |
| 5 | Compute area statistics     |
