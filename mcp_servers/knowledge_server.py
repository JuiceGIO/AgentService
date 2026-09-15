"""知识库检索 MCP server（模拟 RAG：关键词 + 字符 bigram 打分，带引用出处）。"""

from mcp.server.fastmcp import FastMCP

from mock_data import KNOWLEDGE_BASE

mcp = FastMCP("knowledge-server")


def _bigrams(s: str) -> set:
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _score(doc: dict, query: str) -> float:
    score = 0.0
    for tag in doc["tags"]:
        if tag in query:
            score += 2.0
    if doc["title"] in query or query in doc["title"]:
        score += 1.0
    qb = _bigrams(query)
    if qb:
        overlap = len(qb & _bigrams(doc["title"] + doc["content"]))
        score += overlap / len(qb) * 3.0
    return score


@mcp.tool()
def search_knowledge(query: str, top_k: int = 3) -> dict:
    """在售后知识库中检索与问题相关的规则条目（关键词 + bigram 匹配），返回标题/内容/相关度/引用出处。"""
    scored = sorted(KNOWLEDGE_BASE, key=lambda d: _score(d, query), reverse=True)
    top = [d for d in scored if _score(d, query) > 0][: max(1, min(top_k, 5))]
    if not top:
        return {"found": False, "query": query, "message": "知识库中没有匹配条目，建议转人工。", "results": []}
    return {
        "found": True,
        "query": query,
        "results": [
            {"id": d["id"], "title": d["title"], "content": d["content"], "score": _score(d, query)}
            for d in top
        ],
    }


if __name__ == "__main__":
    mcp.run()
