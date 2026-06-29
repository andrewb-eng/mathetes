import sqlite3
conn = sqlite3.connect('data/mathetes.db')
conn.row_factory = sqlite3.Row

phrases = ['forward deployed', 'solutions engineer', 'applied ai', 'ai engineer', 'business operations', 'solutions architect', 'data scientist']

for phrase in phrases:
    result = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE title LIKE ?",
        ('%' + phrase + '%',)
    ).fetchone()
    print(phrase, ':', result[0])