import ast
import math
import operator
from langchain.tools import tool

# AST 安全求值白名单
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}

_SAFE_FUNCS = {
    'abs': abs,
    'round': round,
    'min': min,
    'max': max,
    'sqrt': math.sqrt,
    'log': math.log,
    'log2': math.log2,
    'sin': math.sin,
    'cos': math.cos,
    'tan': math.tan,
    'pi': math.pi,
    'e': math.e,
}

_MAX_EXPONENT = 100  # 项目 7 修复：进一步下调指数上限防止 CPU 耗尽 DoS 攻击

def _safe_eval(node):
    """递归遍历 AST 节点，仅允许白名单操作"""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    elif isinstance(node, ast.BinOp):
        op_func = _SAFE_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"不允许的运算符: {type(node.op).__name__}")
        left, right = _safe_eval(node.left), _safe_eval(node.right)
        
        # 项目 7 修复：除零安全拦截
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and isinstance(right, (int, float)) and right == 0:
            raise ValueError("除数不能为 0")
            
        if isinstance(node.op, ast.Pow) and isinstance(right, (int, float)) and abs(right) > _MAX_EXPONENT:
            raise ValueError(f"指数过大 ({right})，超出安全上限 {_MAX_EXPONENT}")
            
        result = op_func(left, right)
        
        # 项目 7 修复：结果数值溢出拦截防止内存/计算耗尽
        if isinstance(result, (int, float)) and (math.isinf(result) or math.isnan(result) or abs(result) > 1e308):
            raise ValueError("结果溢出，超出计算上限")
        return result
    elif isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.operand))
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        func = _SAFE_FUNCS.get(node.func.id)
        if func is None:
            raise ValueError(f"不允许的函数: {node.func.id}")
        args = [_safe_eval(a) for a in node.args]
        
        # 项目 7 修复：限制多参数函数的参数数量上限
        if node.func.id in ('min', 'max') and len(args) > 8:
            raise ValueError(f"函数 {node.func.id} 最多允许 8 个入参")
            
        result = func(*args)
        if isinstance(result, (int, float)) and (math.isinf(result) or math.isnan(result) or abs(result) > 1e308):
            raise ValueError("结果溢出，超出计算上限")
        return result
    elif isinstance(node, ast.Name) and node.id in _SAFE_FUNCS:
        return _SAFE_FUNCS[node.id]
    else:
        raise ValueError(f"不允许的表达式类型: {type(node).__name__}")

# ==================== 封装计算器工具为 Tool ====================
@tool
def jisuanqi_tool(expression: str) -> str:
    """
    一个用于计算数学表达式的计算器工具。
    适用于：需要精确数值计算、公式求值、内存字节计算、模型参数量相乘等场景。
    输入：标准的 Python 数学表达式，例如 "2**10" 或 "1024 * 1024 * 4"。
    输出：计算结果。
    """
    try:
        clean_expr = expression.strip()
        
        # 限制表达式长度防止拒绝服务
        if len(clean_expr) > 100:
            return "计算失败：表达式超出长度限制（最大 100 字符）。"
            
        # 安全 AST 语法树遍历求值（抵御沙箱逃逸与代码注入）
        tree = ast.parse(clean_expr, mode='eval')
        result = _safe_eval(tree)
        return str(result)
    except Exception as e:
        return f"计算错误：{str(e)}。请确保输入是合法的 Python 数学表达式，例如 '2 ** 10'。"
