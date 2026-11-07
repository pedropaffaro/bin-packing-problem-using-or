# Montagem de Sachês de Suplementação Personalizada

**Disciplina**: SME0110 — Programação Matemática · ICMC/USP · 2026  
**Autores**: Alec Campos Aoki, Henrique Vieira Lima, João Gabriel Pieroli da Silva, Luysa de Souza Gonçalves, Pedro Augusto Ferraro Paffaro

Trata-se de uma variante do *Bin Packing Problem* (BPP) aplicada à embalagem de suplementos nutricionais em pó. Dado que um cliente tem uma prescrição diária de *n* suplementos, como distribuí-los em sachês de três tamanhos com custo mínimo, respeitando incompatibilidades químicas entre ingredientes e um limite de mistura por sachê? O problema é resolvido por um modelo de **Programação Linear Inteira Binária** (PLIB) via Gurobi e SCIP, e por uma **heurística construtiva FFDC** (*First-Fit Decreasing with Conflicts*). 

---

## O Problema

Cada suplemento *i* tem um volume *vᵢ* (cm³). Sachês estão disponíveis em três tipos:

| Tipo    | Capacidade (cm³) | Custo unitário |
|---------|-----------------|----------------|
| Pequeno | 15              | R$ 0,50        |
| Médio   | 35              | R$ 0,85        |
| Grande  | 70              | R$ 1,30        |

**Restrições além do BPP clássico:**

- **Incompatibilidade química e organoléptica** — certos pares de suplementos não podem estar no mesmo sachê.
- **Cardinalidade** — no máximo *N*ᵐᵃˣ = 5 suplementos por sachê (limite de homogeneidade na diluição).
- **Tipos de custo variável** — o objetivo é minimizar o **custo total de embalagem**, não o número de sachês.

---

## Modelo Matemático (PLIB)

**Conjuntos e parâmetros**

- *I* = {1, …, n}: suplementos; *J* = {1, …, m}: sachês disponíveis (m = n); *K* = {1, 2, 3}: tipos de sachê
- *vᵢ*: volume da dose do suplemento *i*; *V*ₖᵐᵃˣ: capacidade do tipo *k*; *cₖ*: custo do tipo *k*
- *E* ⊂ I × I: pares de suplementos incompatíveis; *N*ᵐᵃˣ = 5: limite de itens por sachê

**Variáveis de decisão**

- *x*[*i*, *j*] ∈ {0, 1} — 1 se o suplemento *i* é alocado ao sachê *j*
- *y*[*j*, *k*] ∈ {0, 1} — 1 se o sachê *j* usa a embalagem do tipo *k*

**Função objetivo**

```
min Z = Σⱼ Σₖ cₖ · y[j,k]
```

**Restrições**

| #  | Nome                | Formulação                                      | Propósito |
|----|---------------------|-------------------------------------------------|-----------|
| R1 | Alocação única      | Σⱼ x[i,j] = 1  ∀i                              | cada suplemento em exatamente um sachê |
| R2 | Unicidade de tipo   | Σₖ y[j,k] ≤ 1  ∀j                              | cada sachê tem no máximo um tamanho |
| R3 | Capacidade          | Σᵢ vᵢ·x[i,j] ≤ Σₖ Vₖ·y[j,k]  ∀j              | volume respeita a capacidade do tipo escolhido |
| R4 | Conflitos           | x[i,j] + x[l,j] ≤ 1  ∀(i,l)∈E, ∀j            | pares incompatíveis não compartilham sachê |
| R5 | Cardinalidade       | Σᵢ x[i,j] ≤ Nᵐᵃˣ · Σₖ y[j,k]  ∀j             | no máximo 5 suplementos por sachê |
| R6 | Quebra de simetria  | Σₖ y[j,k] ≥ Σₖ y[j+1,k]  ∀j < m               | sachês ativados com menor índice (reduz espaço do B&B) |

A quebra de simetria (R6) é a única restrição que vai além da formulação base do BPP: ela elimina soluções que diferem apenas pela posição dos sachês vazios, sem alterar o custo, compactando o espaço explorado pelo *branch-and-bound*.

---

## Estrutura do Repositório

```
gerar_instancias.py   gerador paramétrico de instâncias sintéticas (n = 15, 50, 150 por padrão)
gurobi.py             modelo PLIB resolvido com Gurobi 13.0.3 (gurobipy)
scip.py               o mesmo modelo resolvido com SCIP 10.0 (PySCIPOpt)
heuristic.py          heurística construtiva FFDC (First-Fit Decreasing with Conflicts)
verificar.py          verificador independente de soluções (não depende de solver)

results/              instâncias (instancia_saches_n*.json)
                      resultados dos três métodos (resultado_*.json)
                      logs completos dos solvers (log_*.txt)
```

Todos os scripts leem e gravam em `results/`, relativo à pasta de onde são executados. Rode-os a partir da raiz do repositório.

---

## Dependências

- Python 3 (testado com 3.10.12)
- Gurobi 13.0.3 (`gurobipy`)
- SCIP 10.0 com PySCIPOpt 6.2.1

```bash
python3 -m pip install gurobipy==13.0.3 pyscipopt==6.2.1
```

`gerar_instancias.py`, `heuristic.py` e `verificar.py` usam só a biblioteca padrão do Python.

**Licença do Gurobi**: a licença restrita que vem com o `pip` não comporta os modelos de n = 50 e n = 150. É preciso uma licença acadêmica (*Named-User Academic*): crie uma conta no site do Gurobi, gere a licença no User Portal e rode `grbgetkey <chave>` conectado à rede da universidade. O arquivo `gurobi.lic` é gravado na pasta pessoal, onde o `gurobipy` o encontra automaticamente. Para verificar:

