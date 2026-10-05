# VadeMecum AI — Backend e Banco de Dados (IA via API gpt-6-luna)

Arquivo consolidado com o backend e o banco de dados do sistema. Destinado ao
Copilot (VS Code): cada seção indica o CAMINHO DO ARQUIVO no título — crie os
arquivos exatamente nesses caminhos e cole o conteúdo do bloco de código sem
alterações.

## Instruções para o Copilot

- Crie cada arquivo no caminho indicado no título da seção.
- O conteúdo entre os cercados de código é o arquivo inteiro.
- `texto_integral.py` JÁ EXISTE no projeto (script validado de extração do
  Senado) — NÃO recriar, NÃO alterar. Os demais módulos importam dele a função
  `extrair_texto_integral(id_senado, numero=..., ano=...)`.
- `static/index.html` JÁ EXISTE (criado pelo arquivo `frontend-vademecum.md`)
  — NÃO recriar neste arquivo.
- A camada de IA (`ia.py`) usa a API da OpenAI, modelo `gpt-6-luna`. Requer a
  variável de ambiente `IA_API_KEY` (ver seção "Configuração da chave de API").
- A ordem de instalação e teste está no arquivo `checklist-testes.md`
  (observação: os passos referentes ao Ollama foram substituídos — ver seção
  "Ajustes no checklist-testes.md" no fim deste arquivo).

## Estrutura do projeto

```
vademecum-ai/
├── vademecum.db            (gerado pelo seed.py)
├── schema.sql
├── texto_integral.py       (seu arquivo já validado — manter como está)
├── seed.py
├── gerar_embeddings.py
├── busca.py
├── ia.py
├── app.py
├── atualizar.py
├── checklist-testes.md     (entregue separadamente)
└── static/
    └── index.html          (já criado pelo frontend-vademecum.md)
```

## 0. Configuração da chave de API (uma vez)

1. Crie a chave em https://platform.openai.com/api-keys
2. No PowerShell, configure a variável de ambiente (permanente):

```powershell
setx IA_API_KEY "sua-chave-aqui"
```

3. Feche e reabra o terminal/VS Code para a variável valer.
4. Custo: o gpt-6-luna é o modelo mais barato da família GPT-6, cobrado por
   token. Consulte https://openai.com/api/pricing

## 1. Banco de dados — `schema.sql`

