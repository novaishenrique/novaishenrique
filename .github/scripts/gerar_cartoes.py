"""Gera os cartões de estatísticas do perfil (SVG) com dados do GitHub.

Roda no GitHub Actions (workflow cartoes.yml) e grava em assets/:
  estatisticas.svg · sequencia.svg · grafico.svg · linguagens.svg

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

# Tema preto e branco, igual ao banner
FUNDO, BORDA, LINHA = "#000000", "#e4e2e2", "#3a3a3a"
TITULO, TEXTO, DESTAQUE, ANEL = "#ffffff", "#d9d9d9", "#ffffff", "#ffffff"
CINZAS = ["#ffffff", "#c9c9c9", "#9a9a9a", "#747474", "#555555", "#3d3d3d"]
NOME = os.environ.get("NOME", "Henrique")
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
    dias, commits, commits_ano = {}, 0, 0
    inicio = criado_em
    while inicio <= HOJE:
        fim = min(dt.date(inicio.year, 12, 31), HOJE)
        dado = graphql(CONSULTA_ANO, {
            "login": USUARIO,
            "de": f"{inicio.isoformat()}T00:00:00Z",
            "ate": f"{fim.isoformat()}T23:59:59Z",
        })["user"]["contributionsCollection"]
        commits += dado["totalCommitContributions"]
        if inicio.year == HOJE.year:
            commits_ano = dado["totalCommitContributions"]
        for semana in dado["contributionCalendar"]["weeks"]:
            for dia in semana["contributionDays"]:
                data = dt.date.fromisoformat(dia["date"])
                if inicio <= data <= HOJE:
                    dias[data] = dias.get(data, 0) + dia["contributionCount"]
        inicio = dt.date(inicio.year + 1, 1, 1)
    return dias, commits, commits_ano


def contribuicoes_rest(repos):
    """Alternativa: conta os commits do usuário nos próprios repositórios públicos."""
    dias, commits, commits_ano = {}, 0, 0
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
                commits_ano += data.year == HOJE.year
            pagina += 1
    return dias, commits, commits_ano


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
        dias, commits, commits_ano = contribuicoes_graphql(criado_em)
        fonte = "GraphQL"
    except Exception as erro:
        print("Contribuições pelo GraphQL indisponíveis:", erro, "- usando a API REST")
        dias, commits, commits_ano = contribuicoes_rest([r["name"] for r in repos])
        fonte = "REST"

    return {
        "repos": perfil["repositories"]["totalCount"],
        "estrelas": sum(r["stargazerCount"] for r in repos),
        "seguidores": perfil["followers"]["totalCount"],
        "prs": perfil["pullRequests"]["totalCount"],
        "issues": perfil["issues"]["totalCount"],
        "contribuiu": perfil["repositoriesContributedTo"]["totalCount"],
        "commits": commits,
        "commits_ano": commits_ano,
        "dias": dias,
        "linguagens": linguagens,
        "fonte": fonte,
    }


def dados_de_teste():
    dias = {HOJE - dt.timedelta(days=i): (i % 3) + 1 for i in range(0, 9)}
    dias.update({HOJE - dt.timedelta(days=i): (i * 7) % 5 for i in range(12, 32)})
    return {
        "repos": 6, "estrelas": 1, "seguidores": 0, "prs": 3, "issues": 2, "contribuiu": 3,
        "commits": 58, "commits_ano": 58, "dias": dias, "fonte": "teste",
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


# ---------------------------------------------------------------- nota (rank)
def nota(d):
    """Nota de A+ a C, com a mesma ideia do github-readme-stats (percentil estimado)."""
    def exp(x):
        return 1 - 2 ** -x

    def lognormal(x):
        return x / (1 + x)

    pesos = [
        (2, exp(d["commits_ano"] / 250)),
        (3, exp(d["prs"] / 50)),
        (1, exp(d["issues"] / 25)),
        (4, lognormal(d["estrelas"] / 50)),
        (1, lognormal(d["seguidores"] / 10)),
    ]
    total = sum(p for p, _ in pesos)
    percentil = 100 * (1 - sum(p * v for p, v in pesos) / total)
    for limite, letra in [(1, "S"), (12.5, "A+"), (25, "A"), (37.5, "A-"), (50, "B+"),
                          (62.5, "B"), (75, "B-"), (87.5, "C+"), (100, "C")]:
        if percentil <= limite:
            return letra, percentil
    return "C", percentil


# ---------------------------------------------------------------- SVG
ICONES = {
    # desenhos simples em 16x16
    "estrela": '<path d="M8 1.5l1.9 4 4.4.5-3.3 3 .9 4.3L8 11.1l-3.9 2.2.9-4.3-3.3-3 4.4-.5z" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>',
    "commit": '<circle cx="8" cy="8" r="3" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M1 8h4M11 8h4" stroke="currentColor" stroke-width="1.4"/>',
    "pr": '<circle cx="4" cy="3.5" r="1.8" fill="none" stroke="currentColor" stroke-width="1.3"/><circle cx="4" cy="12.5" r="1.8" fill="none" stroke="currentColor" stroke-width="1.3"/><circle cx="12" cy="12.5" r="1.8" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M4 5.3v5.4M12 10.7V6.5a2 2 0 0 0-2-2H7.5M9 3l-1.6 1.5L9 6" fill="none" stroke="currentColor" stroke-width="1.3"/>',
    "issue": '<circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="8" cy="8" r="1.4" fill="currentColor"/>',
    "repo": '<path d="M3 2.5h8.5a1 1 0 0 1 1 1V13H4.2A1.2 1.2 0 0 1 3 11.8z M3 11.8a1.2 1.2 0 0 1 1.2-1.2h8.3" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>',
}


def moldura(largura, altura, titulo, conteudo, rotulo, titulo_x=25, ancora="start"):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{largura}" height="{altura}" viewBox="0 0 {largura} {altura}" role="img" aria-label="{escape(rotulo)}">
  <title>{escape(rotulo)}</title>
  <style>
    .t {{ font: 600 18px {FONTE}; fill: {TITULO}; }}
    .r {{ font: 600 14px {FONTE}; fill: {TEXTO}; }}
    .v {{ font: 700 14px {FONTE}; fill: {DESTAQUE}; }}
    .n {{ font: 700 28px {FONTE}; fill: {DESTAQUE}; }}
    .p {{ font: 400 12px {FONTE}; fill: {TEXTO}; opacity: .7; }}
    .x {{ font: 400 11px {FONTE}; fill: {TEXTO}; opacity: .8; }}
    .a {{ animation: surgir .8s ease-out both; }}
    @keyframes surgir {{ from {{ opacity: 0 }} to {{ opacity: 1 }} }}
    .anel {{ animation: encher 1.2s ease-out both; }}
  </style>
  <rect x="0.5" y="0.5" width="{largura - 1}" height="{altura - 1}" rx="6" fill="{FUNDO}" stroke="{BORDA}"/>
  <text class="t" x="{titulo_x}" y="35" text-anchor="{ancora}">{escape(titulo)}</text>
{conteudo}
</svg>
"""


