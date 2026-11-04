import json
import os
import random
import sys

PASTA_RESULTADOS = "results"

# Base de dados com 54 suplementos reais e diversas categorias funcionais
SUPPLEMENT_DATABASE = [
    # Proteínas e Aminoácidos
    {"name": "Whey Protein Concentrado", "volume": 25.0, "category": "protein"},
    {"name": "Colágeno Hidrolisado", "volume": 12.0, "category": "protein"},
    {"name": "Creatina Monohidratada", "volume": 6.0, "category": "amino_acid"},
    {"name": "L-Glutamina", "volume": 7.0, "category": "amino_acid"},
    {"name": "Beta-Alanina", "volume": 4.5, "category": "amino_acid"},
    {"name": "L-Arginina", "volume": 5.0, "category": "amino_acid"},
    {"name": "L-Carnitina em Pó", "volume": 3.5, "category": "amino_acid"},
    {"name": "Taurina", "volume": 3.0, "category": "amino_acid"},
    {"name": "BCAA 2:1:1", "volume": 8.0, "category": "amino_acid"},
    {"name": "HMB (β-Hidroxi-β-Metilbutirato)", "volume": 4.0, "category": "amino_acid"},
    {"name": "L-Teanina", "volume": 1.0, "category": "amino_acid"},
    {"name": "Glicina em Pó", "volume": 5.0, "category": "amino_acid"},
    {"name": "Peptídeos de Glutamina", "volume": 6.0, "category": "amino_acid"},
    {"name": "L-Leucina Isolada", "volume": 4.0, "category": "amino_acid"},

    # Nootrópicos, Adaptógenos e Fitoterápicos
    {"name": "Alpha-GPC 50%", "volume": 1.5, "category": "nootropic"},
    {"name": "Fosfatidilserina em Pó", "volume": 2.0, "category": "nootropic"},
    {"name": "Rhodiola Rosea (Extrato)", "volume": 2.0, "category": "herbal"},
    {"name": "Cogumelo Lion's Mane (Juba de Leão)", "volume": 3.5, "category": "herbal"},
    {"name": "Ashwagandha (Extrato KSM-66)", "volume": 2.0, "category": "herbal"},
    {"name": "Maca Peruana em Pó", "volume": 5.0, "category": "herbal"},
    {"name": "Tribulus Terrestris", "volume": 3.0, "category": "herbal"},
    {"name": "Extrato de Semente de Uva", "volume": 1.5, "category": "antioxidant"},

    # Enzimas Digestivas, Saúde Intestinal e Fibras
    {"name": "Blend de Enzimas Digestivas (Lactase/Protease)", "volume": 2.0, "category": "enzyme"},
    {"name": "Psyllium (Fibra em Pó)", "volume": 10.0, "category": "fiber"},
    {"name": "Inulina (Prebiótico)", "volume": 7.0, "category": "fiber"},
    {"name": "Beta-Glucana de Levedura", "volume": 2.5, "category": "immunomodulator"},
    {"name": "Betaína Anidra (TMG)", "volume": 4.0, "category": "digestive"},

    # Minerais e Eletrólitos
    {"name": "Citrato de Magnésio", "volume": 4.0, "category": "mineral"},
    {"name": "Bisglicinato de Magnésio", "volume": 4.5, "category": "mineral"},
    {"name": "Picolinato de Zinco", "volume": 1.5, "category": "mineral"},
    {"name": "Carbonato de Cálcio", "volume": 5.0, "category": "mineral"},
    {"name": "Sulfato Ferroso (Ferro)", "volume": 2.0, "category": "mineral"},
    {"name": "Bisglicinato de Cobre", "volume": 1.0, "category": "mineral"},
    {"name": "Cloreto de Potássio", "volume": 3.0, "category": "electrolyte"},
    {"name": "Citrato de Sódio", "volume": 4.0, "category": "electrolyte"},

    # Vitaminas e Antioxidantes
    {"name": "Vitamina C (Ácido Ascórbico)", "volume": 2.5, "category": "vitamin_acid"},
    {"name": "Ácido Cítrico (Flavorizante)", "volume": 2.0, "category": "acid"},
    {"name": "Bicarbonato de Sódio", "volume": 5.0, "category": "alkaline"},
    {"name": "Vitamina D3 em Pó", "volume": 1.0, "category": "vitamin"},
    {"name": "Vitamina E em Pó", "volume": 1.5, "category": "vitamin"},
    {"name": "Complexo B Concentrado", "volume": 2.0, "category": "vitamin"},
    {"name": "Coenzima Q10", "volume": 1.5, "category": "antioxidant"},
    {"name": "Curcumina / Cúrcuma 95%", "volume": 3.0, "category": "antioxidant"},
    {"name": "N-Acetilcisteína (NAC)", "volume": 2.0, "category": "antioxidant"},
    {"name": "Resveratrol em Pó", "volume": 1.5, "category": "antioxidant"},
    {"name": "Astaxantina em Pó", "volume": 1.0, "category": "antioxidant"},
    {"name": "Extrato de Tart Cherry", "volume": 3.0, "category": "antioxidant"},

    # Carboidratos e Estimulantes
    {"name": "Cafeína Anidra", "volume": 1.0, "category": "stimulant"},
    {"name": "Extrato de Chá Verde (EGCG)", "volume": 2.0, "category": "stimulant"},
    {"name": "Spirulina em Pó", "volume": 6.0, "category": "superfood"},
    {"name": "Açaí Liofilizado em Pó", "volume": 8.0, "category": "superfood"},
    {"name": "Maltodextrina", "volume": 20.0, "category": "carbohydrate"},
    {"name": "Palatinose (Isomaltulose)", "volume": 18.0, "category": "carbohydrate"},
    {"name": "Waxy Maize", "volume": 22.0, "category": "carbohydrate"},
]

