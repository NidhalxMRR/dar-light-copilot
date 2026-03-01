"""Keyword search demo (no plaintext retrieval)."""

import sys
from rag.scripts.db import connect


def main():
    q = " ".join(sys.argv[1:]).strip().lower()
    if not q:
        print("usage: python -m rag.scripts.search <keyword>")
        raise SystemExit(2)

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT k.keyword, k.weight, t.title, t.slug
                FROM rag_keyword k
                LEFT JOIN rag_topic t ON t.id = k.topic_id
                WHERE k.keyword = %s
                ORDER BY k.weight DESC
                LIMIT 50
                """,
                (q,),
            )
            rows = cur.fetchall()

    if not rows:
        print("no hits")
        return

    for kw, w, title, slug in rows:
        print(f"{kw} (w={w}) -> topic={title} slug={slug}")


if __name__ == "__main__":
    main()
