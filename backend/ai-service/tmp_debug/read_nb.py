import json
path = r"G:\dev\welove-shop-agt\backend\ai-service\tests\test_check_router.ipynb"
nb = json.load(open(path, encoding="utf-8"))
for i, c in enumerate(nb["cells"]):
    ct = c["cell_type"]
    src = "".join(c["source"])[:400]
    print(f"--- Cell {i} ({ct}) ---")
    print(src)
    print()