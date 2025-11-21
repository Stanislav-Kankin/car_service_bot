import sqlite3

conn = sqlite3.connect("car_service_bot.db")
cursor = conn.cursor()

cursor.execute("ALTER TABLE users ADD COLUMN points INTEGER DEFAULT 0;")

conn.commit()
conn.close()

print("Готово! Поле points добавлено.")
