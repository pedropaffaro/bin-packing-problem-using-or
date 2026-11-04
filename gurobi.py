import json
import math
import os
import time
import gurobipy as gp
from gurobipy import GRB

PASTA_RESULTADOS = "results"

STATUS_MAP = {
    GRB.OPTIMAL: "OPTIMAL",
    GRB.INFEASIBLE: "INFEASIBLE",
    GRB.INF_OR_UNBD: "INF_OR_UNBD",
    GRB.UNBOUNDED: "UNBOUNDED",
    GRB.TIME_LIMIT: "TIME_LIMIT",
    GRB.INTERRUPTED: "INTERRUPTED",
    GRB.SUBOPTIMAL: "SUBOPTIMAL",
}

def resolver_saches_gurobi(caminho_json: str, time_limit: float = 60.0,
                           seed: int = 0, threads: int = 1,
                           caminho_saida: str = None, sufixo: str = ""):
    """
    Resolve o Problema de Empacotamento de Sachês Personalizados via Gurobi
    e salva os resultados em um arquivo JSON.

    Parâmetros:
        caminho_json (str): Caminho para o arquivo JSON da instância.
        time_limit (float): Limite de tempo de execução em segundos.
        seed (int): Semente do Gurobi (parâmetro Seed).
        threads (int): Número de threads (None = padrão do Gurobi).
        caminho_saida (str): Arquivo JSON de saída. Se None, usa
            "results/resultado_gurobi_n{n}_seed{seed}{sufixo}.json".
        sufixo (str): Texto acrescentado ao nome dos arquivos de saída e de log
            (ex.: "_threadspadrao"), para não sobrescrever outras execuções.

    Retorna:
        dict com os resultados (o mesmo conteúdo salvo no JSON).
    """
    # 1. Carregamento dos dados do JSON
    with open(caminho_json, 'r', encoding='utf-8') as f:
        dados = json.load(f)

    n = dados['metadata']['n_items']
    m = dados['metadata']['max_sachets_m']
    N_max = dados['metadata']['max_items_per_sachet_Nmax']

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
    caminho_log = os.path.join(PASTA_RESULTADOS, f"log_gurobi_n{n}_seed{seed}{sufixo}.txt")
    if os.path.exists(caminho_log):
        os.remove(caminho_log)  # o Gurobi acrescenta ao arquivo de log; começa limpo

    # 2. Inicialização do Modelo Gurobi
    model = gp.Model("BPP_Saches_Personalizados")
    model.setParam(GRB.Param.TimeLimit, time_limit)
    model.setParam(GRB.Param.Seed, seed)
    if threads is not None:
        model.setParam(GRB.Param.Threads, threads)
    model.setParam(GRB.Param.OutputFlag, 1)  # 1 para exibir log do solver no console
    model.setParam(GRB.Param.LogFile, caminho_log)  # e também salvá-lo em arquivo

    # 3. Variáveis de Decisão Binárias
    # x[i, j] = 1 se o item i é alocado no sachê j
    x = model.addVars(I, J, vtype=GRB.BINARY, name="x")

    # y[j, k] = 1 se o sachê j é ativado com o tipo/tamanho k
    y = model.addVars(J, K, vtype=GRB.BINARY, name="y")

    # 4. Função Objetivo: Minimizar Custo Total de Embalagens
    model.setObjective(
        gp.quicksum(c[k] * y[j, k] for j in J for k in K),
        GRB.MINIMIZE
    )

    # 5. Restrições do Modelo

    # R1: Alocação Única (Todo item i deve ser inserido em exatamente 1 sachê)
    for i in I:
        model.addConstr(
            gp.quicksum(x[i, j] for j in J) == 1,
            name=f"Alocacao_Unica_Item_{i}"
        )

    # R2: Unicidade de Tipo por Sachê (No máximo 1 tamanho de sachê por posição j)
    for j in J:
        model.addConstr(
            gp.quicksum(y[j, k] for k in K) <= 1,
            name=f"Tipo_Unico_Sache_{j}"
        )

    # R3: Capacidade Volumétrica (Soma dos volumes em j <= capacidade do tipo k)
    for j in J:
        model.addConstr(
            gp.quicksum(v[i] * x[i, j] for i in I) <= gp.quicksum(V_max[k] * y[j, k] for k in K),
            name=f"Capacidade_Volumetrica_Sache_{j}"
        )

    # R4: Incompatibilidade entre Ingredientes (Conflitos)
    for idx, (i1, i2) in enumerate(E):
        for j in J:
            model.addConstr(
                x[i1, j] + x[i2, j] <= 1,
                name=f"Conflito_{i1}_{i2}_Sache_{j}"
            )

    # R5: Limite de Cardinalidade (Máximo N_max ingredientes por sachê)
    for j in J:
        model.addConstr(
            gp.quicksum(x[i, j] for i in I) <= N_max * gp.quicksum(y[j, k] for k in K),
            name=f"Cardinalidade_Sache_{j}"
        )

    # R6: Quebra de Simetria (Ordena ativação dos sachês para acelerar o Branch-and-Bound)
    for j in range(1, m):
        model.addConstr(
            gp.quicksum(y[j, k] for k in K) >= gp.quicksum(y[j + 1, k] for k in K),
            name=f"Quebra_Simetria_{j}"
        )

    # 6. Otimização
    start_time = time.time()
    model.optimize()
    elapsed_time = time.time() - start_time

    # 7. Montagem do dicionário de resultados
    status_str = STATUS_MAP.get(model.Status, f"OTHER_{model.Status}")
    tem_solucao = model.SolCount > 0

    # Limitantes inferiores simples, para referência
    lb_cardinalidade = math.ceil(n / N_max)
    lb_volume = math.ceil(sum(v.values()) / max(V_max.values()))

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
            "solver": "Gurobi",
            "versao": ".".join(str(p) for p in gp.gurobi.version()),
            "seed": seed,
            "threads": threads,
            "time_limit_s": time_limit,
        },
        "status": status_str,
        "status_code": model.Status,
        "tem_solucao_factivel": tem_solucao,
        "tempo_execucao_s": round(elapsed_time, 4),
        "tempo_runtime_gurobi_s": round(model.Runtime, 4),
        "nos_explorados": model.NodeCount,
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
        resultado["custo_total"] = round(model.ObjVal, 4)
        resultado["gap_otimalidade_pct"] = round(model.MIPGap * 100, 6)
        try:
            resultado["limitante_inferior_custo"] = round(model.ObjBound, 4)
        except gp.GurobiError:
            pass

        for j in J:
            tipo_ativo = None
            for k in K:
                if y[j, k].X > 0.5:
                    tipo_ativo = k
                    break

            if tipo_ativo is not None:
                itens_alocados = [i for i in I if x[i, j].X > 0.5]
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
            PASTA_RESULTADOS, f"resultado_gurobi_n{n}_seed{seed}{sufixo}.json")
    os.makedirs(os.path.dirname(caminho_saida) or ".", exist_ok=True)
    with open(caminho_saida, 'w', encoding='utf-8') as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)

    # 9. Resumo no console
    print("\n" + "=" * 60)
    print(f"RELATÓRIO DE DESEMPENHO - GUROBI (Instância: {caminho_json})")
    print("=" * 60)
    print(f"Status da Solução : {status_str}")
    if tem_solucao:
        print(f"Valor da F.O. (Custo) : R$ {resultado['custo_total']:.2f}")
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
    # Testar com as instâncias geradas (n=15, 50, 150)
    for n_inst in [15, 50, 150]:
        resolver_saches_gurobi(
            os.path.join(PASTA_RESULTADOS, f"instancia_saches_n{n_inst}.json"),
            time_limit=60,
            seed=0,
        )

    # Execução opcional com o número de threads padrão do Gurobi, sem sobrescrever
    # os resultados de 1 thread (descomente para rodar):
    # for n_inst in [50, 150]:
    #     resolver_saches_gurobi(
    #         os.path.join(PASTA_RESULTADOS, f"instancia_saches_n{n_inst}.json"),
    #         time_limit=60, seed=0, threads=None, sufixo="_threadspadrao",
    #     )