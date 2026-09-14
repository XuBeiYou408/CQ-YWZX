# -*- coding: utf-8 -*-
"""
企业知识库 MCP 一键安装脚本（随项目分发，换电脑直接运行本脚本即可）。

功能（全部幂等，可重复运行）：
  1. 检查/创建项目 venv 并安装依赖（requirements.txt，含 torch/faiss 等，首次较久），
     并做 mcp 版本兼容性体检（2.x 移除了 mcp.server.fastmcp，会致服务 import 即崩，
     检测到不兼容会自动降级修复）
  2. 检查/预取 BGE 嵌入模型（约 400MB，不在 git 中；缺失则从 hf-mirror 提前下载）
  3. 把 enterprise-knowledge-base 注册进 WorkBuddy 的 mcp.json（合并，不动其他服务）
  4. 把 deploy/skills/enterprise-kb-query 部署为用户级 Skill（~/.workbuddy/skills/）
  5. 向 ~/.workbuddy/MEMORY.md 写入企业知识库路由规则（带标记，幂等 upsert）
  6. 检查 WorkBuddy 信任状态 + 端到端体检（真实启动本项目的 MCP 服务，
     协议握手计时、列出工具、实际检索"年假制度"一次）——不依赖 WorkBuddy 即可
     确认服务本身完全可用

用法：
  python install_to_workbuddy.py            # 全部安装 + 体检
  python install_to_workbuddy.py --mcp-only # 只更新 mcp.json（依赖与 Skill 已就绪时用）
  python install_to_workbuddy.py --no-verify # 跳过第 6 步端到端体检

注意：知识库索引会在缺失/损坏时自动重建（源文档在 data/documents，随 git 一起分发）；
      BGE 模型体积大、不随 git 分发，安装时会尝试预取，失败也不阻断（首次检索会自愈）。
      运行需要本机 Python 3.10+ 与联网（首次装依赖与模型）。
"""
import ast
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

# ---------- 路径 ----------
PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / ".venv"
VENV_PY = VENV_DIR / "Scripts" / "python.exe"
WORKBUDDY_DIR = Path.home() / ".workbuddy"
MCP_JSON = WORKBUDDY_DIR / "mcp.json"
SKILL_SRC = PROJECT_ROOT / "deploy" / "skills" / "enterprise-kb-query"
SKILL_DST = WORKBUDDY_DIR / "skills" / "enterprise-kb-query"
MEMORY_MD = WORKBUDDY_DIR / "MEMORY.md"

MCP_ENTRY_NAME = "enterprise-knowledge-base"

# mcp 版本约束：MCP Python SDK 2.x 移除了 mcp.server.fastmcp（改名为 MCPServer，
# 路径迁到 mcp.server.mcpserver 且无兼容别名）。若 venv 中装到 2.x，本项目
# mcp_server.py 会在 import 阶段直接崩溃，客户端只表现为「连接失败」。
# 该约束与 requirements.txt 保持一致，用于安装后的自动体检与自愈。
MCP_SPEC = "mcp>=1.0.0,<2"

# BGE 嵌入模型相对目录（缺失时首次检索会自动从 hf-mirror 下载，此处在安装阶段提前拉取）
EMBED_MODEL_REL = Path("data") / "models" / "bge-base-zh-v1.5"
EMBED_MODEL_REPO = "BAAI/bge-base-zh-v1.5"
MEMORY_MARKER_BEGIN = "# >>> enterprise-kb routes (auto-managed, do not edit between markers)"
MEMORY_MARKER_END = "# <<< enterprise-kb routes (auto-managed)"

# 平台层规则块：两个 MCP 项目共用同一组标记 + 同一份内容，
# 因此先后运行任一项目的安装脚本都不会产生重复段落（后一个只做等值替换）。
MEMORY_MARKER_MCP_BEGIN = "# >>> mcp tool call format (auto-managed, shared by all local MCP projects)"
MEMORY_MARKER_MCP_END = "# <<< mcp tool call format (auto-managed)"

