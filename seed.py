# seed.py — Popula o banco VadeMecum AI a partir da API do Senado
# Requisitos: requests instalado; schema.sql e texto_integral.py na mesma pasta.
# Uso: python seed.py

import re
import sys
import time
import sqlite3
import requests

try:
    from texto_integral import extrair_texto_integral
except ImportError:
    print("ERRO: texto_integral.py não encontrado na mesma pasta do seed.py")
    sys.exit(1)

DB = "vademecum.db"
SCHEMA = "schema.sql"
BASE_API = "https://legis.senado.leg.br/dadosabertos/senado/dados"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

# ------------------------------------------------------------
# IDs confirmados manualmente (pulem a busca na API).
# Preencha aqui os IDs que a busca automática não encontrar.
# ------------------------------------------------------------
# --- 17 normas novas (IDs verificados na API do Senado em 18/10/2026) ---
# ATENÇÃO: a chave DEVE ser idêntica ao apelido usado na tupla VADE_MECUM.
# Se divergir (acentos, parênteses, maiúsculas), a busca manual falha
# silenciosamente e o sistema volta a depender da busca automática.
IDS_MANUAIS = {
    "Lei da Propriedade Industrial": 551155,                        # Lei 9.279/1996
    "Lei Orgânica da Seguridade Social": 550088,                    # Lei 8.212/1991
    "Plano de Benefícios da Previdência Social": 550089,            # Lei 8.213/1991
    "Regulamento da Previdência Social": 399211,                    # Decreto 3.048/1999
    "Lei Orgânica da Assistência Social (LOAS)": 550618,            # Lei 8.742/1993
    "Política Nacional do Meio Ambiente": 548814,                   # Lei 6.938/1981
    "Estatuto da Terra": 546356,                                    # Lei 4.504/1964
    "Normas Gerais de Direito Financeiro": 546169,                  # Lei 4.320/1964
    "Lei de Defesa da Concorrência": 584385,                        # Lei 12.529/2011
    "Lei Geral de Proteção de Dados Pessoais (LGPD)": 27457334,     # Lei 13.709/2018
    "Marco Civil da Internet": 584776,                              # Lei 12.965/2014
    "Lei dos Crimes Informáticos (Lei Carolina Dieckmann)": 588113, # Lei 12.737/2012
    "Juizados Especiais da Fazenda Pública": 580845,                # Lei 12.153/2009
    "Lei do Mandado de Segurança": 580239,                          # Lei 12.016/2009
    "Lei da Ação Popular": 546570,                                  # Lei 4.717/1965
    "Lei da Ação Civil Pública": 549223,                            # Lei 7.347/1985
    "Lei de Arbitragem": 551183,                                    # Lei 9.307/1996
}

