#!/usr/bin/env python3
"""
bpp_public_scip.py
SME0110 - Programacao Matematica (ICMC/USP)

Otimizacao do Orcamento Publico Plurianual via PLIB (Bin Packing multidimensional
com equidade), resolvida com SCIP (PySCIPOpt).

Implementa:
  - Gerador de instancias sinteticas (n projetos, m periodos, 3 grupos) com
    dois cenarios: "forte" e "moderada" (secao 3.4 do relatorio).
  - Modelo exato: Eqs. (5)-(13) + interseccionalidade (11) em 3 variantes
    (fuzzy / aditivo / composicao), secao 4.1.
  - Resolucao lexicografica em 3 passes (secao 3.2, item 1) e escalarizacao
    (Eq. 14, item 2).
  - Metricas: status, tempo, Z1/Z2/Z3, gap B&B, gap vs relaxacao linear,
    verificacao de conformidade das metas (9), (10), (11).
  - Benchmark n = 20, 100, 500 x dois cenarios.

Uso:
  pip install pyscipopt
  python bpp_public_scip.py                         # n=20, cenario forte
  python bpp_public_scip.py --n 100 --cenario moderada
  python bpp_public_scip.py --modo escalar
  python bpp_public_scip.py --comparar-intersec
  python bpp_public_scip.py --benchmark
  python bpp_public_scip.py --salvar-instancia inst.json   # compartilhar com Gurobi/FFD
"""

import argparse
import json
import random
import time

from pyscipopt import Model, quicksum

TOL = 1e-6
GRUPOS = ["indigenas", "mulheres", "rurais"]
GRUPOS_VULNER = ["indigenas", "rurais"]
PESOS = {"indigenas": 1.5, "rurais": 1.0}   # w_g
THETA = 0.5                                  # limiar de pertencimento (Eq. 10)
PAR_INTERSEC = ("indigenas", "mulheres")     # grupo composto da Eq. (11)

CENARIOS = {
    # frac_alvo: fracao da cota maxima (relaxacao fracionaria) usada como meta
    # frac_max : fracao de B_j permitida a projetos com alpha > theta (Eq. 10)
    "forte":    {"frac_alvo": 0.30, "frac_max": 0.50, "frac_inter": 0.15},
    "moderada": {"frac_alvo": 0.15, "frac_max": 0.70, "frac_inter": 0.08},
}


# ----------------------------------------------------------------------------
# 1. Instancia
# ----------------------------------------------------------------------------
def _cota_fracionaria(valores, custos, orcamento):
    """Limitante superior (mochila fracionaria) do valor obtido com 'orcamento'."""
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

    # Teto por periodo: ~50% do custo total do portfolio dividido em m ciclos
    B_val = max(0.5 * sum(c) / m, 1.2 * max(c))
    B = [round(B_val)] * m

    # Metas acumuladas (Eq. 9) e tetos de concentracao (Eq. 10)
    alvo = {g: [] for g in GRUPOS}
    for g in GRUPOS:
        for j in J:
            cota = _cota_fracionaria(pg[g], c, sum(B[: j + 1]))
            alvo[g].append(round(cen["frac_alvo"] * cota))
    max_aloc = {g: [round(cen["frac_max"] * B[j]) for j in J] for g in GRUPOS}

    # Precedencias (i1 antes de i2) e conflitos (a, b mutuamente exclusivos)
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

    # Meta de interseccionalidade (Eq. 11), calibrada no modelo fuzzy
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


# ----------------------------------------------------------------------------
# 2. Modelo exato
# ----------------------------------------------------------------------------
def coef_intersec(inst, modelo):
    """Coeficiente de cada projeto na restricao (11), por modelo (secao 4.1)."""
    g1, g2 = PAR_INTERSEC
    a1, a2, p = inst["alpha"][g1], inst["alpha"][g2], inst["p"]
    I = range(inst["n"])
    if modelo == "fuzzy":        # min(alpha1, alpha2) * p_i   (proposto)
        return [min(a1[i], a2[i]) * p[i] for i in I]
    if modelo == "aditivo":      # soma dos beneficiarios (dupla contagem, ingenuo)
        return [inst["pg"][g1][i] + inst["pg"][g2][i] for i in I]
    if modelo == "composicao":   # parametro independente; aqui, independencia: a1*a2*p
        return [a1[i] * a2[i] * p[i] for i in I]
    raise ValueError(modelo)


