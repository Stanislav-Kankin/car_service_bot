import sqlite3

DB_PATH = "car_service_bot.db"  # если лежит рядом с run.py

def safe_alter(cursor, sql: str):
    try:
        cursor.execute(sql)
        print(f"OK: {sql}")
    except sqlite3.OperationalError as e:
        print(f"Skip: {sql} -> {e}")

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # VIN у машины
    safe_alter(cur, "ALTER TABLE cars ADD COLUMN vin VARCHAR(50);")

    # Поля в заявках
    safe_alter(cur, "ALTER TABLE requests ADD COLUMN location_lat REAL;")
    safe_alter(cur, "ALTER TABLE requests ADD COLUMN location_lon REAL;")
    safe_alter(cur, "ALTER TABLE requests ADD COLUMN location_description TEXT;")
    safe_alter(cur, "ALTER TABLE requests ADD COLUMN can_drive BOOLEAN;")

    conn.commit()
    conn.close()
    print("Миграция завершена.")

if __name__ == '__main__':
    main()
