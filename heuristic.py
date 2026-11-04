import json
import math
import os
import sys
import time

PASTA_RESULTADOS = "results"

def resolver_saches_heuristica(caminho_json: str, caminho_saida: str = None):
    """
    Resolve o Problema de Empacotamento de Sachês Personalizados via
    heurística construtiva FFDC (First-Fit Decreasing with Conflicts): FFD com
    verificação de conflitos e dimensionamento pelo menor tipo viável de sachê,
    e salva os resultados em um arquivo JSON (mesmo formato usado em gurobi.py e scip.py).

    Parâmetros:
        caminho_json (str): Caminho para o ficheiro JSON da instância.
        caminho_saida (str): Arquivo JSON de saída. Se None, usa
            "results/resultado_heuristica_n{n}.json".

    Retorna:
        dict com os resultados (o mesmo conteúdo salvo no JSON).
    """
    # 1. Carregamento dos dados do JSON
    with open(caminho_json, 'r', encoding='utf-8') as f:
        dados = json.load(f)

    n = dados['metadata']['n_items']
    N_max = dados['metadata']['max_items_per_sachet_Nmax']

    itens = dados['items']
    nome_item = {it['id']: it['name'] for it in itens}
    v = {it['id']: it['volume'] for it in itens}

    # Ordenar tipos de sachês por capacidade crescente (para escolher o menor sachê viável)
    tipos = sorted(dados['sachet_types'], key=lambda k: k['capacity_cm3'])
    nome_tipo = {k['id']: k['name'] for k in tipos}
    c = {k['id']: k['cost'] for k in tipos}
    V_max = {k['id']: k['capacity_cm3'] for k in tipos}
    cap_max_absoluta = max(V_max.values())

    # Construção de um grafo de conflitos rápido (Set de pares ordenados)
    E = dados['conflicts']
    conflitos_set = set()
    grau_conflito = {it['id']: 0 for it in itens}
    for i1, i2 in E:
        conflitos_set.add((min(i1, i2), max(i1, i2)))
        if i1 in grau_conflito:
            grau_conflito[i1] += 1
        if i2 in grau_conflito:
            grau_conflito[i2] += 1

    def ha_conflito(item_id, lista_itens_sache):
        """Verifica se o item_id é incompatível com qualquer item já alocado no sachê."""
        for item_alocado in lista_itens_sache:
            par = (min(item_id, item_alocado), max(item_id, item_alocado))
            if par in conflitos_set:
                return True
        return False

    start_time = time.time()

    # 2. Ordenação dos Itens (FFD: Prioriza volume decrescente e grau de conflito)
    itens_ordenados = sorted(
        itens,
        key=lambda it: (it['volume'], grau_conflito[it['id']]),
        reverse=True
    )

    # 3. Algoritmo Guloso de Alocação (First-Fit Decreasing com Conflitos)
    saches = []  # Lista de dicionários representando cada sachê aberto

    for item in itens_ordenados:
        item_id = item['id']
        vol_item = item['volume']
        alocado = False

        # Tentar alocar no primeiro sachê existente que respeite todas as restrições
        for sache in saches:
            # Restrição de Cardinalidade (Máximo N_max itens)
            if len(sache['itens']) >= N_max:
                continue

            # Restrição de Capacidade Absoluta (Não excede o maior sachê do estoque)
            if sache['volume_total'] + vol_item > cap_max_absoluta:
                continue

            # Restrição de Conflitos Químicos/Organolépticos
            if ha_conflito(item_id, sache['itens']):
                continue

            # Alocação confirmada
            sache['itens'].append(item_id)
            sache['volume_total'] += vol_item
            alocado = True
            break

        # Se não coube em nenhum sachê existente, abre um novo sachê
        if not alocado:
            saches.append({
                'itens': [item_id],
                'volume_total': vol_item
            })

    # 4. Dimensionamento: atribui a cada sachê o menor tipo que comporta o volume
    custo_total = 0.0
    for sache in saches:
        vol_tot = sache['volume_total']
        tipo_escolhido = None
        for t in tipos:
            if vol_tot <= t['capacity_cm3']:
                tipo_escolhido = t
                break

        sache['tipo'] = tipo_escolhido['id']
        custo_total += tipo_escolhido['cost']

    elapsed_time = time.time() - start_time

    # 5. Verificação da factibilidade (recalcula as restrições da solução)
    todos_itens = [i for s in saches for i in s['itens']]
    verif_alocacao = sorted(todos_itens) == sorted(v.keys())
    verif_capacidade = all(s['volume_total'] <= V_max[s['tipo']] + 1e-9 for s in saches)
    verif_cardinalidade = all(len(s['itens']) <= N_max for s in saches)
    verif_conflitos = all(
        (min(a, b), max(a, b)) not in conflitos_set
        for s in saches
        for idx_a, a in enumerate(s['itens'])
        for b in s['itens'][idx_a + 1:]
    )
    factivel = (verif_alocacao and verif_capacidade
                and verif_cardinalidade and verif_conflitos)

    # 6. Montagem do dicionário de resultados
    lb_cardinalidade = math.ceil(n / N_max)
    lb_volume = math.ceil(sum(v.values()) / cap_max_absoluta)

    resultado = {
        "instancia": {
            "arquivo": os.path.basename(caminho_json),
            "n_itens": n,
            "m_saches_disponiveis": dados['metadata'].get('max_sachets_m'),
            "N_max": N_max,
            "n_conflitos": len(E),
            "seed_instancia": dados['metadata'].get('seed'),
        },
        "configuracao_solver": {
            "solver": "Heurística FFDC",
            "deterministica": True,
            "seed": None,
            "threads": 1,
            "time_limit_s": None,
        },
        "status": "FEASIBLE_HEURISTIC" if factivel else "INFEASIBLE_HEURISTIC",
        "tem_solucao_factivel": factivel,
        "verificacao": {
            "todos_itens_alocados_uma_vez": verif_alocacao,
            "capacidade": verif_capacidade,
            "cardinalidade": verif_cardinalidade,
            "conflitos": verif_conflitos,
        },
        "tempo_execucao_s": round(elapsed_time, 6),
        "nos_explorados": None,
        "limitantes_inferiores_simples": {
            "cardinalidade": lb_cardinalidade,
            "volume": lb_volume,
        },
        "custo_total": round(custo_total, 4),
        "limitante_inferior_custo": None,
        "gap_otimalidade_pct": None,
        "n_saches_utilizados": len(saches),
        "saches": [],
    }

    for idx, sache in enumerate(saches, 1):
        tipo_id = sache['tipo']
        vol_ocupado = sache['volume_total']
        cap_max = V_max[tipo_id]
        resultado["saches"].append({
            "id_sache": idx,
            "tipo_id": tipo_id,
            "tipo_nome": nome_tipo[tipo_id],
            "custo": c[tipo_id],
            "capacidade_cm3": cap_max,
            "volume_ocupado_cm3": round(vol_ocupado, 4),
            "taxa_ocupacao_pct": round(vol_ocupado / cap_max * 100, 2),
            "n_itens": len(sache['itens']),
            "itens": [
                {"id": i_id, "nome": nome_item[i_id], "volume_cm3": v[i_id]}
                for i_id in sache['itens']
            ],
        })

    # 7. Salvamento em JSON
    if caminho_saida is None:
        caminho_saida = os.path.join(PASTA_RESULTADOS, f"resultado_heuristica_n{n}.json")
    os.makedirs(os.path.dirname(caminho_saida) or ".", exist_ok=True)
    with open(caminho_saida, 'w', encoding='utf-8') as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)

    # 8. Resumo na consola
    print("\n" + "=" * 60)
    print(f"RELATÓRIO DE DESEMPENHO - HEURÍSTICA FFDC (Instância: {caminho_json})")
    print("=" * 60)
    print(f"Status da Solução : {resultado['status']}")
    print(f"Valor da F.O. (Custo) : R$ {custo_total:.2f}")
    print(f"Tempo de Execução   : {elapsed_time:.6f} segundos")
    print(f"Resumo: {n} itens empacotados em {len(saches)} sachês "
          f"(limitante de cardinalidade: {lb_cardinalidade}).")
    print(f"Resultados salvos em: {caminho_saida}")
    print("=" * 60)

    return resultado


if __name__ == "__main__":
    # Uso: python heuristic.py            -> n = 15, 50, 150
    #      python heuristic.py 300 500    -> tamanhos escolhidos (instâncias já geradas)
    tamanhos = [int(a) for a in sys.argv[1:]] or [15, 50, 150]
    for n_inst in tamanhos:
        resolver_saches_heuristica(
            os.path.join(PASTA_RESULTADOS, f"instancia_saches_n{n_inst}.json"))