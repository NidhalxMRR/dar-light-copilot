"""Initialize the topic tree (idempotent)."""

from rag.scripts.db import connect

TREE = {
    "business": {
        "title": "Business",
        "children": {
            "mr-r": {
                "title": "MR R",
                "children": {
                    "security-startup": {"title": "Security startup", "children": {}},
                    "devops": {"title": "DevOps", "children": {}},
                    "trading": {"title": "Trading", "children": {}},
                },
            }
        },
    },
    "security": {
        "title": "Security",
        "children": {
            "vps-hardening": {
                "title": "VPS hardening",
                "children": {
                    "ufw": {"title": "UFW", "children": {}},
                    "fail2ban": {"title": "fail2ban", "children": {}},
                    "secwatch": {"title": "secwatch monitoring", "children": {}},
                },
            }
        },
    },
    "openclaw": {
        "title": "OpenClaw",
        "children": {
            "windows-node": {
                "title": "Windows node pairing",
                "children": {
                    "tunnel": {"title": "SSH tunnel", "children": {}},
                    "approvals": {"title": "Exec approvals", "children": {}},
                    "debug": {"title": "Debugging", "children": {}},
                },
            }
        },
    },
}


def upsert_topic(cur, parent_id, slug, title):
    cur.execute(
        "INSERT INTO rag_topic(parent_id, slug, title) VALUES (%s,%s,%s) ON CONFLICT(parent_id, slug) DO UPDATE SET title=EXCLUDED.title RETURNING id",
        (parent_id, slug, title),
    )
    return cur.fetchone()[0]


def walk(cur, parent_id, node_dict):
    for slug, node in node_dict.items():
        tid = upsert_topic(cur, parent_id, slug, node["title"])
        walk(cur, tid, node.get("children", {}))


def main():
    with connect() as conn:
        with conn.cursor() as cur:
            walk(cur, None, TREE)
        conn.commit()
    print("ok: init_tree")


if __name__ == "__main__":
    main()
