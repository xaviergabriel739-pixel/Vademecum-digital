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
