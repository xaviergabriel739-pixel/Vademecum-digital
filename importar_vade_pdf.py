"""Importa um Vade Mecum em PDF para as tabelas normas e dispositivos.

Dependencia:
    pip install pymupdf

Exemplos:
    # PDF com uma unica lei, informando os metadados na linha de comando
    python importar_vade_pdf.py vade.pdf --id-senado 123456 \
        --tipo LEI --numero 9503 --ano 1997 \
        --apelido "Codigo de Transito Brasileiro" --area TRANSITO

    # PDF com varias leis. O manifesto associa cada lei ao id do Senado.
    python importar_vade_pdf.py vade.pdf --manifesto normas.json

Formato de normas.json:
[
  {
    "id_senado": 123456,
    "tipo_norma": "LEI",
    "numero": "9503",
    "ano": 1997,
    "apelido": "Codigo de Transito Brasileiro",
    "area_direito": "TRANSITO",
    "ementa": "..."
  }
]

O PDF precisa ter texto selecionavel. PDFs digitalizados devem passar por OCR
antes desta importacao. O script nao tenta adivinhar id_senado: normas sem esse
identificador sao reportadas e nao entram no banco.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERRO: dependencia ausente. Instale com: pip install pymupdf")
    raise SystemExit(1)


DB_PADRAO = "vademecum.db"
TIPOS_VALIDOS = {
    "LEI", "DECRETO-LEI", "DECRETO", "CONSTITUICAO",
    "MEDIDA PROVISORIA", "OUTRO",
}
AREAS_VALIDAS = {
    "CONSTITUCIONAL", "PENAL", "CIVIL", "PROCESSUAL PENAL",
    "PROCESSUAL CIVIL", "ADMINISTRATIVO", "TRIBUTARIO", "TRABALHISTA",
    "CONSUMIDOR", "TRANSITO", "AMBIENTAL", "ELEITORAL", "MILITAR",
    "INTERNACIONAL", "EMPRESARIAL", "OUTRO",
}

# Aceita "Art. 5o", "Art. 5º", "Art. 5-A" e variações produzidas por OCR.
ARTIGO_RE = re.compile(
    r"^\s*(Art\.?\s*\d+[ºo°]?(?:[-‑–—][A-Z])?)(?:\s*[-.]?\s*)(.*)$",
    re.IGNORECASE,
)

# Cabecalhos usuais no inicio de cada norma dentro de um Vade Mecum.
NORMA_RE = re.compile(
    r"^\s*(CONSTITUIÇÃO(?:\s+FEDERAL)?|CONSTITUICAO(?:\s+FEDERAL)?|"
    r"LEI(?:\s+COMPLEMENTAR)?|DECRETO-LEI|DECRETO|MEDIDA\s+PROVISÓRIA|"
    r"MEDIDA\s+PROVISORIA)\s*(?:N[.º°o]?\s*)?"
    r"(\d[\d.]*)\b(?P<resto>.*)$",
    re.IGNORECASE,
)


@dataclass
class NormaMeta:
    id_senado: int
    tipo_norma: str
    numero: str
    ano: int
    apelido: str | None = None
    area_direito: str = "OUTRO"
    ementa: str | None = None
    pagina_inicio: int | None = None
    pagina_fim: int | None = None


@dataclass
class BlocoNorma:
    meta: NormaMeta | None
    titulo_pdf: str
    linhas: list[str]
    registros: list[tuple[str, str | None]] | None = None


# Espacos unicode (NBSP, EN/EM SPACE etc.) que o PDF usa no lugar do espaco comum
_ESPACOS_UNICODE_RE = re.compile("[\u00a0\u2000-\u200a\u202f\u205f\u3000]")


def normalizar_linha(linha: str) -> str:
    """Limpa espacos (inclusive unicode) e hifens quebrados sem destruir acentuacao."""
    linha = linha.replace("\u00ad", "")
    linha = _ESPACOS_UNICODE_RE.sub(" ", linha)
    linha = re.sub(r"[ \t]+", " ", linha)
    return linha.strip()


def sem_acento(texto: str) -> str:
    return "".join(
        caractere
        for caractere in unicodedata.normalize("NFD", texto)
        if unicodedata.category(caractere) != "Mn"
    )


def numero_normalizado(numero: str) -> str:
    return numero.replace(".", "").strip()


def tipo_normalizado(tipo: str) -> str:
    tipo = sem_acento(tipo).upper().replace("  ", " ").strip()
    if tipo == "CONSTITUICAO FEDERAL":
        return "CONSTITUICAO"
    if tipo == "LEI COMPLEMENTAR":
        return "LEI"
    if tipo == "MEDIDA PROVISORIA":
        return "MEDIDA PROVISORIA"
    return tipo


def extrair_cabecalho_norma(linha: str) -> tuple[str, str, int | None] | None:
    """Retorna tipo, numero e ano quando a linha parece inicio de uma lei."""
    encontrada = NORMA_RE.match(sem_acento(linha))
    if not encontrada:
        return None
    tipo, numero = encontrada.group(1), encontrada.group(2)
    resto = encontrada.group("resto")
    anos = re.findall(r"\b(1[89]\d{2}|20\d{2})\b", resto)
    ano = int(anos[-1]) if anos else None
    return tipo_normalizado(tipo), numero_normalizado(numero), ano


def extrair_paginas_pdf(caminho_pdf: Path) -> list[str]:
    """Extrai o texto normalizado de cada pagina, mantendo a ordem do PDF."""
    paginas = []
    with fitz.open(caminho_pdf) as documento:
        for pagina in documento:
            texto = pagina.get_text("text")
            paginas.append("\n".join(
                linha for linha in (normalizar_linha(x) for x in texto.splitlines())
                if linha
            ))
    return paginas


def extrair_texto_pdf(caminho_pdf: Path) -> str:
    """Extrai e normaliza texto, removendo linhas de pagina vazias."""
    return "\n".join(extrair_paginas_pdf(caminho_pdf))


_FLAG_NEGRITO = 1 << 4  # bit "bold" retornado por PyMuPDF em span["flags"]


def _rotulo_se_cabecalho_negrito(spans: list[dict]) -> str | None:
    """Retorna o rotulo ('Art. 23.') se o inicio da linha for um cabecalho de
    artigo em negrito, ou None caso contrario.

    Nas edicoes comentadas do Vade Mecum, citacoes de outros artigos dentro
    do texto (ex.: "art. 173, º 1o, III") usam a fonte normal, enquanto o
    cabecalho real do artigo (ex.: "Art. 23.") e impresso em negrito. Usar a
    formatacao em vez de apenas o texto evita que essas citacoes sejam
    confundidas com o inicio de um novo artigo.
    """
    prefixo: list[str] = []
    for span in spans:
        negrito = bool(span.get("flags", 0) & _FLAG_NEGRITO) or "Bold" in span.get("font", "")
        if not negrito:
            break
        prefixo.append(span["text"])
    if not prefixo:
        return None
    texto_prefixo = normalizar_linha("".join(prefixo))
    encontrada = ARTIGO_RE.match(texto_prefixo)
    if not encontrada:
        return None
    rotulo = re.sub(r"\s+", " ", encontrada.group(1))
    return rotulo[:1].upper() + rotulo[1:]


def extrair_registros_paginas(caminho_pdf: Path) -> list[list[tuple[str, str | None]]]:
    """Extrai, por pagina, pares (texto_da_linha, rotulo_se_for_cabecalho).

    O rotulo so e preenchido quando a linha comeca com um cabecalho de
    artigo em negrito (ver _rotulo_se_cabecalho_negrito).
    """
    paginas: list[list[tuple[str, str | None]]] = []
    with fitz.open(caminho_pdf) as documento:
        for pagina in documento:
            linhas_pagina: list[tuple[str, str | None]] = []
            dados = pagina.get_text("dict")
            for bloco in dados.get("blocks", []):
                for linha in bloco.get("lines", []):
                    spans = linha.get("spans", [])
                    texto_linha = normalizar_linha("".join(s["text"] for s in spans))
                    if not texto_linha:
                        continue
                    rotulo = _rotulo_se_cabecalho_negrito(spans)
                    linhas_pagina.append((texto_linha, rotulo))
            paginas.append(linhas_pagina)
    return paginas


def linha_e_artigo(linha: str) -> bool:
    return ARTIGO_RE.match(linha) is not None


def separar_artigos(linhas: Iterable[str]) -> list[tuple[str, str]]:
    """Separa uma norma em artigos a partir de texto simples (sem informacao
    de negrito), usado apenas no modo de deteccao automatica de cabecalhos
    de norma (sem manifesto com paginas)."""
    artigos: list[tuple[str, str]] = []
    rotulo_atual: str | None = None
    acumulado: list[str] = []

    for linha in linhas:
        linha = normalizar_linha(linha)
        if not linha:
            continue
        encontrada = ARTIGO_RE.match(linha)
        if encontrada:
            if rotulo_atual is not None:
                texto = "\n".join(acumulado).strip()
                if texto:
                    artigos.append((rotulo_atual, texto))
            rotulo = re.sub(r"\s+", " ", encontrada.group(1))
            rotulo_atual = rotulo[:1].upper() + rotulo[1:]
            acumulado = [linha]
        elif rotulo_atual is not None:
            acumulado.append(linha)

    if rotulo_atual is not None:
        texto = "\n".join(acumulado).strip()
        if texto:
            artigos.append((rotulo_atual, texto))
    return artigos


def separar_artigos_registros(registros: Iterable[tuple[str, str | None]]) -> list[tuple[str, str]]:
    """Separa artigos usando cabecalhos ja identificados via negrito
    (ver extrair_registros_paginas). Mais confiavel que separar_artigos
    porque nao depende de heuristicas sobre o texto puro."""
    artigos: list[tuple[str, str]] = []
    rotulo_atual: str | None = None
    acumulado: list[str] = []

    for texto_linha, rotulo in registros:
        if rotulo:
            if rotulo_atual is not None:
                corpo = "\n".join(acumulado).strip()
                if corpo:
                    artigos.append((rotulo_atual, corpo))
            rotulo_atual = rotulo
            acumulado = [texto_linha]
        elif rotulo_atual is not None:
            acumulado.append(texto_linha)

    if rotulo_atual is not None:
        corpo = "\n".join(acumulado).strip()
        if corpo:
            artigos.append((rotulo_atual, corpo))
    return artigos


def localizar_blocos(texto: str, metadados: list[NormaMeta]) -> list[BlocoNorma]:
    """Divide um PDF por cabecalhos de norma e associa metadados conhecidos."""
    linhas = texto.splitlines()
    inicios: list[tuple[int, tuple[str, str, int | None]]] = []
    for indice, linha in enumerate(linhas):
        cabecalho = extrair_cabecalho_norma(linha)
        if cabecalho:
            inicios.append((indice, cabecalho))

    if not inicios:
        return [BlocoNorma(metadados[0] if len(metadados) == 1 else None,
                           "PDF inteiro", linhas)]

    blocos: list[BlocoNorma] = []
    for posicao, (inicio, cabecalho) in enumerate(inicios):
        fim = inicios[posicao + 1][0] if posicao + 1 < len(inicios) else len(linhas)
        tipo, numero, ano = cabecalho
        meta = encontrar_meta(metadados, tipo, numero, ano)
        blocos.append(BlocoNorma(meta, linhas[inicio], linhas[inicio:fim]))
    return blocos


def encontrar_meta(metadados: list[NormaMeta], tipo: str, numero: str,
                    ano: int | None) -> NormaMeta | None:
    numero = numero_normalizado(numero)
    for meta in metadados:
        mesmo_tipo = tipo_normalizado(meta.tipo_norma) == tipo
        mesmo_numero = numero_normalizado(meta.numero) == numero
        mesmo_ano = ano is None or meta.ano == ano
        if mesmo_tipo and mesmo_numero and mesmo_ano:
            return meta
    return None


def carregar_metadados(caminho: Path | None, argumentos: argparse.Namespace) -> list[NormaMeta]:
    if caminho:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        if isinstance(dados, dict):
            dados = dados.get("normas", [])
        return [NormaMeta(
            id_senado=int(item["id_senado"]),
            tipo_norma=tipo_normalizado(item["tipo_norma"]),
            numero=numero_normalizado(str(item["numero"])),
            ano=int(item["ano"]),
            apelido=item.get("apelido"),
            area_direito=sem_acento(item.get("area_direito", "OUTRO")).upper(),
            ementa=item.get("ementa"),
            pagina_inicio=item.get("pagina_inicio"),
            pagina_fim=item.get("pagina_fim"),
        ) for item in dados]

    if not argumentos.id_senado:
        return []
    return [NormaMeta(
        id_senado=argumentos.id_senado,
        tipo_norma=tipo_normalizado(argumentos.tipo),
        numero=numero_normalizado(argumentos.numero),
        ano=argumentos.ano,
        apelido=argumentos.apelido,
        area_direito=sem_acento(argumentos.area).upper(),
        ementa=argumentos.ementa,
    )]


def validar_meta(meta: NormaMeta) -> None:
    if meta.tipo_norma not in TIPOS_VALIDOS:
        raise ValueError(f"tipo_norma invalido: {meta.tipo_norma}")
    if meta.area_direito not in AREAS_VALIDAS:
        raise ValueError(f"area_direito invalida: {meta.area_direito}")
    if not meta.numero or meta.ano < 1800:
        raise ValueError(f"numero/ano invalidos: {meta.numero}/{meta.ano}")


def preparar_banco(conn: sqlite3.Connection, schema: Path) -> None:
    tabelas = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='normas'"
    ).fetchone()
    if not tabelas:
        conn.executescript(schema.read_text(encoding="utf-8"))
    conn.execute("PRAGMA foreign_keys = ON")


def inserir_bloco(conn: sqlite3.Connection, bloco: BlocoNorma) -> tuple[int, int]:
    if bloco.meta is None:
        raise ValueError(
            f"Norma sem metadados confiaveis detectada no PDF: {bloco.titulo_pdf}. "
            "Inclua-a no manifesto normas.json."
        )
    validar_meta(bloco.meta)
    artigos = (separar_artigos_registros(bloco.registros) if bloco.registros is not None
               else separar_artigos(bloco.linhas))
    if not artigos:
        raise ValueError(f"Nenhum artigo encontrado na norma: {bloco.titulo_pdf}")

    meta = bloco.meta
    # ids negativos sao sinteticos (sem id_senado real confirmado): nao gerar URL do Senado
    url_fonte = (f"https://legis.senado.leg.br/norma/{meta.id_senado}"
                 if meta.id_senado > 0 else None)
    conn.execute("""
        INSERT INTO normas (
            id_senado, tipo_norma, numero, ano, ementa, apelido,
            area_direito, vade_mecum, situacao, url_fonte
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'VIGENTE', ?)
        ON CONFLICT(id_senado) DO UPDATE SET
            ementa = excluded.ementa,
            apelido = excluded.apelido,
            area_direito = excluded.area_direito,
            vade_mecum = 1,
            data_indexacao = datetime('now', 'localtime')
    """, (
        meta.id_senado, meta.tipo_norma, meta.numero, meta.ano, meta.ementa,
        meta.apelido, meta.area_direito, url_fonte,
    ))
    id_norma = conn.execute(
        "SELECT id FROM normas WHERE id_senado = ?", (meta.id_senado,)
    ).fetchone()[0]

    inseridos = 0
    for rotulo, texto in artigos:
        cursor = conn.execute("""
            INSERT INTO dispositivos (
                id_norma, tipo_dispositivo, rotulo, texto, situacao
            ) VALUES (?, 'ARTIGO', ?, ?, 'VIGENTE')
            ON CONFLICT(id_norma, rotulo) DO UPDATE SET
                texto = excluded.texto,
                situacao = 'VIGENTE',
                data_alteracao = NULL,
                embedding = NULL
        """, (id_norma, rotulo, texto))
        inseridos += cursor.rowcount
    return len(artigos), inseridos


def blocos_por_pagina(registros_paginas: list[list[tuple[str, str | None]]],
                       metadados: list[NormaMeta]) -> list[BlocoNorma]:
    """Monta um bloco por norma usando as paginas informadas no manifesto
    (tipicamente extraidas do sumario/TOC do PDF, mais confiavel que a
    deteccao de cabecalhos no texto corrido). Usa os registros com
    deteccao de negrito para separar artigos corretamente."""
    blocos = []
    total_paginas = len(registros_paginas)
    for meta in metadados:
        inicio = (meta.pagina_inicio or 1) - 1
        # pagina_fim e o 1o pagina da PROXIMA norma (exclusiva); subtrai 1 para
        # nao incluir essa pagina no slice 0-based.
        fim = (meta.pagina_fim - 1) if meta.pagina_fim else total_paginas
        if inicio < 0 or fim > total_paginas or inicio >= fim:
            raise ValueError(
                f"Intervalo de paginas invalido para {meta.apelido}: "
                f"{meta.pagina_inicio}-{meta.pagina_fim} (PDF tem {total_paginas} paginas)"
            )
        registros = [r for pagina in registros_paginas[inicio:fim] for r in pagina]
        blocos.append(BlocoNorma(
            meta, meta.apelido or f"{meta.tipo_norma} {meta.numero}", [], registros))
    return blocos


def executar(args: argparse.Namespace) -> int:
    pdf = Path(args.pdf)
    if not pdf.is_file():
        print(f"ERRO: PDF nao encontrado: {pdf}")
        return 2
    manifesto = Path(args.manifesto) if args.manifesto else None
    if manifesto and not manifesto.is_file():
        print(f"ERRO: manifesto nao encontrado: {manifesto}")
        return 2

    try:
        metadados = carregar_metadados(manifesto, args)
        usa_paginas = metadados and all(m.pagina_inicio for m in metadados)
        if usa_paginas:
            registros_paginas = extrair_registros_paginas(pdf)
            if not any(registros_paginas):
                print("ERRO: nenhum texto extraido. O PDF pode ser digitalizado; rode OCR antes.")
                return 2
            blocos = blocos_por_pagina(registros_paginas, metadados)
        else:
            texto = extrair_texto_pdf(pdf)
            if not texto.strip():
                print("ERRO: nenhum texto extraido. O PDF pode ser digitalizado; rode OCR antes.")
                return 2
            blocos = localizar_blocos(texto, metadados)
        if not blocos:
            print("ERRO: nenhuma norma encontrada no PDF.")
            return 2

        conn = sqlite3.connect(args.db)
        try:
            preparar_banco(conn, Path(args.schema))
            total_artigos = 0
            total_normas = 0
            for bloco in blocos:
                artigos, _ = inserir_bloco(conn, bloco)
                total_artigos += artigos
                total_normas += 1
                nome = bloco.meta.apelido if bloco.meta else bloco.titulo_pdf
                print(f"OK: {nome} -> {artigos} artigos")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as erro:
        print(f"ERRO: {erro}")
        return 1

    print(f"Importacao concluida: {total_normas} normas, {total_artigos} artigos.")
    return 0


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="caminho do PDF do Vade Mecum")
    parser.add_argument("--db", default=DB_PADRAO, help="banco SQLite (padrao: vademecum.db)")
    parser.add_argument("--schema", default="schema.sql", help="schema SQL (padrao: schema.sql)")
    parser.add_argument("--manifesto", help="JSON com metadados das normas")
    parser.add_argument("--id-senado", type=int, help="id_senado para PDF de uma unica norma")
    parser.add_argument("--tipo", default="LEI", help="tipo para PDF de uma unica norma")
    parser.add_argument("--numero", help="numero para PDF de uma unica norma")
    parser.add_argument("--ano", type=int, help="ano para PDF de uma unica norma")
    parser.add_argument("--apelido", help="apelido da norma")
    parser.add_argument("--area", default="OUTRO", help="area_direito da norma")
    parser.add_argument("--ementa", help="ementa da norma")
    return parser


if __name__ == "__main__":
    argumentos = criar_parser().parse_args()
    if argumentos.id_senado and (not argumentos.numero or not argumentos.ano):
        print("ERRO: --id-senado exige --numero e --ano.")
        raise SystemExit(2)
    raise SystemExit(executar(argumentos))
