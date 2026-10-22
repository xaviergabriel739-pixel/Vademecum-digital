import re
import requests
from lxml import html

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

def _achar_inicio(texto, numero=None, ano=None):
    """Localiza onde o texto da norma começa, ignorando o cabeçalho do portal."""
    # 1) Marcadores fixos do portal
    for marcador in [
        "Normas Jurídicas em Texto Integral",
        "Este texto não substitui o original publicado no Diário Oficial.",
    ]:
        pos = texto.find(marcador)
        if pos != -1:
            return pos + len(marcador)

    # 2) Título da norma (ex.: "DECRETO-LEI N. 2.848, DE 7 DE DEZEMBRO DE 1940")
    if numero and ano:
        numero_limpo = str(numero).replace(".", "")
        linhas = texto.splitlines()
        for i, linha in enumerate(linhas):
            linha_limpa = linha.replace(".", "").replace("º", "").replace("°", "")
            if numero_limpo in linha_limpa and str(ano) in linha:
                return sum(len(l) + 1 for l in linhas[:i])
    return 0

def _cortar_rodape(texto):
    for rodape in ["Fale com o Senado", "Senado Federal - Praça dos Três Poderes", "Intranet"]:
        pos = texto.find(rodape)
        if pos != -1:
            texto = texto[:pos]
    return texto

import requests
from lxml import html

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

def extrair_texto_integral(id_norma, numero=None, ano=None, debug=True):
    """Extrai o texto integral de uma norma federal. Nunca lança exceção."""
    try:
        # 1) Página de detalhes -> achar o link "Ver texto no Sigen"
        url_detalhes = f"https://legis.senado.leg.br/norma/{id_norma}"
        if debug: print(f"[1/4] Buscando: {url_detalhes}", flush=True)
        resp = requests.get(url_detalhes, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            if debug: print(f"[ERRO] Detalhes: status {resp.status_code}", flush=True)
            return None
        arvore = html.fromstring(resp.content)

        url_texto = None
        for link in arvore.xpath("//a"):
            if "ver texto" in " ".join(link.text_content().split()).lower():
                href = link.get("href", "")
                if href and not href.startswith(("javascript:", "#")):
                    url_texto = requests.compat.urljoin(url_detalhes, href)
                    break
        if not url_texto:
            if debug: print("[ERRO] Nenhum link 'Ver texto no Sigen' encontrado", flush=True)
            return None
        if debug: print(f"[2/4] Link do texto: {url_texto}", flush=True)

        # 2) Baixar a página do texto
        resp_texto = requests.get(url_texto, headers=HEADERS, timeout=30)
        if resp_texto.status_code != 200:
            if debug: print(f"[ERRO] Texto: status {resp_texto.status_code}", flush=True)
            return None
        if debug: print(f"[3/4] Página baixada: {len(resp_texto.content)} bytes", flush=True)

        # 3) Remover scripts/estilos/navegação do portal
        arvore_texto = html.fromstring(resp_texto.content)
        for tag in arvore_texto.xpath("//script | //style | //nav | //header | //footer | //aside"):
            pai = tag.getparent()
            if pai is not None:
                pai.remove(tag)
        texto = arvore_texto.text_content()

        # 4) Localizar o início do texto da norma
        inicio = 0
        for marcador in ["Normas Jurídicas em Texto Integral",
                         "Este texto não substitui o original publicado no Diário Oficial."]:
            pos = texto.find(marcador)
            if pos != -1:
                inicio = pos + len(marcador)
                break
        else:
            if numero and ano:
                numero_limpo = str(numero).replace(".", "")
                linhas = texto.splitlines()
                for i, linha in enumerate(linhas):
                    if numero_limpo in linha.replace(".", "").replace("º", "").replace("°", "") and str(ano) in linha:
                        inicio = sum(len(l) + 1 for l in linhas[:i])
                        break
        texto = texto[inicio:]

        # 5) Cortar rodapé e limpar
        for rodape in ["Fale com o Senado", "Senado Federal - Praça dos Três Poderes", "Intranet"]:
            pos = texto.find(rodape)
            if pos != -1:
                texto = texto[:pos]
        linhas = [l.strip() for l in texto.splitlines() if l.strip()]
        texto_limpo = "\n".join(linhas)
        if debug: print(f"[4/4] Texto extraído: {len(texto_limpo)} caracteres", flush=True)
        return texto_limpo if len(texto_limpo) > 100 else None
    except Exception as e:
        if debug: print(f"[ERRO] Exceção: {e}", flush=True)
        return None

# ===== TESTE =====
"""if __name__ == "__main__":
    id_norma = 549945   # Código Penal (Decreto-Lei 2.848/1940)
    numero = 8069
    ano = 1990

    texto = extrair_texto_integral(id_norma, numero, ano, debug=True)

    if texto:
        print("\n" + "=" * 60)
        print("TEXTO EXTRAÍDO:")
        print("=" * 60)
        print(texto)
        print("=" * 60)
        print(f"\nTamanho total: {len(texto)} caracteres")
        with open("texto_norma.txt", "w", encoding="utf-8") as f:
            f.write(texto)
        print("Salvo em: texto_norma.txt")
    else:
        print("\nFALHOU: a função retornou None. Veja as mensagens [ERRO] acima.")"""