# ------------------------------------------------------------
# Núcleo do Vade Mecum
# (sigla, tipo_norma, numero, ano, apelido, area_direito, id_senado, palavras_chave)
# id_senado = None -> o script busca na API (ou usa IDS_MANUAIS)
# ------------------------------------------------------------
VADE_MECUM = [
    ("CF", "CONSTITUICAO", "1988", 1988, "Constituição Federal", "CONSTITUCIONAL", 579494,
     ["direitos fundamentais", "igualdade"]),
    ("LEI", "LEI", "10406", 2002, "Código Civil", "CIVIL", 552282,
     ["obrigações", "contratos"]),
    ("LEI", "LEI", "8078", 1990, "Código de Defesa do Consumidor", "CONSUMIDOR", 549954,
     ["consumidor", "publicidade"]),
    ("LEI", "LEI", "13146", 2015, "Estatuto da Pessoa com Deficiência", "CIVIL", 584958,
     ["deficiência", "capacidade civil"]),
    ("DL", "DECRETO-LEI", "2848", 1940, "Código Penal", "PENAL", 527942,                            # veio do seu seed
     ["homicídio", "crime", "pena"]),
    ("DL", "DECRETO-LEI", "1001", 1969, "Código Penal Militar", "PENAL", 524625,
    ["crime militar"]),
    ("LEI", "LEI", "7210", 1984, "Lei de Execução Penal", "PENAL", 549086,
     ["execução penal", "preso"]),
    ("LEI", "LEI", "8072", 1990, "Lei de Crimes Hediondos", "PENAL", 549948,
     ["hediondez"]),
    ("LEI", "LEI", "9455", 1997, "Lei de Tortura", "PENAL", 551331,
     ["tortura"]),
    ("LEI", "LEI", "9605", 1998, "Lei de Crimes Ambientais", "AMBIENTAL", 551481,
     ["meio ambiente", "crime ambiental"]),
    ("LEI", "LEI", "11343", 2006, "Lei de Drogas", "PENAL", 572128,
     ["drogas", "entorpecentes"]),
    ("LEI", "LEI", "11340", 2006, "Lei Maria da Penha", "PENAL", 572125,
     ["violência doméstica", "mulher"]),
    ("LEI", "LEI", "8069", 1990, "Estatuto da Criança e do Adolescente", "PENAL", 549945,
     ["criança", "adolescente"]),
    ("LEI", "LEI", "10741", 2003, "Estatuto do Idoso", "PENAL", 552617,
    ["idoso"]),
    ("LEI", "LEI", "10826", 2003, "Estatuto do Desarmamento", "PENAL", 552702,
     ["arma de fogo"]),
    ("DL", "DECRETO-LEI", "3689", 1941, "Código de Processo Penal", "PROCESSUAL PENAL", 528776,
    ["processo penal", "prisão"]),
    ("LEI", "LEI", "9099", 1995, "Lei dos Juizados Especiais", "PROCESSUAL PENAL", 550975,
     ["juizado especial", "infração de menor potencial"]),
    ("LEI", "LEI", "13105", 2015, "Código de Processo Civil", "PROCESSUAL CIVIL", 584917,
     ["processo civil", "jurisdição"]),
    ("DL", "DECRETO-LEI", "5452", 1943, "Consolidação das Leis do Trabalho", "TRABALHISTA", 530547,
     ["trabalho", "empregado"]),
    ("LEI", "LEI", "5172", 1966, "Código Tributário Nacional", "TRIBUTARIO", 547034,
     ["tributo", "imposto"]),
    ("LEI", "LEI", "9503", 1997, "Código de Trânsito Brasileiro", "TRANSITO", 551379,
     ["trânsito", "racha", "corrida ilegal"]),
    ("LEI", "LEI", "8112", 1990, "Regime Jurídico dos Servidores Federais", "ADMINISTRATIVO", 549988,
    ["servidor público"]),
    ("LEI", "LEI", "8429", 1992,"Lei de Improbidade Administrativa", "ADMINISTRATIVO", 550305,
     ["improbidade"]),
    ("LEI", "LEI", "9784", 1999, "Lei de Processo Administrativo Federal", "ADMINISTRATIVO", 551660,
    ["processo administrativo"]),
    ("LEI", "LEI", "12527", 2011, "Lei de Acesso à Informação", "ADMINISTRATIVO", 584383,
    ["informação", "transparência"]),
    ("LEI", "LEI", "14133", 2021,"Lei de Licitações e Contratos", "ADMINISTRATIVO", 33382036,
    ["licitação", "contrato administrativo"]),
    ("LEI", "LEI", "4737", 1965,"Código Eleitoral", "ELEITORAL", 546590,
    ["eleição", "voto"]),
    ("LEI", "LEI", "6404", 1976, "Lei de Sociedades por Ações", "EMPRESARIAL", 548280,
    ["sociedade anônima", "acionista"]),
    ("LEI", "LEI", "11101", 2005, "Lei de Falências e Recuperação Judicial", "EMPRESARIAL", 570550,
     ["falência", "recuperação judicial"]),
        # --- 17 novas normas (IDs verificados na API do Senado em 18/10/2026) ---
    ("LEI", "LEI", "9279", 1996, "Lei da Propriedade Industrial", "EMPRESARIAL", 551155,
     ["propriedade industrial", "patente", "marca"]),
    ("LEI", "LEI", "8212", 1991, "Lei Orgânica da Seguridade Social", "PREVIDENCIARIO", 550088,
     ["seguridade social", "custeio", "contribuição social"]),
    ("LEI", "LEI", "8213", 1991, "Plano de Benefícios da Previdência Social", "PREVIDENCIARIO", 550089,
     ["previdência social", "benefício", "aposentadoria"]),
    ("DEC", "DECRETO", "3048", 1999, "Regulamento da Previdência Social", "PREVIDENCIARIO", 399211,
     ["previdência social", "regulamento", "benefício"]),
    ("LEI", "LEI", "8742", 1993, "Lei Orgânica da Assistência Social (LOAS)", "PREVIDENCIARIO", 550618,
     ["assistência social", "benefício de prestação continuada", "BPC"]),
    ("LEI", "LEI", "6938", 1981, "Política Nacional do Meio Ambiente", "AMBIENTAL", 548814,
     ["meio ambiente", "política ambiental", "licenciamento"]),
    ("LEI", "LEI", "4504", 1964, "Estatuto da Terra", "AGRARIO", 546356,
     ["reforma agrária", "imóvel rural", "terra"]),
    ("LEI", "LEI", "4320", 1964, "Normas Gerais de Direito Financeiro", "FINANCEIRO", 546169,
     ["direito financeiro", "orçamento", "despesa pública"]),
    ("LEI", "LEI", "12529", 2011, "Lei de Defesa da Concorrência", "ECONOMICO", 584385,
     ["concorrência", "cartel", "CADE"]),
    ("LEI", "LEI", "13709", 2018, "Lei Geral de Proteção de Dados Pessoais (LGPD)", "TECNOLOGIA", 27457334,
     ["proteção de dados", "dado pessoal", "privacidade"]),
    ("LEI", "LEI", "12965", 2014, "Marco Civil da Internet", "TECNOLOGIA", 584776,
     ["internet", "neutralidade de rede", "provedor"]),
    ("LEI", "LEI", "12737", 2012, "Lei dos Crimes Informáticos (Lei Carolina Dieckmann)", "TECNOLOGIA", 588113,
     ["crime informático", "dado eletrônico", "invasão de dispositivo"]),
    ("LEI", "LEI", "12153", 2009, "Juizados Especiais da Fazenda Pública", "PROCESSUAL CIVIL", 580845,
     ["juizado especial", "fazenda pública", "causa de pequeno valor"]),
    ("LEI", "LEI", "12016", 2009, "Lei do Mandado de Segurança", "PROCESSUAL CIVIL", 580239,
     ["mandado de segurança", "direito líquido e certo", "segurança"]),
    ("LEI", "LEI", "4717", 1965, "Lei da Ação Popular", "PROCESSUAL CIVIL", 546570,
     ["ação popular", "cidadão", "patrimônio público"]),
    ("LEI", "LEI", "7347", 1985, "Lei da Ação Civil Pública", "PROCESSUAL CIVIL", 549223,
     ["ação civil pública", "interesse difuso", "interesse coletivo"]),
    ("LEI", "LEI", "9307", 1996, "Lei de Arbitragem", "PROCESSUAL CIVIL", 551183,
     ["arbitragem", "árbitro", "convenção de arbitragem"]),
]


