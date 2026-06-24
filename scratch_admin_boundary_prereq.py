import os, sys
sys.path.insert(0, "/home/uttkarsh/core-stack-backend")
os.chdir("/home/uttkarsh/core-stack-backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")
import django
django.setup()

from nrm_app.celery import app
app.conf.task_always_eager = True

from computing.misc.admin_boundary import generate_tehsil_shape_file_data
print("Running generate_tehsil_shape_file_data for Tamil Nadu / Chennai / Guindy ...")
r = generate_tehsil_shape_file_data.delay(
    state="tamil nadu",
    district="chennai",
    block="guindy",
    gee_account_id=1
)
print("Result:", r.get())
print("Done.")
