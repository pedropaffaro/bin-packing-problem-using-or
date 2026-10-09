#!/usr/bin/env python3
"""
bpp_public_gurobi.py
SME0110 - Programacao Matematica (ICMC/USP)

Versao Gurobi de bpp_public_scip.py: mesmo gerador de instancias, mesmo modelo
(Eqs. 5-13 + interseccionalidade), mesmas metricas e mesmo formato de saida,
para comparacao direta SCIP x Gurobi.

Modos:
  lex       : 3 passes sequenciais (igual ao SCIP), com warm start entre passes
  lexnativo : lexicografico nativo do Gurobi (setObjectiveN com prioridades)
  escalar   : escalarizacao (Eq. 14), igual ao SCIP

Para comparacao justa, por padrao: Threads=1 (SCIP e single-thread) e
MIPGap=0 (o padrao do Gurobi e 1e-4, o do SCIP e 0).

Uso:
  pip install gurobipy
  python bpp_public_gurobi.py --n 100 --cenario moderada
  python bpp_public_gurobi.py --n 100 --cenario moderada --instancia inst.json
  python bpp_public_gurobi.py --modo lexnativo
  python bpp_public_gurobi.py --comparar-intersec
  python bpp_public_gurobi.py --benchmark
"""

import argparse
import json
import random
import time

import gurobipy as gp
from gurobipy import GRB

TOL = 1e-6
GRUPOS = ["indigenas", "mulheres", "rurais"]
GRUPOS_VULNER = ["indigenas", "rurais"]
PESOS = {"indigenas": 1.5, "rurais": 1.0}   # w_g
THETA = 0.5                                  # limiar de pertencimento (Eq. 10)
PAR_INTERSEC = ("indigenas", "mulheres")     # grupo composto da Eq. (11)

CENARIOS = {
    "forte":    {"frac_alvo": 0.30, "frac_max": 0.50, "frac_inter": 0.15},
    "moderada": {"frac_alvo": 0.15, "frac_max": 0.70, "frac_inter": 0.08},
}

STATUS = {
    GRB.OPTIMAL: "optimal", GRB.INFEASIBLE: "infeasible",
    GRB.INF_OR_UNBD: "inf_or_unbd", GRB.UNBOUNDED: "unbounded",
    GRB.TIME_LIMIT: "timelimit", GRB.SUBOPTIMAL: "suboptimal",
    GRB.INTERRUPTED: "interrupted", GRB.NODE_LIMIT: "nodelimit",
    GRB.SOLUTION_LIMIT: "sollimit", GRB.MEM_LIMIT: "memlimit",
}


def nome_status(model):
    return STATUS.get(model.Status, f"status_{model.Status}")


# ----------------------------------------------------------------------------
# 1. Instancia (identica a versao SCIP: mesma seed => mesma instancia)
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


# ----------------------------------------------------------------------------
# 2. Modelo exato
# ----------------------------------------------------------------------------
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


def construir_modelo(inst, relaxar=False, modelo_inter="fuzzy", threads=1, gap=0.0):
    """Constroi o modelo (Eqs. 5-13). Retorna (model, x, y, Z1, Z2, Z3)."""
    n, m = inst["n"], inst["m"]
    I, J = range(n), range(m)
    c, p, pg, alpha, B = inst["c"], inst["p"], inst["pg"], inst["alpha"], inst["B"]

    model = gp.Model("PPA_equidade")
    model.Params.OutputFlag = 0
    model.Params.Threads = threads
    model.Params.MIPGap = gap

    vt = GRB.CONTINUOUS if relaxar else GRB.BINARY
    x = {(i, j): model.addVar(vtype=vt, lb=0, ub=1, name=f"x_{i}_{j}")
         for i in I for j in J}
    y = {j: model.addVar(vtype=vt, lb=0, ub=1, name=f"y_{j}") for j in J}

    # (5) capacidade orcamentaria com chave y_j
    for j in J:
        model.addConstr(gp.quicksum(c[i] * x[i, j] for i in I) <= B[j] * y[j],
                        name=f"cap_{j}")

    # (6) unicidade
    for i in I:
        model.addConstr(gp.quicksum(x[i, j] for j in J) <= 1, name=f"uniq_{i}")

    # (7) precedencia
    for (i1, i2) in inst["prec"]:
        for j in J:
            model.addConstr(x[i2, j] <= gp.quicksum(x[i1, k] for k in range(j + 1)),
                            name=f"prec_{i1}_{i2}_{j}")

    # (8) incompatibilidade
    for (a, b) in inst["conf"]:
        for j in J:
            model.addConstr(x[a, j] + x[b, j] <= 1, name=f"conf_{a}_{b}_{j}")

    # (9) meta minima acumulada por grupo
    for g in GRUPOS:
        for j in J:
            if inst["alvo"][g][j] > 0:
                model.addConstr(
                    gp.quicksum(pg[g][i] * x[i, k] for i in I for k in range(j + 1))
                    >= inst["alvo"][g][j], name=f"meta_{g}_{j}")

    # (10) limite maximo de concentracao (apenas projetos com alpha > theta)
    for g in GRUPOS:
        sel = [i for i in I if alpha[g][i] > THETA]
        for j in J:
            model.addConstr(gp.quicksum(c[i] * x[i, j] for i in sel) <= inst["max_aloc"][g][j],
                            name=f"maxaloc_{g}_{j}")

    # (11) interseccionalidade
    if modelo_inter != "nenhum":
        coef = coef_intersec(inst, modelo_inter)
        model.addConstr(gp.quicksum(coef[i] * x[i, j] for i in I for j in J)
                        >= inst["alvo_inter"], name="intersec")

    # Objetivos (1), (2), (3)
    Z1 = gp.quicksum(PESOS[g] * pg[g][i] * x[i, j]
                     for g in GRUPOS_VULNER for i in I for j in J)
    Z2 = gp.quicksum(p[i] * x[i, j] for i in I for j in J)
    Z3 = gp.quicksum(B[j] * y[j] for j in J) - gp.quicksum(c[i] * x[i, j] for i in I for j in J)
    model.update()
    return model, x, y, Z1, Z2, Z3


