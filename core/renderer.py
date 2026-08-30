"""Playwright 异步自适应渲染引擎 - art-template 编译 + DOM 动态边界截图。"""

from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from typing import Any

from .config import scale_pct
from .context import CommandError

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIRS = [
    PLUGIN_ROOT / "resources" / "HTML",
    PLUGIN_ROOT / "resources" / "template",
    PLUGIN_ROOT / "resources" / "help",
]
BASE_HREF_DIR = TEMPLATE_DIRS[0]
RESOURCES_DIR = PLUGIN_ROOT / "resources"


def resources_uri() -> str:
    return RESOURCES_DIR.as_uri().rstrip("/") + "/"


_compile_cache: dict[str, tuple[float, Any]] = {}


def _find_template(name: str) -> Path | None:
    filename = name if name.endswith(".html") else f"{name}.html"
    candidates = [directory / filename for directory in TEMPLATE_DIRS]
    candidates.append(RESOURCES_DIR / filename)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


class JDict(dict):
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    @property
    def length(self) -> int:
        return len(self)


def _wrap(value: Any) -> Any:
    if isinstance(value, dict):
        return JDict({k: _wrap(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_wrap(v) for v in value]
    return value


def _s(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _esc(value: Any) -> str:
    return _s(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _truthy(value: Any) -> bool:
    if value is None or value is False or value == 0 or value == "":
        return False
    if isinstance(value, (list, tuple, dict, set)) and len(value) == 0:
        return True
    return True


def _g(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _idx(obj: Any, key: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (list, tuple)):
        try:
            return obj[int(key)]
        except (ValueError, IndexError):
            return None
    if isinstance(obj, dict):
        return obj.get(key)
    return None


def _iter_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _ln(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (list, tuple, dict, str)):
        return len(value)
    return 0


def _num(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def _cmp(left: Any, op: str, right: Any) -> bool:
    if op in {"===", "=="}:
        return left == right or _s(left) == _s(right)
    if op in {"!==", "!="}:
        return not (left == right or _s(left) == _s(right))
    if left is None or right is None:
        return False
    nl, nr = _num(left), _num(right)
    if op == "<":
        return nl < nr
    if op == "<=":
        return nl <= nr
    if op == ">":
        return nl > nr
    if op == ">=":
        return nl >= nr
    return False


def _arith(left: Any, op: str, right: Any) -> Any:
    if op == "-":
        return _num(left) - _num(right)
    if op == "*":
        return _num(left) * _num(right)
    if op == "/":
        divisor = _num(right)
        if divisor == 0:
            return float("inf")
        return _num(left) / divisor
    if op == "%":
        divisor = _num(right)
        if divisor == 0:
            return 0.0
        return _num(left) % divisor
    return _num(left)


def _concat(left: Any, right: Any) -> Any:
    if isinstance(left, str) or isinstance(right, str):
        return _s(left) + _s(right)
    try:
        return left + right
    except TypeError:
        return _num(left) + _num(right)


def _m(obj: Any, method_name: str, *args: Any) -> Any:
    if obj is None:
        return None
    if method_name == "toFixed":
        digits = int(args[0]) if args else 0
        return f"{_num(obj):.{digits}f}"
    if method_name == "join":
        sep = str(args[0]) if args else ","
        return sep.join(_s(v) for v in _iter_list(obj))
    if method_name == "map" and args:
        return [args[0](item) for item in _iter_list(obj)]
    if method_name == "filter" and args:
        return [item for item in _iter_list(obj) if args[0](item)]
    return None


class _Text:
    __slots__ = ("value",)
    def __init__(self, value: str) -> None: self.value = value


class _Out:
    __slots__ = ("escape", "expr")
    def __init__(self, expr: str, escape: bool) -> None:
        self.expr = expr
        self.escape = escape


class _SetVar:
    __slots__ = ("expr", "name")
    def __init__(self, name: str, expr: str) -> None:
        self.name = name
        self.expr = expr


class _If:
    __slots__ = ("branches",)
    def __init__(self) -> None:
        self.branches: list[tuple[str | None, list]] = []


class _Each:
    __slots__ = ("body", "idx", "seq", "var")
    def __init__(self, seq_expr: str, var: str, idx: str, body: list) -> None:
        self.seq = seq_expr
        self.var = var
        self.idx = idx
        self.body = body


_COMBINED_RE = re.compile(
    r"\{\{(?:(?!<\?)(.*?))\}\}|\<\?(=?)(.*?)\?\>", re.DOTALL
)
_EXTEND_RE = re.compile(r"^\s*\{\{extend\s+(?:'[^']+'|\"[^\"]+\"|\w+)\}\}")
_BLOCK_DEF_RE = re.compile(r"\{\{block\s+'([\w-]+)'\s*\}\}(.*?)\{\{/block\}\}", re.DOTALL)
_LAYOUT_PATH = RESOURCES_DIR / "common" / "layout" / "default.html"


def _resolve_layout(source: str) -> str:
    match = _EXTEND_RE.match(source)
    if not match or not _LAYOUT_PATH.exists():
        return source
    found: dict[str, str] = {}
    def repl(m):
        found[m.group(1)] = m.group(2)
        return ""
    _BLOCK_DEF_RE.sub(repl, source[match.end():])
    layout = _LAYOUT_PATH.read_text(encoding="utf-8")
    return _BLOCK_DEF_RE.sub(lambda m: found.get(m.group(1), m.group(2)), layout)


class _Tokenizer:
    def __init__(self, text: str) -> None:
        self.tokens = self._tokenize(text)
        self.pos = 0

    def _tokenize(self, text: str) -> list[tuple[str, str]]:
        toks = []
        scanner = re.Scanner([
            (r"\s+", None),
            (r"\b(?:true|false|null|undefined)\b", lambda s, t: ("keyword", t)),
            (r"(?:\d+\.\d+|\d+)", lambda s, t: ("number", t)),
            (r"'[^']*'|\"[^\"]*\"", lambda s, t: ("string", t)),
            (r"`[^`]*`", lambda s, t: ("template_str", t)),
            (r"[a-zA-Z_$][a-zA-Z0-9_$]*", lambda s, t: ("ident", t)),
            (r"===|!==|==|!=|<=|>=|=>|\?\.|&&|\|\||[-+*/%?:!.<>=(),\[\]{}]", lambda s, t: ("punct", t)),
        ])
        results, remainder = scanner.scan(text)
        if remainder.strip():
            toks.extend(results)
            toks.append(("ident", remainder.strip()))
        else:
            toks.extend(results)
        return toks

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self) -> tuple[str, str]:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def eat(self, val: str) -> bool:
        if self.pos < len(self.tokens) and self.tokens[self.pos][1] == val:
            self.pos += 1
            return True
        return False


class ExprCompiler:
    def __init__(self, bound: set[str]) -> None:
        self.bound = bound

    def compile(self, expr: str) -> str:
        self.tokens = _Tokenizer(expr)
        res = self.parse_ternary()
        return res

    def parse_ternary(self) -> str:
        cond = self.parse_logical_or()
        if self.tokens.eat("?"):
            true_expr = self.parse_ternary()
            if not self.tokens.eat(":"):
                return f"({true_expr} if _truthy({cond}) else None)"
            false_expr = self.parse_ternary()
            return f"({true_expr} if _truthy({cond}) else {false_expr})"
        return cond

    def parse_logical_or(self) -> str:
        left = self.parse_logical_and()
        while self.tokens.eat("||"):
            right = self.parse_logical_and()
            left = f"({left} if _truthy({left}) else {right})"
        return left

    def parse_logical_and(self) -> str:
        left = self.parse_relational()
        while self.tokens.eat("&&"):
            right = self.parse_relational()
            left = f"({right} if _truthy({left}) else {left})"
        return left

    def parse_relational(self) -> str:
        left = self.parse_additive()
        tok = self.tokens.peek()
        if tok and tok[1] in {"===", "==", "!==", "!=", "<", "<=", ">", ">="}:
            self.tokens.next()
            right = self.parse_additive()
            return f"_cmp({left}, '{tok[1]}', {right})"
        return left

    def parse_additive(self) -> str:
        left = self.parse_multiplicative()
        while True:
            tok = self.tokens.peek()
            if tok and tok[1] in {"+", "-"}:
                self.tokens.next()
                right = self.parse_multiplicative()
                if tok[1] == "+":
                    left = f"_concat({left}, {right})"
                else:
                    left = f"_arith({left}, '-', {right})"
            else:
                return left

    def parse_multiplicative(self) -> str:
        left = self.parse_unary()
        while True:
            tok = self.tokens.peek()
            if tok and tok[1] in {"*", "/", "%"}:
                self.tokens.next()
                right = self.parse_unary()
                left = f"_arith({left}, '{tok[1]}', {right})"
            else:
                return left

    def parse_unary(self) -> str:
        tok = self.tokens.peek()
        if tok and tok[1] == "!":
            self.tokens.next()
            return f"(not _truthy({self.parse_unary()}))"
        if tok and tok[1] == "-":
            self.tokens.next()
            return f"(-{self.parse_unary()})"
        return self.parse_postfix()

    def parse_postfix(self) -> str:
        expr = self.parse_primary()
        while True:
            tok = self.tokens.peek()
            if not tok:
                return expr
            if tok[1] in {".", "?."}:
                self.tokens.next()
                ntok = self.tokens.next()
                name = ntok[1].lstrip("$")
                nxt = self.tokens.peek()
                if nxt and nxt[1] == "(":
                    args = self.parse_args()
                    expr = f"_m({expr}, '{name}'{args})"
                elif name == "length":
                    expr = f"_ln({expr})"
                else:
                    expr = f"_g({expr}, '{name}')"
            elif tok[1] == "[":
                self.tokens.next()
                key = self.parse_ternary()
                self.tokens.eat("]")
                expr = f"_idx({expr}, {key})"
            else:
                return expr

    def parse_args(self) -> str:
        self.tokens.eat("(")
        parts = []
        while not self.tokens.eat(")"):
            tok = self.tokens.peek()
            if tok and tok[0] == "ident":
                self.tokens.next()
                if self.tokens.eat("=>"):
                    body = self.parse_ternary()
                    parts.append(f"(lambda {tok[1]}: {body})")
                else:
                    self.tokens.pos -= 1
                    parts.append(self.parse_ternary())
            else:
                parts.append(self.parse_ternary())
            if not self.tokens.eat(","):
                self.tokens.eat(")")
                break
        return ", " + ", ".join(parts) if parts else ""

    def parse_primary(self) -> str:
        tok = self.tokens.next()
        if tok[0] == "number":
            return tok[1]
        if tok[0] == "string":
            return repr(tok[1][1:-1])
        if tok[0] == "keyword":
            return {"true": "True", "false": "False", "null": "None", "undefined": "None"}.get(tok[1], "None")
        if tok[0] == "ident":
            name = tok[1].lstrip("$")
            return name if name in self.bound else f"__ctx.get('{name}')"
        if tok[1] == "(":
            e = self.parse_ternary()
            self.tokens.eat(")")
            return e
        return "None"


def _parse_structure(segments: list[Any]) -> list:
    root: list = []
    stack: list[tuple[str, Any, list]] = [("root", None, root)]
    for seg in segments:
        if isinstance(seg, _Text):
            stack[-1][2].append(seg)
            continue
        kind, payload = seg
        if kind == "RAW":
            stack[-1][2].append(_Out(payload, escape=False))
            continue
        inner = payload.strip()
        lowered = inner.lower()
        if lowered.startswith("if "):
            node = _If()
            b = []
            node.branches.append((inner[3:].strip(), b))
            stack[-1][2].append(node)
            stack.append(("if", node, b))
        elif lowered.startswith("each "):
            parts = inner[5:].strip().split()
            if len(parts) >= 2 and parts[1] == "as":
                parts = [parts[0], *parts[2:]]
            seq = parts[0] if parts else "_none_"
            var = parts[1].lstrip("$") if len(parts) > 1 else "value"
            idx = parts[2].lstrip("$") if len(parts) > 2 else "index"
            node = _Each(seq, var, idx, [])
            stack[-1][2].append(node)
            stack.append(("each", node, node.body))
        elif lowered.startswith("else"):
            cont = stack[-1][1]
            if not isinstance(cont, _If):
                continue
            b = []
            c = inner[4:].strip()[3:].strip() if lowered.startswith("else if") else None
            cont.branches.append((c, b))
            stack[-1] = (stack[-1][0], cont, b)
        elif lowered in {"/if", "/each", "/block"}:
            if len(stack) > 1:
                stack.pop()
        elif lowered.startswith("set "):
            m = re.match(r"^set\s+(\w+)\s*=\s*(.+)$", inner)
            if m:
                stack[-1][2].append(_SetVar(m.group(1), m.group(2)))
        elif lowered.startswith("block "):
            b = []
            node = _If()
            node.branches.append(("True", b))
            stack[-1][2].append(node)
            stack.append(("block", node, b))
        else:
            stack[-1][2].append(_Out(inner, escape=True))
    return root


class _CodeGen:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.bound: set[str] = set()

    def emit(self, indent: int, line: str) -> None:
        self.lines.append("    " * indent + line)

    def walk(self, nodes: list, indent: int) -> None:
        for node in nodes:
            if isinstance(node, _Text):
                if node.value:
                    self.emit(indent, f"__out.append({repr(node.value)})")
            elif isinstance(node, _Out):
                expr = ExprCompiler(self.bound).compile(node.expr)
                fn = "_esc" if node.escape else "_s"
                self.emit(indent, f"__out.append({fn}({expr}))")
            elif isinstance(node, _SetVar):
                expr = ExprCompiler(self.bound).compile(node.expr)
                self.emit(indent, f"{node.name} = {expr}")
                self.bound.add(node.name)
            elif isinstance(node, _If):
                for idx, (cond, body) in enumerate(node.branches):
                    keyword = "if" if idx == 0 else ("elif" if cond else "else")
                    if cond:
                        c_expr = ExprCompiler(self.bound).compile(cond)
                        self.emit(indent, f"{keyword} _truthy({c_expr}):")
                    else:
                        self.emit(indent, "else:")
                    mark = len(self.lines)
                    self.walk(body, indent + 1)
                    if len(self.lines) == mark:
                        self.emit(indent + 1, "pass")
            elif isinstance(node, _Each):
                seq = ExprCompiler(self.bound).compile(node.seq)
                self.emit(indent, f"for {node.idx}, {node.var} in enumerate(_iter_list({seq})):")
                saved = set(self.bound)
                self.bound.update({node.var, node.idx})
                mark = len(self.lines)
                self.walk(node.body, indent + 1)
                if len(self.lines) == mark:
                    self.emit(indent + 1, "pass")
                self.bound = saved


def compile_template(source: str) -> Any:
    source = _resolve_layout(source)
    segments = []
    pos = 0
    for match in _COMBINED_RE.finditer(source):
        if match.start() > pos:
            segments.append(_Text(source[pos : match.start()]))
        art_inner, _, ejs_inner = match.group(1), match.group(2), match.group(3)
        inner = (ejs_inner or art_inner or "").strip()
        if inner.startswith("@"):
            segments.append(("RAW", inner[1:]))
        else:
            segments.append(("EXPR", inner))
        pos = match.end()
    if pos < len(source):
        segments.append(_Text(source[pos:]))

    tree = _parse_structure(segments)
    gen = _CodeGen()
    gen.emit(1, "__out = []")
    gen.walk(tree, 1)
    body = "\n".join(gen.lines) or "__out = []"
    program = f"def __render(__ctx):\n{body}\n    return ''.join(__out)\n"
    ns = {
        "_truthy": _truthy, "_esc": _esc, "_s": _s, "_g": _g, "_idx": _idx,
        "_iter_list": _iter_list, "_ln": _ln, "_num": _num, "_cmp": _cmp,
        "_arith": _arith, "_concat": _concat, "_m": _m
    }
    exec(program, ns)
    fn = ns["__render"]

    def runner(data: dict) -> str:
        return fn(_wrap(data or {}))
    return runner


def get_runner(name: str) -> Any:
    path = _find_template(name)
    if path is None:
        raise FileNotFoundError(f"template not found: {name}")
    mtime = path.stat().st_mtime
    cached = _compile_cache.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    runner = compile_template(path.read_text(encoding="utf-8"))
    _compile_cache[str(path)] = (mtime, runner)
    return runner


def render_template(name: str, data: dict) -> str:
    return get_runner(name)(data)


class Renderer:
    def __init__(self, out_dir: Path | None = None) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._lock = asyncio.Lock()
        self.out_dir = out_dir or (PLUGIN_ROOT / "resources" / "data" / "_runtime" / "images")
        self.out_dir.mkdir(parents=True, exist_ok=True)

    async def _ensure_browser(self) -> None:
        if self._browser is not None and self._browser.is_connected():
            return
        if self._playwright is None:
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise CommandError(
                    "图片渲染组件未安装。请执行：pip install playwright && playwright install chromium"
                ) from exc
            self._playwright = await async_playwright().start()
        scale = scale_pct()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 800, "height": 600},
            device_scale_factor=max(0.5, min(2.5, scale)),
        )

    async def render_image(self, template_name: str, data: dict, options: dict | None = None) -> str:
        html_text = render_template(template_name, data)
        return await self.render_html(html_text, options=options)

    async def render_html(self, html_text: str, options: dict | None = None) -> str:
        options = options or {}
        async with self._lock:
            await self._ensure_browser()
            page = await self._context.new_page()
            tmp_path: Path | None = None
            try:
                stem = uuid.uuid4().hex[:12]
                tmp_path = self.out_dir / f"page_{stem}.html"
                tmp_path.write_text(self._inject_base(html_text), encoding="utf-8")
                await page.goto(tmp_path.as_uri(), wait_until="networkidle")
                try:
                    await page.evaluate("document.fonts.ready.then(() => true)")
                except Exception:
                    pass
                await page.wait_for_timeout(int(options.get("delay_ms", 150)))
                out_file = self.out_dir / f"{options.get('filename') or stem}.png"

                target_loc = None
                selectors = [
                    "#container", ".container", ".user-info", ".gift-container",
                    ".farm-container", ".lottery-container", ".property-container",
                    ".panel", ".help-box", ".main-box", ".status-box", "#app",
                    "body > div:not(.deco):not(.scanline):first-of-type"
                ]
                for sel in selectors:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        box = await loc.bounding_box()
                        if box and box["width"] >= 50 and box["height"] >= 50:
                            target_loc = loc
                            break

                if target_loc is not None and not options.get("force_full_page"):
                    await target_loc.screenshot(path=str(out_file), type="png")
                else:
                    dims = await page.evaluate("""() => ({
                        width: Math.max(document.body.scrollWidth, document.documentElement.scrollWidth, 600),
                        height: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight, 400)
                    })""")
                    await page.set_viewport_size({"width": int(dims["width"]), "height": int(dims["height"])})
                    await page.screenshot(path=str(out_file), full_page=True, type="png")
                return str(out_file)
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
                if tmp_path and tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass

    @staticmethod
    def _inject_base(html_text: str) -> str:
        base_tag = f'<base href="{BASE_HREF_DIR.as_uri()}/">'
        if "<base " in html_text:
            return html_text
        if "</head>" in html_text.lower():
            idx = html_text.lower().index("</head>")
            return html_text[:idx] + base_tag + html_text[idx:]
        if "<head>" in html_text.lower():
            idx = html_text.lower().index("<head>") + len("<head>")
            return html_text[:idx] + base_tag + html_text[idx:]
        return f"{base_tag}\n{html_text}"

    async def shutdown(self) -> None:
        for attr in ("_context", "_browser"):
            obj = getattr(self, attr, None)
            if obj is not None:
                try:
                    await obj.close()
                except Exception:
                    pass
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass


renderer = Renderer()
