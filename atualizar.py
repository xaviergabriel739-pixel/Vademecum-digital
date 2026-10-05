# atualizar.py — Rotina de atualização do VadeMecum AI (sob demanda)
#
# O banco é a fonte de DESCOBERTA e pode ficar desatualizado; este script
# o ressincroniza com a API do Senado quando o programador quiser.
#
# Etapas:
#   1. NOVAS NORMAS — indexa normas da lista do Vade Mecum ausentes no banco
#   2. TEXTOS — reextrai o texto integral de cada norma indexada e atualiza:
#        texto mudou  -> dispositivo marcado ALTERADO (embedding zerado)
#        artigo novo  -> dispositivo marcado INCLUIDO
#        artigo ausente no texto novo -> apenas REPORTADO (conferência
#        manual; não marca REVOGADO automaticamente, para evitar falso
#        positivo por falha de parsing)
#   3. EMBEDDINGS — gera vetores para dispositivos novos/alterados
#
# Uso:
#   python atualizar.py                 -> atualização completa (1 + 2 + 3)
#   python atualizar.py --normas        -> apenas etapa 1
#   python atualizar.py --textos        -> apenas etapa 2
#   python atualizar.py --embeddings    -> apenas etapa 3
#
# Requisitos: vademecum.db já criado (rode seed.py uma vez); requests;
# sentence-transformers (apenas etapa 3); seed.py e texto_integral.py
# na mesma pasta.

import argparse
import sqlite3
import sys
import time

import seed
from texto_integral import extrair_texto_integral

DB = "vademecum.db"
HOJE = time.strftime("%Y-%m-%d")


# ------------------------------------------------------------
# ETAPA 1 — NOVAS NORMAS (lista do Vade Mecum)
# ------------------------------------------------------------
def novas_normas(conn):
    print("\n[1/3] Verificando novas normas do Vade Mecum...")
    novas, falhas = 0, []

    for sigla, tipo, numero, ano, apelido, area, id_fixo, pchaves in seed.VADE_MECUM:
        id_senado = (id_fixo or seed.IDS_MANUAIS.get(apelido)
                     or seed.buscar_id_senado(sigla, numero, ano))
        if id_senado is None:
            print(f"  [FALHA] {apelido}: ID não encontrado (use seed.IDS_MANUAIS).")
            falhas.append(apelido)
            continue

        ja_indexada = conn.execute(
            "SELECT 1 FROM normas WHERE id_senado = ?", (id_senado,)).fetchone()
        if ja_indexada:
            continue  # já no banco — a etapa 2 cuida do texto dela

        print(f"  + Indexando {apelido} (ID {id_senado})...")
        detalhes = seed.detalhar_norma(id_senado)
        ementa = seed._procurar_chave(detalhes, ["EmentaNorma", "Ementa", "ementa"])
        if not isinstance(ementa, str):
            ementa = None

        id_norma = seed.inserir_norma(conn, id_senado, tipo, numero, ano,
                                      apelido, area, ementa)
        texto = extrair_texto_integral(id_senado, numero=numero, ano=ano)
        if not texto or id_norma is None:
            print(f"  [FALHA] {apelido}: texto não extraído.")
            falhas.append(apelido)
            continue

        artigos = seed.dividir_artigos(texto)
        total = seed.inserir_dispositivos(conn, id_norma, artigos, pchaves)
        print(f"    {total} dispositivos indexados.")
        novas += 1
        conn.commit()
        time.sleep(1.5)

    print(f"  Normas novas: {novas}")
    if falhas:
        print(f"  Falhas: {', '.join(falhas)}")


# ------------------------------------------------------------
# ETAPA 2 — RESSINCRONIZAÇÃO DOS TEXTOS
# ------------------------------------------------------------
def _palavras_da_norma(apelido):
    for _, _, _, _, apelido_item, _, _, pchaves in seed.VADE_MECUM:
        if apelido_item == apelido:
            return pchaves
    return []


def _vincular_palavras_chave(conn, id_dispositivo, texto, apelido):
    for palavra in _palavras_da_norma(apelido):
        if palavra.lower() in texto.lower():
            conn.execute(
                "INSERT OR IGNORE INTO palavras_chave (palavra) VALUES (?)",
                (palavra,))
            id_palavra = conn.execute(
                "SELECT id FROM palavras_chave WHERE palavra = ?",
                (palavra,)).fetchone()[0]
            conn.execute("""
                INSERT OR IGNORE INTO dispositivos_palavras_chave
                    (id_dispositivo, id_palavra_chave) VALUES (?, ?)
            """, (id_dispositivo, id_palavra))