def cartao_estatisticas(d):
    linhas = [
        ("estrela", "Estrelas recebidas", d["estrelas"]),
        ("commit", f"Commits em {HOJE.year}", d["commits_ano"]),
        ("pr", "Pull requests", d["prs"]),
        ("issue", "Issues", d["issues"]),
        ("repo", "Contribuiu para", d["contribuiu"]),
    ]
    itens = []
    for i, (icone, rotulo, valor) in enumerate(linhas):
        y = 72 + i * 25
        itens.append(f'  <g class="a" style="animation-delay:{i * 0.12:.2f}s;color:{TEXTO}">'
                     f'<svg x="25" y="{y - 13}" width="16" height="16" viewBox="0 0 16 16">{ICONES[icone]}</svg>'
                     f'<text class="r" x="50" y="{y}">{escape(rotulo)}:</text>'
                     f'<text class="v" x="265" y="{y}" text-anchor="end">{valor}</text></g>')
    letra, percentil = nota(d)
    circ = 2 * 3.14159 * 40
    preenchido = max(0.04, (100 - percentil) / 100)
    itens.append(f"""  <g transform="translate(385 112)">
    <style>@keyframes encher {{ from {{ stroke-dashoffset: {circ:.1f} }} to {{ stroke-dashoffset: {circ * (1 - preenchido):.1f} }} }}</style>
    <circle r="40" fill="none" stroke="{LINHA}" stroke-width="6"/>
    <circle class="anel" r="40" fill="none" stroke="{ANEL}" stroke-width="6" stroke-linecap="round" stroke-dasharray="{circ:.1f}" stroke-dashoffset="{circ * (1 - preenchido):.1f}" transform="rotate(-90)"/>
    <text class="n" text-anchor="middle" y="10">{letra}</text>
  </g>""")
    return moldura(495, 195, f"Estatísticas do {NOME} no GitHub", "\n".join(itens),
                   f"Estatísticas de {USUARIO}: nota {letra}, {d['commits_ano']} commits em {HOJE.year}")


