# -*- coding: utf-8 -*-
"""
合同审查 MCP 一键安装脚本（随项目分发，换电脑直接运行本脚本即可）。

功能（全部幂等，可重复运行）：
  1. 检查/创建项目 venv 并安装依赖（requirements.txt）
  2. 把 contract-reviewer 注册进 WorkBuddy 的 mcp.json（合并，不动其他服务）
  3. 把 deploy/skills/contract-review 部署为用户级 Skill（~/.workbuddy/skills/）
  4. 向 ~/.workbuddy/MEMORY.md 追加合同审查路由规则（带标记，不重复追加）
  5. 探测本机 LM Studio（非致命）+ 检查 WorkBuddy 信任状态 + 端到端体检
     （真实启动本项目的 MCP 服务，协议握手计时、列出工具、调用 ping 环境检测）
     ——不依赖 WorkBuddy 即可确认服务本身完全可用

用法：
  python install_to_workbuddy.py            # 全部安装 + 体检
  python install_to_workbuddy.py --mcp-only # 只更新 mcp.json（依赖与 Skill 已就绪时用）
  python install_to_workbuddy.py --no-verify # 跳过第 5 步端到端体检
"""
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
SKILL_SRC = PROJECT_ROOT / "deploy" / "skills" / "contract-review"
SKILL_DST = WORKBUDDY_DIR / "skills" / "contract-review"
MEMORY_MD = WORKBUDDY_DIR / "MEMORY.md"

MCP_ENTRY_NAME = "contract-reviewer"
MEMORY_MARKER_BEGIN = "# >>> contract-reviewer routes (auto-managed, do not edit between markers)"
MEMORY_MARKER_END = "# <<< contract-reviewer routes (auto-managed)"

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

MEMORY_RULES = """# >>> contract-reviewer routes (auto-managed, do not edit between markers)

## 合同审查路由规则（最高优先级）

- 用户部署了本地合同审查 MCP 服务 `contract-reviewer`。
- **凡是用户提供合同文件（.docx/.pdf/.txt）并表达审查/风险检查/批注/改写/起草意图**（如"帮我审查这份合同"、"看看有没有风险"、"出批注版"），**必须**走 `contract-reviewer` MCP，**禁止**把合同路由到 tencent-docs-routing / tencent-local-office-edit / tencent-docx 等文档编辑技能——那些技能只会读写文档内容，不会做法务审查。
- 正确步骤：先 `ToolSearch` 加载 `mcp__contract-reviewer__review_contract_file`（或按需 `scan_clause_risk` / `search_precedent` / `statute` / `draft_new_contract` / `export_annotated_docx`），再调用。完整审查用 `review_contract_file`，它会返回审查摘要并自动生成 Word 红线批注版（存原文件同目录）。
- **用户拖入/给出合同文件即默认审查意图**：直接调用 contract-review 技能 → review_contract_file，不要反问用户想做什么，不要先调 tencent-docs-routing 探测文件类型。
- 仅当用户明确只想"读文档内容/改格式/转格式"而非审查时，才走腾讯文档技能。

# <<< contract-reviewer routes (auto-managed)
"""


def out(msg):
    print(msg, flush=True)


def find_base_python():
    """找一个可用的系统 Python 用来创建 venv（优先 py 启动器）。"""
    for cmd in (["py", "-3"], ["python"]):
        try:
            r = subprocess.run(cmd + ["-c", "import sys;print(sys.version_info[0])"],
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and r.stdout.strip().startswith("3"):
                return cmd
        except Exception:
            continue
    return None


def ensure_venv():
    """确保 venv 存在且可用（venv 不可跨机器拷贝，损坏时自动重建）。"""
    if VENV_PY.exists():
        try:
            chk = subprocess.run([str(VENV_PY), "-c", "import sys;print(sys.version_info[0])"],
                                 capture_output=True, text=True, timeout=60)
            if chk.returncode == 0 and chk.stdout.strip().startswith("3"):
                out(f"[1/4] venv 已存在且可用: {VENV_PY}")
                return True
        except Exception:
            pass
        import shutil
        shutil.rmtree(VENV_DIR, ignore_errors=True)
        out("[1/4] 检测到 venv 已损坏（多为从其他电脑拷贝所致），已清除并重建...")
    out("[1/4] 未发现 venv，正在新建...")
    base = find_base_python()
    if not base:
        out("    !! 未找到系统 Python 3。请先安装 Python 3.10+ 后重试。")
        return False
    r = subprocess.run(base + ["-m", "venv", str(VENV_DIR)], timeout=300)
    if r.returncode != 0:
        out("    !! venv 创建失败。")
        return False
    out("    正在安装依赖（首次约需几分钟，需联网）...")
    r = subprocess.run([str(VENV_PY), "-m", "pip", "install", "--quiet",
                        "-r", str(PROJECT_ROOT / "requirements.txt")], timeout=1800)
    if r.returncode != 0:
        out("    !! 依赖安装失败，请检查网络后重试：")
        out(f'       "{VENV_PY}" -m pip install -r requirements.txt')
        return False
    out("    依赖安装完成。")
    return True


def update_mcp_json():
    """把 contract-reviewer 合并进 WorkBuddy 的 mcp.json（保留其他服务配置）。"""
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
        },
        "disabled": False,
        "timeout": 600000,
    }
    MCP_JSON.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    existed = "已更新" if cfg["mcpServers"].get(MCP_ENTRY_NAME) else ""
    out(f"[2/4] mcp.json {existed or '已注册'}: {MCP_ENTRY_NAME} -> {VENV_PY}")
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
    """向 MEMORY.md 写入平台层调用格式 + 合同审查路由规则（带标记，幂等）。"""
    WORKBUDDY_DIR.mkdir(parents=True, exist_ok=True)
    text = MEMORY_MD.read_text(encoding="utf-8") if MEMORY_MD.exists() else "# 用户长期记忆\n"
    actions = []
    text, act = upsert_block(text, MEMORY_MARKER_MCP_BEGIN, MEMORY_MARKER_MCP_END, MEMORY_RULES_MCP)
    actions.append(f"平台层调用格式{act}")
    text, act = upsert_block(text, MEMORY_MARKER_BEGIN, MEMORY_MARKER_END, MEMORY_RULES)
    actions.append(f"合同审查路由{act}")
    MEMORY_MD.write_text(text, encoding="utf-8")
    out(f"[4/4] MEMORY.md 规则{'、'.join(actions)}: {MEMORY_MD}")
    return True


