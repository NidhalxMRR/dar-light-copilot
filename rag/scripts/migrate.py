"""Apply schema.sql.

This is intentionally simple for hackathon.
"""

from pathlib import Path
from rag.scripts.db import connect


def main():
    schema_path = Path(__file__).resolve().parents[1] / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    print("ok: migrated")


if __name__ == "__main__":
    main()
