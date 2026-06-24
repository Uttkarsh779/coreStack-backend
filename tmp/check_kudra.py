import os, sys
sys.path.insert(0, "/home/uttkarsh/core-stack-backend")
os.chdir("/home/uttkarsh/core-stack-backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")
import django
django.setup()

from geoadmin.models import TehsilSOI, Block

print("Checking TehsilSOI:")
tehsils = TehsilSOI.objects.filter(tehsil_name__icontains="kudra")
for t in tehsils:
    print(f"  TehsilSOI ID: {t.id}, Name: {t.tehsil_name}")

print("\nChecking Block (non-SOI):")
blocks = Block.objects.filter(block_name__icontains="kudra")
for b in blocks:
    print(f"  Block ID: {b.id}, Name: {b.block_name}, District: {b.district.district_name}")