# Regras de conflito fisiológico/químico expandidas
REAL_CONFLICT_RULES = [
    ("mineral", "Cálcio", "mineral", "Ferro"),                 # Inibição de absorção do ferro pelo cálcio
    ("mineral", "Zinco", "mineral", "Cobre"),                  # Competição por transportadores intestinais
    ("alkaline", "Bicarbonato", "vitamin_acid", "Vitamina C"), # Reação efervescente em pó umedecido
    ("alkaline", "Bicarbonato", "acid", "Ácido Cítrico"),      # Reação efervescente em pó umedecido
    ("fiber", "Psyllium", "antioxidant", "Coenzima Q10"),      # Fibras sequestram lipófilos
    ("fiber", "Psyllium", "nootropic", "Fosfatidilserina"),    # Fibras sequestram compostos lipídicos
    ("enzyme", "Enzimas", "acid", "Ácido Cítrico"),            # Acidez desnatura enzimas em pó
]

def generate_supplement_list(n_items, seed=42):
    rng = random.Random(seed)
    items = []
    base_len = len(SUPPLEMENT_DATABASE)
    
    for i in range(n_items):
        base_item = SUPPLEMENT_DATABASE[i % base_len]
        cycle = i // base_len
        
        if cycle == 0:
            name = base_item["name"]
            vol = base_item["volume"]
        else:
            name = f"{base_item['name']} (Lote {cycle + 1})"
            vol = round(base_item["volume"] * rng.uniform(0.85, 1.25), 1)
            
        items.append({
            "id": i + 1,
            "name": name,
            "volume": vol,
            "category": base_item["category"]
        })
    return items

def generate_conflicts(items, conflict_density=0.05, seed=42):
    rng = random.Random(seed)
    conflicts = set()
    n = len(items)
    
    for i in range(n):
        for j in range(i + 1, n):
            item1, item2 = items[i], items[j]
            for cat1, kw1, cat2, kw2 in REAL_CONFLICT_RULES:
                c1 = (cat1 in item1["category"] and kw1 in item1["name"]) and (cat2 in item2["category"] and kw2 in item2["name"])
                c2 = (cat2 in item1["category"] and kw2 in item1["name"]) and (cat1 in item2["category"] and kw1 in item2["name"])
                if c1 or c2:
                    conflicts.add((item1["id"], item2["id"]))
                    break

    target_conflicts = int(n * (n - 1) / 2 * conflict_density)
    # O limite de tentativas cresce com a meta de conflitos. Para n = 15, 50 e 150
    # ele nunca é atingido, então as instâncias geradas não mudam.
    max_attempts = max(10000, 20 * target_conflicts)
    attempts = 0
    while len(conflicts) < target_conflicts and attempts < max_attempts:
        attempts += 1
        i = rng.randint(1, n)
        j = rng.randint(1, n)
        if i != j:
            conflicts.add((min(i, j), max(i, j)))
            
    return sorted(list(conflicts))

def build_instance(n_items, seed=42):
    items = generate_supplement_list(n_items, seed=seed)
    conflicts = generate_conflicts(items, conflict_density=0.05, seed=seed)
    
    sachet_types = [
        {"id": 1, "name": "Pequeno", "capacity_cm3": 15.0, "cost": 0.50},
        {"id": 2, "name": "Médio",   "capacity_cm3": 35.0, "cost": 0.85},
        {"id": 3, "name": "Grande",  "capacity_cm3": 70.0, "cost": 1.30}
    ]
    
    return {
        "metadata": {
            "description": f"Instância BPP de Sachês Personalizados (n={n_items})",
            "n_items": n_items,
            "max_sachets_m": n_items,
            "max_items_per_sachet_Nmax": 5,
            "seed": seed
        },
        "sachet_types": sachet_types,
        "items": items,
        "conflicts": conflicts
    }

if __name__ == "__main__":
    # Uso: python gerar_instancias.py            -> n = 15, 50, 150
    #      python gerar_instancias.py 300 500    -> tamanhos escolhidos
    tamanhos = [int(a) for a in sys.argv[1:]] or [15, 50, 150]
    os.makedirs(PASTA_RESULTADOS, exist_ok=True)
    for n in tamanhos:
        inst = build_instance(n_items=n, seed=42 + n)
        file_name = os.path.join(PASTA_RESULTADOS, f"instancia_saches_n{n}.json")
        with open(file_name, "w", encoding="utf-8") as f:
            json.dump(inst, f, indent=2, ensure_ascii=False)
        print(f"Instância n={n} gerada em {file_name}: "
              f"{len(inst['items'])} itens, {len(inst['conflicts'])} conflitos.")