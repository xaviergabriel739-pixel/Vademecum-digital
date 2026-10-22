# -*- coding: utf-8 -*-
"""
migrar_v2.py — VadeMecum AI
Corrige os erros de schema do banco:

  1) normas.area_direito: CHECK de 14 -> 19 areas
     (bloqueia PREVIDENCIARIO, AGRARIO, FINANCEIRO, ECONOMICO, TECNOLOGIA)
  2) normas.tipo_norma: inclui 'LEI COMPLEMENTAR'
  3) dispositivos_fts: passa a indexar 'rotulo' alem de 'texto'
     (sem isso, "art. 171" nao e resolvivel por busca textual)

Faz backup do .db antes de qualquer alteracao.
Uso:  python migrar_v2.py
"""
import shutil
import sqlite3
from datetime import datetime

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "vademecum.db")

if not os.path.exists(DB):
    print("[erro] banco nao encontrado em: %s" % DB)
    print("       confira o nome do arquivo .db nesta pasta.")
    raise SystemExit(1)

AREAS = (
    'CONSTITUCIONAL', 'CIVIL', 'PENAL', 'TRABALHISTA', 'ELEITORAL',
    'TRIBUTARIO', 'TRANSITO', 'CONSUMIDOR', 'AMBIENTAL', 'EMPRESARIAL',
    'ADMINISTRATIVO', 'PROCESSUAL CIVIL', 'PROCESSUAL PENAL',
    'PREVIDENCIARIO', 'AGRARIO', 'FINANCEIRO', 'ECONOMICO', 'TECNOLOGIA',
    'OUTRO',
)

TIPOS = (
    'LEI', 'DECRETO-LEI', 'DECRETO', 'CONSTITUICAO', 'MEDIDA PROVISORIA',
    'LEI COMPLEMENTAR', 'OUTRO',
)

COLS_NORMAS = (
    'id', 'id_senado', 'tipo_norma', 'numero', 'ano', 'ementa', 'apelido',
    'area_direito', 'vade_mecum', 'data_assinatura', 'situacao',
    'data_ultima_alteracao', 'url_fonte', 'data_indexacao',
)


def q(values):
    return ", ".join("'%s'" % v for v in values)


def backup(path):
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    dest = '%s.bak_%s' % (path, stamp)
    shutil.copy2(path, dest)
    print('[backup] %s' % dest)


def ddl(con, name):
    row = con.execute(
        'SELECT sql FROM sqlite_master WHERE name = ?', (name,)
    ).fetchone()
    return row[0] if row and row[0] else ''


def migrar_normas(con):
    print('[1/2] normas: expandindo CHECK de area_direito e tipo_norma...')
    con.execute('PRAGMA foreign_keys = OFF')
    con.execute('BEGIN')
    try:
        con.execute('DROP TABLE IF EXISTS normas_novo')
        con.execute("""
            CREATE TABLE normas_novo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_senado INTEGER UNIQUE NOT NULL,
                tipo_norma TEXT NOT NULL CHECK (tipo_norma IN (%s)),
                numero TEXT NOT NULL,
                ano INTEGER NOT NULL,
                ementa TEXT,
                apelido TEXT,
                area_direito TEXT NOT NULL DEFAULT 'OUTRO' CHECK (area_direito IN (%s)),
                vade_mecum INTEGER NOT NULL DEFAULT 0 CHECK (vade_mecum IN (0, 1)),
                data_assinatura TEXT,
                situacao TEXT NOT NULL CHECK (situacao IN ('VIGENTE', 'ALTERADA', 'REVOGADA')),
                data_ultima_alteracao TEXT,
                url_fonte TEXT,
                data_indexacao TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                UNIQUE (tipo_norma, numero, ano)
            )
        """ % (q(TIPOS), q(AREAS)))

        cols = ', '.join(COLS_NORMAS)
        con.execute('INSERT INTO normas_novo (%s) SELECT %s FROM normas' % (cols, cols))
        con.execute('DROP TABLE normas')
        con.execute('ALTER TABLE normas_novo RENAME TO normas')

        con.execute('CREATE INDEX idx_normas_tipo_numero_ano ON normas(tipo_norma, numero, ano)')
        con.execute('CREATE INDEX idx_normas_area ON normas(area_direito)')
        con.execute('CREATE INDEX idx_normas_situacao ON normas(situacao)')
        con.execute('CREATE INDEX idx_normas_vade ON normas(vade_mecum)')

        con.execute(
            'UPDATE sqlite_sequence SET seq = (SELECT COALESCE(MAX(id), 0) FROM normas) '
            'WHERE name = ?', ('normas',)
        )
        con.execute('COMMIT')
    except Exception:
        con.execute('ROLLBACK')
        raise
    con.execute('PRAGMA foreign_keys = ON')
    print('      ok')


