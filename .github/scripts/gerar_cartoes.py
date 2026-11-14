"""Gera os cartões de estatísticas do perfil (SVG) com dados do GitHub.

Roda no GitHub Actions (workflow cartoes.yml) e grava em assets/:
  estatisticas.svg · linguagens.svg · sequencia.svg

Usa a API GraphQL com o token do Actions. Se a parte de contribuições
não estiver disponível para o token, conta os commits pela API REST.
Para testar sem internet: DADOS_TESTE=1 python .github/scripts/gerar_cartoes.py
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from html import escape
from pathlib import Path

USUARIO = os.environ.get("USUARIO", "novaishenrique")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
SAIDA = Path(__file__).resolve().parents[2] / "assets"
HOJE = dt.datetime.now(dt.timezone.utc).date()

# Tema: mesmo céu do banner
FUNDO, BORDA = "#1a1b2e", "#3b2f5c"
TITULO, TEXTO, DESTAQUE, ANEL = "#ff8fb1", "#e6e1f5", "#ffd27a", "#ff6e96"
FONTE = "'Segoe UI', Ubuntu, 'Helvetica Neue', sans-serif"

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


# ---------------------------------------------------------------- API
def requisitar(url, corpo=None):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "cartoes-do-perfil",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def graphql(consulta, variaveis):
    resp = requisitar("https://api.github.com/graphql", {"query": consulta, "variables": variaveis})
    if resp.get("errors"):
        raise RuntimeError(resp["errors"][0].get("message", "erro no GraphQL"))
    return resp["data"]


CONSULTA_PERFIL = """
query($login: String!) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    repositoriesContributedTo(contributionTypes: [COMMIT, PULL_REQUEST, ISSUE, REPOSITORY]) { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      totalCount
      nodes {
        name
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}"""

CONSULTA_ANO = """
query($login: String!, $de: DateTime!, $ate: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $de, to: $ate) {
      totalCommitContributions
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    }
  }
}"""


def contribuicoes_graphql(criado_em):
    """Dias com contribuições e total de commits, ano a ano desde a criação da conta."""
    dias, commits = {}, 0
    inicio = criado_em
    while inicio <= HOJE:
        fim = min(dt.date(inicio.year, 12, 31), HOJE)
        dado = graphql(CONSULTA_ANO, {
            "login": USUARIO,
            "de": f"{inicio.isoformat()}T00:00:00Z",
            "ate": f"{fim.isoformat()}T23:59:59Z",
        })["user"]["contributionsCollection"]
        commits += dado["totalCommitContributions"]
        for semana in dado["contributionCalendar"]["weeks"]:
            for dia in semana["contributionDays"]:
                data = dt.date.fromisoformat(dia["date"])
                if inicio <= data <= HOJE:
                    dias[data] = dias.get(data, 0) + dia["contributionCount"]
        inicio = dt.date(inicio.year + 1, 1, 1)
    return dias, commits


def contribuicoes_rest(repos):
    """Alternativa: conta os commits do usuário nos próprios repositórios públicos."""
    dias, commits = {}, 0
    for nome in repos:
        pagina = 1
        while True:
            url = (f"https://api.github.com/repos/{USUARIO}/{nome}/commits"
                   f"?author={USUARIO}&per_page=100&page={pagina}")
            try:
                lista = requisitar(url)
            except Exception:
                break
            if not lista:
                break
            for item in lista:
                data = dt.date.fromisoformat(item["commit"]["author"]["date"][:10])
                dias[data] = dias.get(data, 0) + 1
                commits += 1
            pagina += 1
    return dias, commits


def coletar():
    perfil = graphql(CONSULTA_PERFIL, {"login": USUARIO})["user"]
    criado_em = dt.date.fromisoformat(perfil["createdAt"][:10])
    repos = perfil["repositories"]["nodes"]

    linguagens = {}
    for repo in repos:
        for borda in repo["languages"]["edges"]:
            nome = borda["node"]["name"]
            cor = borda["node"]["color"] or "#9aa0b4"
            tamanho, _ = linguagens.get(nome, (0, cor))
            linguagens[nome] = (tamanho + borda["size"], cor)

    try:
        dias, commits = contribuicoes_graphql(criado_em)
        fonte = "GraphQL"
    except Exception as erro:
        print("Contribuições pelo GraphQL indisponíveis:", erro, "- usando a API REST")
        dias, commits = contribuicoes_rest([r["name"] for r in repos])
        fonte = "REST"

    return {
        "repos": perfil["repositories"]["totalCount"],
        "estrelas": sum(r["stargazerCount"] for r in repos),
        "seguidores": perfil["followers"]["totalCount"],
        "prs": perfil["pullRequests"]["totalCount"],
        "issues": perfil["issues"]["totalCount"],
        "contribuiu": perfil["repositoriesContributedTo"]["totalCount"],
        "commits": commits,
        "dias": dias,
        "linguagens": linguagens,
        "fonte": fonte,
    }


def dados_de_teste():
    dias = {HOJE - dt.timedelta(days=i): (i % 3) + 1 for i in range(0, 9)}
    dias.update({HOJE - dt.timedelta(days=i): 2 for i in range(20, 32)})
    return {
        "repos": 6, "estrelas": 1, "seguidores": 0, "prs": 3, "issues": 2, "contribuiu": 3,
        "commits": 58, "dias": dias, "fonte": "teste",
        "linguagens": {"HTML": (52000, "#e34c26"), "JavaScript": (31000, "#f1e05a"),
                       "CSS": (18000, "#663399"), "C": (6000, "#555555"), "TSQL": (4000, "#e38c00")},
    }


# ---------------------------------------------------------------- cálculos
def sequencias(dias):
    """Sequência atual (aceita hoje ainda sem contribuição) e maior sequência."""
    ativos = sorted(d for d, n in dias.items() if n > 0)
    maior, maior_ini, maior_fim = 0, None, None
    atual_ini, tamanho, anterior = None, 0, None
    for d in ativos:
        if anterior is not None and (d - anterior).days == 1:
            tamanho += 1
        else:
            tamanho, atual_ini = 1, d
        if tamanho > maior:
            maior, maior_ini, maior_fim = tamanho, atual_ini, d
        anterior = d
    atual, atual_desde = 0, None
    if ativos and (HOJE - ativos[-1]).days <= 1:
        atual, atual_desde = tamanho, atual_ini
    return atual, atual_desde, maior, maior_ini, maior_fim


def data_curta(d):
    return f"{d.day} {MESES[d.month - 1]} {d.year}" if d else "-"


# ---------------------------------------------------------------- SVG
def moldura(largura, altura, titulo, conteudo, rotulo):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{largura}" height="{altura}" viewBox="0 0 {largura} {altura}" role="img" aria-label="{escape(rotulo)}">
  <title>{escape(rotulo)}</title>
  <style>
    .t {{ font: 600 18px {FONTE}; fill: {TITULO}; }}
    .r {{ font: 400 14px {FONTE}; fill: {TEXTO}; }}
    .v {{ font: 700 14px {FONTE}; fill: {DESTAQUE}; }}
    .n {{ font: 700 28px {FONTE}; fill: {TEXTO}; }}
    .p {{ font: 400 12px {FONTE}; fill: {TEXTO}; opacity: .75; }}
    .a {{ animation: surgir .8s ease-out both; }}
    @keyframes surgir {{ from {{ opacity: 0 }} to {{ opacity: 1 }} }}
  </style>
  <rect x="0.5" y="0.5" width="{largura - 1}" height="{altura - 1}" rx="10" fill="{FUNDO}" stroke="{BORDA}"/>
  <text class="t" x="25" y="35">{escape(titulo)}</text>
{conteudo}
</svg>
"""


