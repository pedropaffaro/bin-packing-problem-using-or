# Montagem otimizada de sachês de suplementação personalizada

Trabalho de SME0110 (Programação Matemática, ICMC/USP): empacotamento de suplementos em pó em sachês de três tamanhos, com conflitos entre itens e limite de cinco itens por sachê. O objetivo é minimizar o custo total de embalagem. O problema é resolvido por um modelo de Programação Linear Inteira Binária (Gurobi e SCIP) e por uma heurística construtiva (FFDC, First-Fit Decreasing with Conflicts). O modelo e a análise estão no relatório em PDF.

## Estrutura

```
gerar_instancias.py   gera as instâncias sintéticas (n = 15, 50, 150 por padrão)
gurobi.py             modelo PLIB resolvido com o Gurobi
scip.py               o mesmo modelo resolvido com o SCIP (PySCIPOpt)
heuristic.py          heurística FFDC
verificar.py          verificador independente das soluções (não depende de solver)
results/              instâncias (instancia_saches_n*.json), resultados (resultado_*.json) e logs (log_*.txt)
```

Todos os scripts leem e gravam em `results/`, relativo à pasta de onde são executados. Rode-os a partir da raiz do repositório.

## Dependências

- Python 3
- Gurobi 13.0.3 (`gurobipy`). O Gurobi exige licença; a licença restrita que vem com o `pip` não comporta as instâncias com n = 50 e n = 150, então é preciso uma licença acadêmica ou completa.
- SCIP 10.0 com PySCIPOpt 6.2.1 (`pip install pyscipopt`).

`gerar_instancias.py`, `heuristic.py` e `verificar.py` usam só a biblioteca padrão.

## Ordem de execução

```bash
python gerar_instancias.py      # cria results/instancia_saches_n{15,50,150}.json
python gurobi.py                # results/resultado_gurobi_n{n}_seed0.json + log_gurobi_n{n}_seed0.txt
python scip.py                  # results/resultado_scip_n{n}_seed0.json   + log_scip_n{n}_seed0.txt
python heuristic.py             # results/resultado_heuristica_n{n}.json
python verificar.py --varrer    # confere todos os results/resultado_*.json
```

`verificar.py` também aceita um único par: `python verificar.py results/instancia_saches_n15.json results/resultado_gurobi_n15_seed0.json`. Ele termina com código diferente de zero se algum resultado for inválido.

## Configuração dos experimentos

Limite de tempo de 60 s, semente 0, uma thread e m = n sachês disponíveis, para os dois solvers. A heurística é determinística. As sementes das instâncias são `42 + n` (57, 92 e 192).

## Reprodutibilidade

As execuções limitadas por tempo (n = 150 nos dois solvers e SCIP em n = 50) dependem do hardware: o número de nós explorados e a melhor solução encontrada em 60 s podem variar de uma máquina para outra. Os casos resolvidos até a otimalidade (n = 15 nos dois solvers e Gurobi em n = 50) devem reproduzir o mesmo custo ótimo, embora o agrupamento dos itens possa mudar, já que existem soluções ótimas alternativas.

## Execução opcional: Gurobi com threads padrão

Para rodar o Gurobi com o número de threads escolhido por ele, sem sobrescrever os resultados de uma thread, use `threads=None` e um sufixo (há um trecho comentado no `__main__` de `gurobi.py`):

```python
from gurobi import resolver_saches_gurobi

for n in [50, 150]:
    resolver_saches_gurobi(f"results/instancia_saches_n{n}.json",
                           time_limit=60, seed=0, threads=None,
                           sufixo="_threadspadrao")
# gera results/resultado_gurobi_n{n}_seed0_threadspadrao.json e o log correspondente
```

Com várias threads o Gurobi não é determinístico, então os valores podem diferir de uma execução para outra.

## Heurística em instâncias maiores

O gerador e a heurística aceitam os tamanhos pela linha de comando:

```bash
python gerar_instancias.py 300 500
python heuristic.py 300 500
python verificar.py --varrer
```

Isso cria `results/instancia_saches_n300.json` e `n500`, e os respectivos `resultado_heuristica_n*.json`. A heurística leva milissegundos nesses tamanhos. Para esses n não há resultado dos solvers para comparação.

Observação: o gerador sorteia conflitos aleatórios até atingir 5% das arestas possíveis, com um limite de tentativas proporcional à meta (no mínimo 10 000). Esse limite não é atingido para n = 15, 50 e 150, então as instâncias do relatório não mudam. Para n muito grande, instâncias com densidade menor que 5% podem ser geradas se o limite de tentativas for atingido.

## Ambiente de execução

- CPU: `<preencher>`
- RAM: `<preencher>`
- Sistema operacional: `<preencher>`
- Versão do Python: `<preencher>`
- Licença do Gurobi: `<preencher>`