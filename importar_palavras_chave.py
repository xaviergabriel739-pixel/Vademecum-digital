# ============================================================================
# importar_palavras_chave.py
# Importa palavras-chave de um CSV (exportação da planilha de expansão) para
# o banco SQLite do VadeMecum AI.
#
# REGRA DE OURO: vincula por (norma, rotulo do dispositivo), NUNCA pelo
# id_dispositivo do CSV — nas linhas marcadas CORRIGIDO o id antigo aponta
# para o artigo errado (a planilha já traz a norma/rotulo corrigidos).
#
# Uso:
#   python importar_palavras_chave.py [caminho_do.csv] [caminho_do.db]
#
# Flags opcionais:
#   --todos               importa também REVISAR e PENDENTE
#   --incluir-revisar     importa também as linhas REVISAR
#   --incluir-pendente    importa também as linhas PENDENTE
#   --dry-run             apenas mostra o que SERIA importado, sem gravar
#
# ANTES DE RODAR DE VERDADE:
#   1. Faça backup do vademecum.db (ou rode primeiro em uma cópia).
#   2. Cadastre antes as normas novas (VADE_MECUM + atualizar.py --normas):
#      as linhas cuja norma não estiver no banco serão reportadas e puladas.
# ============================================================================

import csv
import io
import re
import sqlite3
import sys
import unicodedata

# ---------------------------------------------------------------------------
# Configuração (pode ser passada por argumento)
# ---------------------------------------------------------------------------
CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else "planilha_expansao_vade_mecum.csv"
DB_PATH  = sys.argv[2] if len(sys.argv) > 2 else "vademecum.db"

TODOS            = "--todos"           in sys.argv
INCLUIR_REVISAR  = "--incluir-revisar" in sys.argv
INCLUIR_PENDENTE = "--incluir-pendente"in sys.argv
DRY_RUN          = "--dry-run"         in sys.argv

# ---------------------------------------------------------------------------
# Normalização (tolerância a variações de formatação)
# ---------------------------------------------------------------------------

def _sem_acentos(texto):
    """Remove acentos para comparar nomes de normas de forma tolerante."""
    texto = unicodedata.normalize("NFD", texto or "")
    return texto.encode("ascii", "ignore").decode("ascii")


def normalizar_norma(nome):
    """Normaliza o nome da norma para casar com normas.apelido."""
    return re.sub(r"\s+", " ", _sem_acentos(nome).strip().lower())


def parse_rotulo(rotulo):
    """
    Extrai (numero, sufixo) de rótulos variados:
      'Art. 5o'  -> (5, '')
      'Art. 5º'  -> (5, '')
      'Art. 5'   -> (5, '')
      'Art. 58-A'-> (58, 'a')
    Retorna None se não parecer um artigo.
    """
    if not rotulo:
        return None
    m = re.search(
        r"(?:art|artigo)\.?\s*(\d+)(?:[º°oªa]?)(?:[-\s]([a-zA-Z]))?",
        rotulo.lower().strip(),
    )
    if m:
        return (int(m.group(1)), (m.group(2) or "").lower())
    return None


def chave_rotulo(rotulo):
    """Chave canônica usada no dict de dispositivos."""
    p = parse_rotulo(rotulo)
    return f"{p[0]}{p[1]}" if p else normalizar_norma(rotulo)


# ---------------------------------------------------------------------------
# Leitura do CSV — detecta encoding (UTF-8/UTF-16/Latin-1) e delimitador
# ---------------------------------------------------------------------------

def _ler_csv_bytes():
    with open(CSV_PATH, "rb") as fh:
        raw = fh.read()

    # BOMs explícitos primeiro
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        texto = raw.decode("utf-16")
    elif raw.startswith(b"\xef\xbb\xbf"):
        texto = raw.decode("utf-8-sig")
    else:
        # sem BOM: tenta UTF-8, depois Latin-1 (sempre decodifica)
        try:
            texto = raw.decode("utf-8")
        except UnicodeDecodeError:
            texto = raw.decode("latin-1")

    linhas = texto.splitlines()
    primeiro = linhas[0]
    delim = ";" if primeiro.count(";") > primeiro.count(",") else ","
    return list(csv.DictReader(io.StringIO(texto), delimiter=delim))


def _col(linha, *nomes):
    """Busca o valor da coluna aceitando variações de nome/caixa."""
    for nome in nomes:
        for k, v in linha.items():
            if k and k.strip().lower() == nome.lower():
                return (v or "").strip()
    return ""


# ---------------------------------------------------------------------------
# Filtro por status da coluna "verificacao"
# ---------------------------------------------------------------------------

