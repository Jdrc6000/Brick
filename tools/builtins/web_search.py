import re, requests
from bs4 import BeautifulSoup
from tools.base import BaseTool

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

class WebSearch(BaseTool):
    name = "web_search"
    description = (
        "Search the web using DuckDuckGo. Returns title, URL, and snippet for each result. "
        "Use this when you need current information, documentation, CVE details, "
        "package info, or anything that isn't on the local machine."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (default 8, max 20)",
                },
                "fetch_first": {
                    "type": "boolean",
                    "description": (
                        "Also fetch and return the text content of the first result URL. "
                        "Useful for reading docs or man pages. Default false."
                    ),
                },
            },
            "required": ["query"],
        }

    def run(
        self,
        query: str,
        num_results: int = 8,
        fetch_first: bool = False,
    ) -> dict:
        num_results = min(num_results, 20)

        try:
            resp = requests.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query, "kl": "us-en"},
                headers=_HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            return {"error": f"Search request failed: {e}"}

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        for result in soup.select(".result")[:num_results]:
            title_el = result.select_one(".result__title a")
            snippet_el = result.select_one(".result__snippet")

            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            raw_url = title_el.get("href", "")

            # DDG wraps URLs — extract real URL
            url_match = re.search(r"uddg=([^&]+)", raw_url)
            if url_match:
                from urllib.parse import unquote
                url = unquote(url_match.group(1))
            else:
                url = raw_url

            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            results.append({
                "title": title,
                "url": url,
                "snippet": snippet,
            })

        output = {
            "query": query,
            "results": results,
            "count": len(results),
        }

        if fetch_first and results:
            output["first_page_content"] = _fetch_text(results[0]["url"])

        return output

def _fetch_text(url: str, max_chars: int = 4000) -> str:
    """Fetch a URL and return its visible text content."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # Collapse excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:max_chars]
    except Exception as e:
        return f"[fetch failed: {e}]"