# corrigir_ids.py — Corrige id_senado inválidos (negativos) no banco
#
# Causa do problema: o buscar_id_senado antigo usava o endpoint
# /senado/dados/lista/textos (descontinuado pelo Senado em fev/2026) e
# gravava o primeiro campo "id" genérico do JSON — inclusive valores
# internos negativos (-1001, -1003...). IDs negativos geram URLs
# inválidas (/norma/-1003) e a extração do texto oficial falha.
#
# O que faz:
#   1. Lista as normas com id_senado <= 0 (ou nulo)
#   2. Re-busca o ID correto no endpoint ATUAL (/dadosabertos/legislacao)
#      — usa o buscar_id_senado do seed.py, que já tem o patch
#   3. IDS_MANUAIS do seed.py tem prioridade (nunca erra)
#   4. Casos especiais:
#        - ADCT: busca pela URN própria (não pela URN da Constituição)
#        - LRF (LEI 101/2000) e Emprego Doméstico (LEI 150/2015): na
#          verdade são Leis COMPLEMENTARES — tenta LCP se LEI falhar
#   5. Após corrigir, exibe o nome oficial da norma (da API) para
#      conferência visual
#   6. Bônus: preenche a ementa, se estiver vazia no banco
#
# PRÉ-REQUISITO: seed.py com o patch do endpoint atual (SIGLAS_API,
# URNS_ESPECIAIS, _extrair_id_documento, buscar_id_senado, detalhar_norma).
# Se rodar com o seed antigo, as buscas voltam a dar 404.
#
# Uso: python corrigir_ids.py

import sqlite3
import time

import seed

DB = "vademecum.db"

# tipo_norma do banco -> sigla que o buscar_id_senado do seed.py entende
# (o seed traduz por dentro: DL->DEL, CF->CON-v via URN, MP->MPV etc.)
SIGLAS_BANCO = {
    "LEI": "LEI",
    "DECRETO-LEI": "DL",
    "DECRETO": "DEC",
    "CONSTITUICAO": "CF",
    "MEDIDA PROVISORIA": "MP",
}

# Normas catalogadas como LEI no banco, mas que são Leis Complementares:
# tentar a sigla LCP quando a busca como LEI falhar
TENTATIVA_LCP = {
    "Lei de Responsabilidade Fiscal",   # LC 101/2000
    "Lei do Emprego Doméstico",         # LC 150/2015
}


def _sigla_para_busca(tipo, apelido):
    """Define a sigla da busca, com exceção para o ADCT.
    Sem isso, o ADCT (tipo CONSTITUICAO) seria buscado pela URN da
    Constituição e receberia o ID errado."""
    if "Constitucionais Transit" in apelido:  # cobre Transitórias/Transitorias
        return "ADCT"
    return SIGLAS_BANCO.get(tipo, tipo)


def _nome_da_norma(id_senado):
    """Busca o nome oficial na API para conferência visual.
    Tolerante: se o detalhar_norma ainda for o antigo, retorna (None, None)."""
    try:
        detalhes = seed.detalhar_norma(id_senado)
    except Exception:
        return None, None
    if not isinstance(detalhes, dict):
        return None, None
    return detalhes.get("normaNome"), detalhes.get("ementa")


def main():
    conn = sqlite3.connect(DB)
    normas = conn.execute("""
        SELECT id, tipo_norma, numero, ano, apelido, id_senado
        FROM normas
        WHERE id_senado IS NULL OR id_senado <= 0
        ORDER BY id
    """).fetchall()

    if not normas:
        print("Nenhum id_senado inválido no banco — nada a corrigir.")
        conn.close()
        return

    print("=" * 70)
    print(f"CORREÇÃO DE IDs — {len(normas)} norma(s) com ID inválido")
    print("Endpoint em uso: /dadosabertos/legislacao (atual)")
    print("=" * 70)

    corrigidas, falhas = 0, []

    for id_norma, tipo, numero, ano, apelido, id_errado in normas:
        print(f"\n{apelido} ({tipo} {numero}/{ano}) — ID atual: {id_errado}")

        # 1) Tentativa principal: IDS_MANUAIS > busca pela sigla do tipo
        sigla = _sigla_para_busca(tipo, apelido)
        id_novo = (seed.IDS_MANUAIS.get(apelido)
                   or seed.buscar_id_senado(sigla, numero, ano))

        # 2) Tentativa alternativa como Lei Complementar (LCP)
        if not id_novo and apelido in TENTATIVA_LCP:
            print("  [TENTATIVA] Buscando como Lei Complementar (LCP)...")
            id_novo = seed.buscar_id_senado("LCP", numero, ano)

        if not id_novo or id_novo <= 0:
            print("  [FALHA] ID correto não encontrado.")
            print("         Opções: (a) preencher IDS_MANUAIS no seed.py;")
            print("                 (b) pegar o ID na URL da norma no site:")
            print("                     legis.senado.leg.br/norma/XXXXX")
            falhas.append(apelido)
            continue

        # 3) Colisão: o ID já pertence a outra norma?
        colisao = conn.execute(
            "SELECT id, apelido FROM normas WHERE id_senado = ? AND id != ?",
            (id_novo, id_norma)).fetchone()
        if colisao:
            print(f"  [AVISO] ID {id_novo} já pertence a '{colisao[1]}' — pulando.")
            falhas.append(apelido)
            continue

        # 4) Conferência visual: nome oficial da norma na API
        nome, ementa = _nome_da_norma(id_novo)
        if nome:
            print(f"  [CONFERIR] Nome oficial: {nome}")

        # 5) Atualizar o ID (e preencher a ementa, se estiver vazia)
        if ementa:
            conn.execute("""
                UPDATE normas SET id_senado = ?,
                    ementa = COALESCE(ementa, ?)
                WHERE id = ?
            """, (id_novo, ementa, id_norma))
        else:
            conn.execute("UPDATE normas SET id_senado = ? WHERE id = ?",
                         (id_novo, id_norma))
        conn.commit()
        print(f"  [OK] Atualizado: {id_errado} -> {id_novo}")
        corrigidas += 1
        time.sleep(1.5)

    # 6) Resumo
    restantes = conn.execute(
        "SELECT COUNT(*) FROM normas WHERE id_senado IS NULL OR id_senado <= 0"
    ).fetchone()[0]
    print("\n" + "=" * 70)
    print(f"Corrigidas: {corrigidas} | Falhas: {len(falhas)} | "
          f"Restantes inválidas: {restantes}")
    if falhas:
        print("Pendentes (preencher IDS_MANUAIS no seed.py):")
        for apelido in falhas:
            print(f"  - {apelido}")
    print("=" * 70)
    conn.close()


if __name__ == "__main__":
    main()