# ------------------------------------------------------------
# Utilidades de parsing (defensivas — a estrutura do JSON da
# API pode variar; a busca é case-insensitive e recursiva)
# ------------------------------------------------------------
def _procurar_chave(dados, nomes):
    """Busca recursiva pela primeira chave cujo nome (lowercase)
    esteja em `nomes`. Retorna o valor ou None."""
    alvos = {n.lower() for n in nomes}
    if isinstance(dados, dict):
        for chave, valor in dados.items():
            if str(chave).lower() in alvos:
                return valor
        for valor in dados.values():
            resultado = _procurar_chave(valor, nomes)
            if resultado is not None:
                return resultado
    elif isinstance(dados, list):
        for item in dados:
            resultado = _procurar_chave(item, nomes)
            if resultado is not None:
                return resultado
    return None


# ------------------------------------------------------------
# CONFIGURAÇÃO DA API (atualizada — endpoints de /legislacao)
# ------------------------------------------------------------
BASE_API = "https://legis.senado.leg.br/dadosabertos"

# Siglas da lista do Vade Mecum -> siglas aceitas pela API atual
# (tabela oficial: /dadosabertos/legislacao/tiposNorma.csv)
SIGLAS_API = {
    "CF": "CON-v", "CONSTITUICAO": "CON-v", "CON": "CON-v",
    "ADCT": "ADCT",
    "DL": "DEL", "DECRETO-LEI": "DEL",
    "DEC": "DEC-n", "DECRETO": "DEC-n",
    "LEI": "LEI",
    "MP": "MPV", "MPV": "MPV", "MEDIDA PROVISORIA": "MPV",
}

