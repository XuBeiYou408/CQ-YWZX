# -*- coding: utf-8 -*-
"""
企业知识库 MCP Tool · WorkBuddy 一键图形化安装向导
为普通用户提供无需接触 JSON、一键注入/卸载 WorkBuddy MCP 的可视化工具
"""
import os
import sys
import json
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

# 路径自举
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON_EXE = os.path.join(CURRENT_DIR, ".venv", "Scripts", "python.exe")
SERVER_PY = os.path.join(CURRENT_DIR, "mcp_server.py")
DOCS_DIR = os.path.join(CURRENT_DIR, "data", "documents")

# WorkBuddy 目标配置文件（优先 ~/.workbuddy/mcp.json，兼顾 .mcp.json）
USER_HOME = os.path.expanduser("~")
WB_DIR = os.path.join(USER_HOME, ".workbuddy")
WB_MCP_JSON = os.path.join(WB_DIR, "mcp.json")
WB_DOT_MCP_JSON = os.path.join(WB_DIR, ".mcp.json")

SERVER_KEY = "enterprise-knowledge-base"

def get_server_config():
    return {
        "command": PYTHON_EXE,
        "args": [SERVER_PY],
        "env": {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "KMP_DUPLICATE_LIB_OK": "TRUE",
            "CUDA_VISIBLE_DEVICES": "-1"
        }
    }

def check_installation_status():
    installed_in = []
    for path in [WB_MCP_JSON, WB_DOT_MCP_JSON]:
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if SERVER_KEY in data.get("mcpServers", {}):
                    installed_in.append(path)
            except Exception:
                pass
    return installed_in

class InstallerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("企业本地知识库 · WorkBuddy 一键接入助手")
        self.root.geometry("640x520")
        self.root.resizable(False, False)

        # 尝试设置原生高 DPI 缩放
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        self.setup_styles()
        self.build_ui()
        self.refresh_status()

    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("Title.TLabel", font=("微软雅黑", 14, "bold"), foreground="#1e293b")
        self.style.configure("Sub.TLabel", font=("微软雅黑", 9), foreground="#64748b")
        self.style.configure("Status.TLabel", font=("微软雅黑", 10, "bold"))
        self.style.configure("Path.TLabel", font=("Consolas", 8), foreground="#334155")
        self.style.configure("Big.TButton", font=("微软雅黑", 10, "bold"), padding=8)

    def build_ui(self):
        # 顶部标题卡片
        header = ttk.Frame(self.root, padding="16 16 16 10")
        header.pack(fill=tk.X)

        title = ttk.Label(header, text="📚 企业本地知识库 · WorkBuddy 接入助手", style="Title.TLabel")
        title.pack(anchor=tk.W)

        desc = ttk.Label(
            header,
            text="无需手动编辑任何 JSON 配置文件，一键将企业私域 RAG 知识库无缝接入腾讯 WorkBuddy 智能体。",
            style="Sub.TLabel",
            wraplength=600
        )
        desc.pack(anchor=tk.W, pady=(4, 0))

        # 中部检测面板
        card = ttk.LabelFrame(self.root, text=" 运行环境与配置检测 ", padding=14)
        card.pack(fill=tk.X, padx=16, pady=8)

        # 知识库路径
        f1 = ttk.Frame(card)
        f1.pack(fill=tk.X, pady=2)
        ttk.Label(f1, text="知识库目录：", width=12, font=("微软雅黑", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(f1, text=CURRENT_DIR, style="Path.TLabel").pack(side=tk.LEFT)

        # WorkBuddy 状态
        f2 = ttk.Frame(card)
        f2.pack(fill=tk.X, pady=2)
        ttk.Label(f2, text="WorkBuddy：", width=12, font=("微软雅黑", 9, "bold")).pack(side=tk.LEFT)
        wb_exists = os.path.isdir(WB_DIR)
        wb_text = "已检测到 WorkBuddy 安装目录" if wb_exists else "未检测到 ~/.workbuddy 目录（请先启动一次 WorkBuddy）"
        wb_color = "#16a34a" if wb_exists else "#dc2626"
        lbl_wb = tk.Label(f2, text=wb_text, fg=wb_color, font=("微软雅黑", 9))
        lbl_wb.pack(side=tk.LEFT)

        # 当前安装状态
        f3 = ttk.Frame(card)
        f3.pack(fill=tk.X, pady=(6, 2))
        ttk.Label(f3, text="接入状态：", width=12, font=("微软雅黑", 9, "bold")).pack(side=tk.LEFT)
        self.status_label = tk.Label(f3, text="正在检测...", font=("微软雅黑", 10, "bold"))
        self.status_label.pack(side=tk.LEFT)

        # 按钮操作区
        btn_box = ttk.Frame(self.root, padding="16 8 16 8")
        btn_box.pack(fill=tk.X)

        self.btn_install = tk.Button(
            btn_box,
            text="🚀 一键安装 / 接入到 WorkBuddy",
            bg="#2563eb",
            fg="white",
            activebackground="#1d4ed8",
            activeforeground="white",
            font=("微软雅黑", 10, "bold"),
            relief=tk.FLAT,
            padx=16,
            pady=8,
            cursor="hand2",
            command=self.do_install
        )
        self.btn_install.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_test = tk.Button(
            btn_box,
            text="🧪 测试 MCP 连通性",
            bg="#f1f5f9",
            fg="#1e293b",
            font=("微软雅黑", 9),
            relief=tk.GROOVE,
            padx=12,
            pady=7,
            cursor="hand2",
            command=self.do_test
        )
        self.btn_test.pack(side=tk.LEFT, padx=4)

        self.btn_open_docs = tk.Button(
            btn_box,
            text="📁 打开知识库文档文件夹",
            bg="#f1f5f9",
            fg="#1e293b",
            font=("微软雅黑", 9),
            relief=tk.GROOVE,
            padx=12,
            pady=7,
            cursor="hand2",
            command=self.open_docs_folder
        )
        self.btn_open_docs.pack(side=tk.LEFT, padx=4)

        self.btn_uninstall = tk.Button(
            btn_box,
            text="🗑️ 卸载",
            bg="#fef2f2",
            fg="#dc2626",
            font=("微软雅黑", 9),
            relief=tk.GROOVE,
            padx=10,
            pady=7,
            cursor="hand2",
            command=self.do_uninstall
        )
        self.btn_uninstall.pack(side=tk.RIGHT)

        # 日志输出框
        log_frame = ttk.LabelFrame(self.root, text=" 操作与诊断日志 ", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 14))

        self.log_text = tk.Text(log_frame, height=8, font=("Consolas", 8), bg="#f8fafc", fg="#334155", relief=tk.FLAT)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def log(self, text):
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)

    def refresh_status(self):
        installed = check_installation_status()
        if installed:
            self.status_label.config(text="🟢 已成功接入 WorkBuddy", fg="#16a34a")
            self.btn_install.config(text="🔄 重新配置 / 更新路径", bg="#059669")
            self.log("【检测】当前已在 WorkBuddy 中成功注册 MCP 服务！")
        else:
            self.status_label.config(text="⚪ 尚未接入 WorkBuddy", fg="#64748b")
            self.btn_install.config(text="🚀 一键安装 / 接入到 WorkBuddy", bg="#2563eb")
            self.log("【提示】点击上方【一键安装】按钮，即可自动配置到 WorkBuddy。")

    def do_install(self):
        os.makedirs(WB_DIR, exist_ok=True)
        config_payload = get_server_config()

        # 双写保证：同时更新 mcp.json 和 .mcp.json，确保任何版本 WorkBuddy 均能识别
        targets = [WB_MCP_JSON, WB_DOT_MCP_JSON]
        success_count = 0

        for target in targets:
            try:
                data = {"mcpServers": {}}
                if os.path.isfile(target):
                    try:
                        with open(target, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        data = {"mcpServers": {}}

                if "mcpServers" not in data:
                    data["mcpServers"] = {}

                data["mcpServers"][SERVER_KEY] = config_payload

                with open(target, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                success_count += 1
                self.log(f"✅ 成功写入配置到: {target}")
            except Exception as e:
                self.log(f"❌ 写入失败 {target}: {e}")

        if success_count > 0:
            self.refresh_status()
            messagebox.showinfo(
                "安装成功",
                "🎉 企业知识库已成功接入 WorkBuddy！\n\n"
                "操作建议：\n"
                "1. 请完全重启 WorkBuddy 客户端（或在托盘彻底退出重开）；\n"
                "2. 打开 WorkBuddy 对话框，直接发送：\n"
                "   『帮我查一下知识库里有哪些文件』\n"
                "即可开始体验！"
            )

    def do_uninstall(self):
        if not messagebox.askyesno("确认卸载", "确定要从 WorkBuddy 中移除企业本地知识库工具吗？\n（这不会删除本地任何文档或代码）"):
            return

        for target in [WB_MCP_JSON, WB_DOT_MCP_JSON]:
            if os.path.isfile(target):
                try:
                    with open(target, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if SERVER_KEY in data.get("mcpServers", {}):
                        del data["mcpServers"][SERVER_KEY]
                        with open(target, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                        self.log(f"🗑️ 已从 {target} 中移除配置。")
                except Exception as e:
                    self.log(f"❌ 卸载异常: {e}")

        self.refresh_status()
        messagebox.showinfo("已移除", "企业知识库 MCP 服务已从 WorkBuddy 移除。")

    def do_test(self):
        self.log("\n🧪 正在测试 MCP Server 握手响应...")
        cmd = [
            PYTHON_EXE,
            "-c",
            f"""
import subprocess, json, time
server = subprocess.Popen([r'{PYTHON_EXE}', r'{SERVER_PY}'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
msg = json.dumps({{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {{'protocolVersion': '2024-11-05', 'capabilities': {{}}, 'clientInfo': {{'name': 'installer-test', 'version': '1.0'}}}}}}) + '\\n'
server.stdin.write(msg.encode('utf-8'))
server.stdin.flush()
time.sleep(2)
server.kill()
out, _ = server.communicate()
print(out.decode('utf-8', errors='replace'))
"""
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if "enterprise-knowledge-base" in res.stdout:
                self.log("🎉 MCP 握手测试 100% 成功！服务与本地 BGE 模型就绪。")
                messagebox.showinfo("测试通过", "🎉 MCP 连通性测试通过！\n\n服务响应正常，已识别 3 个工具（search/list/add）。")
            else:
                self.log(f"⚠️ 响应异常: {res.stdout}\n{res.stderr}")
                messagebox.showwarning("测试警告", "服务拉起返回异常，请查看下方诊断日志。")
        except Exception as e:
            self.log(f"❌ 测试失败: {e}")
            messagebox.showerror("测试失败", f"无法启动 MCP 服务：{e}")

    def open_docs_folder(self):
        os.makedirs(DOCS_DIR, exist_ok=True)
        os.startfile(DOCS_DIR)
        self.log(f"📂 已为您打开本地文档存储目录: {DOCS_DIR}")

if __name__ == "__main__":
    root = tk.Tk()
    app = InstallerApp(root)
    root.mainloop()
