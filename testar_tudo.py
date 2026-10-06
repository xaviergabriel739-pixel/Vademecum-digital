# testar_tudo.py — Validação ponta a ponta do VadeMecum AI
#
# Uso:
#   python testar_tudo.py             -> testes rápidos (sem custo, sem carregar modelo pesado)
#   python testar_tudo.py --completo  -> também roda busca semântica real, chama a IA
#                                        (custo de tokens na API) e faz um POST completo
#
# Observação: o script VALIDA o sistema; ele não recria o banco. Se o
# vademecum.db não existir, rode primeiro:  python seed.py

import os
import sys
import time
import sqlite3

DB = "vademecum.db"
ARQUIVOS = [
    "schema.sql", "seed.py", "texto_integral.py", "gerar_embeddings.py",
    "busca.py", "ia.py", "app.py", "atualizar.py",
]

OK, FALHA, AVISO = "OK", "FALHA", "AVISO"
resultados = []


def checar(etapa, status, detalhe=""):
    resultados.append((etapa, status, detalhe))
    sufixo = f" — {detalhe}" if detalhe else ""
    print(f"  [{status:5}] {etapa}{sufixo}")


def main():
    completo = "--completo" in sys.argv
    modo = "MODO COMPLETO" if completo else "MODO RÁPIDO (use --completo p/ semântica + IA + POST)"
    print("=" * 70)
    print(f"VADEMECUM AI — TESTE PONTA A PONTA ({modo})")
    print("=" * 70)

    teste_ambiente()
    teste_banco()
    teste_embeddings(completo)
    teste_busca()
    teste_ia(completo)
    teste_web(completo)

    # ---------------------------------------------------------- resumo
    falhas = [r for r in resultados if r[1] == FALHA]
    avisos = [r for r in resultados if r[1] == AVISO]
    ok = len(resultados) - len(falhas) - len(avisos)
    print("\n" + "=" * 70)
    print(f"RESUMO: {ok} OK | {len(avisos)} AVISOS | {len(falhas)} FALHAS")
    if falhas:
        print("\nPróximos passos para as falhas:")
        for etapa, _, detalhe in falhas:
            print(f"  - {etapa}: {detalhe}")
    if avisos:
        print("\nAtenção (não bloqueiam, mas confira):")
        for etapa, _, detalhe in avisos:
            print(f"  - {etapa}: {detalhe}")
    print("=" * 70)
    sys.exit(1 if falhas else 0)


# --------------------------------------------------------------
# 1. AMBIENTE
# --------------------------------------------------------------
def teste_ambiente():
    print("\n[1/6] AMBIENTE")
    if sys.version_info < (3, 8):
        checar("Python 3.8+", FALHA, f"versão {sys.version.split()[0]} detectada")
    else:
        checar("Python", OK, sys.version.split()[0])

    for pacote in ("requests", "flask", "numpy"):
        try:
            __import__(pacote)
            checar(f"pacote {pacote}", OK)
        except ImportError:
            checar(f"pacote {pacote}", FALHA, f"pip install {pacote}")
    try:
        import sentence_transformers  # noqa
        checar("pacote sentence-transformers", OK)
    except ImportError:
        checar("pacote sentence-transformers", AVISO,
               "pip install sentence-transformers (necessário p/ busca semântica)")

    for arquivo in ARQUIVOS:
        checar(f"arquivo {arquivo}", OK if os.path.isfile(arquivo) else FALHA,
               "" if os.path.isfile(arquivo) else "não encontrado na pasta do projeto")
    checar("arquivo static/index.html", OK if os.path.isfile("static/index.html") else AVISO,
           "" if os.path.isfile("static/index.html") else "falta o frontend (frontend-vademecum.md)")


# --------------------------------------------------------------
# 2. BANCO DE DADOS
# --------------------------------------------------------------
def _contagem(conn, sql):
    return conn.execute(sql).fetchone()[0]