# Normas sem número próprio: busca direta pela URN (endpoint /legislacao/urn)
URNS_ESPECIAIS = {
    "CF": "urn:lex:br:federal:constituicao:1988-10-05;1988",
    "ADCT": "urn:lex:br:federal:constituicao:1988-10-05;adct",
}


def _extrair_id_documento(dados):
    """Extrai o ID da norma. Estrutura verificada:
    DetalheDocumento > documentos > documento[0] > id"""
    docs = (dados.get("DetalheDocumento", {}).get("documentos", {}) or {}) \
        .get("documento") or []
    if not docs:
        return None
    try:
        valor = int(str(docs[0].get("id")).strip())
        return valor if valor > 0 else None
    except (TypeError, ValueError):
        return None


def buscar_id_senado(sigla, numero, ano):
    """Busca o ID da norma na API ATUAL do Senado.
    O endpoint antigo (/senado/dados/lista/textos) foi descontinuado."""
    # 1) Normas sem número (CF, ADCT): endpoint por URN
    urn = URNS_ESPECIAIS.get(sigla)
    if urn:
        try:
            resp = requests.get(f"{BASE_API}/legislacao/urn",
                                params={"urn": urn}, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                id_norma = _extrair_id_documento(resp.json())
                if id_norma:
                    return id_norma
            print(f"      [AVISO] Busca por URN: status {resp.status_code}")
        except Exception as e:
            print(f"      [AVISO] Busca por URN falhou: {e}")

    # 2) Demais normas: endpoint por sigla/número/ano
    sigla_api = SIGLAS_API.get(sigla, sigla)
    url = f"{BASE_API}/legislacao/{sigla_api}/{numero}/{ano}.json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            print(f"      [AVISO] Busca: status {resp.status_code} — {url}")
            return None
        dados = resp.json()
        id_norma = _extrair_id_documento(dados)
        if not id_norma:
            print(f"      [AVISO] Norma não encontrada (resposta vazia): {url}")
            return None
        # Validação: o número retornado precisa bater com o pedido
        docs = dados["DetalheDocumento"]["documentos"]["documento"]
        numero_retornado = (docs[0].get("identificacao") or {}).get("numero")
        if numero_retornado and str(numero_retornado) != str(numero):
            print(f"      [AVISO] Número divergente (API: {numero_retornado}) — "
                  f"confira manualmente: {url}")
            return None
        return id_norma
    except Exception as e:
        print(f"      [AVISO] Busca falhou: {e}")
        return None


def detalhar_norma(id_norma):
    """Busca metadados da norma (ementa) no endpoint atual."""
    url = f"{BASE_API}/legislacao/{id_norma}.json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            return {}
        dados = resp.json()
        docs = (dados.get("DetalheDocumento", {}).get("documentos", {}) or {}) \
            .get("documento") or []
        if not docs:
            return {}
        doc = docs[0]
        return {
            "ementa": doc.get("ementa"),
            "normaNome": (doc.get("identificacao") or {}).get("normaNome"),
        }
    except Exception:
        return {}


def dividir_artigos(texto_norma):
    # PATCH — restaura quebras de linha (texto extraído em linha única)
    texto_norma = texto_norma.replace("\r\n", "\n").replace("\r", "\n")
    texto_norma = re.sub(r"\s*(Art\.\s*\d+[ºo°]?(?:-[A-Z])?)", r"\n\1", texto_norma)
    texto_norma = re.sub(r"\s*(§\s*\d+[ºo°]?)", r"\n\1", texto_norma)
    # ... resto da função existente, sem alterações
    linhas = texto_norma.splitlines()
    artigos = []
    rotulo_atual = None
    buffer = []
    for linha in linhas:
        m = re.match(r"^Art\.\s*(\d+[ºo°]?(?:-[A-Z])?)", linha.strip())
        if m:
            if rotulo_atual:
                artigos.append((rotulo_atual, "\n".join(buffer).strip()))
            rotulo_atual = f"Art. {m.group(1)}"
            buffer = [linha.strip()]
        elif rotulo_atual:
            buffer.append(linha.strip())
    if rotulo_atual:
        artigos.append((rotulo_atual, "\n".join(buffer).strip()))
    return artigos


# ------------------------------------------------------------
# Inserção no banco
# ------------------------------------------------------------
def inserir_norma(conn, id_senado, tipo, numero, ano, apelido, area, ementa):
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO normas
            (id_senado, tipo_norma, numero, ano, ementa, apelido,
             area_direito, vade_mecum, situacao, url_fonte)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'VIGENTE', ?)
    """, (id_senado, tipo, numero, ano, ementa, apelido, area,
          f"https://legis.senado.leg.br/norma/{id_senado}"))
    cur.execute("SELECT id FROM normas WHERE id_senado = ?", (id_senado,))
    linha = cur.fetchone()
    return linha[0] if linha else None


def inserir_dispositivos(conn, id_norma, artigos, palavras_chave):
    cur = conn.cursor()
    total = 0
    for rotulo, texto in artigos:
        if len(texto) < 10:
            continue
        cur.execute("""
            INSERT OR IGNORE INTO dispositivos
                (id_norma, tipo_dispositivo, rotulo, texto, situacao)
            VALUES (?, 'ARTIGO', ?, ?, 'VIGENTE')
        """, (id_norma, rotulo, texto))
        if cur.rowcount == 0:
            continue
        id_dispositivo = cur.lastrowid
        total += 1
        for palavra in palavras_chave:
            if palavra.lower() in texto.lower():
                cur.execute(
                    "INSERT OR IGNORE INTO palavras_chave (palavra) VALUES (?)",
                    (palavra,))
                cur.execute(
                    "SELECT id FROM palavras_chave WHERE palavra = ?", (palavra,))
                id_palavra = cur.fetchone()[0]
                cur.execute("""
                    INSERT OR IGNORE INTO dispositivos_palavras_chave
                        (id_dispositivo, id_palavra_chave) VALUES (?, ?)
                """, (id_dispositivo, id_palavra))
    return total


# ------------------------------------------------------------
# Fluxo principal
# ------------------------------------------------------------
def main():
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())

    normas_ok, dispositivos_ok, falhas = 0, 0, []

    for sigla, tipo, numero, ano, apelido, area, id_fixo, pchaves in VADE_MECUM:
        print(f"\n=== {apelido} ({sigla} {numero}/{ano}) ===")

        # 1) Obter o ID na API do Senado
        id_senado = id_fixo or IDS_MANUAIS.get(apelido) or buscar_id_senado(sigla, numero, ano)
        if id_senado is None:
            print("      [FALHA] ID não encontrado. Preencha IDS_MANUAIS no seed.py.")
            falhas.append(apelido)
            continue
        print(f"      ID Senado: {id_senado}")

        # 2) Metadados (ementa etc.) — best-effort
        detalhes = detalhar_norma(id_senado)
        ementa = _procurar_chave(detalhes, ["EmentaNorma", "Ementa", "ementa"])
        if isinstance(ementa, str):
            ementa = ementa.strip()
        else:
            ementa = None

        # 3) Inserir a norma
        id_norma = inserir_norma(conn, id_senado, tipo, numero, ano, apelido, area, ementa)
        if id_norma is None:
            print("      [AVISO] Norma já indexada — pulando.")
            continue

        # 4) Extrair o texto integral (função que você já validou)
        texto = extrair_texto_integral(id_senado, numero=numero, ano=ano)
        if not texto:
            print("      [FALHA] Texto integral não extraído.")
            falhas.append(apelido)
            continue
        print(f"      Texto extraído: {len(texto)} caracteres")

        # 5) Dividir em artigos e inserir
        artigos = dividir_artigos(texto)
        total = inserir_dispositivos(conn, id_norma, artigos, pchaves)
        print(f"      Dispositivos inseridos: {total}")
        normas_ok += 1
        dispositivos_ok += total

        conn.commit()
        time.sleep(1.5)  # pausa para não sobrecarregar o site

    # 6) Resumo
    n_normas = conn.execute("SELECT COUNT(*) FROM normas").fetchone()[0]
    n_disp = conn.execute("SELECT COUNT(*) FROM dispositivos").fetchone()[0]
    print("\n" + "=" * 60)
    print(f"SEED CONCLUÍDO — normas no banco: {n_normas} | dispositivos: {n_disp}")
    print(f"Processadas nesta execução: {normas_ok} | dispositivos: {dispositivos_ok}")
    if falhas:
        print(f"Falhas (preencher IDS_MANUAIS e rodar de novo): {', '.join(falhas)}")
    print("=" * 60)
    conn.close()


if __name__ == "__main__":
    main()
