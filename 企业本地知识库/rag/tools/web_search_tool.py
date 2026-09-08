import re
import logging
import urllib.request
import urllib.parse
import requests
from bs4 import BeautifulSoup
from langchain.tools import tool
from config import FIRECRAWL_API_KEY

logger = logging.getLogger(__name__)

# 记录单次进程/会话内的工具调用次数，物理斩断死循环
_SEARCH_CALL_COUNT = {}

def _clean_query(raw_query: str) -> str:
    """自动剥离引号、格式字符，提炼核心搜索词"""
    if not raw_query: return ""
    clean = re.sub(r'[\"\'“”‘’`]', '', str(raw_query)).strip()
    words = clean.split()
    if len(words) > 6:
        clean = " ".join(words[:6])
    return clean

def _search_firecrawl_api(query: str, limit: int = 5) -> str:
    """使用 Firecrawl 官方云端搜索引擎（最高召回、最强 Markdown 正文）"""
    if not FIRECRAWL_API_KEY:
        return ""
    try:
        clean_q = _clean_query(query)
        if not clean_q: return ""
        
        url = "https://api.firecrawl.dev/v1/search"
        headers = {
            "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "query": clean_q,
            "limit": limit
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.status_code == 200:
            res_json = resp.json()
            if res_json.get("success") and res_json.get("data"):
                data_obj = res_json["data"]
                raw_items = data_obj.get("web", []) if isinstance(data_obj, dict) else data_obj
                if isinstance(raw_items, list) and len(raw_items) > 0:
                    results = []
                    for item in raw_items[:limit]:
                        title = item.get("title") or item.get("metadata", {}).get("title") or "技术网页"
                        item_url = item.get("url") or item.get("metadata", {}).get("sourceURL") or ""
                        description = item.get("description") or item.get("markdown") or item.get("snippet") or ""
                        results.append(f"【{title}】\n链接：{item_url}\n内容摘要：{description[:300]}")
                    if results:
                        return "\n\n".join(results)
    except Exception as e:
        logger.warning(f"Firecrawl API 遇到异常，降级至本地备用引擎: {e}")
    return ""

def _search_bing_universal(query: str, max_results: int = 5) -> str:
    """通用后备 Bing 提取器（含页脚与 ICP 备案强过滤）"""
    try:
        clean_q = _clean_query(query)
        if not clean_q: return ""
        
        url = f"https://cn.bing.com/search?q={urllib.parse.quote(clean_q)}"
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
            }
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

        soup = BeautifulSoup(html, 'html.parser')
        results = []
        seen_links = set()

        for a in soup.find_all('a'):
            link = a.get('href', '')
            text = a.get_text(strip=True)
            
            # 过滤内部链接、备案信息及无用页脚
            if not link.startswith('http') or any(d in link for d in ['bing.com', 'microsoft.com', 'live.com', 'miit.gov.cn', 'mps.gov.cn', 'gov.cn']):
                continue
            if any(kw in text for kw in ['ICP', '备案', '许可证', '公网安备', '隐私与 Cookie', '法律声明', '广告']):
                continue
            if len(text) < 6 or link in seen_links:
                continue
            
            seen_links.add(link)
            parent_text = a.parent.parent.get_text(strip=True) if a.parent and a.parent.parent else text
            snippet = parent_text[:140] if parent_text else text
            results.append(f"【{text}】\n链接：{link}\n摘要：{snippet}")
            if len(results) >= max_results:
                break

        return "\n\n".join(results)
    except Exception:
        return ""

def _check_and_increment_call(tool_name: str) -> bool:
    """计数防刷，当单次会话调用超过 2 次时强制中断死循环"""
    count = _SEARCH_CALL_COUNT.get(tool_name, 0) + 1
    _SEARCH_CALL_COUNT[tool_name] = count
    if count > 2:
        return False
    return True

@tool
def bing_web_search_tool(query: str) -> str:
    """
    使用 Firecrawl 与 Bing 搜索引擎获取全球最新技术动态与在线网页资讯（Firecrawl 驱动）。
    输入：具体的搜索关键词或问题。
    输出：Firecrawl 检索返回的前 5 条精准结果列表。
    """
    if not _check_and_increment_call('bing_web_search_tool'):
        return "【系统强制指令】：已完成 2 次网页搜索尝试。绝对禁止再次调用本工具！请立即在下一步的 Thought 中总结已知信息，并输出 Final Answer 结合通用知识回答！"
        
    res_fc = _search_firecrawl_api(query)
    if res_fc:
        return res_fc
        
    res_bing = _search_bing_universal(query)
    if res_bing:
        return res_bing
    return "网络搜索未查到匹配网页，请基于大模型知识储备输出 Final Answer。"

@tool
def baidu_web_search_tool(query: str) -> str:
    """
    使用百度与 Firecrawl 搜索引擎获取最新技术博客、新闻与社区资讯（Firecrawl 驱动）。
    输入：中文搜索关键词或具体提问。
    输出：搜索引擎召回的网页标题与内容片段。
    """
    if not _check_and_increment_call('baidu_web_search_tool'):
        return "【系统强制指令】：已完成 2 次网页搜索尝试。绝对禁止再次调用本工具！请立即在下一步的 Thought 中总结已知信息，并输出 Final Answer 结合通用知识回答！"

    res_fc = _search_firecrawl_api(query)
    if res_fc:
        return res_fc

    res_bing = _search_bing_universal(query)
    if res_bing:
        return res_bing
    return "百度搜索未查到匹配网页，请基于大模型知识储备输出 Final Answer。"

@tool
def wangye_sousuo_tool(query: str) -> str:
    """
    通用网页搜索引擎工具（优先由顶尖 Firecrawl 驱动，支持 100% 优雅降级）。
    输入：具体的搜索引擎关键词或问题。
    输出：前 5 条搜索结果的标题、链接和摘要。
    """
    if not _check_and_increment_call('wangye_sousuo_tool'):
        return "【系统强制指令】：当前轮次已执行过网页搜索。绝对禁止再次调用网页搜索工具！请立即在下一个 Thought 中直接总结，并紧接着输出 Final Answer 结合已有知识回答！"

    # 1. 优先调用工业级最强 Firecrawl API
    res_fc = _search_firecrawl_api(query)
    if res_fc:
        return res_fc

    # 2. 降级使用通用网页提取器
    res_bing = _search_bing_universal(query)
    if res_bing:
        return res_bing

    return "网页搜索未召回相关结果，请基于大模型知识储备输出 Final Answer。"
