# Kudra LULC Change Detection Verification Log
## Bihar / Kaimur / Kudra — OCaml vs Python/GEE

**Started:** 2026-06-13  
**Purpose:** Verify OCaml migration reproduces Python/GEE change_detection outputs on real-world Kudra LULC data  
**GEE Project:** arcane-mason-493503-a6  
**GEE Asset Root:** `projects/arcane-mason-493503-a6/assets/apps/mws/bihar/kaimur/kudra/`

---

## Directory Layout
```
kudra_verification/
  lulc_downloads/     — downloaded LULC GeoTIFFs per year + MWS GeoJSON
  python_output/      — change detection rasters/vectors from Python
  ocaml_output/       — change detection rasters/vectors from OCaml
  diff_output/        — difference rasters and comparison stats
  logs/               — intermediate command logs
  VERIFICATION_LOG.md — this file
```

---

## Phase 1: GEE Asset Audit — COMPLETE

### 2026-06-13 — Results

**Phase 1a (initial audit):**
| Asset | Status |
|---|---|
| `filtered_mws_kaimur_kudra_uid` | MISSING |
| LULC 2018–2023 (6 years) | ALL MISSING |
| Change detection rasters | ALL MISSING |
| Change detection vectors | ALL MISSING |

**Phase 1b (deep audit):**
- GEE folder `bihar/kaimur/kudra` EXISTS but is empty
- Pan-India LULC v3 EXISTS for all 6 years at `projects/corestack-datasets/assets/datasets/LULC_v3_river_basin/pan_india_lulc_v3_{Y}_{Y+1}`
- Pan-India MWS dataset EXISTS at `projects/corestack-datasets/assets/datasets/hydrological_boundaries/microwatershed`
- Local admin boundary: `data/admin-boundary/input/bihar/kaimur.geojson` (8.6MB, 1873 village features)

**Phase 1c–1e (boundary investigation):**
- kaimur.geojson has only TEHSIL values 'KAIMUR' and 'MOHANIA' — Kudra not found by name
- SOI tehsil dataset also lacks 'kudra'
- **RESOLUTION**: Identified Kudra block as TID=0007 in kaimur.geojson (178 villages, centroid 83.45°E/24.96°N, closest to Kudra town at 83.49°E/25.03°N)
- Kudra block bounds: [83.3468°E, 24.7919°N, 83.5655°E, 25.1716°N]
- pc11_subdistrict_id: 1452

**Asset IDs to be generated:**
```
projects/arcane-mason-493503-a6/assets/apps/mws/bihar/kaimur/kudra/admin_boundary_kaimur_kudra
projects/arcane-mason-493503-a6/assets/apps/mws/bihar/kaimur/kudra/filtered_mws_kaimur_kudra_uid
projects/arcane-mason-493503-a6/assets/apps/mws/bihar/kaimur/kudra/kaimur_kudra_2018-07-01_2019-06-30_LULCmap_10m
projects/arcane-mason-493503-a6/assets/apps/mws/bihar/kaimur/kudra/kaimur_kudra_2019-07-01_2020-06-30_LULCmap_10m
projects/arcane-mason-493503-a6/assets/apps/mws/bihar/kaimur/kudra/kaimur_kudra_2020-07-01_2021-06-30_LULCmap_10m
projects/arcane-mason-493503-a6/assets/apps/mws/bihar/kaimur/kudra/kaimur_kudra_2021-07-01_2022-06-30_LULCmap_10m
projects/arcane-mason-493503-a6/assets/apps/mws/bihar/kaimur/kudra/kaimur_kudra_2022-07-01_2023-06-30_LULCmap_10m
projects/arcane-mason-493503-a6/assets/apps/mws/bihar/kaimur/kudra/kaimur_kudra_2023-07-01_2024-06-30_LULCmap_10m
```

---

## Phase 2: Asset Generation

### 2026-06-13 — In Progress

Running `phase2_generate_gee_assets.py` to:
1. Upload admin boundary (178 Kudra villages from kaimur.geojson TID=0007)
2. Filter pan-India MWS by Kudra boundary
3. Clip pan-India LULC v3 for each of 6 years

---