def teste_banco():
    print("\n[2/6] BANCO DE DADOS")
    if not os.path.isfile(DB):
        checar("vademecum.db", FALHA, "banco não existe — rode: python seed.py")
        return
    conn = sqlite3.connect(DB)
    normas = _contagem(conn, "SELECT COUNT(*) FROM normas") \
        if _tabela(conn, "normas") else None
    dispositivos = _contagem(conn, "SELECT COUNT(*) FROM dispositivos") \
        if _tabela(conn, "dispositivos") else None

    checar("tabela normas", OK if (normas or 0) > 0 else FALHA,
           f"{normas or 0} normas" if normas is not None else "tabela ausente")
    checar("tabela dispositivos", OK if (dispositivos or 0) > 0 else FALHA,
           f"{dispositivos or 0} dispositivos" if dispositivos is not None else "tabela ausente")
    checar("índice FTS5 (dispositivos_fts)", OK if _tabela(conn, "dispositivos_fts") else FALHA,
           "" if _tabela(conn, "dispositivos_fts") else "SQLite sem FTS5? Atualize o Python")
    checar("tabelas de histórico (conversas)", OK if _tabela(conn, "conversas") else FALHA)
    checar("tabelas de histórico (mensagens)", OK if _tabela(conn, "mensagens") else FALHA)
    conn.close()


def _tabela(conn, nome):
    linha = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (nome,)).fetchone()
    return linha and linha[0] > 0


# --------------------------------------------------------------
# 3. EMBEDDINGS
# --------------------------------------------------------------
def teste_embeddings(completo):
    print("\n[3/6] EMBEDDINGS")
    if not os.path.isfile(DB):
        checar("vademecum.db", FALHA, "rode: python seed.py")
        return
    conn = sqlite3.connect(DB)
    total = _contagem(conn, "SELECT COUNT(*) FROM dispositivos")
    com = _contagem(conn, "SELECT COUNT(*) FROM dispositivos WHERE embedding IS NOT NULL")
    conn.close()
    if com == 0:
        checar("embedding na coluna", AVISO,
               "nenhum vetor ainda — rode: python gerar_embeddings.py")
    else:
        checar("embedding na coluna", OK, f"{com}/{total} dispositivos vetorizados")

    if completo and com > 0:
        print("    Busca semântica real (carrega o modelo...):")
        try:
            import numpy as np
            from sentence_transformers import SentenceTransformer
            modelo = SentenceTransformer("intfloat/multilingual-e5-small")
            q = modelo.encode("query: corrida ilegal de carros", normalize_embeddings=True)
            conn = sqlite3.connect(DB)
            linhas = conn.execute("""
                SELECT d.rotulo, d.texto, n.apelido, d.embedding
                FROM dispositivos d JOIN normas n ON n.id = d.id_norma
                WHERE d.embedding IS NOT NULL
            """).fetchall()
            conn.close()
            topo = max(
                ((float(np.dot(q, np.frombuffer(blob, dtype=np.float32))), rotulo, apelido)
                 for rotulo, _, apelido, blob in linhas),
                key=lambda x: x[0],
            )
            ok = "Art. 308" in topo[1] and "Trânsito" in topo[2]
            checar("semântica: Art. 308 do CTB no topo",
                   OK if ok else AVISO,
                   f"{topo[0]:.4f} | {topo[1]} — {topo[2]}")
        except Exception as e:
            checar("semântica real", FALHA, str(e))


