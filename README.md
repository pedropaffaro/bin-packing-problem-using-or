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

- Python 3 (testado com 3.10.12)
- Gurobi 13.0.3 (`gurobipy`)
- SCIP 10.0 com PySCIPOpt 6.2.1

```bash
python3 -m pip install gurobipy==13.0.3 pyscipopt==6.2.1
```

O Gurobi exige licença. A licença restrita que vem com o `pip` não comporta os modelos de n = 50 e n = 150, então é preciso uma licença acadêmica ou completa. Para uso acadêmico em uma única máquina, a mais simples é a Named-User Academic: crie uma conta acadêmica no site do Gurobi, gere a licença no User Portal e rode `grbgetkey <chave>` conectado à rede da universidade (o `grbgetkey` vem nas Gurobi License Tools ou no instalador completo). Ele grava o `gurobi.lic` na pasta pessoal, onde o `gurobipy` o encontra sozinho. Para conferir:

```bash
python3 -c "import gurobipy as gp; gp.Model()"   # deve aparecer "Academic license"
```

`gerar_instancias.py`, `heuristic.py` e `verificar.py` usam só a biblioteca padrão.

## Ordem de execução

```bash
python3 gerar_instancias.py      # cria results/instancia_saches_n{15,50,150}.json
python3 gurobi.py                # results/resultado_gurobi_n{n}_seed0.json + log_gurobi_n{n}_seed0.txt
python3 scip.py                  # results/resultado_scip_n{n}_seed0.json   + log_scip_n{n}_seed0.txt
python3 heuristic.py             # results/resultado_heuristica_n{n}.json
python3 verificar.py --varrer    # confere todos os results/resultado_*.json
```

O Gurobi e o SCIP levam cerca de 1 minuto cada, quase todo gasto em n = 150, que roda até o limite de tempo. Rodar os solvers sobrescreve os resultados e logs que já estão em `results/`.

`verificar.py` também aceita um único par: `python3 verificar.py results/instancia_saches_n15.json results/resultado_gurobi_n15_seed0.json`. Ele termina com código diferente de zero se algum resultado for inválido.

## Configuração dos experimentos

Limite de tempo de 60 s, semente 0, uma thread e m = n sachês disponíveis, para os dois solvers. A heurística é determinística. As sementes das instâncias são `42 + n` (57, 92 e 192).

## Resultados

Resultados em `results/`, obtidos no ambiente descrito no fim deste arquivo. Gap calculado como (Z − LB)/Z para os dois solvers.

| n   | Método   | Status       | Custo (R$) | Sachês | Gap (%) | Tempo (s) | Nós   |
|-----|----------|--------------|-----------:|-------:|--------:|----------:|------:|
| 15  | Gurobi   | Ótima        | 2,55       | 3      | 0,00    | 0,11      | 28    |
| 15  | SCIP     | Ótima        | 2,55       | 3      | 0,00    | 0,97      | 26    |
| 15  | FFDC     | Factível     | 3,15       | 4      |         | < 0,001   |       |
| 50  | Gurobi   | Ótima        | 6,05       | 10     | 0,00    | 3,59      | 1 021 |
| 50  | SCIP     | Tempo limite | 6,15       | 10     | 6,87    | 60,21     | 1 411 |
| 50  | FFDC     | Factível     | 7,70       | 11     |         | < 0,001   |       |
| 150 | Gurobi   | Tempo limite | 20,20      | 31     | 4,95    | 60,03     | 464   |
| 150 | SCIP     | Tempo limite | 25,55      | 31     | 24,98   | 60,02     | 1     |
| 150 | FFDC     | Factível     | 24,15      | 31     |         | < 0,001   |       |

`python3 verificar.py --varrer` confirma as 9 soluções como válidas.

## Reprodutibilidade

As execuções limitadas por tempo (n = 150 nos dois solvers e SCIP em n = 50) dependem do hardware: o número de nós explorados e a melhor solução encontrada em 60 s podem variar de uma máquina para outra. Em uma execução anterior, em outra máquina, o Gurobi terminou n = 150 com R$ 20,35, 32 sachês e 36 nós, contra R$ 20,20, 31 sachês e 464 nós na tabela acima. Os casos resolvidos até a otimalidade (n = 15 nos dois solvers e Gurobi em n = 50) devem reproduzir o mesmo custo ótimo, embora o agrupamento dos itens possa mudar, já que existem soluções ótimas alternativas.

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
python3 gerar_instancias.py 300 500
python3 heuristic.py 300 500
python3 verificar.py --varrer
```

Isso cria `results/instancia_saches_n300.json` e `n500`, e os respectivos `resultado_heuristica_n*.json`. A heurística leva milissegundos nesses tamanhos. Para esses n não há resultado dos solvers para comparação.

Observação: o gerador sorteia conflitos aleatórios até atingir 5% das arestas possíveis, com um limite de tentativas proporcional à meta (no mínimo 10 000). Esse limite não é atingido para n = 15, 50 e 150, então as instâncias do relatório não mudam. Para n muito grande, instâncias com densidade menor que 5% podem ser geradas se o limite de tentativas for atingido.

## Ambiente de execução

- CPU: Intel Core i5-1335U (13ª geração, 10 núcleos, 12 threads)
- RAM: 8 GB (7,4 GiB utilizáveis)
- Sistema operacional: Pop!_OS 22.04 LTS
- Versão do Python: 3.10.12
- Licença do Gurobi: Named-User Academic