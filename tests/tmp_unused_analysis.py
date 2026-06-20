import ast
import glob
import re
from collections import defaultdict

files = sorted(glob.glob('**/*.py', recursive=True))
all_src = {f: open(f, encoding='utf-8').read() for f in files}

def get_defs(src):
    tree = ast.parse(src)
    return [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))]

refs = defaultdict(set)
for f, src in all_src.items():
    for tok in set(re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\b', src)):
        refs[tok].add(f)

for f in files:
    defs = get_defs(all_src[f])
    for name in defs:
        if name in ('main', '__init__', '__main__'):
            continue
        cross = [path for path in refs.get(name, []) if path != f]
        if not cross:
            print('UNUSED_DEF', f, name, 'refs', sorted(refs.get(name, [])))