# ----------------------------------------------------------------------------
# 3. Resolucao
# ----------------------------------------------------------------------------
def _extrair(model, x, inst):
    return {(i, j) for i in range(inst["n"]) for j in range(inst["m"])
            if x[i, j].X > 0.5}


def _warm_start(x, y):
    """Usa a solucao do passe anterior como MIP start do proximo."""
    for v in list(x.values()) + list(y.values()):
        v.Start = round(v.X)


def avaliar(inst, aloc):
    """Calcula Z1, Z2, Z3 e verifica metas (9), (10) para uma alocacao."""
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


def resolver_lexicografico(inst, tempo_limite=60.0, modelo_inter="fuzzy",
                           threads=1, gap=0.0, warm=True):
    """Tres passes sequenciais (igual ao SCIP). tempo_limite e POR PASSE."""
    model, x, y, Z1, Z2, Z3 = construir_modelo(inst, modelo_inter=modelo_inter,
                                               threads=threads, gap=gap)
    model.Params.TimeLimit = tempo_limite
    res = {"status": None, "tempo": 0.0, "passes": []}
    t0 = time.time()

    def passe(obj, sentido, nome):
        model.setObjective(obj, sentido)
        model.optimize()
        info = {"passe": nome, "status": nome_status(model)}
        if model.SolCount > 0:
            info["obj"] = model.ObjVal
            info["gap_bb"] = model.MIPGap
            info["bound"] = model.ObjBound
            info["gap_abs"] = abs(model.ObjBound - model.ObjVal)
            info["tempo"] = model.Runtime
        res["passes"].append(info)
        return info

    # Passe 1: max Z1
    info = passe(Z1, GRB.MAXIMIZE, "Z1")
    if "obj" not in info:
        res["status"] = info["status"]
        res["tempo"] = time.time() - t0
        return res
    z1 = info["obj"]
    aloc = _extrair(model, x, inst)
    res["lp_gap_z1"] = gap_relaxacao(inst, z1, modelo_inter)
    if warm:
        _warm_start(x, y)

    # Passe 2: max Z2 s.a. Z1 >= Z1*
    model.addConstr(Z1 >= z1 - max(TOL, 1e-7 * abs(z1)), name="fix_Z1")
    info = passe(Z2, GRB.MAXIMIZE, "Z2")
    if "obj" in info:
        z2 = info["obj"]
        aloc = _extrair(model, x, inst)
        if warm:
            _warm_start(x, y)
        # Passe 3: min Z3 s.a. Z1 >= Z1*, Z2 >= Z2*
        model.addConstr(Z2 >= z2 - max(TOL, 1e-7 * abs(z2)), name="fix_Z2")
        info = passe(Z3, GRB.MINIMIZE, "Z3")
        if "obj" in info:
            aloc = _extrair(model, x, inst)

    res["status"] = res["passes"][-1]["status"]
    res["tempo"] = time.time() - t0
    res["alocacao"] = sorted(aloc)
    res["metricas"] = avaliar(inst, aloc)
    return res