def cartao_estatisticas(d):
    linhas = [
        ("Commits", d["commits"]),
        ("Pull requests", d["prs"]),
        ("Issues", d["issues"]),
        ("Repositórios públicos", d["repos"]),
        ("Contribuiu para", d["contribuiu"]),
    ]
    itens = []
    for i, (rotulo, valor) in enumerate(linhas):
        y = 70 + i * 25
        itens.append(f'  <g class="a" style="animation-delay:{i * 0.12:.2f}s">'
                     f'<circle cx="32" cy="{y - 5}" r="4" fill="{ANEL}"/>'
                     f'<text class="r" x="45" y="{y}">{escape(rotulo)}:</text>'
                     f'<text class="v" x="230" y="{y}">{valor}</text></g>')
    total = sum(d["dias"].values())
    circ = 2 * 3.14159 * 40
    itens.append(f"""  <g transform="translate(395 105)">
    <circle r="40" fill="none" stroke="{BORDA}" stroke-width="6"/>
    <circle r="40" fill="none" stroke="{ANEL}" stroke-width="6" stroke-linecap="round" stroke-dasharray="{circ:.1f}" stroke-dashoffset="{circ * 0.25:.1f}" transform="rotate(-90)"/>
    <text class="n" text-anchor="middle" y="9">{total}</text>
    <text class="p" text-anchor="middle" y="62">contribuições</text>
  </g>""")
    return moldura(495, 195, "Estatísticas no GitHub", "\n".join(itens),
                   f"Estatísticas de {USUARIO}: {d['commits']} commits, {d['repos']} repositórios públicos")