MEMORY_RULES_MCP = """# >>> mcp tool call format (auto-managed, shared by all local MCP projects)

## MCP 工具调用格式（最高优先级·平台层，适用于所有 MCP 工具）

- 本环境所有 MCP 工具（`enterprise-knowledge-base`、`contract-reviewer` 等）都必须通过 **`DeferExecuteTool`** 调用，参数是**两层平级结构**：`toolName`（工具全名，最外层）与 `params`（工具自己的参数，一个对象）。
- ✅ 正确：`DeferExecuteTool({"toolName": "mcp__<服务名>__<工具名>", "params": { ...工具参数... }})`
- ❌ 错误：把 `toolName` 写进 `params` 内部，或把 `params` 再套一层——会返回 `Error: "toolName" is required. Provide the exact tool name as returned by ToolSearch.`
- 口诀：**toolName 和 params 是兄弟，不是父子**。调用失败时先检查 toolName 是否在最外层，不要反复重试同一错误形状。

# <<< mcp tool call format (auto-managed)
"""

MEMORY_RULES = """# >>> enterprise-kb routes (auto-managed, do not edit between markers)

## 企业知识库查询规则（最高优先级）

- 用户所在公司部署了本地企业知识库 MCP 服务 `enterprise-knowledge-base`。
- **凡是用户询问公司内部信息**（年假、休假、考勤、请假、报销、差旅、福利、入职、办公用品、保密、数据安全、专利、公司制度、公司规定、内部流程、员工手册等），**必须**先调用 `ToolSearch` 加载 `mcp__enterprise-knowledge-base__search_knowledge_base` 工具并用它检索，基于检索结果回答。
- **禁止**用 WebSearch/网络搜索来回答公司内部制度问题——公司制度只存在于内部知识库，互联网检索结果不适用且会误导。
- 若工具检索无结果，如实告知"知识库中未找到"，并建议用户确认文档是否已录入知识库（可用 `list_knowledge_documents` 查看已收录文档）。

# <<< enterprise-kb routes (auto-managed)
"""


def out(msg):
    print(msg, flush=True)