def probe_lm_studio():
    """探测本机 LM Studio（非致命：不在线只提示，不判失败）。"""
    import json as _json
    import urllib.request
    base = os.getenv("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
    probe = base.rstrip("/")
    probe = probe[: -len("/v1")] + "/v1/models" if probe.endswith("/v1") else probe + "/v1/models"
    try:
        with urllib.request.urlopen(probe, timeout=5) as r:
            data = _json.loads(r.read())
        ids = [m.get("id", "?") for m in data.get("data", [])]
        out(f"[5/5] LM Studio 在线 ✅ 可用模型：{'、'.join(ids[:8]) or '(空)'}")
        out("      完整审查可用（引擎运行时自动选择模型，模型名不同无需改配置）。")
    except Exception:
        out("[5/5] LM Studio 未检测到 ⚠️（非致命）")
        out("      影响：轻量轨（风险扫描/法条/判例检索）不受影响；")
        out("            完整审查、批注版导出、起草新合同需要 LM Studio。")
        out("      处理：安装并启动 LM Studio 加载模型；端口非 1234 时设置")
        out("            环境变量 LM_STUDIO_BASE_URL（如 http://127.0.0.1:8080/v1）。")
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
    """读取 mcp.json 中本服务配置的 env（与 WorkBuddy spawn 行为一致）。"""
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
    """端到端体检：真实 spawn 本项目 MCP 服务 → 握手计时 → 列工具 → 调 ping 环境检测。"""
    out("")
    out("=" * 62)
    out("[6/6] 端到端体检（真实启动 MCP 服务 + ping 环境检测）")
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

        probe.send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "ping", "arguments": {}}})
        resp = probe.wait_id(3, timeout=120)
        if "error" in resp:
            raise RuntimeError(f"工具调用失败: {resp['error']}")
        text = "\n".join(c.get("text", "") for c in resp.get("result", {}).get("content") or []
                         if isinstance(c, dict))
        mark = "✅" if ("就绪" in text) else "⚠️"
        out(f"    {mark} ping 环境体检完成:")
        for line in text.splitlines():
            out("      " + line)
        # 轻量轨就绪即算通过；LM Studio 不在线只影响完整轨，不算失败
        return "轻量轨" in text and "就绪" in text
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
    out("合同审查 MCP (contract-reviewer) — WorkBuddy 一键安装")
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
        ok = ensure_venv() and update_mcp_json() and deploy_skill() and append_memory_rules()
    probe_lm_studio()

    if ok and not no_verify:
        ok = verify_install()

    out("-" * 62)
    if ok:
        if check_trust():
            out("安装完成！WorkBuddy 已信任本服务，新开会话拖入合同即可审查。")
        else:
            out("安装完成！最后一步（手动）：")
            out("  打开 WorkBuddy 连接器管理页 -> 自定义连接器 -> 对 contract-reviewer 点击「信任」")
            out("  （或重启 WorkBuddy）。之后新开会话拖入合同即可审查。")
        out("注意：本脚本不迁移 LM Studio——新机器需自行安装 LM Studio 并加载模型，")
        out("      然后在合同审查项目 config.py 中核对模型名与 http://127.0.0.1:1234/v1 地址。")
    else:
        out("安装未完全成功，请按上方提示处理后重跑本脚本。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
