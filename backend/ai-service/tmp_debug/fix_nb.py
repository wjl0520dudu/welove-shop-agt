import json

path = r"G:\dev\welove-shop-agt\backend\ai-service\tests\test_check_router.ipynb"
nb = json.load(open(path, encoding="utf-8"))

# Fix cell 4 typo: "uestion" -> "question"
c4 = nb["cells"][4]
old = "".join(c4["source"])
fixed = old.replace("uestion =", "question =")
c4["source"] = [fixed]

# Insert a new cell after cell 4 for the "我刚刚问了什么问题？" test
# Actually just fix the existing cell

json.dump(nb, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# Verify
nb2 = json.load(open(path, encoding="utf-8"))
print("Fixed cell 4:", repr("".join(nb2["cells"][4]["source"])))