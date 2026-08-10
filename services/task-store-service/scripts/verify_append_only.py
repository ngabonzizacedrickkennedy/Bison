from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from task_store_service.database import database_path


def main() -> int:
    conn = sqlite3.connect(database_path())

    conn.execute(
        "INSERT INTO execution_log (id, request_id, event, created_at) "
        "VALUES ('t1', 'r1', 'test', '2026-08-10')"
    )
    conn.commit()
    print("insert  ok")

    for row in conn.execute("SELECT id, event FROM execution_log"):
        print(f"row     {row}")

    try:
        conn.execute("UPDATE execution_log SET event = 'tampered' WHERE id = 't1'")
    except sqlite3.IntegrityError as exc:
        print(f"update  refused: {exc}")
    else:
        print("update  SUCCEEDED — trigger is not working")
        return 1

    try:
        conn.execute("DELETE FROM execution_log WHERE id = 't1'")
    except sqlite3.IntegrityError as exc:
        print(f"delete  refused: {exc}")
    else:
        print("delete  SUCCEEDED — trigger is not working")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