```sql
-- schema.sql — VadeMecum AI
-- SQLite 3 com FTS5. Execute antes do seed.py.

PRAGMA foreign_keys = ON;

-- ==========================================================
-- NORMAS
-- ==========================================================
CREATE TABLE normas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_senado INTEGER UNIQUE NOT NULL,
    tipo_norma TEXT NOT NULL CHECK (tipo_norma IN (
        'LEI', 'DECRETO-LEI', 'DECRETO', 'CONSTITUICAO',
        'MEDIDA PROVISORIA', 'OUTRO')),
    numero TEXT NOT NULL,
    ano INTEGER NOT NULL,
    ementa TEXT,
    apelido TEXT,
    area_direito TEXT NOT NULL CHECK (area_direito IN (
        'CONSTITUCIONAL', 'PENAL', 'CIVIL', 'PROCESSUAL PENAL',
        'PROCESSUAL CIVIL', 'ADMINISTRATIVO', 'TRIBUTARIO',
        'TRABALHISTA', 'CONSUMIDOR', 'TRANSITO', 'AMBIENTAL',
        'ELEITORAL', 'MILITAR', 'INTERNACIONAL', 'EMPRESARIAL', 'OUTRO')),
    vade_mecum INTEGER NOT NULL DEFAULT 0 CHECK (vade_mecum IN (0, 1)),
    data_assinatura TEXT,
    situacao TEXT NOT NULL CHECK (situacao IN ('VIGENTE', 'ALTERADA', 'REVOGADA')),
    data_ultima_alteracao TEXT,
    url_fonte TEXT,
    data_indexacao TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (tipo_norma, numero, ano)
);

-- ==========================================================
-- DISPOSITIVOS (artigos, parágrafos, incisos)
-- ==========================================================
CREATE TABLE dispositivos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_norma INTEGER NOT NULL REFERENCES normas(id) ON DELETE CASCADE,
    tipo_dispositivo TEXT NOT NULL CHECK (tipo_dispositivo IN (
        'ARTIGO', 'PARAGRAFO', 'INCISO', 'ALINEA', 'PREAMBULO', 'OUTRO')),
    rotulo TEXT NOT NULL,
    texto TEXT NOT NULL,
    situacao TEXT NOT NULL CHECK (situacao IN ('VIGENTE', 'INCLUIDO', 'ALTERADO', 'REVOGADO')),
    data_alteracao TEXT,
    embedding BLOB,
    UNIQUE (id_norma, rotulo)
);

-- ==========================================================
-- PALAVRAS-CHAVE (N:N com dispositivos)
-- ==========================================================
CREATE TABLE palavras_chave (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    palavra TEXT UNIQUE NOT NULL
);

CREATE TABLE dispositivos_palavras_chave (
    id_dispositivo INTEGER NOT NULL REFERENCES dispositivos(id) ON DELETE CASCADE,
    id_palavra_chave INTEGER NOT NULL REFERENCES palavras_chave(id) ON DELETE CASCADE,
    PRIMARY KEY (id_dispositivo, id_palavra_chave)
);

-- ==========================================================
-- ALTERAÇÕES LEGISLATIVAS
-- ==========================================================
CREATE TABLE alteracoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_norma_afetada INTEGER NOT NULL REFERENCES normas(id) ON DELETE CASCADE,
    id_norma_origem INTEGER REFERENCES normas(id),
    tipo_alteracao TEXT NOT NULL CHECK (tipo_alteracao IN ('ALTERACAO', 'ACRESCIMO', 'REVOGACAO')),
    dispositivo_afetado TEXT,
    data_alteracao TEXT NOT NULL,
    descricao TEXT
);

-- ==========================================================
-- HISTÓRICO DO CHAT
-- ==========================================================
CREATE TABLE conversas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL DEFAULT 'Nova conversa',
    criada_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    atualizada_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE mensagens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_conversa INTEGER NOT NULL REFERENCES conversas(id) ON DELETE CASCADE,
    papel TEXT NOT NULL CHECK (papel IN ('USUARIO', 'IA')),
    conteudo TEXT NOT NULL,
    fontes TEXT,
    criada_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ==========================================================
-- BUSCA DE TEXTO COMPLETO (FTS5, conteúdo externo)
-- ==========================================================
CREATE VIRTUAL TABLE dispositivos_fts USING fts5(
    texto,
    content='dispositivos',
    content_rowid='id'
);

CREATE TRIGGER dispositivos_ai AFTER INSERT ON dispositivos BEGIN
    INSERT INTO dispositivos_fts(rowid, texto) VALUES (new.id, new.texto);
END;

CREATE TRIGGER dispositivos_ad AFTER DELETE ON dispositivos BEGIN
    INSERT INTO dispositivos_fts(dispositivos_fts, rowid, texto)
    VALUES ('delete', old.id, old.texto);
END;

CREATE TRIGGER dispositivos_au AFTER UPDATE ON dispositivos BEGIN
    INSERT INTO dispositivos_fts(dispositivos_fts, rowid, texto)
    VALUES ('delete', old.id, old.texto);
    INSERT INTO dispositivos_fts(rowid, texto) VALUES (new.id, new.texto);
END;

-- ==========================================================
-- ÍNDICES
-- ==========================================================
CREATE INDEX idx_normas_tipo_numero_ano ON normas(tipo_norma, numero, ano);
CREATE INDEX idx_normas_area ON normas(area_direito);
CREATE INDEX idx_normas_situacao ON normas(situacao);
CREATE INDEX idx_normas_vade ON normas(vade_mecum);
CREATE INDEX idx_dispositivos_norma ON dispositivos(id_norma);
CREATE INDEX idx_dispositivos_situacao ON dispositivos(situacao);
CREATE INDEX idx_alteracoes_norma ON alteracoes(id_norma_afetada);
CREATE INDEX idx_alteracoes_data ON alteracoes(data_alteracao);
CREATE INDEX idx_mensagens_conversa ON mensagens(id_conversa);
CREATE INDEX idx_conversas_atualizada ON conversas(atualizada_em);
```

