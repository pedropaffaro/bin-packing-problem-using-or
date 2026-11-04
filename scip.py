import json
import math
import os
import time
import pyscipopt
from pyscipopt import Model, quicksum

PASTA_RESULTADOS = "results"

# Mesmo m usado no gurobi.py: floor(Z_FFDC / 0.50), cota superior válida para o
# número de sachês de uma solução ótima (Z_FFDC = 3.15 e 7.70).
M_SACHES = {15: 6, 50: 15}

def resolver_saches_scip(caminho_json: str, time_limit: float = 60.0,
                         seed: int = 0, caminho_saida: str = None,
                         sufixo: str = "", m: int = None):
    """
    Resolve o Problema de Empacotamento de Sachês Personalizados via SCIP (PySCIPOpt)
    e salva os resultados em um arquivo JSON (mesmo formato usado no gurobi.py).

    Parâmetros:
        caminho_json (str): Caminho para o ficheiro JSON da instância.
        time_limit (float): Limite de tempo de execução em segundos.
        seed (int): Semente do SCIP (parâmetro randomization/randomseedshift).
        caminho_saida (str): Arquivo JSON de saída. Se None, usa
            "results/resultado_scip_n{n}_seed{seed}{sufixo}.json".
        sufixo (str): Texto acrescentado ao nome dos arquivos de saída e de log.
        m (int): Número de sachês potenciais. Se None, usa o da instância.

    Retorna:
        dict com os resultados (o mesmo conteúdo salvo no JSON).
    """
    # 1. Carregamento dos dados do JSON
    with open(caminho_json, 'r', encoding='utf-8') as f:
        dados = json.load(f)

    n = dados['metadata']['n_items']
    if m is None:
        m = dados['metadata']['max_sachets_m']
    N_max = dados['metadata']['max_items_per_sachet_Nmax']

    if m < math.ceil(n / N_max):
        raise ValueError(f"m = {m} é menor que o mínimo possível "
                         f"({math.ceil(n / N_max)} sachês).")

    itens = dados['items']
    I = [it['id'] for it in itens]
    v = {it['id']: it['volume'] for it in itens}
    nome_item = {it['id']: it['name'] for it in itens}

    tipos = dados['sachet_types']
    K = [k['id'] for k in tipos]
    V_max = {k['id']: k['capacity_cm3'] for k in tipos}
    c = {k['id']: k['cost'] for k in tipos}
    nome_tipo = {k['id']: k['name'] for k in tipos}

    E = dados['conflicts']
    J = list(range(1, m + 1))

    os.makedirs(PASTA_RESULTADOS, exist_ok=True)
    caminho_log = os.path.join(PASTA_RESULTADOS, f"log_scip_n{n}_seed{seed}{sufixo}.txt")

    # 2. Inicialização do Modelo SCIP
    model = Model("BPP_Saches_Personalizados")
    model.setParam("limits/time", time_limit)
    model.setParam("randomization/randomseedshift", seed)
    model.setLogfile(caminho_log)

    # 3. Variáveis de Decisão Binárias
    x = {}
    for i in I:
        for j in J:
            x[i, j] = model.addVar(vtype="B", name=f"x_{i}_{j}")

    y = {}
    for j in J:
        for k in K:
            y[j, k] = model.addVar(vtype="B", name=f"y_{j}_{k}")

    # 4. Função Objetivo
    model.setObjective(
        quicksum(c[k] * y[j, k] for j in J for k in K),
        sense="minimize"
    )

    # 5. Restrições do Modelo

    # R1: Alocação Única
    for i in I:
        model.addCons(
            quicksum(x[i, j] for j in J) == 1,
            name=f"Alocacao_Unica_Item_{i}"
        )

    # R2: Unicidade de Tipo por Sachê
    for j in J:
        model.addCons(
            quicksum(y[j, k] for k in K) <= 1,
            name=f"Tipo_Unico_Sache_{j}"
        )

    # R3: Capacidade Volumétrica
    for j in J:
        model.addCons(
            quicksum(v[i] * x[i, j] for i in I) <= quicksum(V_max[k] * y[j, k] for k in K),
            name=f"Capacidade_Volumetrica_Sache_{j}"
        )

    # R4: Incompatibilidade entre Ingredientes (Conflitos)
    for i1, i2 in E:
        for j in J:
            model.addCons(
                x[i1, j] + x[i2, j] <= 1,
                name=f"Conflito_{i1}_{i2}_Sache_{j}"
            )

    # R5: Limite de Cardinalidade
    for j in J:
        model.addCons(
            quicksum(x[i, j] for i in I) <= N_max * quicksum(y[j, k] for k in K),
            name=f"Cardinalidade_Sache_{j}"
        )

    # R6: Quebra de Simetria
    for j in range(1, m):
        model.addCons(
            quicksum(y[j, k] for k in K) >= quicksum(y[j + 1, k] for k in K),
            name=f"Quebra_Simetria_{j}"
        )

    # 6. Otimização
    start_time = time.time()
    model.optimize()
    elapsed_time = time.time() - start_time

    # 7. Montagem do dicionário de resultados
    status = model.getStatus()
    tem_solucao = model.getNSols() > 0

    lb_cardinalidade = math.ceil(n / N_max)
    lb_volume = math.ceil(sum(v.values()) / max(V_max.values()))

    try:
        versao_scip = str(model.version())
    except Exception:
        versao_scip = None

    resultado = {
        "instancia": {
            "arquivo": os.path.basename(caminho_json),
            "n_itens": n,
            "m_saches_disponiveis": m,
            "N_max": N_max,
            "n_conflitos": len(E),
            "seed_instancia": dados['metadata'].get('seed'),
        },
        "configuracao_solver": {
            "solver": "SCIP",
            "versao": versao_scip,
            "versao_pyscipopt": getattr(pyscipopt, "__version__", None),
            "seed": seed,
            "threads": 1,
            "time_limit_s": time_limit,
        },
        "status": status.upper(),
        "tem_solucao_factivel": tem_solucao,
        "tempo_execucao_s": round(elapsed_time, 4),
        "tempo_runtime_scip_s": round(model.getSolvingTime(), 4),
        "nos_explorados": model.getNNodes(),
        "limitantes_inferiores_simples": {
            "cardinalidade": lb_cardinalidade,
            "volume": lb_volume,
        },
        "custo_total": None,
        "limitante_inferior_custo": None,
        "gap_otimalidade_pct": None,
        "n_saches_utilizados": None,
        "saches": [],
    }

    if tem_solucao:
        resultado["custo_total"] = round(model.getObjVal(), 4)

        gap = model.getGap()
        if gap is not None and math.isfinite(gap) and gap < 1e19:
            resultado["gap_otimalidade_pct"] = round(gap * 100, 6)

        dual = model.getDualbound()
        if dual is not None and math.isfinite(dual) and abs(dual) < 1e19:
            resultado["limitante_inferior_custo"] = round(dual, 4)

        for j in J:
            tipo_ativo = None
            for k in K:
                if model.getVal(y[j, k]) > 0.5:
                    tipo_ativo = k
                    break

            if tipo_ativo is not None:
                itens_alocados = [i for i in I if model.getVal(x[i, j]) > 0.5]
                vol_ocupado = sum(v[i] for i in itens_alocados)
                cap_max = V_max[tipo_ativo]
                resultado["saches"].append({
                    "id_sache": j,
                    "tipo_id": tipo_ativo,
                    "tipo_nome": nome_tipo[tipo_ativo],
                    "custo": c[tipo_ativo],
                    "capacidade_cm3": cap_max,
                    "volume_ocupado_cm3": round(vol_ocupado, 4),
                    "taxa_ocupacao_pct": round(vol_ocupado / cap_max * 100, 2),
                    "n_itens": len(itens_alocados),
                    "itens": [
                        {"id": i, "nome": nome_item[i], "volume_cm3": v[i]}
                        for i in itens_alocados
                    ],
                })

        resultado["n_saches_utilizados"] = len(resultado["saches"])

    # 8. Salvamento em JSON
    if caminho_saida is None:
        caminho_saida = os.path.join(
            PASTA_RESULTADOS, f"resultado_scip_n{n}_seed{seed}{sufixo}.json")
    os.makedirs(os.path.dirname(caminho_saida) or ".", exist_ok=True)
    with open(caminho_saida, 'w', encoding='utf-8') as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)

    # 9. Resumo na consola
    print("\n" + "=" * 60)
    print(f"RELATÓRIO DE DESEMPENHO - SCIP (Instância: {caminho_json}, m={m})")
    print("=" * 60)
    print(f"Status da Solução : {status.upper()}")
    if tem_solucao:
        print(f"Valor da F.O. (Custo) : R$ {resultado['custo_total']:.2f}")
        if resultado["gap_otimalidade_pct"] is not None:
            print(f"Gap de Otimalidade  : {resultado['gap_otimalidade_pct']:.4f}%")
        print(f"Tempo de Execução   : {elapsed_time:.4f} segundos")
        print(f"Resumo: {n} itens empacotados em {resultado['n_saches_utilizados']} sachês.")
    else:
        print("Nenhuma solução factível foi encontrada no tempo limite fornecido.")
    print(f"Resultados salvos em: {caminho_saida}")
    print(f"Log do solver em    : {caminho_log}")
    print("=" * 60)

    return resultado

if __name__ == "__main__":
    for n_inst in [15, 50]:
        resolver_saches_scip(
            os.path.join(PASTA_RESULTADOS, f"instancia_saches_n{n_inst}.json"),
            time_limit=60,
            seed=0,
            m=M_SACHES[n_inst],
        )