def construir_modelo(inst, relaxar=False, modelo_inter="fuzzy"):
    """Constroi o modelo (Eqs. 5-13). Retorna (model, x, y, Z1, Z2, Z3)."""
    n, m = inst["n"], inst["m"]
    I, J = range(n), range(m)
    c, p, pg, alpha, B = inst["c"], inst["p"], inst["pg"], inst["alpha"], inst["B"]

    model = Model("PPA_equidade")
    model.hideOutput()

    vt = "C" if relaxar else "B"
    x = {(i, j): model.addVar(vtype=vt, lb=0, ub=1, name=f"x_{i}_{j}")
         for i in I for j in J}
    y = {j: model.addVar(vtype=vt, lb=0, ub=1, name=f"y_{j}") for j in J}

    # (5) capacidade orcamentaria com chave y_j
    for j in J:
        model.addCons(quicksum(c[i] * x[i, j] for i in I) <= B[j] * y[j], name=f"cap_{j}")

    # (6) unicidade
    for i in I:
        model.addCons(quicksum(x[i, j] for j in J) <= 1, name=f"uniq_{i}")

    # (7) precedencia
    for (i1, i2) in inst["prec"]:
        for j in J:
            model.addCons(x[i2, j] <= quicksum(x[i1, k] for k in range(j + 1)),
                          name=f"prec_{i1}_{i2}_{j}")

    # (8) incompatibilidade
    for (a, b) in inst["conf"]:
        for j in J:
            model.addCons(x[a, j] + x[b, j] <= 1, name=f"conf_{a}_{b}_{j}")

    # (9) meta minima acumulada por grupo
    for g in GRUPOS:
        for j in J:
            if inst["alvo"][g][j] > 0:
                model.addCons(
                    quicksum(pg[g][i] * x[i, k] for i in I for k in range(j + 1))
                    >= inst["alvo"][g][j], name=f"meta_{g}_{j}")

    # (10) limite maximo de concentracao (apenas projetos com alpha > theta)
    for g in GRUPOS:
        sel = [i for i in I if alpha[g][i] > THETA]
        for j in J:
            model.addCons(quicksum(c[i] * x[i, j] for i in sel) <= inst["max_aloc"][g][j],
                          name=f"maxaloc_{g}_{j}")

    # (11) interseccionalidade
    if modelo_inter != "nenhum":
        coef = coef_intersec(inst, modelo_inter)
        model.addCons(quicksum(coef[i] * x[i, j] for i in I for j in J)
                      >= inst["alvo_inter"], name="intersec")

    # Objetivos (1), (2), (3)
    Z1 = quicksum(PESOS[g] * pg[g][i] * x[i, j]
                  for g in GRUPOS_VULNER for i in I for j in J)
    Z2 = quicksum(p[i] * x[i, j] for i in I for j in J)
    Z3 = quicksum(B[j] * y[j] for j in J) - quicksum(c[i] * x[i, j] for i in I for j in J)
    return model, x, y, Z1, Z2, Z3


# ----------------------------------------------------------------------------
# 3. Resolucao
# ----------------------------------------------------------------------------
def _tem_solucao(model):
    return model.getNSols() > 0


def _extrair(model, x, inst):
    return {(i, j) for i in range(inst["n"]) for j in range(inst["m"])
            if model.getVal(x[i, j]) > 0.5}


def avaliar(inst, aloc):
    """Calcula Z1, Z2, Z3 e verifica metas (9), (10), (11) para uma alocacao."""
    n, m = inst["n"], inst["m"]
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