def resolver_lex_nativo(inst, tempo_limite=60.0, modelo_inter="fuzzy",
                        threads=1, gap=0.0):
    """Lexicografico nativo do Gurobi (multi-objetivo hierarquico)."""
    model, x, y, Z1, Z2, Z3 = construir_modelo(inst, modelo_inter=modelo_inter,
                                               threads=threads, gap=gap)
    model.ModelSense = GRB.MAXIMIZE
    model.setObjectiveN(Z1, 0, priority=3, abstol=0.0, reltol=0.0, name="Z1")
    model.setObjectiveN(Z2, 1, priority=2, abstol=0.0, reltol=0.0, name="Z2")
    model.setObjectiveN(Z3, 2, priority=1, weight=-1.0, abstol=0.0, reltol=0.0, name="Z3")
    for k in range(3):                       # limite de tempo/gap POR objetivo
        env = model.getMultiobjEnv(k)
        env.setParam("TimeLimit", tempo_limite)
        env.setParam("MIPGap", gap)
    t0 = time.time()
    model.optimize()
    res = {"status": nome_status(model), "tempo": time.time() - t0, "passes": []}
    if model.SolCount > 0:
        for k, nome in enumerate(["Z1", "Z2", "Z3"]):
            model.params.ObjNumber = k
            res["passes"].append({"passe": nome, "status": "-", "obj": model.ObjNVal,
                                  "gap_bb": float("nan"), "bound": float("nan"),
                                  "gap_abs": float("nan")})
        aloc = _extrair(model, x, inst)
        res["alocacao"] = sorted(aloc)
        res["metricas"] = avaliar(inst, aloc)
    return res


def resolver_escalar(inst, tempo_limite=60.0, modelo_inter="fuzzy", threads=1, gap=0.0):
    """Escalarizacao (Eq. 14). Atencao: M1 ~ 1e10 gera coeficientes ~1e14,
    numericamente ruim em qualquer solver; prefira lex / lexnativo."""
    model, x, y, Z1, Z2, Z3 = construir_modelo(inst, modelo_inter=modelo_inter,
                                               threads=threads, gap=gap)
    model.Params.TimeLimit = tempo_limite
    M3 = 1.0
    M2 = sum(inst["B"]) + 1.0
    M1 = M2 * (sum(inst["p"]) + 1.0)
    model.setObjective(M1 * Z1 + M2 * Z2 - M3 * Z3, GRB.MAXIMIZE)
    t0 = time.time()
    model.optimize()
    res = {"status": nome_status(model), "tempo": time.time() - t0, "M": (M1, M2, M3)}
    if model.SolCount > 0:
        aloc = _extrair(model, x, inst)
        res["gap_bb"] = model.MIPGap
        res["alocacao"] = sorted(aloc)
        res["metricas"] = avaliar(inst, aloc)
    return res


def gap_relaxacao(inst, z1_inteiro, modelo_inter="fuzzy"):
    """Gap (Z1) entre a relaxacao linear e o otimo inteiro (secao 3.1)."""
    model, x, y, Z1, _, _ = construir_modelo(inst, relaxar=True, modelo_inter=modelo_inter)
    model.setObjective(Z1, GRB.MAXIMIZE)
    model.optimize()
    if model.Status != GRB.OPTIMAL:
        return None
    lp = model.ObjVal
    return {"Z1_lp": lp, "gap_rel": (lp - z1_inteiro) / max(1.0, abs(z1_inteiro))}


# ----------------------------------------------------------------------------
# 4. Relatorios
# ----------------------------------------------------------------------------
def imprimir_resultado(inst, res, titulo):
    print(f"\n=== {titulo} ===")
    print(f"Instancia: n={inst['n']}, m={inst['m']}, cenario={inst['cenario']}, seed={inst['seed']}")
    print(f"Status final: {res['status']} | tempo total: {res['tempo']:.2f}s")
    for ps in res.get("passes", []):
        extra = ""
        if "obj" in ps:
            extra = (f", obj={ps['obj']:.2f}, gap_bb={ps['gap_bb']:.2e}, "
                     f"bound={ps['bound']:.2f}, gap_abs={ps['gap_abs']:.2f}")
        print(f"  passe {ps['passe']}: {ps['status']}{extra}")
    if res.get("lp_gap_z1"):
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


