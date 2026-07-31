"""Print the current shortlist to the terminal.

Top 50 scored jobs with qualification >= 50 and fit >= 40, restricted to the
latest profile version (so stale scores from earlier profile/resume edits are
excluded), ranked by combined score.
"""
from db import get_connection


def main():
    conn = get_connection()
    try:
        rows = conn.execute("""
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
        """).fetchall()
    finally:
        conn.close()

    if not rows:
        print("No winners yet — run pull.py and match_batch.py first.")
        return

    print(f'{"Company":<25} {"Title":<45} {"Q":>3} {"F":>3}')
    print("-" * 80)
    for r in rows:
        print(f'{r["company"][:24]:<25} {r["title"][:44]:<45} {r["q"]:>3} {r["f"]:>3}')


if __name__ == "__main__":
    main()
