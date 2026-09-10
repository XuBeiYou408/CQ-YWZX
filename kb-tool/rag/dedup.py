# ==================== 定义去重函数====================
def deduplicate_docs(docs):
    seen = set()
    result_docs = []
    for doc in docs:
        content = doc.page_content.strip()
        source = doc.metadata.get("source", "")
        key = (source, content)
        if key not in seen:
            seen.add(key)
            result_docs.append(doc)
    return result_docs