def cartao_linguagens(d):
    ordenadas = sorted(d["linguagens"].items(), key=lambda kv: kv[1][0], reverse=True)[:6]
    total = sum(t for _, (t, _) in ordenadas) or 1
    partes, x = [], 25
    largura_barra = 300
    for nome, (tam, cor) in ordenadas:
        w = largura_barra * tam / total
        partes.append(f'  <rect x="{x:.1f}" y="52" width="{w:.1f}" height="10" fill="{cor}"/>')
        x += w
    barra = (f'  <clipPath id="c"><rect x="25" y="52" width="{largura_barra}" height="10" rx="5"/></clipPath>\n'
             f'  <g clip-path="url(#c)">\n' + "\n".join(partes) + "\n  </g>")
    legenda = []
    for i, (nome, (tam, cor)) in enumerate(ordenadas):
        col, lin = i % 2, i // 2
        cx, cy = 30 + col * 150, 92 + lin * 28
        legenda.append(f'  <g class="a" style="animation-delay:{i * 0.12:.2f}s"><circle cx="{cx}" cy="{cy - 4}" r="5" fill="{cor}"/>'
                       f'<text class="r" x="{cx + 12}" y="{cy}">{escape(nome)} <tspan class="p">{100 * tam / total:.1f}%</tspan></text></g>')
    if not ordenadas:
        legenda.append('  <text class="r" x="25" y="95">Ainda sem linguagens detectadas</text>')
    return moldura(350, 195, "Linguagens mais usadas", barra + "\n" + "\n".join(legenda),
                   "Linguagens mais usadas nos repositórios públicos")


def cartao_sequencia(d):
    atual, desde, maior, ini, fim = sequencias(d["dias"])
    total = sum(d["dias"].values())
    primeiro = min((x for x, n in d["dias"].items() if n > 0), default=None)
    circ = 2 * 3.14159 * 38
    conteudo = f"""  <line x1="165" y1="55" x2="165" y2="175" stroke="{BORDA}"/>
  <line x1="330" y1="55" x2="330" y2="175" stroke="{BORDA}"/>
  <g class="a" text-anchor="middle">
    <text class="n" x="82" y="110">{total}</text>
    <text class="r" x="82" y="138">Contribuições</text>
    <text class="p" x="82" y="158">desde {data_curta(primeiro)}</text>
  </g>
  <g class="a" style="animation-delay:.2s" transform="translate(247 100)" text-anchor="middle">
    <circle r="38" fill="none" stroke="{BORDA}" stroke-width="5"/>
    <circle r="38" fill="none" stroke="{ANEL}" stroke-width="5" stroke-linecap="round" stroke-dasharray="{circ:.1f}" stroke-dashoffset="{circ * (0 if atual else 1):.1f}" transform="rotate(-90)"/>
    <text class="n" y="10">{atual}</text>
    <text class="r" y="62" style="fill:{DESTAQUE};font-weight:700">Sequência atual</text>
    <text class="p" y="80">{"desde " + data_curta(desde) if desde else "comece hoje"}</text>
  </g>
  <g class="a" style="animation-delay:.4s" text-anchor="middle">
    <text class="n" x="412" y="110">{maior}</text>
    <text class="r" x="412" y="138">Maior sequência</text>
    <text class="p" x="412" y="158">{data_curta(ini) + " – " + data_curta(fim) if ini else "-"}</text>
  </g>"""
    return moldura(495, 195, "Dias seguidos de contribuição", conteudo,
                   f"Sequência atual de {atual} dias e maior sequência de {maior} dias")


def main():
    if os.environ.get("DADOS_TESTE"):
        dados = dados_de_teste()
    else:
        if not TOKEN:
            sys.exit("Defina GITHUB_TOKEN")
        dados = coletar()
    SAIDA.mkdir(exist_ok=True)
    (SAIDA / "estatisticas.svg").write_text(cartao_estatisticas(dados), encoding="utf-8")
    (SAIDA / "linguagens.svg").write_text(cartao_linguagens(dados), encoding="utf-8")
    (SAIDA / "sequencia.svg").write_text(cartao_sequencia(dados), encoding="utf-8")
    print(f"Cartões gerados ({dados['fonte']}): {dados['commits']} commits, "
          f"{sum(dados['dias'].values())} contribuições, {len(dados['linguagens'])} linguagens")


if __name__ == "__main__":
    main()
