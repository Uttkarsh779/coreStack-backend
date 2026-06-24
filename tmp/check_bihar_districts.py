import os, sys
sys.path.insert(0, "/home/uttkarsh/core-stack-backend")
os.chdir("/home/uttkarsh/core-stack-backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")
import django
django.setup()

from geoadmin.models import StateSOI, DistrictSOI, TehsilSOI

state_bihar = StateSOI.objects.filter(state_name__icontains="bihar").first()
if state_bihar:
    print(f"Bihar State ID: {state_bihar.id}")
    districts = DistrictSOI.objects.filter(state=state_bihar)
    print(f"Districts in Bihar: {districts.count()}")
    for d in districts:
        tehsils = TehsilSOI.objects.filter(district=d)
        print(f"  District: {d.district_name} (ID: {d.id}), Tehsils: {tehsils.count()}")
        for t in tehsils:
            print(f"    - Tehsil: {t.tehsil_name} (ID: {t.id})")
else:
    print("Bihar state not found in DB.")
