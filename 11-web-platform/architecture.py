# 아키텍처 fitness function: 레거시 템플릿 표면을 freeze (core/architecture.py)
# 포트폴리오용으로 sanitize 되었습니다: 내부 endpoint/키/제품 특정 내용 제거.

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# 현재 남아 있는 서버 렌더링 화면을 명시적으로 관리한다.
# 이 목록 밖에서 render()가 추가되면 프론트 분리 방향을 거스르는 것으로 본다.
LEGACY_TEMPLATE_RENDERERS = frozenset({
})


def iter_api_surface_files():
    yield REPO_ROOT / "config" / "api_urls.py"
    for path in sorted((REPO_ROOT / "apps").glob("*/api_urls.py")):
        yield path
    for path in sorted((REPO_ROOT / "apps").glob("*/api_views.py")):
        yield path


def iter_project_python_files():
    for path in sorted((REPO_ROOT / "apps").rglob("*.py")):
        yield path


def find_template_renderer_functions(paths):
    usages = set()
    for path in paths:
        try:
            tree = ast.parse(path.read_text())
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _function_uses_render(node):
                usages.add(f"{_module_name(path)}:{node.name}")
    return usages


def _function_uses_render(node):
    for subnode in ast.walk(node):
        if not isinstance(subnode, ast.Call):
            continue

        func = subnode.func
        if isinstance(func, ast.Name) and func.id == "render":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "render":
            return True
    return False


def _module_name(path):
    relative = path.relative_to(REPO_ROOT)
    return ".".join(relative.with_suffix("").parts)
