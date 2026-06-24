import os, sys
sys.path.insert(0, "/home/uttkarsh/core-stack-backend")
os.chdir("/home/uttkarsh/core-stack-backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")
import django
django.setup()

from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("SELECT * FROM overpass_block_details LIMIT 5;")
    rows = cursor.fetchall()
    print("Sample rows in overpass_block_details:")
    for r in rows:
        print(r)

    # Get column names
    cursor.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'overpass_block_details';")
    cols = cursor.fetchall()
    print("\nColumns in overpass_block_details:")
    for c in cols:
        print(f"  {c[0]} ({c[1]})")
