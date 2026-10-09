#!/usr/bin/env python3
"""
bpp_public_ffd.py
SME0110 - Programacao Matematica (ICMC/USP)

Heuristica construtiva FFD-RBC-EQ (First-Fit Decreasing com Razao Beneficio-Custo
Equitativa), secao 3.3 do relatorio. Nao depende de solver (so biblioteca padrao).

Mesmo gerador de instancias e mesmo formato de saida dos scripts SCIP e Gurobi
(mesma seed => mesma instancia), para comparacao direta.

Algoritmo
  1. Pre-ordenacao equitativa (Eq. 15):
        r_i = (p_i + mu * sum_{g in G_vulner} w_g * p_i^g) / c_i      (decrescente)
  2. Alocacao gulosa first-fit: cada projeto vai para o primeiro periodo j em que
     (i) ha folga orcamentaria (5), (ii) valem precedencia (7) e incompatibilidade (8)
     e (iii) o teto de concentracao (10) nao e violado.
     Obs.: alocar um projeto nunca viola a meta minima (9), que e acumulada e so
     cresce; por isso o teste (iii) usa (10), e as metas (9)/(11) sao tratadas na
     fase de reparo. Varreduras repetidas deixam entrar projetos cujo predecessor
     so foi alocado depois na ordem.
  3. Reparo (busca local), enquanto houver meta (9) ou (11) em deficit: tenta,
     nesta ordem, (a) inserir projeto que beneficie o grupo deficitario, (b) mover
     para periodo anterior um projeto ja alocado, (d) permutar os periodos de dois
     projetos ja alocados, (c) trocar um projeto de baixa razao equitativa por
     outro que beneficie o grupo. Um movimento so e aceito se
     reduzir o deficit total normalizado. Ao final, uma varredura gulosa preenche
     eventuais folgas.

Uso:
  python bpp_public_ffd.py                              # n=20, cenario forte
  python bpp_public_ffd.py --n 100 --cenario moderada
  python bpp_public_ffd.py --mu 0                       # FFD-RBC classica
  python bpp_public_ffd.py --varrer-mu                  # testa varios mu e escolhe o melhor
  python bpp_public_ffd.py --sem-reparo                 # so a fase gulosa (ablation)
  python bpp_public_ffd.py --reinicios 200              # reinicios aleatorios (metas apertadas)
  python bpp_public_ffd.py --instancia inst.json
  python bpp_public_ffd.py --ref-resultado res_gurobi.json   # gaps vs exato
  python bpp_public_ffd.py --benchmark
"""

import argparse
import json
import random
import time

TOL = 1e-6
EPS_MELHORA = 1e-9
GRUPOS = ["indigenas", "mulheres", "rurais"]
GRUPOS_VULNER = ["indigenas", "rurais"]
PESOS = {"indigenas": 1.5, "rurais": 1.0}   # w_g
THETA = 0.5                                  # limiar de pertencimento (Eq. 10)
PAR_INTERSEC = ("indigenas", "mulheres")     # grupo composto da Eq. (11)
MUS_VARREDURA = [0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0]

CENARIOS = {
    "forte":    {"frac_alvo": 0.30, "frac_max": 0.50, "frac_inter": 0.15},
    "moderada": {"frac_alvo": 0.15, "frac_max": 0.70, "frac_inter": 0.08},
}


# ----------------------------------------------------------------------------
# 1. Instancia (identica aos scripts SCIP/Gurobi: mesma seed => mesma instancia)
# ----------------------------------------------------------------------------
def _cota_fracionaria(valores, custos, orcamento):
    ordem = sorted(range(len(custos)), key=lambda i: -valores[i] / custos[i])
    total, resto = 0.0, orcamento
    for i in ordem:
        if resto <= 0:
            break
        f = min(1.0, resto / custos[i])
        total += f * valores[i]
        resto -= f * custos[i]
    return total


