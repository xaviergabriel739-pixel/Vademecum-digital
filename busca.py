# busca.py — Busca híbrida (semântica + FTS5) do VadeMecum AI
#
# ÚNICO ponto de contato entre o backend e o banco de dados.
# Produz a lista de resultados que o ia.py recebe.
#
# Pipeline de cada consulta:
#   1. Busca SEMÂNTICA: similaridade entre a pergunta e os embeddings
#   2. Busca por TEXTO: FTS5 (palavras-chave da pergunta)
#   3. Combinação ponderada (70% semântica + 30% texto) + reforço do Vade Mecum
#   4. Para os melhores: busca o TEXTO ATUAL na API do Senado (texto_api)
#
# Requisitos:
#   - pip install sentence-transformers numpy
#   - vademecum.db com dispositivos e embeddings (seed.py + gerar_embeddings.py)
#   - texto_integral.py na mesma pasta (reutilizado para o texto da API)
#
# Teste isolado:  python busca.py "corrida ilegal de carros"

import re
import sqlite3

import numpy as np
from sentence_transformers import SentenceTransformer

try:
    from texto_integral import extrair_texto_integral
except ImportError:
    extrair_texto_integral = None

DB = "vademecum.db"
MODELO = "intfloat/multilingual-e5-small"

PESO_SEMANTICA = 0.7
PESO_FTS = 0.3
REFORCO_VADE = 0.05      # pequeno bônus para normas do núcleo do Vade Mecum

LIMITE_SEMANTICA = 15    # candidatos da busca semântica
LIMITE_FTS = 15          # candidatos da busca por texto
LIMITE_FINAL = 10        # candidatos após a combinação
TOP_N = 5                # dispositivos entregues à IA

STOPWORDS = {
    "qual", "quais", "que", "sobre", "fala", "como", "para", "com", "dos",
    "das", "uma", "por", "não", "nao", "de", "do", "da", "em", "no", "na",
    "os", "as", "um", "me", "mostre", "mostra", "é", "e", "o", "a", "the",
}

_modelo = None


def _carregar_modelo():
    global _modelo
    if _modelo is None:
        print("[busca] Carregando modelo de embeddings (só na primeira busca)...")
        _modelo = SentenceTransformer(MODELO)
    return _modelo


# ------------------------------------------------------------
# BUSCA SEMÂNTICA (embeddings)
# ------------------------------------------------------------
def _busca_semantica(conn, modelo, pergunta, limite):
    tem_embedding = conn.execute(
        "SELECT EXISTS(SELECT 1 FROM dispositivos WHERE embedding IS NOT NULL)"
    ).fetchone()[0]
    if not tem_embedding:
        return []

    # Prefixo "query:" é OBRIGATÓRIO no modelo E5
    vetor_pergunta = modelo.encode(f"query: {pergunta}", normalize_embeddings=True)

    linhas = conn.execute("""
        SELECT d.id, d.embedding
        FROM dispositivos d
        WHERE d.embedding IS NOT NULL
    """).fetchall()

    resultados = []
    for id_disp, blob in linhas:
        vetor = np.frombuffer(blob, dtype=np.float32)
        resultados.append((id_disp, float(np.dot(vetor_pergunta, vetor))))

    resultados.sort(key=lambda x: x[1], reverse=True)
    return resultados[:limite]


# ------------------------------------------------------------
# BUSCA POR TEXTO (FTS5)
# ------------------------------------------------------------
def _montar_query_fts(pergunta):
    termos = [t for t in re.findall(r"\w+", pergunta, flags=re.UNICODE)
              if len(t) > 2 and t.lower() not in STOPWORDS]
    if not termos:
        return None
    return " OR ".join(f'"{t}"' for t in termos)


