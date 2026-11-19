import tomllib
import random
from datetime import date
import psycopg2
from psycopg2.extras import execute_values

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

cur.execute("SELECT cnpj_orgao FROM dim_orgao;")
orgaos = [r[0] for r in cur.fetchall()]

cur.execute("SELECT cnpj FROM dim_fornecedor LIMIT 25;")
fornecedores = [r[0] for r in cur.fetchall()]

modalidades = ["Pregão Eletrônico", "Dispensa de Licitação", "Inexigibilidade", "Concorrência"]
contratos_2022 = []

for i, cnpj_f in enumerate(fornecedores, start=1):
    contratos_2022.append((
        f"PNCP-2022-{i:04d}",
        cnpj_f,
        orgaos[i % len(orgaos)],
        date(2022, (i % 12) + 1, 15),
        round(20000.0 * i, 2),
        modalidades[i % len(modalidades)],
        "Contrato",
        f"Fornecimento 2022 item {i}",
    ))

execute_values(
    cur,
    """
    INSERT INTO fato_contrato
    (id_contrato_pncp, cnpj_fornecedor, cnpj_orgao, data_assinatura, valor_global, modalidade, tipo_contrato, objeto)
    VALUES %s
    ON CONFLICT (id_contrato_pncp) DO NOTHING;
    """,
    contratos_2022,
    page_size=50,
)

cur.execute("REFRESH MATERIALIZED VIEW mv_painel;")
cur.execute("SELECT COUNT(*), array_agg(DISTINCT ano ORDER BY ano) FROM mv_painel;")
total, anos = cur.fetchone()

cur.close()
conn.close()
print(f"Atualizado! mv_painel com {total} linhas e anos: {anos}")
