import os, sys
sys.path.insert(0, "/home/uttkarsh/core-stack-backend")
os.chdir("/home/uttkarsh/core-stack-backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")
import django
django.setup()

from utilities.gee_utils import ee_initialize
from utilities.constants import MWS_DATASET
import ee

ee_initialize(1)

mws_fc = ee.FeatureCollection(MWS_DATASET)
first_feat = mws_fc.first()
info = first_feat.getInfo()
print("Properties in microwatershed feature collection:")
for k, v in info.get("properties", {}).items():
    print(f"  {k}: {v} ({type(v)})")
