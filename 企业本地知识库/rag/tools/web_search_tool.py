import re
import logging
import urllib.request
import urllib.parse
import requests
from bs4 import BeautifulSoup
from langchain.tools import tool
from config import FIRECRAWL_API_KEY

logger = logging.getLogger(__name__)

# 会话级别调用计数，防止同一会话无限重试搜索
_SESSION_CALL_COUNT = {}

def _clean_query(raw_query: str) -> str:
    """自动剥离引号、格式字符，提炼核心搜索词"""
    if not raw_query:
        return ""
    clean = re.sub(r'[\"\'“”‘’`]', '', str(raw_query)).strip()
    words = clean.split()
    if len(words) > 8:
        clean = " ".join(words[:8])
    return clean

def _search_firecrawl_api(query: str, limit: int = 4) -> str:
    """使用 Firecrawl 官方云端搜索引擎（3秒硬超时）"""
    if not FIRECRAWL_API_KEY:
        return ""
    try:
        clean_q = _clean_query(query)
        if not clean_q:
            return ""
        
        url = "https://api.firecrawl.dev/v1/search"
        headers = {
            "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "query": clean_q,
            "limit": limit
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=3.0)
        if resp.status_code == 200:
            res_json = resp.json()
            if res_json.get("success") and res_json.get("data"):
                data_obj = res_json["data"]
                raw_items = data_obj.get("web", []) if isinstance(data_obj, dict) else data_obj
                if isinstance(raw_items, list) and len(raw_items) > 0:
                    results = []
                    for item in raw_items[:limit]:
                        title = item.get("title") or item.get("metadata", {}).get("title") or "外部网页资讯"
                        item_url = item.get("url") or item.get("metadata", {}).get("sourceURL") or ""
                        description = item.get("description") or item.get("markdown") or item.get("snippet") or ""
                        results.append(f"【{title}】\n来源链接：{item_url}\n内容摘要：{description[:260]}")
                    if results:
                        return "\n\n".join(results)
    except Exception as e:
        logger.warning(f"Firecrawl 搜索未命中或超时 ({e})，切换备用搜索通道")
    return ""

def _search_universal_fallback(query: str, max_results: int = 4) -> str:
    """通用备用搜索提取器（3.0 秒硬超时、强力防假死与页脚广告过滤）"""
    try:
        clean_q = _clean_query(query)
        if not clean_q:
            return ""
        
        url = f"https://cn.bing.com/search?q={urllib.parse.quote(clean_q)}"
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
            }
        )
        # 3.0 秒硬超时，杜绝长时间挂起卡死
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

        soup = BeautifulSoup(html, 'html.parser')
        results = []
        seen_links = set()

        for a in soup.find_all('a'):
            link = a.get('href', '')
            text = a.get_text(strip=True)
            
            # 过滤内部无用跳转、广告与备案信息
            if not link.startswith('http') or any(d in link for d in ['bing.com', 'microsoft.com', 'live.com', 'miit.gov.cn']):
                continue
            if any(kw in text for kw in ['ICP', '备案', '许可证', '公网安备', '隐私与 Cookie', '法律声明', '广告']):
                continue
            if len(text) < 6 or link in seen_links:
                continue
            
            seen_links.add(link)
            parent_text = a.parent.parent.get_text(strip=True) if a.parent and a.parent.parent else text
            snippet = parent_text[:140] if parent_text else text
            results.append(f"【{text}】\n来源链接：{link}\n内容要点：{snippet}")
            if len(results) >= max_results:
                break

        if results:
            return "\n\n".join(results)
    except Exception as e:
        logger.debug(f"通用外网搜索网络波动或超时: {e}")
    return ""

@tool
def unified_web_search(query: str) -> str:
    """
    智能外网时效检索工具（支持 Firecrawl 高清正文与通用搜索引擎双通道，具备 3 秒硬超时熔断保护）。
    适用于：本地知识库未收录的事项、国家最新法规时效、外部常识、最新行业动态、天气航班等超纲问题。
    输入：具体的搜索关键词或问题。
    输出：外部权威网页的标题、链接与内容摘要。
    """
    # 1. 优先调用 Firecrawl 云端 API
    res_fc = _search_firecrawl_api(query)
    if res_fc:
        return f"[🌐 外部互联网检索结果 (Firecrawl)]:\n{res_fc}"

    # 2. 降级备用通道 (3秒硬超时)
    res_fallback = _search_universal_fallback(query)
    if res_fallback:
        return f"[🌐 外部互联网检索结果]:\n{res_fallback}"

    # 3. 优雅降级，绝不卡死
    return "[🌐 外部互联网检索提示]: 外部网络未查到最新匹配页面，已为您自动激活本地大模型通用知识库直接解答。"

# 向后兼容旧工具名称
wangye_sousuo_tool = unified_web_search
bing_web_search_tool = unified_web_search
baidu_web_search_tool = unified_web_search