```bash
python3 -c "import gurobipy as gp; gp.Model()"   # deve exibir "Academic license"
```

---

## Como Executar

```bash
# 1. Gerar as instâncias
python3 gerar_instancias.py
# → results/instancia_saches_n{15,50,150}.json

# 2. Resolver com os solvers (~1 min cada, quase tudo em n = 150)
python3 gurobi.py
# → results/resultado_gurobi_n{n}_seed0.json + log_gurobi_n{n}_seed0.txt

python3 scip.py
# → results/resultado_scip_n{n}_seed0.json   + log_scip_n{n}_seed0.txt

# 3. Resolver com a heurística (milissegundos)
python3 heuristic.py
# → results/resultado_heuristica_n{n}.json

# 4. Verificar todas as soluções
python3 verificar.py --varrer
# → imprime OK/FALHA para cada resultado_*.json
```

Rodar os solvers sobrescreve os resultados e logs que já estão em `results/`.

**Verificação de um único resultado:**

```bash
python3 verificar.py results/instancia_saches_n15.json results/resultado_gurobi_n15_seed0.json
```

**Heurística em instâncias maiores** (o gerador e a heurística aceitam tamanhos via linha de comando):

```bash
python3 gerar_instancias.py 300 500
python3 heuristic.py 300 500
python3 verificar.py --varrer
```

**Gurobi com múltiplas threads** (sem sobrescrever os resultados de 1 thread, descomente o trecho no `__main__` de `gurobi.py` ou use a API):

```python
from gurobi import resolver_saches_gurobi
for n in [50, 150]:
    resolver_saches_gurobi(f"results/instancia_saches_n{n}.json",
                           time_limit=60, seed=0, threads=None,
                           sufixo="_threadspadrao")
```

---

## Configuração dos Experimentos

Todos os resultados em `results/` foram obtidos com: limite de 60 s, semente 0, **uma thread** e m = n sachês disponíveis. As sementes das instâncias são `42 + n` (57 para n = 15, 92 para n = 50, 192 para n = 150). A heurística é determinística.

---

## Resultados

Comparação completa entre os três métodos. Gap calculado como (Z − LB)/Z para Gurobi e SCIP.


| n   | Método | Status           | Custo Z (R$) | Sachês | LB (R$) | Gap (%) | Desvio de Z* (%) | Tempo (s)        | Nós   |
|-----|--------|------------------|-------------:|-------:|--------:|--------:|-----------------:|------------------|------:|
| 15  | Gurobi | **Ótima**        | 2,55         | 3      | 2,55    | 0,00    | 0,00             | 0,11             | 28    |
| 15  | SCIP   | **Ótima**        | 2,55         | 3      | 2,55    | 0,00    | 0,00             | 0,97             | 26    |
| 15  | FFDC   | Factível         | 3,15         | 4      | —       | —       | 23,53            | 1,8 × 10⁻⁵       | —     |
| 50  | Gurobi | **Ótima**        | 6,05         | 10     | 6,05    | 0,00    | 0,00             | 3,59             | 1 021 |
| 50  | SCIP   | Tempo limite     | 6,15         | 10     | 5,73    | 6,87    | 1,65             | 60,21            | 1 411 |
| 50  | FFDC   | Factível         | 7,70         | 11     | —       | —       | 27,27            | 5,1 × 10⁻⁵       | —     |
| 150 | Gurobi | Tempo limite     | **20,20**    | 31     | 19,20   | 4,95    | 0,00             | 60,03            | 464   |
| 150 | SCIP   | Tempo limite     | 25,55        | 31     | 19,17   | 24,98   | 26,49            | 60,02            | 1     |
| 150 | FFDC   | Factível         | 24,15        | 31     | —       | —       | 19,55            | 2,4 × 10⁻⁴       | —     |

Z* é a solução ótima conhecida (Gurobi para n = 15 e 50; melhor solução encontrada — Gurobi — para n = 150).

**Destaques:**
- Gurobi foi ~9× mais rápido que SCIP em n = 15 e é o único a provar otimalidade em n = 50 (3,6 s).
- Em n = 150, o SCIP ficou preso no nó raiz com uma única solução de R$ 25,55 (heurística de cliques); o Gurobi chegou a R$ 20,20 explorando 464 nós.
- A FFDC superou o SCIP em n = 150 (R$ 24,15 contra R$ 25,55) com tempo desprezível.
- A FFDC responde em menos de 1 ms em todos os tamanhos, com custo entre 19,6% e 27,3% acima da melhor solução conhecida.
- `python3 verificar.py --varrer` confirma as 9 soluções como válidas.

---

## Reprodutibilidade

As execuções com limite de tempo (n = 150 nos dois solvers e SCIP em n = 50) dependem do hardware: o número de nós explorados e a melhor solução encontrada em 60 s podem variar entre máquinas. 

Os casos resolvidos até a otimalidade (n = 15 nos dois solvers e Gurobi em n = 50) devem reproduzir o mesmo custo ótimo, embora o agrupamento específico dos itens possa diferir entre soluções ótimas alternativas.

---

## Ambiente de Execução

- **CPU**: Intel Core i5-1335U (13ª geração, 10 núcleos, 12 threads)
- **RAM**: 8 GB (7,4 GiB utilizáveis)
- **SO**: Pop!\_OS 22.04 LTS
- **Python**: 3.10.12
- **Gurobi**: 13.0.3 (licença Named-User Academic)
- **SCIP / PySCIPOpt**: 10.0 / 6.2.1
