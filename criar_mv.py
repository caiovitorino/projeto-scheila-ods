import tomllib
import psycopg2

with open(".streamlit/secrets.toml", "rb") as f:
    s = tomllib.load(f)["postgres"]

conn = psycopg2.connect(
    host=s["host"],
    port=int(s["port"]),
    dbname=s.get("dbname", "defaultdb"),
    user=s["user"],
    password=s["password"],
    sslmode="require",
    connect_timeout=20,
)
conn.autocommit = True
cur = conn.cursor()

with open("sql/01_schema.sql", "r", encoding="utf-8") as f:
    sql_script = f.read()

for statement in sql_script.split(";"):
    linhas_validas = [
        linha for linha in statement.splitlines()
        if linha.strip() and not linha.strip().startswith("--")
    ]
    stmt = "\n".join(linhas_validas).strip()
    if stmt:
        cur.execute(stmt + ";")

cur.execute("REFRESH MATERIALIZED VIEW mv_painel;")
cur.execute("SELECT COUNT(*) FROM mv_painel;")
total_linhas = cur.fetchone()[0]

cur.close()
conn.close()
print(f"Pronto! mv_painel criada e atualizada com {total_linhas} linhas.")