def atualizar_textos(conn):
    print("\n[2/3] Ressincronizando textos com a API do Senado...")
    normas = conn.execute("""
        SELECT id, id_senado, numero, ano, apelido FROM normas ORDER BY id
    """).fetchall()

    alterados = incluidos = 0
    conferir, falhas = [], []

    for id_norma, id_senado, numero, ano, apelido in normas:
        try:
            texto = extrair_texto_integral(id_senado, numero=numero, ano=ano)
        except Exception:
            texto = None
        if not texto:
            print(f"  [AVISO] {apelido}: texto não obtido — não atualizada.")
            falhas.append(apelido)
            continue

        texto_novo = {rot: t for rot, t in seed.dividir_artigos(texto)
                      if len(t) >= 10}

        rotulos_atuais = {r for (r,) in conn.execute(
            "SELECT rotulo FROM dispositivos WHERE id_norma = ?",
            (id_norma,)).fetchall()}
        vivos = conn.execute("""
            SELECT id, rotulo, texto FROM dispositivos
            WHERE id_norma = ? AND situacao != 'REVOGADO'
        """, (id_norma,)).fetchall()

        mudancas = 0
        for id_disp, rotulo, texto_atual in vivos:
            if rotulo not in texto_novo:
                conferir.append(f"{apelido} — {rotulo}")
                continue
            if texto_novo[rotulo].strip() != texto_atual.strip():
                conn.execute("""
                    UPDATE dispositivos
                    SET texto = ?, situacao = 'ALTERADO',
                        data_alteracao = ?, embedding = NULL
                    WHERE id = ?
                """, (texto_novo[rotulo], HOJE, id_disp))
                alterados += 1
                mudancas += 1

        for rotulo, t in texto_novo.items():
            if rotulo in rotulos_atuais:
                continue
            conn.execute("""
                INSERT OR IGNORE INTO dispositivos
                    (id_norma, tipo_dispositivo, rotulo, texto,
                     situacao, data_alteracao)
                VALUES (?, 'ARTIGO', ?, ?, 'INCLUIDO', ?)
            """, (id_norma, rotulo, t, HOJE))
            linha = conn.execute("""
                SELECT id FROM dispositivos WHERE id_norma = ? AND rotulo = ?
            """, (id_norma, rotulo)).fetchone()
            if linha:
                _vincular_palavras_chave(conn, linha[0], t, apelido)
                incluidos += 1
                mudancas += 1

        if mudancas:
            conn.execute("""
                UPDATE normas SET data_indexacao = ?, situacao = 'ALTERADA'
                WHERE id = ? AND situacao != 'REVOGADA'
            """, (HOJE, id_norma))
        else:
            conn.execute(
                "UPDATE normas SET data_indexacao = ? WHERE id = ?",
                (HOJE, id_norma))
        conn.commit()
        time.sleep(1.5)

    print(f"  Dispositivos alterados: {alterados} | incluídos: {incluidos}")
    if conferir:
        print(f"  Conferir manualmente ({len(conferir)}) — ausentes no texto "
              "atual, possivelmente revogados:")
        for item in conferir[:15]:
            print(f"    - {item}")
        if len(conferir) > 15:
            print(f"    ... e mais {len(conferir) - 15}")
    if falhas:
        print(f"  Normas não atualizadas: {', '.join(falhas)}")


# ------------------------------------------------------------
# ETAPA 3 — EMBEDDINGS PENDENTES
# ------------------------------------------------------------
def gerar_embeddings_pendentes():
    print("\n[3/3] Gerando embeddings pendentes...")
    try:
        import gerar_embeddings
    except ImportError:
        print("  [AVISO] sentence-transformers não instalado — etapa pulada.")
        return
    gerar_embeddings.gerar()


# ------------------------------------------------------------
# FLUXO PRINCIPAL
# ------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Atualização do VadeMecum AI")
    parser.add_argument("--normas", action="store_true",
                        help="apenas indexar novas normas")
    parser.add_argument("--textos", action="store_true",
                        help="apenas ressincronizar textos")
    parser.add_argument("--embeddings", action="store_true",
                        help="apenas gerar embeddings pendentes")
    args = parser.parse_args()
    tudo = not (args.normas or args.textos or args.embeddings)

    conn = sqlite3.connect(DB)
    tem_banco = conn.execute("""
        SELECT COUNT(*) FROM sqlite_master
        WHERE type = 'table' AND name = 'normas'
    """).fetchone()[0]
    if not tem_banco:
        print(f"[ERRO] Banco {DB} vazio ou inexistente. Rode primeiro: python seed.py")
        conn.close()
        sys.exit(1)

    print("=" * 60)
    print(f"VADEMECUM AI — ATUALIZAÇÃO ({HOJE})")
    print("=" * 60)

    if tudo or args.normas:
        novas_normas(conn)
    if tudo or args.textos:
        atualizar_textos(conn)
    conn.close()
    if tudo or args.embeddings:
        gerar_embeddings_pendentes()

    print("\nAtualização concluída.")


if __name__ == "__main__":
    main()
