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
IDS_MANUAIS = {
    "Código Penal": 527942,
}

# ------------------------------------------------------------
# Núcleo do Vade Mecum
# (sigla, tipo_norma, numero, ano, apelido, area_direito, id_senado, palavras_chave)
# id_senado = None -> o script busca na API (ou usa IDS_MANUAIS)
# ------------------------------------------------------------
VADE_MECUM = [
    ("CF", "CONSTITUICAO", "1988", 1988, "Constituição Federal", "CONSTITUCIONAL", None,
     ["direitos fundamentais", "igualdade"]),
    ("LEI", "LEI", "10406", 2002, "Código Civil", "CIVIL", None,
     ["obrigações", "contratos"]),
    ("LEI", "LEI", "8078", 1990, "Código de Defesa do Consumidor", "CONSUMIDOR", None,
     ["consumidor", "publicidade"]),
    ("LEI", "LEI", "13146", 2015, "Estatuto da Pessoa com Deficiência", "CIVIL", None,
     ["deficiência", "capacidade civil"]),
    ("DL", "DECRETO-LEI", "2848", 1940, "Código Penal", "PENAL", 527942,
     ["homicídio", "crime", "pena"]),
    ("DL", "DECRETO-LEI", "1002", 1969, "Código Penal Militar", "PENAL", None,
     ["crime militar"]),
    ("LEI", "LEI", "7210", 1984, "Lei de Execução Penal", "PENAL", None,
     ["execução penal", "preso"]),
    ("LEI", "LEI", "8072", 1990, "Lei de Crimes Hediondos", "PENAL", None,
     ["hediondez"]),
    ("LEI", "LEI", "9455", 1997, "Lei de Tortura", "PENAL", None,
     ["tortura"]),
    ("LEI", "LEI", "9605", 1998, "Lei de Crimes Ambientais", "AMBIENTAL", None,
     ["meio ambiente", "crime ambiental"]),
    ("LEI", "LEI", "11343", 2006, "Lei de Drogas", "PENAL", None,
     ["drogas", "entorpecentes"]),
    ("LEI", "LEI", "11340", 2006, "Lei Maria da Penha", "PENAL", None,
     ["violência doméstica", "mulher"]),
    ("LEI", "LEI", "8069", 1990, "Estatuto da Criança e do Adolescente", "PENAL", None,
     ["criança", "adolescente"]),
    ("LEI", "LEI", "10741", 2003, "Estatuto do Idoso", "PENAL", None,
     ["idoso"]),
    ("LEI", "LEI", "10826", 2003, "Estatuto do Desarmamento", "PENAL", None,
     ["arma de fogo"]),
    ("DL", "DECRETO-LEI", "3689", 1941, "Código de Processo Penal", "PROCESSUAL PENAL", None,
     ["processo penal", "prisão"]),
    ("LEI", "LEI", "9099", 1995, "Lei dos Juizados Especiais", "PROCESSUAL PENAL", None,
     ["juizado especial", "infração de menor potencial"]),
    ("LEI", "LEI", "13105", 2015, "Código de Processo Civil", "PROCESSUAL CIVIL", None,
     ["processo civil", "jurisdição"]),
    ("DL", "DECRETO-LEI", "5452", 1943, "Consolidação das Leis do Trabalho", "TRABALHISTA", None,
     ["trabalho", "empregado"]),
    ("LEI", "LEI", "5172", 1966, "Código Tributário Nacional", "TRIBUTARIO", None,
     ["tributo", "imposto"]),
    ("LEI", "LEI", "9503", 1997, "Código de Trânsito Brasileiro", "TRANSITO", None,
     ["trânsito", "racha", "corrida ilegal"]),
    ("LEI", "LEI", "8112", 1990, "Regime Jurídico dos Servidores Federais", "ADMINISTRATIVO", None,
     ["servidor público"]),
    ("LEI", "LEI", "8429", 1992, "Lei de Improbidade Administrativa", "ADMINISTRATIVO", None,
     ["improbidade"]),
    ("LEI", "LEI", "9784", 1999, "Lei de Processo Administrativo Federal", "ADMINISTRATIVO", None,
     ["processo administrativo"]),
    ("LEI", "LEI", "12527", 2011, "Lei de Acesso à Informação", "ADMINISTRATIVO", None,
     ["informação", "transparência"]),
    ("LEI", "LEI", "14133", 2021, "Lei de Licitações e Contratos", "ADMINISTRATIVO", None,
     ["licitação", "contrato administrativo"]),
    ("LEI", "LEI", "4737", 1965, "Código Eleitoral", "ELEITORAL", None,
     ["eleição", "voto"]),
    ("LEI", "LEI", "6404", 1976, "Lei de Sociedades por Ações", "EMPRESARIAL", None,
     ["sociedade anônima", "acionista"]),
    ("LEI", "LEI", "11101", 2005, "Lei de Falências e Recuperação Judicial", "EMPRESARIAL", None,
     ["falência", "recuperação judicial"]),
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


def buscar_id_senado(sigla, numero, ano):
    """Busca o ID da norma na API do Senado. Retorna int ou None."""
    url = f"{BASE_API}/lista/textos"
    params = {"sigla": sigla, "numero": numero, "ano": ano, "formato": "json"}
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            print(f"      [AVISO] Busca: status {resp.status_code}")
            return None
        dados = resp.json()
        id_norma = _procurar_chave(dados, ["ID", "Id", "id"])
        if id_norma is not None:
            try:
                return int(str(id_norma).strip())
            except ValueError:
                return None
        print(f"      [AVISO] Busca: nenhum ID na resposta. Confira no navegador: {resp.url}")
        return None
    except Exception as e:
        print(f"      [AVISO] Busca falhou: {e}")
        return None


def detalhar_norma(id_norma):
    """Busca metadados da norma (ementa, numero, ano). Retorna dict."""
    url = f"{BASE_API}/norma/{id_norma}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            return {}
        return resp.json()
    except Exception:
        return {}


def dividir_artigos(texto_norma):
    """Divide o texto da lei em artigos. Retorna lista de (rotulo, texto)."""
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
