import logging
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse
import requests
from requests.exceptions import RequestException, Timeout, ConnectionError
from open_webui.retrieval.web.main import SearchResult, get_filtered_results
from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["RAG"])

SCRAPERS = ["ddg", "brave", "google", "startpage", "ghostery", "mojeek"]
DEFAULT_TIMEOUT = 3
MAX_RETRIES = 0

def validate_url(url: str) -> bool:
    """验证URL是否有效"""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False

def process_search_results(results: Dict[str, Any], count: int) -> List[SearchResult]:
    """处理搜索结果，统一处理可能的异常情况"""
    try:
        news_results = []
        web_results = []
        
        # 处理新闻结果
        if isinstance(results.get("news"), list):
            news_results = [
                SearchResult(
                    link=str(result.get("url", "")),
                    title=str(result.get("title", "")),
                    snippet=str(result.get("description", "")),
                )
                for result in results.get("news", [])[:count]
                if result.get("url") and result.get("title")
            ]
        
        # 处理网页结果
        if isinstance(results.get("web"), list):
            web_results = [
                SearchResult(
                    link=str(result.get("url", "")),
                    title=str(result.get("title", "")),
                    snippet=str(result.get("description", "")),
                )
                for result in results.get("web", [])[:count]
                if result.get("url") and result.get("title")
            ]
        
        return web_results + news_results
    except Exception as e:
        log.error(f"Error processing search results: {e}")
        return []

def search_external(
    external_url: str,
    external_api_key: str,
    query: str,
    count: int,
    filter_list: Optional[List[str]] = None,
) -> List[SearchResult]:
    """执行外部搜索，包含完整的错误处理和重试逻辑"""
    
    # 参数验证
    if not query or not query.strip():
        log.error("Empty query provided")
        return []
    
    if not validate_url(external_url):
        log.error(f"Invalid external URL: {external_url}")
        return []
    
    if count < 1:
        log.warning("Invalid count parameter, using default of 10")
        count = 10
    
    # 创建session以复用连接
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Open WebUI (https://github.com/open-webui/open-webui) RAG Bot",
        "Accept": "*/*",
        "Content-Type": "application/json",
    })
    
    if external_api_key:
        session.headers["Authorization"] = f"Bearer {external_api_key}"
    
    for scraper in SCRAPERS:
        retries = 0
        while retries <= MAX_RETRIES:
            try:
                log.info(f"Attempting search with {scraper} (attempt {retries + 1}/{MAX_RETRIES + 1})")
                
                response = session.get(
                    external_url,
                    params={
                        "s": query.strip(),
                        "scraper": scraper,
                        "nsfw": "yes",
                    },
                    timeout=DEFAULT_TIMEOUT
                )
                
                # 检查HTTP状态码
                if response.status_code == 429:  # Too Many Requests
                    log.warning(f"{scraper} rate limit exceeded, trying next scraper")
                    break  # 直接尝试下一个搜索引擎
                
                response.raise_for_status()
                
                try:
                    results = response.json()
                except ValueError as e:
                    log.error(f"Invalid JSON response from {scraper}: {e}")
                    break  # JSON解析错误，尝试下一个搜索引擎
                
                if filter_list:
                    results = get_filtered_results(results, filter_list)
                
                search_results = process_search_results(results, count)
                
                if search_results:
                    log.info(f"Successfully got {len(search_results)} results from {scraper}")
                    return search_results
                
                log.warning(f"No results from {scraper}, trying next scraper")
                break  # 没有结果，尝试下一个搜索引擎
                
            except Timeout:
                log.warning(f"Timeout with {scraper} (attempt {retries + 1})")
                retries += 1
                
            except ConnectionError as e:
                log.error(f"Connection error with {scraper}: {e}")
                break  # 连接错误，尝试下一个搜索引擎
                
            except RequestException as e:
                log.error(f"Request error with {scraper}: {e}")
                retries += 1
                
            except Exception as e:
                log.error(f"Unexpected error with {scraper}: {e}")
                break  # 未知错误，尝试下一个搜索引擎
    
    log.error("All scrapers failed")
    return []
