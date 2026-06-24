#!/usr/bin/env python3
"""
check_gee_tasks.py
------------------
Monitors the status of running GEE export tasks.
Run this after export_lulc_to_local.py to know when TIFFs are ready in Drive.
"""
import os, sys, json
sys.path.insert(0, '/home/uttkarsh/core-stack-backend')
os.chdir('/home/uttkarsh/core-stack-backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nrm_app.settings')
import django
django.setup()

from utilities.gee_utils import ee_initialize
import ee

ee_initialize(1)

meta_path = 'data/lulc_exports/export_meta.json'
with open(meta_path) as f:
    meta = json.load(f)

task_ids = meta['task_ids']
print(f"Checking {len(task_ids)} task(s)...\n")

all_done = True
for task_id in task_ids:
    status = ee.data.getTaskStatus([task_id])[0]
    state = status['state']
    desc = status.get('description', task_id[:12])
    err = status.get('error_message', '')
    print(f"  Task {task_id[:12]}... [{state}] {desc}")
    if err:
        print(f"    Error: {err}")
    if state not in ('COMPLETED', 'FAILED', 'CANCELLED'):
        all_done = False

if all_done:
    print("\n✓ All tasks done. Download TIFFs from Google Drive folder 'core_stack_lulc_exports'.")
    print("  Then place at data/lulc_exports/lulc_guindy_2022-2023.tif etc.")
else:
    print("\n⏳ Tasks still running. Re-run this script in a few minutes.")