def status_permitido(status):
    if TODOS:
        return True
    s = (status or "").strip().upper()
    if not s:
        return True
    if s.startswith("OK") or s.startswith("CORRIGIDO"):
        return True
    if s.startswith("REVISAR") and INCLUIR_REVISAR:
        return True
    if s.startswith("PENDENTE") and INCLUIR_PENDENTE:
        return True
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    linhas = _ler_csv_bytes()
    if not linhas:
        raise SystemExit("CSV vazio ou sem cabeçalho.")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    # Carrega normas e dispositivos UMA vez (evita consulta por linha)
    normas = {}
    for id_n, apelido in conn.execute("SELECT id, apelido FROM normas"):
        normas.setdefault(normalizar_norma(apelido), []).append(id_n)

    disp_por_norma = {}
    for id_d, id_n, rotulo in conn.execute(
        "SELECT id, id_norma, rotulo FROM dispositivos"
    ):
        disp_por_norma.setdefault(id_n, {})
        disp_por_norma[id_n].setdefault(chave_rotulo(rotulo), []).append(id_d)

    # Contadores
    total = len(linhas)
    importados = 0
    pulados_status = 0
    norma_nao_achada = set()
    disp_nao_achado = 0
    multiplos = 0
    pendentes = {}

    def registrar(motivo, ref):
        pendentes.setdefault(motivo, []).append(ref)

    for linha in linhas:
        palavra = _col(linha, "palavra_chave", "palavra")
        norma_csv = _col(linha, "norma", "norma_alvo")
        rotulo_csv = _col(linha, "dispositivo", "rotulo", "referencia_artigo_dispositivo")
        status = _col(linha, "verificacao", "verificação")

        if not all((palavra, norma_csv, rotulo_csv)):
            registrar("linha incompleta (sem palavra/norma/rotulo)", str(linha))
            continue

        ref = f"{norma_csv} | {rotulo_csv} | {palavra}"

        if not status_permitido(status):
            pulados_status += 1
            continue

        # 1) Encontra a norma (por apelido normalizado)
        chave_norma = normalizar_norma(norma_csv)
        ids_norma = normas.get(chave_norma)
        if not ids_norma:
            ids_norma = [x for k, lista in normas.items()
                         if chave_norma in k for x in lista]
        if not ids_norma:
            norma_nao_achada.add(norma_csv)
            registrar("norma nao encontrada no banco", ref)
            continue
        id_norma = ids_norma[0]

        # 2) Encontra o dispositivo (por rótulo canônico)
        ids_disp = disp_por_norma.get(id_norma, {}).get(chave_rotulo(rotulo_csv), [])
        if not ids_disp:
            disp_nao_achado += 1
            registrar(f"dispositivo '{rotulo_csv}' nao encontrado na norma", ref)
            continue
        if len(ids_disp) > 1:
            multiplos += 1
        id_disp = ids_disp[0]

        # 3) Garante a palavra-chave e grava o vínculo
        if not DRY_RUN:
            conn.execute(
                "INSERT OR IGNORE INTO palavras_chave (palavra) VALUES (?)",
                (palavra,),
            )
            id_pc = conn.execute(
                "SELECT id FROM palavras_chave WHERE palavra = ?", (palavra,)
            ).fetchone()[0]
            conn.execute(
                "INSERT OR IGNORE INTO dispositivos_palavras_chave "
                "(id_dispositivo, id_palavra_chave) VALUES (?, ?)",
                (id_disp, id_pc),
            )
        importados += 1

    if not DRY_RUN:
        conn.commit()

    # ------------------------------------------------------------------
    # Relatório
    # ------------------------------------------------------------------
    print("=" * 70)
    print(f"CSV: {CSV_PATH} | DB: {DB_PATH}"
          f"{' | DRY-RUN (nada gravado)' if DRY_RUN else ''}")
    print(f"Linhas no CSV: {total}")
    print(f"Vínculos importados: {importados}")
    print(f"Pulados por status (REVISAR/PENDENTE): {pulados_status}")
    print(f"Dispositivos não encontrados: {disp_nao_achado}")
    print(f"Vínculos com múltiplos artigos candidatos (usou o 1º): {multiplos}")
    if norma_nao_achada:
        print(f"\nNorma(s) não encontrada(s) no banco — cadastre antes "
              f"({len(norma_nao_achada)}):")
        for n in sorted(norma_nao_achada):
            print(f"  - {n}")
    if pendentes:
        print("\nLinhas pendentes de resolução:")
        for motivo, refs in sorted(pendentes.items()):
            print(f"\n  [{motivo}] ({len(refs)})")
            for r in refs[:10]:
                print(f"    - {r}")
            if len(refs) > 10:
                print(f"    ... e mais {len(refs) - 10}")
    print("=" * 70)
    conn.close()


if __name__ == "__main__":
    main()