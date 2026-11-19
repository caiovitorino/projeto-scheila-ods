import tomllib
import random
from datetime import date, timedelta
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

municipios = [
    ("2927408", "Salvador", "BA", 83.20, "acima de 70%"),
    ("3550308", "São Paulo", "SP", 43.50, "30% a 50%"),
    ("3304557", "Rio de Janeiro", "RJ", 51.70, "50% a 70%"),
    ("5300108", "Brasília", "DF", 57.60, "50% a 70%"),
    ("2304400", "Fortaleza", "CE", 66.80, "50% a 70%"),
    ("4106902", "Curitiba", "PR", 23.40, "até 30%"),
]
execute_values(
    cur,
    "INSERT INTO dim_municipio (cod_ibge, nome, uf, pct_preta_parda, faixa_racial) VALUES %s ON CONFLICT (cod_ibge) DO NOTHING;",
    municipios,
    page_size=50,
)

orgaos = [
    ("00394460000141", "Ministério da Fazenda", "federal", "DF", "5300108"),
    ("13927801000149", "Prefeitura Municipal de Salvador", "municipal", "BA", "2927408"),
    ("46395000000139", "Prefeitura Municipal de São Paulo", "municipal", "SP", "3550308"),
    ("42498733000148", "Prefeitura da Cidade do Rio de Janeiro", "municipal", "RJ", "3304557"),
]
execute_values(
    cur,
    "INSERT INTO dim_orgao (cnpj_orgao, razao_social, esfera, uf, cod_ibge) VALUES %s ON CONFLICT (cnpj_orgao) DO NOTHING;",
    orgaos,
    page_size=50,
)

# Tenta aproveitar dados das tabelas antigas se existirem; caso contrário, gera dados base de exemplo
fornecedores_dados = []
socias_dados = []
contratos_dados = []

cur.execute("""
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'dim_fornecedores'
    );
""")
tem_antigas = cur.fetchone()[0]

portes = ["MEI", "Microempresa", "EPP", "Demais"]
modalidades = ["Pregão Eletrônico", "Dispensa de Licitação", "Inexigibilidade", "Concorrência"]

if tem_antigas:
    cur.execute("SELECT id_fornecedor, cnpj, razao_social FROM dim_fornecedores;")
    ant_f = cur.fetchall()
    mapa_id = {}
    for idx, (id_f, cnpj_raw, razao) in enumerate(ant_f, start=1):
        cnpj_14 = ("".join(filter(str.isdigit, str(cnpj_raw))) or f"{idx:014d}").zfill(14)[:14]
        mapa_id[id_f] = cnpj_14
        mun = random.choice(municipios)
        fornecedores_dados.append((
            cnpj_14, razao or f"Fornecedor {idx}", random.choice(portes), "4751201",
            mun[2], mun[0], 2, 1, 0, True, idx % 2 == 0
        ))
    fornecedores_dados = list({x[0]: x for x in fornecedores_dados}.values())

    cur.execute("SELECT documento, nome_socio, qualificacao FROM dim_socios;")
    for doc, nome, qualif in cur.fetchall():
        cnpj_14 = "".join(filter(str.isdigit, str(doc))).zfill(14)[:14]
        if any(x[0] == cnpj_14 for x in fornecedores_dados):
            p_nome = str(nome).strip().split()[0] if nome else "Maria"
            socias_dados.append((cnpj_14, p_nome, qualif or "Sócia-Administradora", "F", 0.985))

    cur.execute("SELECT id_contratacao, id_fornecedor, data_contratacao, valor_global, objeto_contratacao FROM fato_contratacoes;")
    for id_c, id_f, dt, val, obj in cur.fetchall():
        cnpj_f = mapa_id.get(id_f)
        if cnpj_f and any(x[0] == cnpj_f for x in fornecedores_dados):
            org = random.choice(orgaos)
            contratos_dados.append((
                f"PNCP-{id_c}", cnpj_f, org[0], dt or date(2024, 6, 15),
                float(val or 15000.0), random.choice(modalidades), "Contrato", obj or "Serviço público"
            ))

if not fornecedores_dados:
    for i in range(1, 26):
        cnpj_14 = f"{i:014d}"
        mun = municipios[i % len(municipios)]
        fornecedores_dados.append((
            cnpj_14, f"Empresa Exemplo {i} Ltda", portes[i % len(portes)], "6201501",
            mun[2], mun[0], 2, 1, 0, True, i % 2 == 0
        ))
        socias_dados.append((cnpj_14, "Ana", "Sócia-Administradora", "F", 0.990))
        for ano in (2023, 2024):
            contratos_dados.append((
                f"PNCP-{ano}-{i:04d}", cnpj_14, orgaos[i % len(orgaos)][0],
                date(ano, (i % 12) + 1, 10), round(25000.0 * i, 2),
                modalidades[i % len(modalidades)], "Contrato", f"Fornecimento {ano} item {i}"
            ))

execute_values(
    cur,
    """
    INSERT INTO dim_fornecedor
    (cnpj, razao_social, porte, cnae_principal, uf, cod_ibge, qtd_socios, qtd_socias, qtd_indeterminados, tem_socia, maioria_feminina)
    VALUES %s ON CONFLICT (cnpj) DO NOTHING;
    """,
    fornecedores_dados,
    page_size=50,
)

cur.execute("DELETE FROM dim_socio;")
if socias_dados:
    execute_values(
        cur,
        "INSERT INTO dim_socio (cnpj, primeiro_nome, qualificacao, genero_inferido, confianca_inferencia) VALUES %s;",
        socias_dados,
        page_size=50,
    )

execute_values(
    cur,
    """
    INSERT INTO fato_contrato
    (id_contrato_pncp, cnpj_fornecedor, cnpj_orgao, data_assinatura, valor_global, modalidade, tipo_contrato, objeto)
    VALUES %s ON CONFLICT (id_contrato_pncp) DO NOTHING;
    """,
    contratos_dados,
    page_size=50,
)

cur.execute("REFRESH MATERIALIZED VIEW mv_painel;")
cur.execute("SELECT COUNT(*), MIN(ano), MAX(ano) FROM mv_painel;")
qtd, min_ano, max_ano = cur.fetchone()

cur.close()
conn.close()
print(f"Sucesso! mv_painel com {qtd} linhas (anos: {min_ano} a {max_ano}).")
