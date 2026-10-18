import os
import sqlite3

def clean_db(path):
    if not os.path.exists(path):
        return
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("UPDATE users SET telegram_chat_id = '6856103038', telegram_status = 'linked' WHERE email IN ('dirtbike000000@gmail.com', 'tapise.utkarsh@gmail.com')")
    cur.execute("UPDATE users SET telegram_chat_id = NULL, telegram_status = 'not_linked' WHERE telegram_chat_id IN ('123456789', '98765432', '12345678', '987654321', 'simulation_chat')")
    conn.commit()
    print("Cleaned:", path)
    cur.execute("SELECT email, telegram_status, telegram_chat_id FROM users WHERE telegram_chat_id IS NOT NULL")
    for row in cur.fetchall():
        print(" ", row)
    conn.close()

if __name__ == "__main__":
    clean_db("C:/Vyzn testing data/index.db")
    clean_db("data/clips/index.db")
    clean_db("index.db")
