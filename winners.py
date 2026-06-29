import sqlite3
conn = sqlite3.connect('data/mathetes.db')
conn.row_factory = sqlite3.Row
print(f'{"Company":<25} {"Title":<45} {"Q":>3} {"F":>3}')
print('-' * 80)
rows = conn.execute('''
    SELECT c.name AS company, j.title,
           s.qualification_score AS q,
           s.fit_score AS f
    FROM match_scores s
    JOIN jobs j ON j.id = s.job_id
    JOIN companies c ON c.id = j.company_id
    WHERE s.profile_version = (SELECT profile_version FROM match_scores ORDER BY id DESC LIMIT 1)
      AND s.qualification_score >= 50
      AND s.fit_score >= 40
    ORDER BY (s.qualification_score + s.fit_score) DESC
    LIMIT 50
''').fetchall()
for r in rows:
    print(f'{r["company"][:24]:<25} {r["title"][:44]:<45} {r["q"]:>3} {r["f"]:>3}')