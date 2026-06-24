import os, sys
sys.path.insert(0, "/home/uttkarsh/core-stack-backend")
os.chdir("/home/uttkarsh/core-stack-backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")
import django
django.setup()

from geoadmin.models import StateSOI, DistrictSOI, TehsilSOI
print("States containing 'bihar':")
for s in StateSOI.objects.filter(state_name__icontains="bihar"):
    print(f"  id={s.id}: {s.state_name}")

print("\nDistricts containing 'kaimur':")
for d in DistrictSOI.objects.filter(district_name__icontains="kaimur"):
    print(f"  id={d.id}: {d.district_name} under {d.state.state_name}")

print("\nBlocks under Kaimur (Bhabua) district:")
for t in TehsilSOI.objects.filter(district__district_name__icontains="kaimur"):
    print(f"  {t.id}: {t.tehsil_name}")

print("\n--- Tamil Nadu / Chennai / Guindy ---")
print("\nStates containing 'tamil':")
for s in StateSOI.objects.filter(state_name__icontains="tamil"):
    print(f"  id={s.id}: {s.state_name}")

print("\nDistricts containing 'chennai':")
for d in DistrictSOI.objects.filter(district_name__icontains="chennai"):
    print(f"  id={d.id}: {d.district_name} under {d.state.state_name}")

print("\nTehsils/Blocks containing 'guindy':")
for t in TehsilSOI.objects.filter(tehsil_name__icontains="guindy"):
    print(f"  id={t.id}: {t.tehsil_name} under {t.district.district_name}")

print("\nAll Blocks under Chennai district:")
for t in TehsilSOI.objects.filter(district__district_name__icontains="chennai"):
    print(f"  id={t.id}: {t.tehsil_name}")
