import os, sys
sys.path.insert(0, "/home/uttkarsh/core-stack-backend")
os.chdir("/home/uttkarsh/core-stack-backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")
import django
django.setup()

from geoadmin.models import State_Disritct_Block_Properties

props = State_Disritct_Block_Properties.objects.all()
print(f"Total properties rows: {props.count()}")
found = False
for p in props:
    name = p.tehsil.tehsil_name.lower()
    if "kaimur" in name or "mohania" in name:
        found = True
        print(f"Tehsil: {p.tehsil.tehsil_name}")
        print(f"  Has GeoJSON: {p.dashboard_geojson is not None}")
        if p.dashboard_geojson:
            # print first 200 chars of geojson keys or info
            print(f"  GeoJSON keys: {list(p.dashboard_geojson.keys()) if isinstance(p.dashboard_geojson, dict) else 'not a dict'}")

if not found:
    print("No matching block properties found.")
