"""
Verificador independente de soluções do problema de empacotamento de sachês.

Confere, a partir da instância e do JSON de resultado (de qualquer um dos três
métodos), sem depender de nenhum solver:
  - todo item é alocado exatamente uma vez (e não há itens desconhecidos);
  - o volume de cada sachê não excede a capacidade do tipo declarado;
  - o número de itens por sachê não excede N_max;
  - nenhum par de itens em conflito está no mesmo sachê;
  - custos, volumes e o custo_total do JSON são consistentes com a instância.

Uso:
    python verificar.py instancia.json resultado.json   # um resultado
    python verificar.py --varrer [pasta]                 # todos os resultado_*.json (padrão: results/)

Código de saída: 0 se tudo passou; 1 se algum resultado falhou ou nada foi encontrado.
"""
import glob
import json
import os
import sys

TOL = 1e-6

def verificar(caminho_instancia: str, caminho_resultado: str):
    """Retorna a lista de erros encontrados (lista vazia = solução válida)."""
    with open(caminho_instancia, 'r', encoding='utf-8') as f:
        inst = json.load(f)
    with open(caminho_resultado, 'r', encoding='utf-8') as f:
        res = json.load(f)

    erros = []
    if not res.get("tem_solucao_factivel"):
        return ["o resultado não contém solução factível"]

    N_max = inst['metadata']['max_items_per_sachet_Nmax']
    v = {it['id']: it['volume'] for it in inst['items']}
    tipos = {k['id']: k for k in inst['sachet_types']}
    conflitos = {(min(a, b), max(a, b)) for a, b in inst['conflicts']}

    contagem = {}
    custo_soma = 0.0
    ids_saches = set()

    for s in res['saches']:
        sid = s['id_sache']
        if sid in ids_saches:
            erros.append(f"sachê {sid} aparece mais de uma vez")
        ids_saches.add(sid)

        t = tipos.get(s['tipo_id'])
        if t is None:
            erros.append(f"sachê {sid}: tipo {s['tipo_id']} não existe na instância")
            continue
        if abs(s['custo'] - t['cost']) > TOL:
            erros.append(f"sachê {sid}: custo {s['custo']} difere do custo do tipo ({t['cost']})")
        if abs(s['capacidade_cm3'] - t['capacity_cm3']) > TOL:
            erros.append(f"sachê {sid}: capacidade declarada difere da do tipo")
        custo_soma += t['cost']

        ids = [it['id'] for it in s['itens']]
        for it in s['itens']:
            if it['id'] not in v:
                erros.append(f"sachê {sid}: item {it['id']} não existe na instância")
            elif abs(it['volume_cm3'] - v[it['id']]) > TOL:
                erros.append(f"sachê {sid}: volume do item {it['id']} difere da instância")
            contagem[it['id']] = contagem.get(it['id'], 0) + 1

        vol = sum(v.get(i, 0.0) for i in ids)
        if vol > t['capacity_cm3'] + TOL:
            erros.append(f"sachê {sid}: volume {vol:.2f} excede a capacidade {t['capacity_cm3']}")
        if abs(vol - s['volume_ocupado_cm3']) > 1e-3:
            erros.append(f"sachê {sid}: volume_ocupado_cm3 declarado difere da soma dos itens")
        if len(ids) > N_max:
            erros.append(f"sachê {sid}: {len(ids)} itens excedem N_max = {N_max}")
        if s['n_itens'] != len(ids):
            erros.append(f"sachê {sid}: n_itens declarado difere do número de itens")
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                if (min(ids[a], ids[b]), max(ids[a], ids[b])) in conflitos:
                    erros.append(f"sachê {sid}: conflito entre os itens {ids[a]} e {ids[b]}")

    for i in v:
        if contagem.get(i, 0) != 1:
            erros.append(f"item {i} alocado {contagem.get(i, 0)} vezes (esperado: 1)")

    if abs(custo_soma - res['custo_total']) > 1e-3:
        erros.append(f"custo_total {res['custo_total']} difere da soma dos custos ({custo_soma:.4f})")
    if res.get('n_saches_utilizados') != len(res['saches']):
        erros.append("n_saches_utilizados difere do número de sachês listados")

    return erros

def _instancia_do_resultado(caminho_resultado: str, pasta: str):
    with open(caminho_resultado, 'r', encoding='utf-8') as f:
        res = json.load(f)
    nome = os.path.basename(res['instancia']['arquivo'])
    return os.path.join(pasta, nome)

def varrer(pasta: str = "results") -> int:
    arquivos = sorted(glob.glob(os.path.join(pasta, "resultado_*.json")))
    if not arquivos:
        print(f"Nenhum resultado_*.json encontrado em {pasta}/")
        return 1
    falhas = 0
    for arq in arquivos:
        try:
            inst = _instancia_do_resultado(arq, pasta)
            erros = verificar(inst, arq)
        except Exception as e:  # arquivo ausente, JSON inválido, campo faltando...
            erros = [f"não foi possível verificar: {e!r}"]
        if erros:
            falhas += 1
            print(f"FALHA  {os.path.basename(arq)}")
            for e in erros:
                print(f"         - {e}")
        else:
            print(f"OK     {os.path.basename(arq)}")
    print(f"\n{len(arquivos) - falhas} de {len(arquivos)} resultados válidos.")
    return 1 if falhas else 0

if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--varrer":
        sys.exit(varrer(args[1] if len(args) > 1 else "results"))
    if len(args) == 2:
        erros = verificar(args[0], args[1])
        if erros:
            print("FALHA")
            for e in erros:
                print(f"  - {e}")
            sys.exit(1)
        print("OK")
        sys.exit(0)
    print(__doc__)
    sys.exit(2)