def cartao_linguagens(d):
    ordenadas = sorted(d["linguagens"].items(), key=lambda kv: kv[1][0], reverse=True)[:6]
    total = sum(t for _, (t, _) in ordenadas) or 1
    partes, x = [], 25
    largura_barra = 300
    for i, (nome, (tam, _)) in enumerate(ordenadas):
        w = largura_barra * tam / total
        partes.append(f'  <rect x="{x:.1f}" y="52" width="{w:.1f}" height="10" fill="{CINZAS[i]}"/>')
        x += w
    barra = (f'  <clipPath id="c"><rect x="25" y="52" width="{largura_barra}" height="10" rx="5"/></clipPath>\n'
             f'  <g clip-path="url(#c)">\n' + "\n".join(partes) + "\n  </g>")
    legenda = []
    for i, (nome, (tam, _)) in enumerate(ordenadas):
        col, lin = i % 2, i // 2
        cx, cy = 30 + col * 150, 92 + lin * 28
        legenda.append(f'  <g class="a" style="animation-delay:{i * 0.12:.2f}s"><circle cx="{cx}" cy="{cy - 4}" r="5" fill="{CINZAS[i]}" stroke="{LINHA}"/>'
                       f'<text class="r" x="{cx + 12}" y="{cy}">{escape(nome)} <tspan class="p">{100 * tam / total:.1f}%</tspan></text></g>')
    if not ordenadas:
        legenda.append('  <text class="r" x="25" y="95">Ainda sem linguagens detectadas</text>')
    return moldura(350, 195, "Linguagens mais usadas", barra + "\n" + "\n".join(legenda),
                   "Linguagens mais usadas nos repositórios públicos")


def cartao_sequencia(d):
    atual, desde, maior, ini, fim = sequencias(d["dias"])
    total = sum(d["dias"].values())
    primeiro = min((x for x, n in d["dias"].items() if n > 0), default=None)
    raio = 38
    circ = 2 * 3.14159 * raio
    abertura = 26  # espaço no topo do anel para a chama
    conteudo = f"""  <line x1="165" y1="28" x2="165" y2="170" stroke="{BORDA}" stroke-opacity=".9"/>
  <line x1="330" y1="28" x2="330" y2="170" stroke="{BORDA}" stroke-opacity=".9"/>
  <g class="a" text-anchor="middle">
    <text class="n" x="82" y="92">{total}</text>
    <text class="r" x="82" y="122">Total de</text>
    <text class="r" x="82" y="139">contribuições</text>
    <text class="p" x="82" y="162">{data_curta(primeiro)} – hoje</text>
  </g>
  <g class="a" style="animation-delay:.2s" transform="translate(247 80)" text-anchor="middle">
    <circle r="{raio}" fill="none" stroke="{ANEL}" stroke-width="5" stroke-dasharray="{circ - abertura:.1f} {abertura}" stroke-dashoffset="{-abertura / 2:.1f}" transform="rotate(-90)"/>
    <path d="M0 -50 C 7 -44 8 -38 4 -33 C 3 -37 1 -38 -1 -39 C 0 -35 -3 -33 -5 -31 C -9 -36 -7 -44 0 -50 Z" fill="{ANEL}"/>
    <text class="n" y="10">{atual}</text>
    <text class="r" y="66" style="fill:{DESTAQUE};font-weight:700">Sequência atual</text>
    <text class="p" y="84">{"desde " + data_curta(desde) if desde else "comece hoje"}</text>
  </g>
  <g class="a" style="animation-delay:.4s" text-anchor="middle">
    <text class="n" x="412" y="92">{maior}</text>
    <text class="r" x="412" y="122">Maior</text>
    <text class="r" x="412" y="139">sequência</text>
    <text class="p" x="412" y="162">{data_curta(ini) + " – " + data_curta(fim) if ini else "-"}</text>
  </g>"""
    return moldura(495, 195, "", conteudo,
                   f"Sequência atual de {atual} dias e maior sequência de {maior} dias")


def curva_monotona(pontos):
    """Caminho suave que não passa abaixo de zero entre os pontos (Fritsch-Carlson)."""
    n = len(pontos)
    if n < 2:
        return ""
    xs = [p[0] for p in pontos]
    ys = [p[1] for p in pontos]
    dx = [xs[i + 1] - xs[i] for i in range(n - 1)]
    m = [(ys[i + 1] - ys[i]) / dx[i] for i in range(n - 1)]
    t = [m[0]] + [0.0] * (n - 2) + [m[-1]]
    for i in range(1, n - 1):
        t[i] = 0.0 if m[i - 1] * m[i] <= 0 else (m[i - 1] + m[i]) / 2
    for i in range(n - 1):
        if m[i] == 0:
            t[i] = t[i + 1] = 0.0
        else:
            a, b = t[i] / m[i], t[i + 1] / m[i]
            s = a * a + b * b
            if s > 9:
                k = 3 / s ** 0.5
                t[i], t[i + 1] = k * a * m[i], k * b * m[i]
    d = f"M{xs[0]:.1f},{ys[0]:.1f}"
    for i in range(n - 1):
        c1 = (xs[i] + dx[i] / 3, ys[i] + t[i] * dx[i] / 3)
        c2 = (xs[i + 1] - dx[i] / 3, ys[i + 1] - t[i + 1] * dx[i] / 3)
        d += f" C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {xs[i + 1]:.1f},{ys[i + 1]:.1f}"
    return d


