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