def find_base_python():
    """找一个可用的系统 Python（要求 >=3.10）用来创建 venv（优先 py 启动器）。

    要求 3.10+：MCP Python SDK 1.x（FastMCP）与本项目全部依赖均以 3.10 为下限。
    """
    for cmd in (["py", "-3"], ["python"], ["python3"]):
        try:
            r = subprocess.run(cmd + ["-c", "import sys;print(sys.version_info[:2])"],
                               capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                continue
            try:
                major, minor = ast.literal_eval(r.stdout.strip())
            except Exception:
                continue
            if (major, minor) >= (3, 10):
                return cmd
        except Exception:
            continue
    return None


def ensure_mcp_compat() -> bool:
    """确保 venv 里的 mcp 是 1.x（能 import mcp.server.fastmcp）。

    这是「换电脑部署」最容易静默失败的一环：requirements 若未锁 `<2`，
    新机 pip 会装到 2.x，服务在 import 阶段就死。此处做安装后体检 + 自动自愈，
    即使 venv 是别人拷贝/被 `pip install -U mcp` 污染过的也能修回来。
    """
    probe = "from mcp.server.fastmcp import FastMCP"

    def _import_ok() -> bool:
        try:
            r = subprocess.run([str(VENV_PY), "-c", probe],
                               capture_output=True, text=True, timeout=180)
            return r.returncode == 0
        except Exception:
            return False

    if _import_ok():
        out("[1/4] mcp 兼容性体检通过（1.x，包含 mcp.server.fastmcp）")
        return True

    out("[1/4] !! 检测到 mcp 版本不兼容（2.x 已移除 mcp.server.fastmcp），正在自动修复...")
    try:
        r = subprocess.run([str(VENV_PY), "-m", "pip", "install", "--quiet", "--upgrade", MCP_SPEC],
                           timeout=1800)
    except Exception as e:
        out(f"     !! 修复命令执行异常: {e}")
        return False
    if r.returncode == 0 and _import_ok():
        out("     ✅ 已修复：mcp 已回到 1.x，服务可正常启动。")
        return True
    out("     !! 自动修复失败，请手动执行：")
    out(f'        "{VENV_PY}" -m pip install "{MCP_SPEC}"')
    return False


def ensure_kb_assets() -> bool:
    """检查 BGE 嵌入模型是否随项目带过来（非致命）。

    模型体积约 400MB 且在 .gitignore 中——`git clone` 得到的新机不会带模型。
    缺失时检索内核会自动从 hf-mirror 下载（首次检索会明显变慢），此处提前拉取，
    让「首次提问」不必等下载。离线或失败只警告，不影响安装结果。
    """
    target = PROJECT_ROOT / EMBED_MODEL_REL
    if (target / "config.json").exists():
        out(f"[1/4] BGE 嵌入模型已就位: {target}")
        return True

    out(f"[1/4] 未发现 BGE 模型（{EMBED_MODEL_REL}），正在提前下载约 400MB（走 hf-mirror）...")
    code = (
        "import os;"
        "os.environ.setdefault('HF_ENDPOINT','https://hf-mirror.com');"
        "from sentence_transformers import SentenceTransformer;"
        f"m=SentenceTransformer({EMBED_MODEL_REPO!r});"
        f"m.save({str(target)!r});"
        "print('MODEL_SAVED')"
    )
    try:
        r = subprocess.run([str(VENV_PY), "-c", code], cwd=str(PROJECT_ROOT),
                           capture_output=True, text=True, timeout=3600)
        if r.returncode == 0 and "MODEL_SAVED" in r.stdout:
            out("     ✅ BGE 模型下载完成。")
            return True
        out("     ⚠️ 模型下载未完成（可能离线）。不影响安装：首次检索会自动重试下载。")
        if r.stderr:
            out("        详情: " + r.stderr.strip().splitlines()[-1][:160])
    except Exception as e:
        out(f"     ⚠️ 模型下载异常（{e}）。不影响安装：首次检索会自动重试下载。")
    return True


def ensure_venv():
    """确保 venv 存在且可用（venv 不可跨机器拷贝，损坏时自动重建）。"""
    if VENV_PY.exists():
        try:
            chk = subprocess.run([str(VENV_PY), "-c", "import sys;print(sys.version_info[0])"],
                                 capture_output=True, text=True, timeout=60)
            if chk.returncode == 0 and chk.stdout.strip().startswith("3"):
                out(f"[1/4] venv 已存在且可用: {VENV_PY}")
                return ensure_mcp_compat()
        except Exception:
            pass
        import shutil
        shutil.rmtree(VENV_DIR, ignore_errors=True)
        out("[1/4] 检测到 venv 已损坏（多为从其他电脑拷贝所致），已清除并重建...")
    out("[1/4] 未发现 venv，正在新建...")
    base = find_base_python()
    if not base:
        out("    !! 未找到可用的系统 Python 3.10+。")
        out("       请先安装 Python 3.10（推荐 3.12 / 3.13）并勾选 Add to PATH：")
        out("       https://www.python.org/downloads/windows/")
        return False
    r = subprocess.run(base + ["-m", "venv", str(VENV_DIR)], timeout=300)
    if r.returncode != 0:
        out("    !! venv 创建失败。")
        return False
    out("    正在安装依赖（含 torch/faiss 等，体积大，首次约需 10~30 分钟，需联网）...")
    r = subprocess.run([str(VENV_PY), "-m", "pip", "install", "--quiet",
                        "-r", str(PROJECT_ROOT / "requirements.txt")], timeout=7200)
    if r.returncode != 0:
        out("    !! 依赖安装失败，请检查网络后重试：")
        out(f'       "{VENV_PY}" -m pip install -r requirements.txt')
        return False
    out("    依赖安装完成。")
    return ensure_mcp_compat()


def update_mcp_json():
    """把 enterprise-knowledge-base 合并进 WorkBuddy 的 mcp.json（保留其他服务配置）。"""
    WORKBUDDY_DIR.mkdir(parents=True, exist_ok=True)
    cfg = {"mcpServers": {}}
    if MCP_JSON.exists():
        try:
            cfg = json.loads(MCP_JSON.read_text(encoding="utf-8"))
            if "mcpServers" not in cfg:
                cfg["mcpServers"] = {}
        except Exception as e:
            out(f"[2/4] !! mcp.json 解析失败（{e}），为安全起见中止，请手动检查该文件。")
            return False
    cfg["mcpServers"][MCP_ENTRY_NAME] = {
        "command": str(VENV_PY),
        "args": [str(PROJECT_ROOT / "mcp_server.py")],
        "env": {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "KMP_DUPLICATE_LIB_OK": "TRUE",
            "CUDA_VISIBLE_DEVICES": "-1",
        },
        "disabled": False,
        "timeout": 600000,
    }
    MCP_JSON.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    out(f"[2/4] mcp.json 已注册: {MCP_ENTRY_NAME} -> {VENV_PY}")
    return True


def deploy_skill():
    """部署用户级 Skill（WorkBuddy 每轮会话常驻可见的路由路标）。"""
    if not SKILL_SRC.exists():
        out(f"[3/4] !! 缺少 {SKILL_SRC}，跳过 Skill 部署。")
        return False
    SKILL_DST.mkdir(parents=True, exist_ok=True)
    dst = SKILL_DST / "SKILL.md"
    dst.write_text(SKILL_SRC.joinpath("SKILL.md").read_text(encoding="utf-8"), encoding="utf-8")
    out(f"[3/4] Skill 已部署: {dst}")
    return True


def upsert_block(text: str, begin: str, end: str, body: str):
    """就地替换/追加一个带标记的托管块（幂等）。返回 (新文本, 动作)。"""
    body = body.strip("\n")
    if begin in text and end in text:
        pre = text.split(begin, 1)[0].rstrip("\n")
        post = text.split(end, 1)[1].lstrip("\n")
        joined = "\n\n".join(p for p in (pre, body, post) if p)
        return joined + "\n", "已更新"
    cur = text.rstrip("\n")
    return (cur + "\n\n" + body + "\n") if cur else body + "\n", "已追加"


def append_memory_rules():
    """向 MEMORY.md 写入平台层调用格式 + 企业知识库路由规则（带标记，幂等）。"""
    WORKBUDDY_DIR.mkdir(parents=True, exist_ok=True)
    text = MEMORY_MD.read_text(encoding="utf-8") if MEMORY_MD.exists() else "# 用户长期记忆\n"
    actions = []
    text, act = upsert_block(text, MEMORY_MARKER_MCP_BEGIN, MEMORY_MARKER_MCP_END, MEMORY_RULES_MCP)
    actions.append(f"平台层调用格式{act}")
    text, act = upsert_block(text, MEMORY_MARKER_BEGIN, MEMORY_MARKER_END, MEMORY_RULES)
    actions.append(f"企业知识库路由{act}")
    MEMORY_MD.write_text(text, encoding="utf-8")
    out(f"[4/4] MEMORY.md 规则{'、'.join(actions)}: {MEMORY_MD}")
    return True


# ---------------- 信任状态检查 ----------------

def check_trust() -> bool:
    """检查 ~/.workbuddy/mcp-approvals.json 里本服务是否已被信任（键为 <hash>::<服务名>）。"""
    f = WORKBUDDY_DIR / "mcp-approvals.json"
    if f.exists():
        try:
            approvals = json.loads(f.read_text(encoding="utf-8"))
            for key in approvals:
                if key.endswith("::" + MCP_ENTRY_NAME):
                    return True
        except Exception:
            pass
    return False


# ---------------- 端到端体检（MCP stdio 探针） ----------------

def load_mcp_env() -> dict:
    """读取 mcp.json 中本服务配置的 env（与 WorkBuddy spawn 行为一致）。

    关键：本项目依赖 PYTHONUNBUFFERED=1 等 env——不带这些变量 spawn，
    子进程输出会被缓冲，协议响应永远到不了（实测踩坑）。
    """
    env = os.environ.copy()
    try:
        cfg = json.loads(MCP_JSON.read_text(encoding="utf-8"))
        env.update(cfg.get("mcpServers", {}).get(MCP_ENTRY_NAME, {}).get("env", {}) or {})
    except Exception:
        pass
    return env


class McpProbe:
    """以二进制管道 spawn MCP stdio 服务，行分隔 JSON-RPC 交互。"""

    def __init__(self, exe: str, script: str, env: dict = None):
        self.proc = subprocess.Popen(
            [exe, script],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env or os.environ.copy(),
        )
        self.q = queue.Queue()
        self.t = threading.Thread(target=self._reader, daemon=True)
        self.t.start()

    def _reader(self):
        for raw in self.proc.stdout:
            self.q.put(raw.decode("utf-8", errors="replace"))

    def send(self, obj):
        self.proc.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def wait_id(self, want_id: int, timeout: float):
        """按 id 等响应，顺带丢弃通知/请求；超时抛 TimeoutError。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = self.q.get(timeout=max(0.1, deadline - time.time()))
            except queue.Empty:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if msg.get("id") == want_id:
                return msg
        raise TimeoutError(f"等待 id={want_id} 响应超时")

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def verify_install() -> bool:
    """端到端体检：真实 spawn 本项目 MCP 服务 → 握手计时 → 列工具 → 实际检索一次。"""
    out("")
    out("=" * 62)
    out("[6/6] 端到端体检（真实启动 MCP 服务 + 检索一次）")
    out("=" * 62)
    script = PROJECT_ROOT / "mcp_server.py"
    if not (VENV_PY.exists() and script.exists()):
        out("    !! venv 或 mcp_server.py 缺失，安装步骤未成功，无法体检。")
        return False
    probe = None
    try:
        probe = McpProbe(str(VENV_PY), str(script), env=load_mcp_env())
        t0 = time.time()
        probe.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "install-check", "version": "1.0"}}})
        resp = probe.wait_id(1, timeout=60)
        if "result" not in resp:
            raise RuntimeError(f"initialize 失败: {str(resp)[:200]}")
        probe.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        out(f"    ✅ 协议握手 {time.time() - t0:.2f} 秒（<5 秒为优）")

        probe.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        resp = probe.wait_id(2, timeout=60)
        tools = [t.get("name") for t in resp.get("result", {}).get("tools", [])]
        out(f"    ✅ 工具清单 {len(tools)} 个: {', '.join(tools)}")

        t0 = time.time()
        probe.send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "search_knowledge_base",
                               "arguments": {"query": "年假制度 天数规定", "top_k": 2}}})
        resp = probe.wait_id(3, timeout=300)
        if "error" in resp:
            raise RuntimeError(f"工具调用失败: {resp['error']}")
        text = "\n".join(c.get("text", "") for c in resp.get("result", {}).get("content") or []
                         if isinstance(c, dict))
        dt = time.time() - t0
        ok = ("年" in text) and any(ch.isdigit() for ch in text)
        mark = "✅" if ok else "⚠️"
        out(f"    {mark} 实际检索 '年假制度' 耗时 {dt:.2f} 秒，返回 {len(text)} 字")
        out("    返回开头: " + text[:120].replace("\n", " "))
        return ok
    except TimeoutError as e:
        out(f"    ❌ {e}（服务无响应，请把本输出截图反馈）")
        return False
    except Exception as e:
        out(f"    ❌ 体检异常: {e}")
        return False
    finally:
        if probe:
            probe.close()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    out("=" * 62)
    out("企业知识库 MCP (enterprise-knowledge-base) — WorkBuddy 一键安装")
    out("=" * 62)
    out(f"项目位置: {PROJECT_ROOT}")

    mcp_only = "--mcp-only" in sys.argv
    no_verify = "--no-verify" in sys.argv
    ok = True
    if mcp_only:
        out("[1/4] 跳过 venv（--mcp-only）")
        ok = update_mcp_json()
        out("[3/4] 跳过 Skill（--mcp-only）")
        out("[4/4] 跳过 MEMORY 规则（--mcp-only）")
    else:
        ok = (ensure_venv() and ensure_kb_assets() and update_mcp_json()
              and deploy_skill() and append_memory_rules())

    if ok and not no_verify:
        ok = verify_install()

    out("-" * 62)
    if ok:
        if check_trust():
            out("安装完成！WorkBuddy 已信任本服务，新开会话询问公司制度即可自动检索知识库。")
        else:
            out("安装完成！最后一步（手动）：")
            out("  打开 WorkBuddy 连接器管理页 -> 自定义连接器 -> 对 enterprise-knowledge-base 点击「信任」")
            out("  （或重启 WorkBuddy）。之后新开会话询问公司制度即可自动检索知识库。")
        out("提示：制度文档在 data/documents（随 git 分发），向量索引缺失/损坏会自动重建；")
        out("      BGE 模型约 400MB 不随 git 分发，缺失时会自动从 hf-mirror 下载（首次检索会慢一次）。")
        out("      如需卸载、修改路径或状态自检，可双击本目录下的「图形化配置助手.bat」。")
    else:
        out("安装未完全成功，请按上方提示处理后重跑本脚本。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