def resolver_lexicografico(inst, tempo_limite=60.0, modelo_inter="fuzzy"):
    """Tres passes sequenciais (secao 3.2, item 1)."""
    model, x, y, Z1, Z2, Z3 = construir_modelo(inst, modelo_inter=modelo_inter)
    model.setParam("limits/time", tempo_limite)
    res = {"status": None, "tempo": 0.0, "passes": []}
    t0 = time.time()

    def passe(obj, sentido, nome):
        model.setObjective(obj, sentido)
        model.optimize()
        st = model.getStatus()
        info = {"passe": nome, "status": st}
        if _tem_solucao(model):
            info["obj"] = model.getObjVal()
            info["gap_bb"] = model.getGap()
            info["tempo"] = model.getSolvingTime()
        res["passes"].append(info)
        return st, info

    # Passe 1: max Z1
    st, info = passe(Z1, "maximize", "Z1")
    if "obj" not in info:
        res["status"] = st
        res["tempo"] = time.time() - t0
        return res
    z1 = info["obj"]
    aloc = _extrair(model, x, inst)
    res["lp_gap_z1"] = gap_relaxacao(inst, z1, modelo_inter)

    # Passe 2: max Z2 s.a. Z1 >= Z1*
    model.freeTransform()
    model.addCons(Z1 >= z1 - max(TOL, 1e-7 * abs(z1)), name="fix_Z1")
    st, info = passe(Z2, "maximize", "Z2")
    if "obj" in info:
        z2 = info["obj"]
        aloc = _extrair(model, x, inst)
        # Passe 3: min Z3 s.a. Z1 >= Z1*, Z2 >= Z2*
        model.freeTransform()
        model.addCons(Z2 >= z2 - max(TOL, 1e-7 * abs(z2)), name="fix_Z2")
        st, info = passe(Z3, "minimize", "Z3")
        if "obj" in info:
            aloc = _extrair(model, x, inst)

    res["status"] = res["passes"][-1]["status"]
    res["tempo"] = time.time() - t0
    res["alocacao"] = sorted(aloc)
    res["metricas"] = avaliar(inst, aloc)
    return res


def resolver_escalar(inst, tempo_limite=60.0, modelo_inter="fuzzy"):
    """Escalarizacao (Eq. 14) com M calibrados pelos limites naturais de cada Z."""
    model, x, y, Z1, Z2, Z3 = construir_modelo(inst, modelo_inter=modelo_inter)
    model.setParam("limits/time", tempo_limite)
    M3 = 1.0
    M2 = sum(inst["B"]) + 1.0                 # Z3 <= sum B_j
    M1 = M2 * (sum(inst["p"]) + 1.0)          # Z2 <= sum p_i
    model.setObjective(M1 * Z1 + M2 * Z2 - M3 * Z3, "maximize")
    t0 = time.time()
    model.optimize()
    res = {"status": model.getStatus(), "tempo": time.time() - t0,
           "M": (M1, M2, M3)}
    if _tem_solucao(model):
        aloc = _extrair(model, x, inst)
        res["gap_bb"] = model.getGap()
        res["alocacao"] = sorted(aloc)
        res["metricas"] = avaliar(inst, aloc)
    return res


def gap_relaxacao(inst, z1_inteiro, modelo_inter="fuzzy"):
    """Gap (Z1) entre a relaxacao linear continua e o otimo inteiro (secao 3.1)."""
    model, x, y, Z1, _, _ = construir_modelo(inst, relaxar=True, modelo_inter=modelo_inter)
    model.setObjective(Z1, "maximize")
    model.optimize()
    if model.getStatus() != "optimal":
        return None
    lp = model.getObjVal()
    return {"Z1_lp": lp, "gap_rel": (lp - z1_inteiro) / max(1.0, abs(z1_inteiro))}


# ----------------------------------------------------------------------------
# 4. Relatorios
# ----------------------------------------------------------------------------
def imprimir_resultado(inst, res, titulo):
    print(f"\n=== {titulo} ===")
    print(f"Instancia: n={inst['n']}, m={inst['m']}, cenario={inst['cenario']}, seed={inst['seed']}")
    print(f"Status final: {res['status']} | tempo total: {res['tempo']:.2f}s")
    for ps in res.get("passes", []):
        extra = f", obj={ps['obj']:.2f}, gap_bb={ps['gap_bb']:.2e}" if "obj" in ps else ""
        print(f"  passe {ps['passe']}: {ps['status']}{extra}")
    if "lp_gap_z1" in res and res["lp_gap_z1"]:
        g = res["lp_gap_z1"]
        print(f"  Relaxacao linear (Z1): {g['Z1_lp']:.2f} | gap relativo: {g['gap_rel']:.2e}")
    if "metricas" not in res:
        print("  Sem solucao factivel.")
        return
    mt = res["metricas"]
    print(f"  Z1 (equidade ponderada) = {mt['Z1']:.2f}")
    print(f"  Z2 (impacto geral)      = {mt['Z2']:.2f}")
    print(f"  Z3 (desperdicio)        = {mt['Z3']:.2f}")
    print(f"  Projetos financiados: {mt['n_alocados']}/{inst['n']}")
    print(f"  Orcamento usado por periodo: {[round(u) for u in mt['usado']]} (tetos {inst['B']})")
    print(f"  Violacoes meta (9): {len(mt['viol_meta'])} | violacoes teto (10): {len(mt['viol_max'])}")
    if inst["n"] <= 30:
        for j in range(inst["m"]):
            projs = sorted(i for (i, jj) in res["alocacao"] if jj == j)
            print(f"    periodo {j}: projetos {projs}")