def _busca_fts(conn, pergunta, limite):
    query = _montar_query_fts(pergunta)
    if not query:
        return []
    try:
        linhas = conn.execute("""
            SELECT rowid, rank
            FROM dispositivos_fts
            WHERE dispositivos_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limite)).fetchall()
    except sqlite3.OperationalError:
        return []
    if not linhas:
        return []

    # rank: menor = melhor. Normaliza para 0-1 (melhor = 1.0)
    melhor = min(abs(r) for _, r in linhas)
    resultados = []
    for rowid, rank in linhas:
        score = 1.0 if melhor <= 0 else min(1.0, melhor / max(abs(rank), 1e-9))
        resultados.append((rowid, score))
    return resultados


# ------------------------------------------------------------
# BUSCA HÍBRIDA COMBINADA
# ------------------------------------------------------------
def buscar(pergunta, limite_final=LIMITE_FINAL):
    """Busca híbrida no banco. Retorna dicts com metadados, ordenados
    pela pontuação combinada (semântica 70% + texto 30%)."""
    conn = sqlite3.connect(DB)
    try:
        modelo = _carregar_modelo()
        sem = dict(_busca_semantica(conn, modelo, pergunta, LIMITE_SEMANTICA))
        fts = dict(_busca_fts(conn, pergunta, LIMITE_FTS))

        candidatos = set(sem) | set(fts)
        if not candidatos:
            return []

        pontuados = []
        for id_disp in candidatos:
            score = (PESO_SEMANTICA * sem.get(id_disp, 0.0)
                     + PESO_FTS * fts.get(id_disp, 0.0))
            pontuados.append((id_disp, score))
        pontuados.sort(key=lambda x: x[1], reverse=True)

        resultados = []
        for id_disp, score in pontuados[:limite_final]:
            linha = conn.execute("""
                SELECT d.rotulo, d.texto,
                       n.tipo_norma, n.numero, n.ano, n.apelido,
                       n.area_direito, n.vade_mecum, n.id_senado
                FROM dispositivos d
                JOIN normas n ON n.id = d.id_norma
                WHERE d.id = ?
            """, (id_disp,)).fetchone()
            if not linha:
                continue
            rotulo, texto, tipo, numero, ano, apelido, area, vade, id_senado = linha
            if vade:
                score += REFORCO_VADE
            resultados.append({
                "rotulo": rotulo,
                "norma": _formatar_norma(tipo, numero, ano, apelido),
                "area": area,
                "vade_mecum": vade,
                "similaridade": round(score, 4),
                "texto_indexado": texto,
                "id_senado": id_senado,
                "numero": numero,
                "ano": ano,
            })

        resultados.sort(key=lambda r: r["similaridade"], reverse=True)
        return resultados
    finally:
        conn.close()


# ------------------------------------------------------------
# TEXTO ATUAL NA API DO SENADO
# ------------------------------------------------------------
def _formatar_norma(tipo, numero, ano, apelido):
    nomes = {
        "LEI": f"Lei nº {numero}/{ano}",
        "DECRETO-LEI": f"Decreto-Lei nº {numero}/{ano}",
        "DECRETO": f"Decreto nº {numero}/{ano}",
        "MEDIDA PROVISORIA": f"Medida Provisória nº {numero}/{ano}",
        "CONSTITUICAO": f"Constituição da República de {ano}",
    }
    base = nomes.get(tipo, f"{tipo} nº {numero}/{ano}")
    return f"{base} ({apelido})" if apelido else base


def _extrair_artigo(texto_norma, rotulo):
    """Localiza o texto atual de um artigo dentro do texto integral da norma."""
    num = rotulo.replace("Art.", "").replace("Art", "").strip()
    m = re.search(rf"(?m)^Art\.\s*{re.escape(num)}(?![0-9\-])", texto_norma)
    if not m:
        return None
    inicio = m.start()
    m_prox = re.search(r"(?m)^Art\.\s", texto_norma[inicio + 1:])
    fim = inicio + 1 + m_prox.start() if m_prox else len(texto_norma)
    return texto_norma[inicio:fim].strip()


def montar_resultados(pergunta, top_n=TOP_N):
    """Pipeline completo: busca híbrida + texto atual da API.

    Retorna lista de dicts no formato que o ia.py espera:
    rotulo, norma, area, vade_mecum, similaridade, texto_indexado,
    texto_api (str | None), id_senado, numero, ano
    """
    candidatos = buscar(pergunta, limite_final=LIMITE_FINAL)

    cache_textos = {}  # id_senado -> texto integral (evita refetch da mesma norma)
    finais = []
    for cand in candidatos[:top_n]:
        texto_api = None
        if extrair_texto_integral is not None and cand["id_senado"]:
            chave = cand["id_senado"]
            if chave not in cache_textos:
                try:
                    cache_textos[chave] = extrair_texto_integral(
                        chave, numero=cand["numero"], ano=cand["ano"])
                except Exception:
                    cache_textos[chave] = None
            texto_norma = cache_textos[chave]
            if texto_norma:
                texto_api = _extrair_artigo(texto_norma, cand["rotulo"])
        finais.append({**cand, "texto_api": texto_api})
    return finais


# ------------------------------------------------------------
# TESTE ISOLADO
# ------------------------------------------------------------
if __name__ == "__main__":
    import sys
    pergunta = " ".join(sys.argv[1:]).strip() or "corrida ilegal de carros"
    print(f"\nPergunta: {pergunta}\n" + "=" * 70)
    resultados = montar_resultados(pergunta)
    if not resultados:
        print("Nenhum dispositivo encontrado.")
    for r in resultados:
        status = ("texto atual obtido da API" if r["texto_api"]
                  else "texto NÃO confirmado na API")
        print(f"\n{r['similaridade']:.4f} | {r['rotulo']} — {r['norma']}"
              f" | vade={r['vade_mecum']} | {status}")
        print("  " + r["texto_indexado"][:180].replace("\n", " ") + "...")
    print("=" * 70)
