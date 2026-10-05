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
