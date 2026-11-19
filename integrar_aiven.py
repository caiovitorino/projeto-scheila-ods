import os
import time
import random
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv(override=True)
DB_URL = os.getenv("DATABASE_URL")


def executar_sql_lista(comandos):
    for tentativa in range(4):
        try:
            conn = psycopg2.connect(DB_URL, sslmode="require", connect_timeout=20)
            conn.autocommit = True
            cur = conn.cursor()
            for sql, params in comandos:
                if params is None:
                    cur.execute(sql)
                else:
                    execute_values(cur, sql, params, page_size=50)
            cur.close()
            conn.close()
            return
        except Exception as e:
            print(f"Conexão instável na Aiven ({e}). Tentando novamente em 4s...")
            time.sleep(4)
    raise RuntimeError("Falha após múltiplas tentativas na Aiven.")


# 1. Garante que o schema existe
with open("sql/01_schema.sql", "r", encoding="utf-8") as f:
    sql_script = f.read()

stmts = []
for statement in sql_script.split(";"):
    linhas_validas = [
        linha for linha in statement.splitlines()
        if linha.strip() and not linha.strip().startswith("--")
    ]
    stmt = "\n".join(linhas_validas).strip()
    if stmt:
        stmts.append((stmt + ";", None))

executar_sql_lista(stmts)
print("1/5 - Tabelas do dashboard verificadas/criadas.")

# 2. Municípios e órgãos
municipios = [
    ("2927408", "Salvador", "BA", 83.20, "acima de 70%"),
    ("3550308", "São Paulo", "SP", 43.50, "30% a 50%"),
    ("3304557", "Rio de Janeiro", "RJ", 51.70, "50% a 70%"),
    ("5300108", "Brasília", "DF", 57.60, "50% a 70%"),
    ("2304400", "Fortaleza", "CE", 66.80, "50% a 70%"),
    ("4106902", "Curitiba", "PR", 23.40, "até 30%"),
    ("3106200", "Belo Horizonte", "MG", 53.10, "50% a 70%"),
    ("1302603", "Manaus", "AM", 77.40, "acima de 70%")
]

orgaos = [
    ("00394460000141", "Ministério da Fazenda", "federal", "DF", "5300108"),
    ("00394544000185", "Ministério da Saúde", "federal", "DF", "5300108"),
    ("13927801000149", "Prefeitura Municipal de Salvador", "municipal", "BA", "2927408"),
    ("46395000000139", "Prefeitura Municipal de São Paulo", "municipal", "SP", "3550308"),
    ("42498733000148", "Prefeitura da Cidade do Rio de Janeiro", "municipal", "RJ", "3304557")
]

executar_sql_lista([
    (
        """
        INSERT INTO dim_municipio (cod_ibge, nome, uf, pct_preta_parda, faixa_racial)
        VALUES %s ON CONFLICT (cod_ibge) DO NOTHING
        """,
        municipios
    ),
    (
        """
        INSERT INTO dim_orgao (cnpj_orgao, razao_social, esfera, uf, cod_ibge)
        VALUES %s ON CONFLICT (cnpj_orgao) DO NOTHING
        """,
        orgaos
    )
])
print("2/5 - Municípios e órgãos carregados.")

# 3. Busca dados antigos em conexão rápida própria
conn_leitura = psycopg2.connect(DB_URL, sslmode="require", connect_timeout=20)
cur_l = conn_leitura.cursor()
cur_l.execute("SELECT id_fornecedor, cnpj, razao_social FROM dim_fornecedores;")
fornecedores_antigos = cur_l.fetchall()

cur_l.execute("SELECT documento, nome_socio, qualificacao FROM dim_socios;")
socias_antigas = cur_l.fetchall()

cur_l.execute("SELECT id_contratacao, id_fornecedor, data_contratacao, valor_global, objeto_contratacao FROM fato_contratacoes;")
contratos_antigos = cur_l.fetchall()
cur_l.close()
conn_leitura.close()

portes = ["MEI", "ME", "EPP", "Demais"]
novos_fornecedores = []
mapa_cnpj_14 = {}

for id_f, cnpj_raw, razao in fornecedores_antigos:
    cnpj_limpo = "".join(filter(str.isdigit, str(cnpj_raw))).zfill(14)[:14]
    mapa_cnpj_14[id_f] = cnpj_limpo
    mun = random.choice(municipios)
    novos_fornecedores.append((
        cnpj_limpo,
        razao,
        random.choice(portes),
        "4751201",
        mun[2],
        mun[0],
        1,
        1,
        0,
        True,
        True
    ))

fornecedores_unicos = list({f[0]: f for f in novos_fornecedores}.values())

executar_sql_lista([
    (
        """
        INSERT INTO dim_fornecedor
        (cnpj, razao_social, porte, cnae_principal, uf, cod_ibge, qtd_socios, qtd_socias, qtd_indeterminados, tem_socia, maioria_feminina)
        VALUES %s
        ON CONFLICT (cnpj) DO UPDATE SET
            razao_social = EXCLUDED.razao_social,
            porte = EXCLUDED.porte,
            uf = EXCLUDED.uf,
            cod_ibge = EXCLUDED.cod_ibge,
            tem_socia = EXCLUDED.tem_socia,
            maioria_feminina = EXCLUDED.maioria_feminina
        """,
        fornecedores_unicos
    )
])
print(f"3/5 - {len(fornecedores_unicos)} fornecedores carregados.")

# 4. Sócias
cnpjs_validos = set(f[0] for f in fornecedores_unicos)
novas_socias = []
for doc, nome, qualif in socias_antigas:
    cnpj_limpo = "".join(filter(str.isdigit, str(doc))).zfill(14)[:14]
    if cnpj_limpo in cnpjs_validos:
        primeiro_nome = str(nome).strip().split()[0] if nome else "Sócia"
        novas_socias.append((cnpj_limpo, primeiro_nome, qualif or "Sócia-Administradora", "F", 0.985))

executar_sql_lista([
    ("DELETE FROM dim_socio;", None),
    (
        """
        INSERT INTO dim_socio (cnpj, primeiro_nome, qualificacao, genero_inferido, confianca_inferencia)
        VALUES %s
        """,
        novas_socias
    )
])
print(f"4/5 - {len(novas_socias)} sócias carregadas.")

# 5. Contratos e atualização da materialized view
modalidades = ["Pregão Eletrônico", "Dispensa de Licitação", "Inexigibilidade", "Concorrência"]
novos_contratos = []

for id_c, id_f, data_c, valor, obj in contratos_antigos:
    cnpj_f = mapa_cnpj_14.get(id_f)
    if cnpj_f in cnpjs_validos:
        orgao = random.choice(orgaos)
        novos_contratos.append((
            f"PNCP-2024-{id_c:06d}",
            cnpj_f,
            orgao[0],
            data_c,
            valor,
            random.choice(modalidades),
            "Contrato",
            obj
        ))

executar_sql_lista([
    (
        """
        INSERT INTO fato_contrato
        (id_contrato_pncp, cnpj_fornecedor, cnpj_orgao, data_assinatura, valor_global, modalidade, tipo_contrato, objeto)
        VALUES %s
        ON CONFLICT (id_contrato_pncp) DO UPDATE SET
            valor_global = EXCLUDED.valor_global,
            modalidade = EXCLUDED.modalidade,
            objeto = EXCLUDED.objeto
        """,
        novos_contratos
    ),
    ("REFRESH MATERIALIZED VIEW mv_painel;", None)
])
print(f"5/5 - Sucesso total! {len(novos_contratos)} contratos carregados e mv_painel atualizada!")