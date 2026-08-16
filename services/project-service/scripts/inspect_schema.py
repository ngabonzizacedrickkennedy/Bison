import os
import sqlite3

path = os.path.join(os.environ["LOCALAPPDATA"], "BISON", "project.db")
db = sqlite3.connect(path)

names = [
    row[0]
    for row in db.execute("select name from sqlite_master where type = 'table' order by name")
]
print(len(names), "tables")
for name in names:
    print(" ", name)

print()
for column in db.execute("pragma table_info(project_brief)"):
    print(column[1], column[2], "notnull" if column[3] else "")