def cartao_grafico(d, dias_no_grafico=31):
    largura, altura = 1000, 360
    esq, dir_, topo, base = 80, 960, 70, 300
    datas = [HOJE - dt.timedelta(days=i) for i in range(dias_no_grafico - 1, -1, -1)]
    valores = [d["dias"].get(x, 0) for x in datas]
    maximo = max(1, max(valores))
    passo_y = 1 if maximo <= 6 else (2 if maximo <= 12 else 5)
    teto = ((maximo + passo_y - 1) // passo_y) * passo_y
    px = lambda i: esq + (dir_ - esq) * i / (dias_no_grafico - 1)
    py = lambda v: base - (base - topo) * v / teto
    pontos = [(px(i), py(v)) for i, v in enumerate(valores)]
    curva = curva_monotona(pontos)
    area = curva + f" L{pontos[-1][0]:.1f},{base} L{pontos[0][0]:.1f},{base} Z"
    grade = []
    for v in range(0, teto + 1, passo_y):
        y = py(v)
        grade.append(f'  <line x1="{esq}" y1="{y:.1f}" x2="{dir_}" y2="{y:.1f}" stroke="{LINHA}" stroke-opacity=".6"/>'
                     f'<text class="x" x="{esq - 14}" y="{y + 4:.1f}" text-anchor="end">{v}</text>')
    for i, data in enumerate(datas):
        x = px(i)
        grade.append(f'  <line x1="{x:.1f}" y1="{topo}" x2="{x:.1f}" y2="{base}" stroke="{LINHA}" stroke-opacity=".35"/>'
                     f'<text class="x" x="{x:.1f}" y="{base + 22}" text-anchor="middle">{data.day}</text>')
    marcas = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{FUNDO}" stroke="{ANEL}" stroke-width="2"/>'
                     for x, y in pontos)
    conteudo = f"""  <defs>
    <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffffff" stop-opacity=".28"/>
      <stop offset="1" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
    <style>
      .linha {{ stroke-dasharray: 1; stroke-dashoffset: 1; animation: desenhar 2.2s ease-out forwards; }}
      @keyframes desenhar {{ to {{ stroke-dashoffset: 0 }} }}
    </style>
  </defs>
{chr(10).join(grade)}
  <path d="{area}" fill="url(#area)" class="a"/>
  <path class="linha" pathLength="1" d="{curva}" fill="none" stroke="{ANEL}" stroke-width="2.5"/>
  <g class="a" style="animation-delay:1.2s">{marcas}</g>
  <text class="x" x="{(esq + dir_) / 2:.0f}" y="{altura - 18}" text-anchor="middle">Dias ({MESES[datas[0].month - 1]} – {MESES[datas[-1].month - 1]} {datas[-1].year})</text>
  <text class="x" transform="translate(28 {(topo + base) / 2:.0f}) rotate(-90)" text-anchor="middle">Contribuições</text>"""
    return moldura(largura, altura, f"Gráfico de contribuições do {NOME}", conteudo,
                   f"Contribuições por dia nos últimos {dias_no_grafico} dias",
                   titulo_x=largura / 2, ancora="middle")


def main():
    if os.environ.get("DADOS_TESTE"):
        dados = dados_de_teste()
    else:
        if not TOKEN:
            sys.exit("Defina GITHUB_TOKEN")
        dados = coletar()
    SAIDA.mkdir(exist_ok=True)
    (SAIDA / "estatisticas.svg").write_text(cartao_estatisticas(dados), encoding="utf-8")
    (SAIDA / "sequencia.svg").write_text(cartao_sequencia(dados), encoding="utf-8")
    (SAIDA / "grafico.svg").write_text(cartao_grafico(dados), encoding="utf-8")
    (SAIDA / "linguagens.svg").write_text(cartao_linguagens(dados), encoding="utf-8")
    print(f"Cartões gerados ({dados['fonte']}): {dados['commits']} commits, "
          f"{sum(dados['dias'].values())} contribuições, {len(dados['linguagens'])} linguagens, "
          f"nota {nota(dados)[0]}")


if __name__ == "__main__":
    main()
