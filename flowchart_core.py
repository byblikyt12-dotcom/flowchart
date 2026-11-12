"""Ядро генератора блок-схем (ГОСТ 19.701-90): код Python -> SVG.
Запускается в браузере телефона через Pyodide, сервер не нужен."""
import ast
import json
import re
import textwrap
from html import escape
CW, LH = 7.4, 16                      # ширина символа / высота строки (шрифт 12px)
GV, GH, RAIL, PAD = 34, 44, 26, 30    # отступы: вертикаль, горизонталь, рельсы, поля


def wrap(text, width):
    out = []
    for line in str(text).split("\n"):
        out += textwrap.wrap(line, width, break_long_words=True, break_on_hyphens=False) or [""]
    return out


class Node:
    """kind: proc | io | call | term | if | loop | break | continue"""

    def __init__(self, kind, text="", then=None, els=None):
        self.kind, self.text, self.then, self.els, self.w = kind, text, then or [], els or [], 0

    def fit(self):
        if self.w:
            return
        k = self.kind
        if k in ("if", "loop"):
            self.ls = wrap(self.text, 20)
            tw, th = max(map(len, self.ls)) * CW, len(self.ls) * LH
            self.w = max(150, tw * (1.45 if len(self.ls) == 1 else 1.8) + 24)
            self.h = max(64, th * 2 + 24)
        else:
            self.ls = wrap(self.text, 46)
            tw = max(map(len, self.ls)) * CW
            if k == "term":
                self.w, self.h = max(150, tw + 40), max(40, len(self.ls) * LH + 20)
            else:
                extra = {"io": 40, "call": 24}.get(k, 0)
                self.w, self.h = max(150, tw + 28 + extra), max(44, len(self.ls) * LH + 20)


def ext_seq(items):
    l = r = 0
    for it in items:
        a, b = ext(it)
        l, r = max(l, a), max(r, b)
    return l, r


def ext(it):
    """Ширина блока влево/вправо от его вертикальной оси."""
    it.fit()
    half = it.w / 2
    if it.kind == "if":
        yl, yr = ext_seq(it.then)
        off = max(half, yr) + GH
        if it.els:
            nl, nr = ext_seq(it.els)
            return max(half, yl), off + nl + nr
        return max(half, yl), off
    if it.kind == "loop":
        bl, br = ext_seq(it.then)
        return max(half, bl) + RAIL, max(half, br) + RAIL
    return half, half


