#!/usr/bin/env python3
"""
seed_kudra_block.py
-------------------
Seeds the missing 'Kudra' block/tehsil into the database.

Kaimur (Bhabua) District, Bihar:
  - District ID in DB: 626
  - State ID in DB: 30

Kudra is the official Census 2011 tehsil of Kaimur that is missing.
We add it to both TehsilSOI (used by GEE pipeline) and Block (for API).
"""
import os, sys
sys.path.insert(0, "/home/uttkarsh/core-stack-backend")
os.chdir("/home/uttkarsh/core-stack-backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")
import django
django.setup()

from geoadmin.models import StateSOI, DistrictSOI, TehsilSOI, State, District, Block

print("=" * 60)
print("Step 2: Seeding Kudra block into database")
print("=" * 60)

# ── 1. TehsilSOI (used by GEE pipeline) ─────────────────────────
kaimur_soi_district = DistrictSOI.objects.get(id=626)
print(f"Found DistrictSOI: {kaimur_soi_district.district_name} (id={kaimur_soi_district.id})")

kudra_soi, created = TehsilSOI.objects.get_or_create(
    district=kaimur_soi_district,
    tehsil_name="Kudra",
    defaults={"active_status": True}
)
if created:
    print(f"  ✓ Created TehsilSOI: Kudra (id={kudra_soi.id})")
else:
    print(f"  ℹ TehsilSOI already exists: Kudra (id={kudra_soi.id})")

# ── 2. Block (non-SOI, used by API / Django admin) ──────────────
# Find the non-SOI District for Kaimur
try:
    kaimur_district_nonsoi = District.objects.filter(district_name__icontains="kaimur").first()
    if kaimur_district_nonsoi:
        kudra_block, block_created = Block.objects.get_or_create(
            district=kaimur_district_nonsoi,
            block_name="Kudra",
            defaults={"block_census_code": "0", "active_status": True}
        )
        if block_created:
            print(f"  ✓ Created Block: Kudra (id={kudra_block.id}) under {kaimur_district_nonsoi.district_name}")
        else:
            print(f"  ℹ Block already exists: Kudra (id={kudra_block.id})")
    else:
        print("  ⚠ Non-SOI Kaimur District not found – skipping Block seeding")
except Exception as e:
    print(f"  ⚠ Block seeding skipped: {e}")

print()
print("Current TehsilSOI entries under Kaimur:")
for t in TehsilSOI.objects.filter(district__district_name__icontains="kaimur"):
    print(f"  ID: {t.id}, Name: {t.tehsil_name}")

print("\nDone. Kudra is now seeded in the database.")
