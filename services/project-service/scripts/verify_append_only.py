from __future__ import annotations

import sqlite3
import sys

from project_service.database import database_path


def expect_refusal(
    connection: sqlite3.Connection,
    label: str,
    statement: str,
    parameters: tuple[object, ...],
) -> bool:
    try:
        connection.execute(statement, parameters)
    except sqlite3.IntegrityError as error:
        print(f"{label}: refused ({error})")
        return True

    print(f"{label}: NOT REFUSED")
    return False


def main() -> int:
    path = database_path()

    if not path.is_file():
        print(f"database not found at {path}")
        return 1

    connection = sqlite3.connect(path)

    try:
        row = connection.execute("SELECT id FROM project_event LIMIT 1").fetchone()

        if row is None:
            print("project_event is empty; create a project first")
            return 1

        event_id = str(row[0])

        updated = expect_refusal(
            connection,
            "update",
            "UPDATE project_event SET reason = ? WHERE id = ?",
            ("tampered", event_id),
        )
        deleted = expect_refusal(
            connection,
            "delete",
            "DELETE FROM project_event WHERE id = ?",
            (event_id,),
        )

        connection.rollback()
    finally:
        connection.close()

    return 0 if updated and deleted else 1


if __name__ == "__main__":
    sys.exit(main())