def migrar_fts(con):
    print('[2/2] dispositivos_fts: indexando rotulo + texto...')
    con.executescript("""
        DROP TRIGGER IF EXISTS dispositivos_ai;
        DROP TRIGGER IF EXISTS dispositivos_ad;
        DROP TRIGGER IF EXISTS dispositivos_au;
        DROP TABLE IF EXISTS dispositivos_fts;
    """)
    con.execute("""
        CREATE VIRTUAL TABLE dispositivos_fts USING fts5(
            rotulo,
            texto,
            content='dispositivos',
            content_rowid='id',
            tokenize="unicode61 remove_diacritics 2"
        )
    """)
    con.executescript("""
        CREATE TRIGGER dispositivos_ai AFTER INSERT ON dispositivos BEGIN
            INSERT INTO dispositivos_fts(rowid, rotulo, texto)
            VALUES (new.id, new.rotulo, new.texto);
        END;

        CREATE TRIGGER dispositivos_ad AFTER DELETE ON dispositivos BEGIN
            INSERT INTO dispositivos_fts(dispositivos_fts, rowid, rotulo, texto)
            VALUES ('delete', old.id, old.rotulo, old.texto);
        END;

        CREATE TRIGGER dispositivos_au AFTER UPDATE ON dispositivos BEGIN
            INSERT INTO dispositivos_fts(dispositivos_fts, rowid, rotulo, texto)
            VALUES ('delete', old.id, old.rotulo, old.texto);
            INSERT INTO dispositivos_fts(rowid, rotulo, texto)
            VALUES (new.id, new.rotulo, new.texto);
        END;
    """)
    con.execute("INSERT INTO dispositivos_fts(dispositivos_fts) VALUES('rebuild')")
    print('      ok')


def verificar(con):
    print('\n[verificacao]')
    n = con.execute('SELECT COUNT(*) FROM normas').fetchone()[0]
    d = con.execute('SELECT COUNT(*) FROM dispositivos').fetchone()[0]
    f = con.execute('SELECT COUNT(*) FROM dispositivos_fts').fetchone()[0]
    print('  normas=%d  dispositivos=%d  fts=%d' % (n, d, f))

    print('  art. 171 por rotulo:')
    for apelido, rotulo in con.execute("""
        SELECT n.apelido, d.rotulo
        FROM dispositivos d
        JOIN normas n ON n.id = d.id_norma
        WHERE d.rotulo LIKE 'Art. 171%'
        ORDER BY n.apelido
    """):
        print('    - %s -> %s' % (apelido, rotulo))

    print('  FTS MATCH rotulo:171 ->')
    try:
        for apelido, rotulo in con.execute("""
            SELECT n.apelido, d.rotulo
            FROM dispositivos_fts f
            JOIN dispositivos d ON d.id = f.rowid
            JOIN normas n ON n.id = d.id_norma
            WHERE dispositivos_fts MATCH 'rotulo : 171'
            LIMIT 10
        """):
            print('    - %s -> %s' % (apelido, rotulo))
    except sqlite3.OperationalError as e:
        print('    (falhou: %s)' % e)

    bad = con.execute('PRAGMA foreign_key_check').fetchall()
    print('  foreign_key_check: %s' % ('ok' if not bad else bad))


def main():
    con = sqlite3.connect(DB)
    con.isolation_level = None  # controle manual de transacao

    backup(DB)

    if 'PREVIDENCIARIO' in ddl(con, 'normas'):
        print('[1/2] normas ja migrada — pulando')
    else:
        migrar_normas(con)

    if 'rotulo' in ddl(con, 'dispositivos_fts'):
        print('[2/2] fts ja migrado — pulando')
    else:
        migrar_fts(con)

    verificar(con)
    con.close()
    print('\nConcluido.')


if __name__ == '__main__':
    main()