## 2. Extração de texto — `texto_integral.py`

> **NÃO CRIAR ESTE ARQUIVO.** Ele já existe no projeto e está validado.
> Contrato esperado pelos módulos abaixo:
> `extrair_texto_integral(id_senado, numero=..., ano=...) -> str`
> (retorna o texto integral da norma, ou string vazia/None se falhar).

## 3. População do banco — `seed.py`

```python
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
```

## 4. Embeddings — `gerar_embeddings.py`

```python
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
```

## 5. Camada de IA — `ia.py` (REESCRITO: API gpt-6-luna)

```python
# ia.py — Camada de IA do VadeMecum AI (API da OpenAI — modelo gpt-6-luna)
#
# Este módulo é o ÚNICO ponto de contato entre o sistema e o modelo de IA.
# Todo o resto do backend chama responder() — nunca a API diretamente.
# Trocar de modelo ou provedor no futuro = editar apenas este arquivo.
#
# Diferenças em relação à versão com Ollama:
#   - O modelo roda na nuvem: não ocupa RAM do notebook (só o modelo de
#     embeddings da busca continua local)
#   - Respostas em segundos, não minutos
#   - Requer chave de API na variável de ambiente IA_API_KEY
#   - Custo por uso (tokens) — ver https://openai.com/api/pricing
#
# Requisitos:
#   - pip install requests
#   - Chave configurada:  setx IA_API_KEY "sua-chave"  (PowerShell, uma vez)

import os
import json
import requests

# ------------------------------------------------------------
# CONFIGURAÇÃO
# ------------------------------------------------------------
BASE_URL = "https://api.openai.com/v1"
MODELO = "gpt-6-luna"      # modelo eficiente da família GPT-6 — ideal para
                           # ler os resultados do banco e escrever a resposta
TEMPERATURA = 0.2          # baixa = respostas mais factuais e estáveis
MAX_TOKENS = 2000          # teto da resposta gerada (o modelo suporta até 128K)
RAZONAMENTO = "low"        # none | low | medium | high — "low" basta para este
                           # papel; aumente se quiser análises mais profundas
TIMEOUT = 120              # segundos — a API responde em segundos, não minutos


def _api_key():
    return os.environ.get("IA_API_KEY", "").strip()

# ------------------------------------------------------------
# SYSTEM PROMPT — regras condensadas do VadeMecum AI
# (versão compacta do .prompt.md, otimizada para chamada de API)
# ------------------------------------------------------------
SYSTEM_PROMPT = """Você é o assistente jurídico do sistema VadeMecum AI.

REGRAS FUNDAMENTAIS:
1. O TEXTO LEGAL apresentado vem EXCLUSIVAMENTE do campo "texto_api"
   (fonte oficial). Nunca apresente o campo "texto_indexado" como texto legal.
2. O banco de dados serve apenas para DESCOBERTA: identificar quais normas
   e dispositivos são relevantes. Ele pode estar desatualizado.
3. Se "texto_api" for null, NÃO use o texto_indexado como texto legal.
   Informe que o texto não pôde ser confirmado na fonte oficial.
4. Se o texto da API divergir do indexado, PREVALECE o texto_api.

COMO RESPONDER:
- "Texto legal:" → conteúdo do campo texto_api, sem alterar o significado.
- "Explicação:" → sua interpretação simplificada, claramente separada.
- Cite sempre: norma, artigo e que o texto vem da fonte oficial (Senado).
- Priorize dispositivos de normas com vade_mecum = 1.
- Analise o contexto jurídico: similaridade alta não garante aplicabilidade.
- Se os dados forem insuficientes, diga isso claramente. NUNCA invente
  legislação, artigos, alterações ou jurisprudência.
- Se a pergunta for ambígua, peça esclarecimento antes de responder."""


# ------------------------------------------------------------
# FUNÇÃO PRINCIPAL
# ------------------------------------------------------------
def responder(pergunta, resultados, historico=None):
    """
    Gera a resposta final do VadeMecum AI.

    Parâmetros:
      pergunta: str — pergunta do usuário em linguagem natural.
      resultados: list[dict] — dispositivos vindos do backend, cada um com:
        - rotulo: 'Art. 308'
        - norma: 'Lei nº 9.503/1997 (CTB)'
        - area: 'TRANSITO'
        - vade_mecum: 1 ou 0
        - similaridade: float
        - texto_indexado: str (texto do banco — apenas referência)
        - texto_api: str | None (texto oficial atual — FONTE DO TEXTO LEGAL)
      historico: list[dict] — mensagens anteriores no formato
        [{"role": "user"|"assistant", "content": "..."}] (opcional)

    Retorna:
      str — resposta pronta para exibir ao usuário.
    """
    if not _api_key():
        return ("[ERRO] Chave de API não configurada. No PowerShell, rode: "
                "setx IA_API_KEY \"sua-chave\" e reabra o terminal.")

    payload_resultados = json.dumps(resultados, ensure_ascii=False, indent=2)

    conteudo_usuario = (
        f"PERGUNTA DO USUÁRIO:\n{pergunta}\n\n"
        f"DISPOSITIVOS RECUPERADOS (JSON):\n{payload_resultados}\n\n"
        "Responda seguindo as regras do sistema."
    )

    mensagens = [{"role": "system", "content": SYSTEM_PROMPT}]
    if historico:
        mensagens.extend(historico[-6:])  # últimas 6 mensagens dão contexto
    mensagens.append({"role": "user", "content": conteudo_usuario})

    try:
        resp = requests.post(
            f"{BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {_api_key()}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODELO,
                "messages": mensagens,
                "temperature": TEMPERATURA,
                "max_tokens": MAX_TOKENS,
                "reasoning_effort": RAZONAMENTO,
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        dados = resp.json()
        return dados["choices"][0]["message"]["content"].strip()

    except requests.exceptions.HTTPError as e:
        codigo = e.response.status_code
        if codigo == 401:
            return ("[ERRO] Chave de API inválida (401). Confira a variável "
                    "IA_API_KEY e se a chave está ativa na OpenAI.")
        if codigo == 429:
            return ("[ERRO] Limite de uso atingido (429). Aguarde alguns "
                    "instantes ou verifique o crédito da conta.")
        if codigo == 404:
            return (f"[ERRO] Modelo '{MODELO}' não encontrado (404). Confira "
                    "o nome do modelo em developers.openai.com/api/docs/models.")
        return f"[ERRO] A API retornou erro {codigo}."
    except requests.exceptions.ConnectionError:
        return "[ERRO] Sem conexão com a API. Verifique a internet."
    except requests.exceptions.Timeout:
        return "[ERRO] A API demorou demais para responder. Tente novamente."
    except (KeyError, json.JSONDecodeError):
        return "[ERRO] Resposta inesperada da API. Verifique a documentação do modelo."


# ------------------------------------------------------------
# FUNÇÕES DE APOIO (saúde e diagnóstico)
# ------------------------------------------------------------
def testar_ia():
    """Diagnóstico rápido: chave configurada + teste de resposta."""
    if not _api_key():
        print("[FALHA] Variável IA_API_KEY não configurada.")
        print("No PowerShell:  setx IA_API_KEY \"sua-chave\"  e reabra o terminal.")
        return
    print("[OK] Chave de API encontrada.")
    print(f"Modelo: {MODELO} | Endpoint: {BASE_URL}/chat/completions")
    print("\nTestando resposta do modelo...")
    resposta = responder(
        "Quem é você e qual sua função no sistema VadeMecum AI?",
        resultados=[],
    )
    print(resposta)


if __name__ == "__main__":
    testar_ia()
```