# --------------------------------------------------------------
# 4. BUSCA HÍBRIDA
# --------------------------------------------------------------
def teste_busca():
    print("\n[4/6] BUSCA HÍBRIDA (banco + API do Senado)")
    if not os.path.isfile(DB):
        checar("vademecum.db", FALHA, "rode: python seed.py")
        return
    conn = sqlite3.connect(DB)
    com = _contagem(conn, "SELECT COUNT(*) FROM dispositivos WHERE embedding IS NOT NULL")
    conn.close()
    if com == 0:
        checar("busca híbrida", AVISO,
               "sem embeddings a busca ainda funciona só por FTS — rode gerar_embeddings.py")
        return
    try:
        import busca
        t0 = time.time()
        resultados = busca.montar_resultados("corrida ilegal de carros")
        dt = time.time() - t0
        if not resultados:
            checar("busca retornou resultados", FALHA, "lista vazia")
            return
        topo = resultados[0]
        checar("busca retornou resultados", OK, f"{len(resultados)} dispositivos em {dt:.1f}s")
        certo = "Art. 308" in topo["rotulo"] and "CTB" in topo["norma"]
        checar("Art. 308 do CTB no topo", OK if certo else AVISO,
               f"{topo['rotulo']} — {topo['norma']} (sim {topo['similaridade']})")
        checar("texto atual confirmado na API", OK if topo.get("texto_api") else AVISO,
               "" if topo.get("texto_api") else "texto_api nulo — conferir texto_integral.py")
    except Exception as e:
        checar("busca híbrida", FALHA, str(e))


# --------------------------------------------------------------
# 5. CAMADA DE IA
# --------------------------------------------------------------
def teste_ia(completo):
    print("\n[5/6] CAMADA DE IA")
    try:
        import ia
    except Exception as e:
        checar("import ia", FALHA, str(e))
        return

    if hasattr(ia, "_api_key") and callable(ia._api_key):
        chave = ia._api_key()
        if chave:
            checar("configuração (API)", OK, f"modelo {getattr(ia, 'MODELO', '?')}")
        else:
            checar("configuração (API)", FALHA,
                   "setx IA_API_KEY \"sua-chave\" (PowerShell) e reabra o terminal")
            return
    elif hasattr(ia, "verificar_saude"):
        try:
            ok, modelos = ia.verificar_saude()
            checar("configuração (Ollama)", OK if ok else FALHA,
                   ", ".join(modelos) if modelos else "nenhum modelo — ollama pull qwen2.5:3b")
            if not ok:
                return
        except Exception as e:
            checar("configuração (Ollama)", FALHA, str(e))
            return
    else:
        checar("configuração da IA", AVISO, "provedor não identificado no ia.py")
        return

    if completo:
        try:
            t0 = time.time()
            resposta = ia.responder("Responda apenas: OK", [])
            dt = time.time() - t0
            checar("chamada real à IA", OK if "ERRO" not in resposta else FALHA,
                   f"{dt:.1f}s")
            if "ERRO" not in resposta:
                print("    Resposta do modelo: " + resposta[:150])
        except Exception as e:
            checar("chamada real à IA", FALHA, str(e))


# --------------------------------------------------------------
# 6. BACKEND E CHAT (cliente de teste do Flask)
# --------------------------------------------------------------
def teste_web(completo):
    print("\n[6/6] BACKEND E CHAT (Flask test client)")
    try:
        import app
    except Exception as e:
        checar("import app", FALHA, str(e))
        return

    with app.app.test_client() as c:
        r = c.get("/")
        checar("GET / (página do chat)", OK if r.status_code == 200 else FALHA,
               f"status {r.status_code}")
        try:
            r = c.get("/api/conversas")
            dados = r.get_json() or []
            checar("GET /api/conversas", OK if r.status_code == 200 else FALHA,
                   f"{len(dados)} conversas salvas")
        except Exception as e:
            checar("GET /api/conversas", FALHA, str(e))

        if completo:
            print("    POST /api/perguntar (busca + API do Senado + IA — pode demorar):")
            r = c.post("/api/perguntar",
                       json={"pergunta": "qual lei fala sobre corrida ilegal de carros?"})
            if r.status_code == 200:
                dados = r.get_json()
                checar("POST /api/perguntar", OK,
                       f"resposta gerada, {dados.get('dispositivos_encontrados')} dispositivos")
                print("    Início da resposta: " + (dados.get("resposta") or "")[:150])
            else:
                corpo = r.get_json() or {}
                checar("POST /api/perguntar", FALHA,
                       f"status {r.status_code} — {corpo.get('erro', corpo)}")


if __name__ == "__main__":
    main()