class Chart:
    def __init__(self):
        self.parts, self.loops, self.maxy = [], [], 0
        self.x0 = self.y0 = 1e9
        self.x1 = self.y1 = -1e9

    def bound(self, x, y):
        self.x0, self.x1 = min(self.x0, x), max(self.x1, x)
        self.y0, self.y1 = min(self.y0, y), max(self.y1, y)
        self.maxy = max(self.maxy, y)

    def line(self, pts, arrow=False):
        for x, y in pts:
            self.bound(x, y)
        p = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        m = ' marker-end="url(#a)"' if arrow else ""
        self.parts.append(f'<polyline points="{p}" class="l"{m}/>')

    def label(self, x, y, s):
        self.parts.append(f'<text x="{x:.1f}" y="{y:.1f}" class="lab">{s}</text>')

    def shape(self, it, cx, y):
        it.fit()
        w, h, k = it.w, it.h, it.kind
        x = cx - w / 2
        self.bound(x, y)
        self.bound(x + w, y + h)

        def poly(pts):
            return '<polygon points="%s" class="s"/>' % " ".join(f"{a:.1f},{b:.1f}" for a, b in pts)

        if k == "term":
            s = f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{h/2:.1f}" class="s"/>'
        elif k == "io":
            s = poly([(x + 18, y), (x + w, y), (x + w - 18, y + h), (x, y + h)])
        elif k in ("if", "loop"):
            s = poly([(cx, y), (x + w, y + h / 2), (cx, y + h), (x, y + h / 2)])
        else:
            s = f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" class="s"/>'
            if k == "call":
                s += "".join(
                    f'<line x1="{x+d:.1f}" y1="{y:.1f}" x2="{x+d:.1f}" y2="{y+h:.1f}" class="l"/>'
                    for d in (10, w - 10)
                )
        self.parts.append(s)
        y0 = y + h / 2 - (len(it.ls) - 1) * LH / 2 + 4
        for i, l in enumerate(it.ls):
            self.parts.append(f'<text x="{cx:.1f}" y="{y0 + i*LH:.1f}" class="t">{escape(l)}</text>')

    # ---- раскладка ----
    def seq(self, items, cx, y):
        """Цепочка блоков; y — верх первого. Возвращает y низа или None (ветка завершена)."""
        cur = None
        for i, it in enumerate(items):
            top = y
            if i:
                self.line([(cx, cur), (cx, cur + GV)], True)
                top = cur + GV
            cur = self.item(it, cx, top)
            if cur is None:
                return None
        return cur

    def item(self, it, cx, y):
        it.fit()
        k = it.kind
        if k == "if":
            return self.d_if(it, cx, y)
        if k == "loop":
            return self.d_loop(it, cx, y)
        self.shape(it, cx, y)
        mid = y + it.h / 2
        if k == "term":
            return None
        if k in ("break", "continue") and self.loops:
            L = self.loops[-1]
            if k == "break":
                self.line([(cx + it.w / 2, mid), (L["r"], mid)], True)
            else:
                self.line([(cx - it.w / 2, mid), (L["l"], mid)])
                L["cont"].append(mid)
            return None
        return y + it.h

    def d_if(self, it, cx, y):
        half = it.w / 2
        self.shape(it, cx, y)
        cy, bot = y + it.h / 2, y + it.h
        top = bot + GV
        yl, yr = ext_seq(it.then)
        off = max(half, yr) + GH
        nx = cx + off + (ext_seq(it.els)[0] if it.els else 0)
        old, self.maxy = self.maxy, bot
        self.label(cx + 6, bot + 14, "Да")
        self.label(cx + half + 8, cy - 6, "Нет")
        if it.then:
            self.line([(cx, bot), (cx, top)], True)
            ye = self.seq(it.then, cx, top)
        else:
            ye = bot
        if it.els:
            self.line([(cx + half, cy), (nx, cy), (nx, top)], True)
            ne = self.seq(it.els, nx, top)
        else:
            self.line([(cx + half, cy), (nx, cy)])
            ne = cy
        j = self.maxy + GV / 2
        self.maxy = max(old, self.maxy)
        if ye is None and ne is None:
            return None
        if ye is not None:
            self.line([(cx, ye), (cx, j)])
        if ne is not None:
            self.line([(nx, ne), (nx, j), (cx, j)])
        return j

    def d_loop(self, it, cx, y):
        half = it.w / 2
        self.shape(it, cx, y)
        cy, bot = y + it.h / 2, y + it.h
        bl, br = ext_seq(it.then)
        L = {"l": cx - max(half, bl) - RAIL, "r": cx + max(half, br) + RAIL, "cont": []}
        self.label(cx + 6, bot + 14, "Да")
        self.label(cx + half + 8, cy - 6, "Нет")
        old, self.maxy = self.maxy, bot
        self.loops.append(L)
        if it.then:
            self.line([(cx, bot), (cx, bot + GV)], True)
            be = self.seq(it.then, cx, bot + GV)
        else:
            be = bot
        self.loops.pop()
        low = self.maxy
        yb = low + GV / 2
        if be is not None:
            self.line([(cx, be), (cx, yb), (L["l"], yb), (L["l"], cy), (cx - half, cy)], True)
        elif L["cont"]:
            self.line([(L["l"], max(L["cont"])), (L["l"], cy), (cx - half, cy)], True)
        ye = low + GV
        self.line([(cx + half, cy), (L["r"], cy), (L["r"], ye), (cx, ye)])
        self.maxy = max(old, self.maxy)
        return ye


def build_chart(start, items):
    c = Chart()
    s = Node("term", start)
    s.fit()
    c.shape(s, 0, 0)
    e = s.h
    if items:
        c.line([(0, e), (0, e + GV)], True)
        e = c.seq(items, 0, e + GV)
    if e is not None:
        end = Node("term", "Конец")
        end.fit()
        c.line([(0, e), (0, e + GV)], True)
        c.shape(end, 0, e + GV)
    x0, y0 = c.x0 - PAD, c.y0 - PAD
    w, h = c.x1 - c.x0 + 2 * PAD, c.y1 - c.y0 + 2 * PAD
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" viewBox="{x0:.1f} {y0:.1f} {w:.1f} {h:.1f}">'
        '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
        '<path d="M0,0L10,5L0,10z" fill="#111"/></marker></defs>'
        '<style>.l{fill:none;stroke:#111;stroke-width:1.2}.s{fill:#fff;stroke:#111;stroke-width:1.2}'
        '.t{font:12px Consolas,"DejaVu Sans Mono",monospace;fill:#111;text-anchor:middle}'
        '.lab{font:bold 11px Consolas,"DejaVu Sans Mono",monospace;fill:#111}</style>'
        f'<rect class="bg" x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" fill="#fff"/>'
        + "".join(c.parts) + "</svg>"
    )
    return {"svg": svg, "w": round(w), "h": round(h)}


