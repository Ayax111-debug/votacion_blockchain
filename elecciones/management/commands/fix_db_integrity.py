from django.core.management.base import BaseCommand
from django.db import connection, transaction
import uuid
from datetime import datetime

class Command(BaseCommand):
    help = 'Fix common DB integrity issues: empty id values and string datetimes in elecciones tables.'

    def handle(self, *args, **options):
        self.stdout.write('Starting DB integrity fix...')
        with connection.cursor() as cur:
            # Get all tables in current DB
            cur.execute("SELECT TABLE_NAME FROM information_schema.tables WHERE table_schema=DATABASE()")
            tables = [r[0] for r in cur.fetchall()]

            fixed_counts = {}

            for t in tables:
                # Fix empty id rows if the table has an 'id' column
                try:
                    cur.execute(f"DESCRIBE `{t}`")
                    cols = [r[0] for r in cur.fetchall()]
                except Exception:
                    continue

                if 'id' in cols:
                    # Count empty or NULL id rows
                    cur.execute(f"SELECT COUNT(*) FROM `{t}` WHERE id = '' OR id IS NULL")
                    cnt = cur.fetchone()[0]
                    if cnt > 0:
                        self.stdout.write(f"Table {t} has {cnt} empty id rows. Fixing...")
                        fixed = 0
                        while True:
                            cur.execute(f"SELECT id FROM `{t}` WHERE id = '' OR id IS NULL LIMIT 1")
                            row = cur.fetchone()
                            if not row:
                                break
                            new_id = uuid.uuid4().hex
                            cur.execute(f"UPDATE `{t}` SET id = %s WHERE id = '' OR id IS NULL LIMIT 1", (new_id,))
                            fixed += 1
                        fixed_counts[t] = fixed

                # For known datetime columns, try to fix string values
                # We'll look for common election tables and common datetime columns
                datetime_cols = []
                if t.lower().startswith('elecciones_evento'):
                    datetime_cols = ['fecha_inicio', 'fecha_termino', 'created_at', 'updated_at']
                elif t.lower().startswith('elecciones_candidatura'):
                    datetime_cols = ['fecha_registro']
                elif t.lower().startswith('elecciones_voto'):
                    datetime_cols = ['time_stamp']
                elif t.lower().startswith('elecciones_resultado'):
                    datetime_cols = ['updated_at']
                elif t.lower().startswith('elecciones_persona'):
                    datetime_cols = ['created_at']

                for col in datetime_cols:
                    if col in cols:
                        # Find rows where the DB returned a string for the datetime
                        try:
                            cur.execute(f"SELECT id, `{col}` FROM `{t}` WHERE `{col}` IS NOT NULL LIMIT 1000")
                            rows = cur.fetchall()
                        except Exception:
                            continue

                        for rid, val in rows:
                            if isinstance(val, str):
                                parsed = None
                                for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S'):
                                    try:
                                        parsed = datetime.strptime(val, fmt)
                                        break
                                    except Exception:
                                        continue
                                if parsed:
                                    self.stdout.write(f"Converting string datetime in {t}.{col} (id={rid}) -> {parsed}")
                                    try:
                                        cur.execute(f"UPDATE `{t}` SET `{col}` = %s WHERE id = %s", (parsed, rid))
                                    except Exception as e:
                                        self.stdout.write(f"Failed to update {t}.{col} for id={rid}: {e}")

            self.stdout.write('DB integrity fix complete.')
            if fixed_counts:
                for k, v in fixed_counts.items():
                    self.stdout.write(f'Fixed {v} empty id rows in {k}')