## 6. Backend web — `app.py`

```python
# app.py — Backend web do VadeMecum AI
#
# Conecta: pergunta → busca no banco (busca.py) → texto atual na API
# do Senado (dentro de busca.py) → resposta da IA (ia.py, API gpt-6-luna)
# → histórico.
#
# Requisitos: pip install flask flask-cors
# Uso: python app.py  →  http://localhost:5000 (serve o chat em /)
#
# Endpoints:
#   GET  /                                 página do chat (static/index.html)
#   POST /api/perguntar                    {pergunta, conversa_id?}
#   GET  /api/conversas                    lista de conversas
#   GET  /api/conversas/<id>/mensagens     histórico de uma conversa
#   DELETE /api/conversas/<id>             apaga conversa

import json
import sqlite3

from flask import Flask, request, jsonify, send_from_directory

import busca
import ia

DB = "vademecum.db"

app = Flask(__name__)
try:
    from flask_cors import CORS
    CORS(app)
except ImportError:
    pass  # instale flask-cors quando o frontend rodar em outra origem


def _db():
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _historico(conn, id_conversa):
    linhas = conn.execute("""
        SELECT papel, conteudo FROM mensagens
        WHERE id_conversa = ? ORDER BY id
    """, (id_conversa,)).fetchall()
    return [
        {"role": "user" if papel == "USUARIO" else "assistant", "content": conteudo}
        for papel, conteudo in linhas
    ]


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.post("/api/perguntar")
def perguntar():
    dados = request.get_json(silent=True) or {}
    pergunta = (dados.get("pergunta") or "").strip()
    if not pergunta:
        return jsonify({"erro": "Campo 'pergunta' é obrigatório."}), 400

    conn = _db()
    try:
        # 1) Conversa (nova ou existente)
        id_conversa = dados.get("conversa_id")
        if id_conversa:
            existe = conn.execute(
                "SELECT id FROM conversas WHERE id = ?", (id_conversa,)).fetchone()
            if not existe:
                return jsonify({"erro": "Conversa não encontrada."}), 404
        else:
            titulo = pergunta[:60] + ("..." if len(pergunta) > 60 else "")
            cur = conn.execute(
                "INSERT INTO conversas (titulo) VALUES (?)", (titulo,))
            id_conversa = cur.lastrowid

        # 2) Salvar a pergunta do usuário
        conn.execute(
            "INSERT INTO mensagens (id_conversa, papel, conteudo) "
            "VALUES (?, 'USUARIO', ?)", (id_conversa, pergunta))
        conn.commit()

        # 3) Busca no banco + texto atual na API do Senado
        resultados = busca.montar_resultados(pergunta)

        # 4) Resposta da IA (API gpt-6-luna) — histórico sem a pergunta atual
        historico = _historico(conn, id_conversa)[:-1]
        resposta = ia.responder(pergunta, resultados, historico)

        # 5) Fontes citadas (padrão do prompt: origem de cada informação)
        fontes = [
            {
                "norma": r["norma"],
                "dispositivo": r["rotulo"],
                "texto_confirmado": r["texto_api"] is not None,
                "origem_texto": ("API oficial do Senado Federal"
                                 if r["texto_api"] else
                                 "Não confirmado na fonte oficial"),
                "identificacao": "Índice do sistema (banco de dados)",
            }
            for r in resultados
        ]

        # 6) Salvar a resposta da IA
        conn.execute(
            "INSERT INTO mensagens (id_conversa, papel, conteudo, fontes) "
            "VALUES (?, 'IA', ?, ?)",
            (id_conversa, resposta, json.dumps(fontes, ensure_ascii=False)))
        conn.execute(
            "UPDATE conversas SET atualizada_em = datetime('now','localtime') "
            "WHERE id = ?", (id_conversa,))
        conn.commit()

        return jsonify({
            "conversa_id": id_conversa,
            "resposta": resposta,
            "fontes": fontes,
            "dispositivos_encontrados": len(resultados),
        })
    except Exception as e:
        return jsonify({"erro": f"Falha no processamento: {e}"}), 500
    finally:
        conn.close()


@app.get("/api/conversas")
def listar_conversas():
    conn = _db()
    linhas = conn.execute("""
        SELECT id, titulo, atualizada_em
        FROM conversas ORDER BY atualizada_em DESC
    """).fetchall()
    conn.close()
    return jsonify([
        {"id": i, "titulo": t, "atualizada_em": a} for i, t, a in linhas
    ])


@app.get("/api/conversas/<int:id_conversa>/mensagens")
def mensagens_conversa(id_conversa):
    conn = _db()
    linhas = conn.execute("""
        SELECT papel, conteudo, fontes, criada_em
        FROM mensagens WHERE id_conversa = ? ORDER BY id
    """, (id_conversa,)).fetchall()
    conn.close()
    return jsonify([
        {
            "papel": "usuario" if p == "USUARIO" else "ia",
            "conteudo": c,
            "fontes": json.loads(f) if f else None,
            "criada_em": cr,
        }
        for p, c, f, cr in linhas
    ])


@app.delete("/api/conversas/<int:id_conversa>")
def apagar_conversa(id_conversa):
    conn = _db()
    cur = conn.execute("DELETE FROM conversas WHERE id = ?", (id_conversa,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return jsonify({"erro": "Conversa não encontrada."}), 404
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("=" * 60)
    print("VadeMecum AI — backend rodando em http://localhost:5000")
    print("A primeira busca carrega o modelo de embeddings (local).")
    print("A resposta da IA vem da API gpt-6-luna (requer IA_API_KEY).")
    print("=" * 60)
    app.run(host="localhost", port=5000, debug=False)
```

