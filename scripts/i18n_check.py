"""Çeviri denetimi: verilen kaynak dosyalarda `tx("...")` / `N_("...")` anahtarlarının İngilizce karşılığı var mı; verilen katalog dosyasında kullanılmayan anahtar var mı.

Kullanım:
  python scripts/i18n_check.py server/steps/handlers.py [diğer dosyalar...] [--catalog server/locales/en_steps.py]
  python scripts/i18n_check.py --residue server/steps/handlers.py     # sarılmamış Türkçe metin parçalarını listeler (çeviri adayları)
"""
import ast
import importlib.util
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
CALLEES = {"_", "translate", "N_", "tx"}
TR_CH = re.compile("[ığüşöçİĞÜŞÖÇ]")
TR_WORD = re.compile(r"(görev|kabul|adım|yönetici|ajan|teslim|doğrulama|kullanıcı|karar|sprint|toplantı)", re.I)


def TR_search(t):
    return TR_CH.search(t) or TR_WORD.search(t)


def load_catalog(path):
    spec = importlib.util.spec_from_file_location("cat", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "EN", {})


def merged_catalog():
    out = {}
    d = os.path.join(ROOT, "server", "locales")
    for name in sorted(os.listdir(d)):
        if name.startswith("en_") and name.endswith(".py"):
            out.update(load_catalog(os.path.join(d, name)))
    return out


def used_keys(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args:
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
            arg = node.args[0]
            if name in CALLEES and isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                out.setdefault(arg.value, node.lineno)
    return out


def residue(path):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    wrapped = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args:
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
            if name in CALLEES:
                for sub in ast.walk(node.args[0]):
                    wrapped.add(id(sub))
    docs = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body and isinstance(n.body[0], ast.Expr) \
                and isinstance(getattr(n.body[0], "value", None), ast.Constant) and isinstance(n.body[0].value.value, str):
            docs.add(id(n.body[0].value))
    rows = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in wrapped and id(n) not in docs and TR_search(n.value) and len(n.value) > 3:
            rows.append((n.lineno, n.value[:100].replace("\n", "\\n")))
    return sorted(rows)


def main(argv):
    show_residue = "--residue" in argv
    catalog_path = None
    files = []
    it = iter(argv)
    for a in it:
        if a == "--catalog":
            catalog_path = next(it)
        elif not a.startswith("--"):
            files.append(a)
    cat = merged_catalog()
    bad = 0
    used_all = {}
    for f in files:
        keys = used_keys(f)
        used_all.update(keys)
        miss = [(ln, k) for k, ln in keys.items() if not str(cat.get(k, "")).strip()]
        for ln, k in sorted(miss):
            print(f"MISSING {f}:{ln} {k[:90]!r}")
            bad += 1
        if show_residue:
            for ln, t in residue(f):
                print(f"RESIDUE {f}:{ln} {t!r}")
        print(f"{f}: {len(keys)} marked texts, {len(miss)} without translation")
    if catalog_path:
        own = load_catalog(catalog_path)
        unused = [k for k in own if k not in used_all]
        for k in unused[:30]:
            print(f"UNUSED-IN-CHECKED-FILES {k[:90]!r}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