# ---- AST -> узлы ----
def call_name(n):
    f = n.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def pretty(t):
    """Код Python -> математическая запись для блок-схемы."""
    t = re.sub(r"\btan\(", "tg(", t)
    t = re.sub(r"\bfabs\(", "abs(", t)
    return t.replace("**", "^")


def is_const(v):
    if isinstance(v, ast.UnaryOp) and isinstance(v.op, (ast.USub, ast.UAdd)):
        v = v.operand
    return isinstance(v, ast.Constant) and isinstance(v.value, (int, float))


def out_text(a):
    if isinstance(a, ast.Constant) and isinstance(a.value, str):
        return a.value
    return pretty(ast.unparse(a))


def conv(stmts, funcs):
    out = []

    def proc(t):
        if out and out[-1].kind == "proc":
            out[-1].text += "\n" + t
        else:
            out.append(Node("proc", t))

    for s in stmts:
        if isinstance(s, (ast.Import, ast.ImportFrom, ast.Pass, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str):
            continue  # докстринг
        if isinstance(s, ast.If):
            out.append(Node("if", pretty(ast.unparse(s.test)), conv(s.body, funcs), conv(s.orelse, funcs)))
        elif isinstance(s, (ast.While, ast.For, ast.AsyncFor)):
            t = ast.unparse(s.test) if isinstance(s, ast.While) else f"{ast.unparse(s.target)} in {ast.unparse(s.iter)}"
            out.append(Node("loop", t, conv(s.body, funcs)))
            out += conv(s.orelse, funcs)
        elif isinstance(s, ast.Break):
            out.append(Node("break", "break"))
        elif isinstance(s, ast.Continue):
            out.append(Node("continue", "continue"))
        elif isinstance(s, (ast.Return, ast.Raise)):
            out.append(Node("term", ast.unparse(s)))
        elif isinstance(s, (ast.With, ast.AsyncWith)):
            proc("with " + ", ".join(ast.unparse(i) for i in s.items))
            out += conv(s.body, funcs)
        elif isinstance(s, ast.Try):
            out += conv(s.body, funcs)
            for h in s.handlers:
                out.append(Node("if", "except " + (ast.unparse(h.type) if h.type else "Exception"), conv(h.body, funcs)))
            out += conv(s.orelse, funcs) + conv(s.finalbody, funcs)
        else:
            names = {call_name(n) for n in ast.walk(s) if isinstance(n, ast.Call)}
            kind, label = "proc", pretty(ast.unparse(s))
            if isinstance(s, ast.Assign) and is_const(s.value) and all(isinstance(t, ast.Name) for t in s.targets):
                item = " = ".join([t.id for t in s.targets] + [pretty(ast.unparse(s.value))])
                if out and out[-1].kind == "io" and getattr(out[-1], "data", False):
                    out[-1].text += "; " + item
                else:
                    nd = Node("io", "Ввод " + item)
                    nd.data = True
                    out.append(nd)
                continue
            if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call) and call_name(s.value) == "print":
                args = s.value.args
                keep = [a for a in args if not (isinstance(a, ast.Constant) and isinstance(a.value, str)
                                                and a.value.rstrip().endswith("="))] or args
                kind, label = "io", "Вывод " + (", ".join(out_text(a) for a in keep) or "")
            elif "input" in names:
                kind = "io"
                label = "Ввод " + (", ".join(ast.unparse(t) for t in s.targets) if isinstance(s, ast.Assign) else "")
            elif names & funcs and isinstance(s, (ast.Expr, ast.Assign)):
                kind = "call"
            if kind == "proc":
                proc(label)
            else:
                out.append(Node(kind, label))
    return out


def build_all(code):
    tree = ast.parse(code)
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    names = {f.name for f in funcs}
    top = [n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    charts = []
    if top:
        charts.append({"title": "Основная программа", **build_chart("Начало", conv(top, names))})
    for f in funcs:
        args = ", ".join(a.arg for a in f.args.args)
        charts.append({"title": f"Функция {f.name}", **build_chart(f"{f.name}({args})", conv(f.body, names))})
    return charts

def build_json(code):
    try:
        result = {"charts": build_all(code)}
    except SyntaxError as e:
        result = {"error": f"Синтаксическая ошибка в строке {e.lineno}: {e.msg}"}
    except Exception as e:
        result = {"error": f"Ошибка: {e}"}
    return json.dumps(result, ensure_ascii=False)
