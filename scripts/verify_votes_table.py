import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'votacion.settings')
django.setup()

from django.db import connection

def print_columns(table_name):
    vendor = connection.vendor
    print('DB vendor:', vendor)
    with connection.cursor() as c:
        if vendor == 'sqlite':
            c.execute(f"PRAGMA table_info('{table_name}')")
            rows = c.fetchall()
            print(f"Columns for {table_name}:")
            for r in rows:
                print(r)
        else:
            try:
                c.execute("SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name = %s", [table_name])
                rows = c.fetchall()
                print(f"Columns for {table_name}:")
                for r in rows:
                    print(r)
            except Exception as e:
                print('Could not query information_schema:', e)

if __name__ == '__main__':
    print_columns('elecciones_voto')