def comparar_intersec(inst, args):
    print("\n=== Comparacao de modelos de interseccionalidade ===")
    g1, g2 = PAR_INTERSEC
    print(f"Grupo composto: {g1} x {g2} | meta = {inst['alvo_inter']}")
    sols = {}
    for mod in ["fuzzy", "aditivo", "composicao", "nenhum"]:
        t0 = time.time()
        res = resolver_lexicografico(inst, args.tempo_limite, mod, args.threads, args.gap)
        t = time.time() - t0
        if "alocacao" not in res:
            print(f"  [{mod:10s}] {res['status']}")
            continue
        sols[mod] = set(res["alocacao"])
        coef = coef_intersec(inst, "fuzzy")
        ating = sum(coef[i] for (i, _) in res["alocacao"])
        ok = "ok" if ating >= inst["alvo_inter"] - TOL else "VIOLA"
        mt = res["metricas"]
        print(f"  [{mod:10s}] Z1={mt['Z1']:.0f} Z2={mt['Z2']:.0f} Z3={mt['Z3']:.0f} "
              f"| interseccao(fuzzy)={ating:.0f} ({ok}) | {t:.2f}s")
    if "fuzzy" in sols:
        for mod, s in sols.items():
            if mod != "fuzzy":
                print(f"  diferenca de alocacao fuzzy vs {mod}: {len(sols['fuzzy'] ^ s)} pares (i,j) distintos")


def benchmark(args):
    print("\n=== Benchmark Gurobi (lexicografico) ===")
    print(f"{'n':>5} {'cenario':>9} {'status':>10} {'tempo(s)':>9} {'Z1':>12} {'Z2':>12} "
          f"{'Z3':>9} {'viol':>5}")
    for n in (20, 100, 500):
        for cen in ("forte", "moderada"):
            inst = gerar_instancia(n, args.m, cen, args.seed)
            res = resolver_lexicografico(inst, args.tempo_limite, "fuzzy", args.threads, args.gap)
            imprimir_resultado(inst, res, "")


# ----------------------------------------------------------------------------
# 5. Main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="PPA com equidade - Gurobi")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--m", type=int, default=5)
    ap.add_argument("--cenario", choices=list(CENARIOS), default="forte")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tempo-limite", type=float, default=60.0, help="segundos por passe")
    ap.add_argument("--modo", choices=["lex", "lexnativo", "escalar"], default="lex")
    ap.add_argument("--modelo-inter", choices=["fuzzy", "aditivo", "composicao", "nenhum"],
                    default="fuzzy")
    ap.add_argument("--threads", type=int, default=1, help="1 = comparavel ao SCIP")
    ap.add_argument("--gap", type=float, default=0.0, help="MIPGap relativo alvo (0 = igual ao SCIP)")
    ap.add_argument("--sem-warmstart", action="store_true")
    ap.add_argument("--instancia", metavar="ARQ.json", help="carrega instancia salva pelo script SCIP")
    ap.add_argument("--comparar-intersec", action="store_true")
    ap.add_argument("--benchmark", action="store_true")
    ap.add_argument("--salvar-instancia", metavar="ARQ.json")
    ap.add_argument("--salvar-resultado", metavar="ARQ.json")
    args = ap.parse_args()

    if args.benchmark:
        benchmark(args)
        return

    if args.instancia:
        inst = carregar_instancia(args.instancia)
    else:
        inst = gerar_instancia(args.n, args.m, args.cenario, args.seed)
    if args.salvar_instancia:
        salvar_instancia(inst, args.salvar_instancia)
        print(f"Instancia salva em {args.salvar_instancia}")

    if args.comparar_intersec:
        comparar_intersec(inst, args)
        return

    if args.modo == "lex":
        res = resolver_lexicografico(inst, args.tempo_limite, args.modelo_inter,
                                     args.threads, args.gap, warm=not args.sem_warmstart)
        imprimir_resultado(inst, res, "Gurobi - lexicografico (3 passes)")
    elif args.modo == "lexnativo":
        res = resolver_lex_nativo(inst, args.tempo_limite, args.modelo_inter,
                                  args.threads, args.gap)
        imprimir_resultado(inst, res, "Gurobi - lexicografico nativo")
    else:
        res = resolver_escalar(inst, args.tempo_limite, args.modelo_inter,
                               args.threads, args.gap)
        imprimir_resultado(inst, res, "Gurobi - escalarizacao (Eq. 14)")
        print(f"  M1={res['M'][0]:.3e}, M2={res['M'][1]:.3e}, M3={res['M'][2]:.0f}")

    if args.salvar_resultado:
        with open(args.salvar_resultado, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1, default=str)
        print(f"Resultado salvo em {args.salvar_resultado}")


if __name__ == "__main__":
    main()