## 7. Busca híbrida — `busca.py`

```python
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
```

## 8. Atualização — `atualizar.py`

```python
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
```

## 9. Instalação e execução (resumo)

```bash
pip install requests flask flask-cors sentence-transformers numpy
setx IA_API_KEY "sua-chave-da-openai"   # PowerShell — uma vez; reabra o terminal

python seed.py                    # 1. cria e popula o banco
python gerar_embeddings.py        # 2. gera os vetores
python ia.py                      # 3. valida a camada de IA (via API)
python app.py                     # 4. sobe o sistema em http://localhost:5000
```

Atualização sob demanda: `python atualizar.py` (ou com `--normas`, `--textos`, `--embeddings`).

## 10. Ajustes no checklist-testes.md

Substituir no checklist existente:

- **Passo 0**: remover os itens "Ollama instalado e rodando" e "Modelo de chat
  baixado (`ollama pull qwen2.5:3b`)"; incluir "Chave de API configurada —
  `setx IA_API_KEY`" e "Variável visível no terminal (`echo $env:IA_API_KEY`)".
- **Passo 3 (ia.py)**: esperado muda para `[OK] Chave de API encontrada` +
  apresentação do assistente jurídico. Remover referências a `ollama list`.
- **Passo 5 (app.py)**: remover a expectativa de "primeira pergunta lenta por
  causa do modelo local" — a IA agora responde em segundos; só a primeira
  busca carrega os embeddings.
- **Problemas comuns**: remover as linhas de Ollama; incluir: erro 401 → chave
  inválida; erro 429 → limite de uso; erro 404 → nome do modelo/endpoint.