def gerar_instancia(n, m=5, cenario="forte", seed=0):
    rng = random.Random(seed)
    cen = CENARIOS[cenario]
    I, J = list(range(n)), list(range(m))

    c = [rng.randint(100, 1000) for _ in I]
    p = [rng.randint(1000, 10000) for _ in I]

    alpha = {}
    for g in GRUPOS:
        alpha[g] = [round(rng.uniform(0.5, 1.0), 2) if rng.random() < 0.35
                    else round(rng.uniform(0.0, 0.4), 2) for _ in I]
    pg = {g: [round(alpha[g][i] * p[i]) for i in I] for g in GRUPOS}

    B_val = max(0.5 * sum(c) / m, 1.2 * max(c))
    B = [round(B_val)] * m

    alvo = {g: [] for g in GRUPOS}
    for g in GRUPOS:
        for j in J:
            cota = _cota_fracionaria(pg[g], c, sum(B[: j + 1]))
            alvo[g].append(round(cen["frac_alvo"] * cota))
    max_aloc = {g: [round(cen["frac_max"] * B[j]) for j in J] for g in GRUPOS}

    k = max(1, n // 10)
    prec, usados = [], set()
    while len(prec) < k:
        i1, i2 = sorted(rng.sample(I, 2))
        if i2 not in usados:
            usados.add(i2)
            prec.append((i1, i2))
    conf = []
    while len(conf) < k:
        a, b = sorted(rng.sample(I, 2))
        if (a, b) not in conf:
            conf.append((a, b))

    g1, g2 = PAR_INTERSEC
    coef = [min(alpha[g1][i], alpha[g2][i]) * p[i] for i in I]
    alvo_inter = round(cen["frac_inter"] * _cota_fracionaria(coef, c, sum(B)))

    return {
        "n": n, "m": m, "cenario": cenario, "seed": seed,
        "c": c, "p": p, "pg": pg, "alpha": alpha, "B": B,
        "alvo": alvo, "max_aloc": max_aloc,
        "prec": prec, "conf": conf,
        "alvo_inter": alvo_inter,
    }


def salvar_instancia(inst, caminho):
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(inst, f, ensure_ascii=False, indent=1)


def carregar_instancia(caminho):
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def coef_intersec(inst, modelo):
    g1, g2 = PAR_INTERSEC
    a1, a2, p = inst["alpha"][g1], inst["alpha"][g2], inst["p"]
    I = range(inst["n"])
    if modelo == "fuzzy":
        return [min(a1[i], a2[i]) * p[i] for i in I]
    if modelo == "aditivo":
        return [inst["pg"][g1][i] + inst["pg"][g2][i] for i in I]
    if modelo == "composicao":
        return [a1[i] * a2[i] * p[i] for i in I]
    raise ValueError(modelo)


# ----------------------------------------------------------------------------
# 2. Estado da alocacao (com atualizacao incremental)
# ----------------------------------------------------------------------------
class Estado:
    def __init__(self, inst, coef_inter):
        self.inst = inst
        self.n, self.m = inst["n"], inst["m"]
        self.c, self.p, self.pg = inst["c"], inst["p"], inst["pg"]
        self.B, self.alvo = inst["B"], inst["alvo"]
        self.max_aloc = inst["max_aloc"]
        self.coef = coef_inter                  # None => sem interseccionalidade
        self.alvo_inter = inst["alvo_inter"]
        self.per = [-1] * self.n                # periodo de cada projeto (-1 = fora)
        self.usado = [0] * self.m
        self.ben = {g: [0] * self.m for g in GRUPOS}    # beneficio por periodo
        self.conc = {g: [0] * self.m for g in GRUPOS}   # custo concentrado (Eq. 10)
        self.inter = 0.0
        self.pert = {g: [inst["alpha"][g][i] > THETA for i in range(self.n)]
                     for g in GRUPOS}
        self.pred = {}                          # i2 -> [i1, ...]
        self.dep = {i: [] for i in range(self.n)}   # i1 -> [i2, ...]
        for (i1, i2) in inst["prec"]:
            self.pred.setdefault(i2, []).append(i1)
            self.dep[i1].append(i2)
        self.conf = {i: [] for i in range(self.n)}
        for (a, b) in inst["conf"]:
            self.conf[a].append(b)
            self.conf[b].append(a)

    def pode_colocar(self, i, j):
        if self.per[i] != -1:
            return False
        if self.usado[j] + self.c[i] > self.B[j]:                 # (5)
            return False
        for q in self.pred.get(i, ()):                            # (7)
            if self.per[q] == -1 or self.per[q] > j:
                return False
        for q in self.conf[i]:                                    # (8)
            if self.per[q] == j:
                return False
        for g in GRUPOS:                                          # (10)
            if self.pert[g][i] and self.conc[g][j] + self.c[i] > self.max_aloc[g][j] + TOL:
                return False
        return True

    def colocar(self, i, j):
        self.per[i] = j
        self.usado[j] += self.c[i]
        for g in GRUPOS:
            self.ben[g][j] += self.pg[g][i]
            if self.pert[g][i]:
                self.conc[g][j] += self.c[i]
        if self.coef is not None:
            self.inter += self.coef[i]

    def remover(self, i):
        j = self.per[i]
        self.per[i] = -1
        self.usado[j] -= self.c[i]
        for g in GRUPOS:
            self.ben[g][j] -= self.pg[g][i]
            if self.pert[g][i]:
                self.conc[g][j] -= self.c[i]
        if self.coef is not None:
            self.inter -= self.coef[i]

    def tem_dependentes(self, i):
        return any(self.per[d] != -1 for d in self.dep[i])

    def dependentes_ok(self, i, j):
        """True se mover i para o periodo j nao quebra a precedencia (7) dos seus dependentes."""
        return all(self.per[d] == -1 or self.per[d] >= j for d in self.dep[i])

    def deficits(self):
        """Lista de (deficit relativo, grupo|None, periodo) das metas (9) e (11)."""
        out = []
        for g in GRUPOS:
            acc = 0.0
            for j in range(self.m):
                acc += self.ben[g][j]
                alvo = self.alvo[g][j]
                if alvo > 0 and acc < alvo - TOL:
                    out.append(((alvo - acc) / alvo, g, j))
        if self.coef is not None and self.alvo_inter > 0 and self.inter < self.alvo_inter - TOL:
            out.append(((self.alvo_inter - self.inter) / self.alvo_inter, None, self.m - 1))
        return out

    def shortfall(self):
        s = 0.0
        for g in GRUPOS:
            acc = 0.0
            for j in range(self.m):
                acc += self.ben[g][j]
                alvo = self.alvo[g][j]
                if alvo > 0 and acc < alvo - TOL:
                    s += (alvo - acc) / alvo
        if self.coef is not None and self.alvo_inter > 0 and self.inter < self.alvo_inter - TOL:
            s += (self.alvo_inter - self.inter) / self.alvo_inter
        return s


# ----------------------------------------------------------------------------
# 3. Heuristica FFD-RBC-EQ
# ----------------------------------------------------------------------------
def razao_eq(inst, mu):
    """Eq. (15): razao beneficio-custo ponderada por equidade."""
    c, p, pg = inst["c"], inst["p"], inst["pg"]
    return [(p[i] + mu * sum(PESOS[g] * pg[g][i] for g in GRUPOS_VULNER)) / c[i]
            for i in range(inst["n"])]


def guloso(st, ordem):
    """First-fit na ordem dada; repete a varredura enquanto algo entrar."""
    mudou = True
    while mudou:
        mudou = False
        for i in ordem:
            if st.per[i] != -1:
                continue
            for j in range(st.m):
                if st.pode_colocar(i, j):
                    st.colocar(i, j)
                    mudou = True
                    break


def _tentar_melhorar(st, g, j, K):
    """Um movimento que reduza o deficit total, mirando a meta (g, ate o periodo j).
    g=None => meta de interseccionalidade (11). Retorna True se aplicou um movimento."""
    n, c = st.n, st.c
    val = st.pg[g] if g is not None else st.coef
    base = st.shortfall()

    nao_aloc = [i for i in range(n) if st.per[i] == -1 and val[i] > 0]
    nao_aloc.sort(key=lambda i: -val[i] / c[i])
    nao_aloc = nao_aloc[:K]
    aloc = [i for i in range(n) if st.per[i] != -1]

    # (a) inserir projeto que beneficie o grupo deficitario
    for i in nao_aloc:
        for k in range(j + 1):
            if st.pode_colocar(i, k):
                st.colocar(i, k)
                if st.shortfall() < base - EPS_MELHORA:
                    return True
                st.remover(i)

    # (b) mover um projeto alocado para um periodo anterior
    mover = [r for r in aloc if st.per[r] > 0 and val[r] > 0]
    mover.sort(key=lambda r: -val[r] / c[r])
    for r in mover[:K]:
        kr = st.per[r]
        st.remover(r)
        for k in range(min(kr, j + 1)):
            if st.pode_colocar(r, k):
                st.colocar(r, k)
                if st.shortfall() < base - EPS_MELHORA:
                    return True
                st.remover(r)
        st.colocar(r, kr)

    # (d) permutar os periodos de dois projetos ja alocados: o que beneficia o
    #     grupo vai para um periodo anterior e o de menor beneficio vai para o posterior
    cedo = sorted(aloc, key=lambda s: val[s] / c[s])[:K]
    for r in mover[:K]:
        kr = st.per[r]
        for s in cedo:
            ks = st.per[s]
            if s == r or ks >= kr or ks > j:
                continue
            st.remover(r)
            st.remover(s)
            if st.pode_colocar(r, ks) and st.dependentes_ok(s, kr):
                st.colocar(r, ks)
                if st.pode_colocar(s, kr):
                    st.colocar(s, kr)
                    if st.shortfall() < base - EPS_MELHORA:
                        return True
                    st.remover(s)
                st.remover(r)
            st.colocar(s, ks)
            st.colocar(r, kr)

    # (c) trocar: desalocar projeto de baixa razao equitativa (sem dependentes
    #     alocados) e inserir outro que beneficie o grupo
    sair = [r for r in aloc if not st.tem_dependentes(r)]
    sair.sort(key=lambda r: val[r] / c[r])
    for r in sair[:K]:
        kr = st.per[r]
        st.remover(r)
        for i in nao_aloc:
            for k in range(j + 1):
                if st.pode_colocar(i, k):
                    st.colocar(i, k)
                    if st.shortfall() < base - EPS_MELHORA:
                        return True
                    st.remover(i)
        st.colocar(r, kr)
    return False


def reparar(st, k_cand=25, max_iter=2000):
    """Busca local sobre os deficits de meta. Retorna (iteracoes, movimentos)."""
    movimentos = 0
    it = 0
    while it < max_iter:
        it += 1
        deficits = st.deficits()
        if not deficits:
            break
        deficits.sort(reverse=True)            # pior deficit relativo primeiro
        melhorou = False
        for _, g, j in deficits:
            if _tentar_melhorar(st, g, j, k_cand):
                melhorou = True
                movimentos += 1
                break
        if not melhorou:
            break
    return it, movimentos


def verificar_estrutura(inst, aloc):
    """Confere (5)-(8) de forma independente da heuristica. Retorna lista de problemas."""
    c, B = inst["c"], inst["B"]
    per, probs = {}, []
    for (i, j) in aloc:
        if i in per:
            probs.append(("unicidade", i))
        per[i] = j
    usado = [0] * inst["m"]
    for i, j in per.items():
        usado[j] += c[i]
    for j in range(inst["m"]):
        if usado[j] > B[j]:
            probs.append(("capacidade", j, usado[j], B[j]))
    for (i1, i2) in inst["prec"]:
        if i2 in per and (i1 not in per or per[i1] > per[i2]):
            probs.append(("precedencia", i1, i2))
    for (a, b) in inst["conf"]:
        if a in per and b in per and per[a] == per[b]:
            probs.append(("conflito", a, b))
    return probs


def avaliar(inst, aloc):
    """Calcula Z1, Z2, Z3 e verifica metas (9) e (10) (igual aos scripts SCIP/Gurobi)."""
    m = inst["m"]
    c, p, pg, alpha, B = inst["c"], inst["p"], inst["pg"], inst["alpha"], inst["B"]
    por_per = [[i for (i, jj) in aloc if jj == j] for j in range(m)]
    usado = [sum(c[i] for i in por_per[j]) for j in range(m)]

    Z1 = sum(PESOS[g] * pg[g][i] for g in GRUPOS_VULNER for (i, _) in aloc)
    Z2 = sum(p[i] for (i, _) in aloc)
    Z3 = sum(B[j] for j in range(m) if por_per[j]) - sum(usado)

    viol_meta, viol_max = [], []
    for g in GRUPOS:
        for j in range(m):
            ating = sum(pg[g][i] for (i, jj) in aloc if jj <= j)
            if ating < inst["alvo"][g][j] - TOL:
                viol_meta.append((g, j, ating, inst["alvo"][g][j]))
            conc = sum(c[i] for i in por_per[j] if alpha[g][i] > THETA)
            if conc > inst["max_aloc"][g][j] + TOL:
                viol_max.append((g, j, conc, inst["max_aloc"][g][j]))
    return {"Z1": Z1, "Z2": Z2, "Z3": Z3, "usado": usado,
            "n_alocados": len(aloc),
            "viol_meta": viol_meta, "viol_max": viol_max}


def resolver_ffd(inst, mu=1.0, reparo=True, k_cand=25, max_iter=2000,
                 modelo_inter="fuzzy", ruido=0.0, rng=None):
    """ruido>0 perturba a razao r_i em +-ruido/2 (relativo): usado nos reinicios."""
    t0 = time.time()
    coef = None if modelo_inter == "nenhum" else coef_intersec(inst, modelo_inter)
    st = Estado(inst, coef)
    r = razao_eq(inst, mu)
    if ruido > 0 and rng is not None:
        r = [v * (1.0 + ruido * (rng.random() - 0.5)) for v in r]
    ordem = sorted(range(inst["n"]), key=lambda i: (-r[i], i))

    guloso(st, ordem)
    info = {"mu": mu, "deficit_guloso": st.shortfall(),
            "n_guloso": sum(1 for q in st.per if q != -1),
            "iter_reparo": 0, "mov_reparo": 0}
    if reparo:
        it, mov = reparar(st, k_cand, max_iter)
        guloso(st, ordem)                      # preenche folgas liberadas
        info["iter_reparo"], info["mov_reparo"] = it, mov

    aloc = {(i, st.per[i]) for i in range(inst["n"]) if st.per[i] != -1}
    mt = avaliar(inst, aloc)
    inter_ok = True
    ating_inter = None
    if coef is not None:
        ating_inter = sum(coef[i] for (i, _) in aloc)
        inter_ok = ating_inter >= inst["alvo_inter"] - TOL
    conforme = not mt["viol_meta"] and not mt["viol_max"] and inter_ok
    return {
        "status": "conforme" if conforme else "nao_conforme",
        "tempo": time.time() - t0,
        "alocacao": sorted(aloc),
        "metricas": mt,
        "estrutura": verificar_estrutura(inst, aloc),
        "inter": {"atingido": ating_inter, "meta": inst["alvo_inter"], "ok": inter_ok,
                  "modelo": modelo_inter},
        "heuristica": info,
    }


def _chave(res):
    mt = res["metricas"]
    nviol = len(mt["viol_meta"]) + len(mt["viol_max"]) + (0 if res["inter"]["ok"] else 1)
    return (nviol, -mt["Z1"], -mt["Z2"], mt["Z3"])


def resolver_multi(inst, mus, reinicios=0, ruido=0.3, seed=0, reparo=True,
                   k_cand=25, max_iter=2000, modelo_inter="fuzzy"):
    """Para cada mu: 1 execucao deterministica + `reinicios` com ordenacao perturbada.
    Fica com a melhor (menos violacoes, depois maior Z1, Z2 e menor Z3)."""
    t0 = time.time()
    rng = random.Random(seed)
    candidatos, resumo = [], []
    for mu in mus:
        melhor_mu = None
        for t in range(reinicios + 1):
            res = resolver_ffd(inst, mu, reparo, k_cand, max_iter, modelo_inter,
                               ruido=(ruido if t > 0 else 0.0), rng=rng)
            res["heuristica"]["reinicio"] = t
            if melhor_mu is None or _chave(res) < _chave(melhor_mu):
                melhor_mu = res
        candidatos.append(melhor_mu)
        mt = melhor_mu["metricas"]
        resumo.append({"mu": mu, "status": melhor_mu["status"], "Z1": mt["Z1"],
                       "Z2": mt["Z2"], "Z3": mt["Z3"],
                       "viol": _chave(melhor_mu)[0], "reinicio": melhor_mu["heuristica"]["reinicio"]})
    melhor = dict(min(candidatos, key=_chave))
    melhor["heuristica"] = dict(melhor["heuristica"])
    melhor["heuristica"]["reinicios_total"] = reinicios
    if len(mus) > 1:
        melhor["varredura"] = resumo
    melhor["tempo"] = time.time() - t0
    return melhor


# ----------------------------------------------------------------------------
# 4. Relatorios
# ----------------------------------------------------------------------------
def imprimir_resultado(inst, res, titulo):
    print(f"\n=== {titulo} ===")
    print(f"Instancia: n={inst['n']}, m={inst['m']}, cenario={inst['cenario']}, seed={inst['seed']}")
    print(f"Status final: {res['status']} | tempo total: {res['tempo']:.3f}s")
    h = res["heuristica"]
    print(f"  mu={h['mu']} | guloso: {h['n_guloso']} projetos, deficit={h['deficit_guloso']:.3e} "
          f"| reparo: {h['mov_reparo']} movimentos em {h['iter_reparo']} iteracoes")
    if h.get("reinicios_total"):
        print(f"  reinicios: {h['reinicios_total']} por mu | melhor solucao no reinicio #{h.get('reinicio', 0)}")
    for v in res.get("varredura", []):
        print(f"    mu={v['mu']:<4} {v['status']:>12}  Z1={v['Z1']:.0f} Z2={v['Z2']:.0f} "
              f"Z3={v['Z3']:.0f} viol={v['viol']}")
    mt = res["metricas"]
    print(f"  Z1 (equidade ponderada) = {mt['Z1']:.2f}")
    print(f"  Z2 (impacto geral)      = {mt['Z2']:.2f}")
    print(f"  Z3 (desperdicio)        = {mt['Z3']:.2f}")
    print(f"  Projetos financiados: {mt['n_alocados']}/{inst['n']}")
    print(f"  Orcamento usado por periodo: {[round(u) for u in mt['usado']]} (tetos {inst['B']})")
    print(f"  Violacoes meta (9): {len(mt['viol_meta'])} | violacoes teto (10): {len(mt['viol_max'])}")
    it = res["inter"]
    if it["atingido"] is not None:
        print(f"  Interseccionalidade (11, {it['modelo']}): {it['atingido']:.0f} / meta {it['meta']} "
              f"({'ok' if it['ok'] else 'VIOLA'})")
    print(f"  Restricoes estruturais (5)-(8): {'ok' if not res['estrutura'] else res['estrutura']}")
    if inst["n"] <= 30:
        for j in range(inst["m"]):
            projs = sorted(i for (i, jj) in res["alocacao"] if jj == j)
            print(f"    periodo {j}: projetos {projs}")


def comparar_referencia(res, ref):
    """Gaps da heuristica em relacao a uma solucao exata de referencia."""
    mt = res["metricas"]
    print("  --- vs referencia exata ---")
    if ref.get("Z1"):
        print(f"  gap de equidade   (Z1): {(ref['Z1'] - mt['Z1']) / ref['Z1']:+.3%}")
    if ref.get("Z2"):
        print(f"  gap de eficiencia (Z2): {(ref['Z2'] - mt['Z2']) / ref['Z2']:+.3%}")
    if ref.get("Z3") is not None:
        print(f"  diferenca de desperdicio (Z3 heur - exato): {mt['Z3'] - ref['Z3']:+.2f}")


def benchmark(args):
    print("\n=== Benchmark FFD-RBC-EQ ===")
    print(f"{'n':>5} {'cenario':>9} {'status':>13} {'tempo(s)':>9} {'Z1':>12} {'Z2':>12} "
          f"{'Z3':>9} {'viol':>5}")
    for n in (20, 100, 500):
        for cen in ("forte", "moderada"):
            inst = gerar_instancia(n, args.m, cen, args.seed)
            res = resolver_multi(inst, MUS_VARREDURA if args.varrer_mu else [args.mu],
                                 args.reinicios, args.ruido, args.seed, not args.sem_reparo,
                                 args.k_cand, args.max_iter, args.modelo_inter)
            imprimir_resultado(inst, res, "")


# ----------------------------------------------------------------------------
# 5. Main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="PPA com equidade - heuristica FFD-RBC-EQ")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--m", type=int, default=5)
    ap.add_argument("--cenario", choices=list(CENARIOS), default="forte")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--mu", type=float, default=1.0, help="peso de equidade na Eq. (15)")
    ap.add_argument("--varrer-mu", action="store_true",
                    help=f"testa mu em {MUS_VARREDURA} e fica com o melhor")
    ap.add_argument("--reinicios", type=int, default=0,
                    help="reinicios aleatorios (ordenacao perturbada) por mu; 0 = deterministico")
    ap.add_argument("--ruido", type=float, default=0.3, help="amplitude relativa da perturbacao")
    ap.add_argument("--sem-reparo", action="store_true", help="so a fase gulosa")
    ap.add_argument("--k-cand", type=int, default=25, help="candidatos por movimento no reparo")
    ap.add_argument("--max-iter", type=int, default=2000, help="iteracoes maximas do reparo")
    ap.add_argument("--modelo-inter", choices=["fuzzy", "aditivo", "composicao", "nenhum"],
                    default="fuzzy")
    ap.add_argument("--instancia", metavar="ARQ.json")
    ap.add_argument("--salvar-instancia", metavar="ARQ.json")
    ap.add_argument("--salvar-resultado", metavar="ARQ.json")
    ap.add_argument("--ref-resultado", metavar="ARQ.json",
                    help="resultado do Gurobi (--salvar-resultado) para calcular gaps")
    ap.add_argument("--ref-z1", type=float)
    ap.add_argument("--ref-z2", type=float)
    ap.add_argument("--ref-z3", type=float)
    ap.add_argument("--benchmark", action="store_true")
    args = ap.parse_args()

    if args.benchmark:
        benchmark(args)
        return

    inst = carregar_instancia(args.instancia) if args.instancia else \
        gerar_instancia(args.n, args.m, args.cenario, args.seed)
    if args.salvar_instancia:
        salvar_instancia(inst, args.salvar_instancia)
        print(f"Instancia salva em {args.salvar_instancia}")

    res = resolver_multi(inst, MUS_VARREDURA if args.varrer_mu else [args.mu],
                         args.reinicios, args.ruido, args.seed, not args.sem_reparo,
                         args.k_cand, args.max_iter, args.modelo_inter)
    imprimir_resultado(inst, res, "FFD-RBC-EQ (heuristica)")

    ref = None
    if args.ref_resultado:
        with open(args.ref_resultado, encoding="utf-8") as f:
            mt = json.load(f)["metricas"]
        ref = {"Z1": mt["Z1"], "Z2": mt["Z2"], "Z3": mt["Z3"]}
    elif args.ref_z1 is not None or args.ref_z2 is not None or args.ref_z3 is not None:
        ref = {"Z1": args.ref_z1, "Z2": args.ref_z2, "Z3": args.ref_z3}
    if ref:
        comparar_referencia(res, ref)

    if args.salvar_resultado:
        with open(args.salvar_resultado, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1, default=str)
        print(f"Resultado salvo em {args.salvar_resultado}")


if __name__ == "__main__":
    main()