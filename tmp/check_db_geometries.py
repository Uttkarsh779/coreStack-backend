import os, sys
sys.path.insert(0, "/home/uttkarsh/core-stack-backend")
os.chdir("/home/uttkarsh/core-stack-backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")
import django
django.setup()

from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("""
        SELECT table_name, column_name, udt_name 
        FROM information_schema.columns 
        WHERE udt_name = 'geometry' or column_name LIKE '%geom%';
    """)
    rows = cursor.fetchall()
    print("Geometry columns found in database:")
    for r in rows:
        print(f"  Table: {r[0]}, Column: {r[1]}, Type: {r[2]}")

    # Check if we have any spatial tables or records populated
    cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public';")
    tables = [t[0] for t in cursor.fetchall()]
    print("\nAll tables in public schema:")
    print(", ".join(tables))
