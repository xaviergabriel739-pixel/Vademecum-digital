# gerar_embeddings.py — Preenche dispositivos.embedding com vetores de 384 dimensões
# Modelo: intfloat/multilingual-e5-small (prefixos "passage:" / "query:" obrigatórios)
#
# Requisitos: pip install sentence-transformers
# Uso:
#   python gerar_embeddings.py                          -> gera os embeddings pendentes
#   python gerar_embeddings.py --testar "sua pergunta"  -> testa a busca semântica

import sys
import sqlite3
import numpy as np
from sentence_transformers import SentenceTransformer

DB = "vademecum.db"
MODELO = "intfloat/multilingual-e5-small"
LOTE = 32


def carregar_modelo():
    print(f"Carregando modelo {MODELO}...")
    print("(a primeira execução baixa ~470 MB e pode demorar alguns minutos)")
    modelo = SentenceTransformer(MODELO)
    print("Modelo carregado.\n")
    return modelo


def gerar():
    modelo = carregar_modelo()
    conn = sqlite3.connect(DB)

    pendentes = conn.execute("""
        SELECT d.id, d.texto
        FROM dispositivos d
        WHERE d.embedding IS NULL
        ORDER BY d.id
    """).fetchall()

    total = len(pendentes)
    if total == 0:
        print("Nenhum dispositivo pendente — todos já têm embedding.")
        conn.close()
        return

    print(f"Dispositivos pendentes: {total}\n")

    processados = 0
    for inicio in range(0, total, LOTE):
        lote = pendentes[inicio:inicio + LOTE]
        # Prefixo "passage:" é OBRIGATÓRIO nos textos indexados do modelo E5
        textos = [f"passage: {texto}" for _, texto in lote]
        vetores = modelo.encode(
            textos,
            normalize_embeddings=True,   # vetor unitário: similaridade = produto escalar
            show_progress_bar=False,
        )
        for (id_disp, _), vetor in zip(lote, vetores):
            conn.execute(
                "UPDATE dispositivos SET embedding = ? WHERE id = ?",
                (np.asarray(vetor, dtype=np.float32).tobytes(), id_disp),
            )
        conn.commit()
        processados += len(lote)
        print(f"  [{processados}/{total}] vetorizados")

    com = conn.execute("SELECT COUNT(*) FROM dispositivos WHERE embedding IS NOT NULL").fetchone()[0]
    sem = conn.execute("SELECT COUNT(*) FROM dispositivos WHERE embedding IS NULL").fetchone()[0]
    print("\n" + "=" * 60)
    print(f"CONCLUÍDO — com embedding: {com} | pendentes: {sem}")
    print("=" * 60)
    conn.close()


def testar(pergunta):
    modelo = carregar_modelo()
    conn = sqlite3.connect(DB)

    # Vetor da pergunta — prefixo "query:" é OBRIGATÓRIO no modelo E5
    vetor_pergunta = modelo.encode(
        f"query: {pergunta}", normalize_embeddings=True
    )

    linhas = conn.execute("""
        SELECT d.rotulo, d.texto, n.apelido, n.tipo_norma, n.numero, n.ano, d.embedding
        FROM dispositivos d
        JOIN normas n ON n.id = d.id_norma
        WHERE d.embedding IS NOT NULL
    """).fetchall()

    if not linhas:
        print("Nenhum dispositivo com embedding no banco. Rode primeiro: python gerar_embeddings.py")
        conn.close()
        return

    resultados = []
    for rotulo, texto, apelido, tipo, numero, ano, blob in linhas:
        vetor = np.frombuffer(blob, dtype=np.float32)
        # Vetores normalizados: produto escalar = similaridade de cosseno
        similaridade = float(np.dot(vetor_pergunta, vetor))
        resultados.append((similaridade, rotulo, apelido, tipo, numero, ano, texto))

    resultados.sort(reverse=True)

    print(f"\nBusca semântica por: '{pergunta}'")
    print(f"Dispositivos comparados: {len(resultados)}\n")
    print("=" * 70)
    for sim, rotulo, apelido, tipo, numero, ano, texto in resultados[:5]:
        print(f"\n{sim:.4f} | {rotulo} — {apelido} ({tipo} {numero}/{ano})")
        print("  " + texto[:200].replace("\n", " ") + ("..." if len(texto) > 200 else ""))
    print("=" * 70)
    conn.close()


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--testar":
        testar(" ".join(sys.argv[2:]))
    else:
        gerar()