def comparar_intersec(inst, tempo_limite):
    """Secao 4.2: como cada modelo de interseccionalidade altera a alocacao."""
    print("\n=== Comparacao de modelos de interseccionalidade ===")
    g1, g2 = PAR_INTERSEC
    print(f"Grupo composto: {g1} x {g2} | meta = {inst['alvo_inter']}")
    sols = {}
    for mod in ["fuzzy", "aditivo", "composicao", "nenhum"]:
        t0 = time.time()
        res = resolver_lexicografico(inst, tempo_limite, modelo_inter=mod)
        t = time.time() - t0
        if "alocacao" not in res:
            print(f"  [{mod:10s}] {res['status']}")
            continue
        sols[mod] = set(res["alocacao"])
        # conformidade medida SEMPRE com o modelo fuzzy (conservador)
        coef = coef_intersec(inst, "fuzzy")
        ating = sum(coef[i] for (i, _) in res["alocacao"])
        ok = "ok" if ating >= inst["alvo_inter"] - TOL else "VIOLA"
        mt = res["metricas"]
        print(f"  [{mod:10s}] Z1={mt['Z1']:.0f} Z2={mt['Z2']:.0f} Z3={mt['Z3']:.0f} "
              f"| interseccao(fuzzy)={ating:.0f} ({ok}) | {t:.2f}s")
    if "fuzzy" in sols:
        for mod, s in sols.items():
            if mod != "fuzzy":
                dif = len(sols["fuzzy"] ^ s)
                print(f"  diferenca de alocacao fuzzy vs {mod}: {dif} pares (i,j) distintos")


def benchmark(tempo_limite, m, seed):
    print("\n=== Benchmark SCIP (lexicografico) ===")
    for n in (20, 100, 500):
        for cen in ("forte", "moderada"):
            inst = gerar_instancia(n, m, cen, seed)
            res = resolver_lexicografico(inst, tempo_limite)
            imprimir_resultado(inst, res, "")


# ----------------------------------------------------------------------------
# 5. Main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="PPA com equidade - SCIP")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--m", type=int, default=5)
    ap.add_argument("--cenario", choices=list(CENARIOS), default="forte")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tempo-limite", type=float, default=60.0, help="segundos por passe")
    ap.add_argument("--modo", choices=["lex", "escalar"], default="lex")
    ap.add_argument("--modelo-inter", choices=["fuzzy", "aditivo", "composicao", "nenhum"],
                    default="fuzzy")
    ap.add_argument("--comparar-intersec", action="store_true")
    ap.add_argument("--benchmark", action="store_true")
    ap.add_argument("--salvar-instancia", metavar="ARQ.json")
    args = ap.parse_args()

    if args.benchmark:
        benchmark(args.tempo_limite, args.m, args.seed)
        return

    inst = gerar_instancia(args.n, args.m, args.cenario, args.seed)
    if args.salvar_instancia:
        salvar_instancia(inst, args.salvar_instancia)
        print(f"Instancia salva em {args.salvar_instancia}")

    if args.comparar_intersec:
        comparar_intersec(inst, args.tempo_limite)
        return

    if args.modo == "lex":
        res = resolver_lexicografico(inst, args.tempo_limite, args.modelo_inter)
        imprimir_resultado(inst, res, "SCIP - lexicografico (3 passes)")
    else:
        res = resolver_escalar(inst, args.tempo_limite, args.modelo_inter)
        imprimir_resultado(inst, res, "SCIP - escalarizacao (Eq. 14)")
        print(f"  M1={res['M'][0]:.3e}, M2={res['M'][1]:.3e}, M3={res['M'][2]:.0f}")


if __name__ == "__main__":
    main()