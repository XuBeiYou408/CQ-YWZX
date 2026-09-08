import re
import uuid
import hashlib
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

# ==================== 文件的清洗与父子块的切分 ====================

def pdf_qingxi(daichulipdf):
    zhongwen_rule = re.compile(r'([一-鿿])\n([一-鿿])')
    yingwen_rule = re.compile(r'([^一-鿿\n])\n([^一-鿿\n])')
    for i in daichulipdf:
        i.page_content = re.sub(zhongwen_rule, r'\1\2', i.page_content)
        i.page_content = re.sub(yingwen_rule, r'\1 \2', i.page_content)
    dad_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=100,
        separators=["\n\n", "。", "！", "？", ".\n", "\n", " ", ""]
    )
    son_qiefenguize = RecursiveCharacterTextSplitter(
        chunk_size=300,
        chunk_overlap=45,
        separators=["\n\n", "。", "！", "？", ".\n", "\n", " ", ""]
    )
    son_docs =[]
    dad_docs = dad_splitter.split_documents(daichulipdf)
    for idx ,d_doc in enumerate(dad_docs):
        #为每个父块生成唯一ID
        content_hash = hashlib.md5(d_doc.page_content.encode('utf-8')).hexdigest()[:8]
        d_id = f"pdf_{idx}_{content_hash}"
        d_content = d_doc.page_content
        metadata = d_doc.metadata.copy()
        metadata['dad_id'] = d_id
        temp_docs = Document(page_content=d_content, metadata=metadata)
        sub_chunks = son_qiefenguize.split_documents([temp_docs])#子级规则拆父块
        for s_doc in sub_chunks:
            s_doc.metadata['dad_id'] = d_id
            s_doc.metadata['dad_content'] = d_content
            son_docs.append(s_doc)
    return son_docs

def md_qingxi(daichulimd):
    dad_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=120,
        separators=["\n# ", "\n## ", "\n### ", "\n\n", "\n", " ", ""]
    )
    son_splitter = RecursiveCharacterTextSplitter(
        chunk_size=150,
        chunk_overlap=30,
        separators=["\n# ", "\n## ", "\n### ", "\n\n", "\n", " ", ""]
    )
    son_docs = []
    dad_docs = dad_splitter.split_documents(daichulimd)
    for idx, d_doc in enumerate(dad_docs):
        content_hash = hashlib.md5(d_doc.page_content.encode('utf-8')).hexdigest()[:8]
        d_id = f"md_{idx}_{content_hash}"
        metadata = d_doc.metadata.copy()
        metadata["dad_id"] = d_id
        d_content = d_doc.page_content
        # R2-M2 修复：确保 temp_doc 包含组装好的 dad_id metadata 字典
        temp_doc = Document(page_content=d_content, metadata=metadata)
        sub_chunks = son_splitter.split_documents([temp_doc])
        for c_doc in sub_chunks:
            c_doc.metadata["dad_id"] = d_id
            c_doc.metadata["dad_content"] = d_content
            son_docs.append(c_doc)
    return son_docs

def docx_qingxi(daichulidocx):
    dad_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=100,
        separators=["\n\n", "。", "！", "？", ".\n", "\n", " ", ""]
    )
    son_qiefenguize = RecursiveCharacterTextSplitter(
        chunk_size=300,
        chunk_overlap=45,
        separators=["\n\n", "。", "！", "？", ".\n", "\n", " ", ""]
    )
    son_docs = []
    dad_docs = dad_splitter.split_documents(daichulidocx)
    for idx, d_doc in enumerate(dad_docs):
        content_hash = hashlib.md5(d_doc.page_content.encode('utf-8')).hexdigest()[:8]
        d_id = f"docx_{idx}_{content_hash}"
        d_content = d_doc.page_content
        metadata = d_doc.metadata.copy()
        metadata['dad_id'] = d_id
        temp_docs = Document(page_content=d_content, metadata=metadata)
        sub_chunks = son_qiefenguize.split_documents([temp_docs])
        for s_doc in sub_chunks:
            s_doc.metadata['dad_id'] = d_id
            s_doc.metadata['dad_content'] = d_content
            son_docs.append(s_doc)
    return son_docs

def txt_qingxi(daichulitxt):
    dad_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=100,
        separators=["\n\n", "。", "！", "？", ".\n", "\n", " ", ""]
    )
    son_qiefenguize = RecursiveCharacterTextSplitter(
        chunk_size=300,
        chunk_overlap=45,
        separators=["\n\n", "。", "！", "？", ".\n", "\n", " ", ""]
    )
    son_docs = []
    dad_docs = dad_splitter.split_documents(daichulitxt)
    for idx, d_doc in enumerate(dad_docs):
        content_hash = hashlib.md5(d_doc.page_content.encode('utf-8')).hexdigest()[:8]
        d_id = f"txt_{idx}_{content_hash}"
        d_content = d_doc.page_content
        metadata = d_doc.metadata.copy()
        metadata['dad_id'] = d_id
        temp_docs = Document(page_content=d_content, metadata=metadata)
        sub_chunks = son_qiefenguize.split_documents([temp_docs])
        for s_doc in sub_chunks:
            s_doc.metadata['dad_id'] = d_id
            s_doc.metadata['dad_content'] = d_content
            son_docs.append(s_doc)
    return son_docs
