"""OCR + 结构化 Pipeline。

主流程 process_note(note_id):
  1. 加载笔记行
  2. 文件转图像（PDF 用 PyMuPDF，PNG/JPG 直接读字节）
  3. 调 GPT-4o vision 抽取 {title, ocr_text, summary, keywords[]}
  4. 调 text-embedding-3-small 生成 embedding
  5. 写库 + 生成缩略图
  6. 触发 graph_api.recompute_links_for_note

当未配置 OPENAI_API_KEY 时进入 DEMO 模式：
  - title 取文件名
  - ocr_text 写入提示语
  - keywords 为空
  - embedding 为随机 1536 维向量（保证图谱/检索端到端可用）
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import random
from typing import Any, Dict, List, Optional

import database
import graph_api
from config import get_config

logger = logging.getLogger("brain.ocr")

SUPPORTED_EXTS = (".pdf", ".png", ".jpg", ".jpeg")


# ---------------------------------------------------------------------------
# 文件工具
# ---------------------------------------------------------------------------
def compute_file_hash(path: str, chunk_size: int = 1 << 16) -> str:
    """计算文件 SHA256 哈希，用于去重。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def file_to_images(path: str) -> List[str]:
    """把笔记文件转成 base64 编码的图像列表。

    - PDF：每页渲染为 PNG（PyMuPDF/fitz）
    - PNG/JPG：直接读取字节并 base64
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        try:
            import fitz  # PyMuPDF
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("PyMuPDF(fitz) 未安装，无法处理 PDF") from e
        images: List[str] = []
        doc = fitz.open(path)
        try:
            # 控制总页数，避免超大 PDF 把 token 打爆
            max_pages = min(doc.page_count, 10)
            for i in range(max_pages):
                page = doc.load_page(i)
                # 150 DPI 左右，对 OCR 足够
                zoom = 2.0
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                png_bytes = pix.tobytes("png")
                images.append(base64.b64encode(png_bytes).decode("ascii"))
        finally:
            doc.close()
        return images
    elif ext in (".png", ".jpg", ".jpeg"):
        with open(path, "rb") as f:
            data = f.read()
        return [base64.b64encode(data).decode("ascii")]
    else:
        raise ValueError(f"不支持的文件类型: {ext}")


def generate_thumbnail(path: str, out_path: str, width: int = 200, quality: int = 80) -> str:
    """生成缩略图（200px 宽，JPEG 质量 80）。返回输出路径。

    PDF 取第一页；图片直接缩放。失败时返回空字符串，调用方应处理。
    """
    try:
        from PIL import Image
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("Pillow 未安装，无法生成缩略图") from e

    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".pdf":
            import fitz
            doc = fitz.open(path)
            try:
                if doc.page_count == 0:
                    return ""
                page = doc.load_page(0)
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                png_bytes = pix.tobytes("png")
            finally:
                doc.close()
            import io
            img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        else:
            img = Image.open(path).convert("RGB")

        ratio = width / float(img.width) if img.width else 1.0
        new_height = max(1, int(img.height * ratio))
        thumb = img.resize((width, new_height), Image.LANCZOS)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        thumb.save(out_path, "JPEG", quality=quality)
        return out_path
    except Exception as e:
        logger.warning("缩略图生成失败 %s: %s", path, e)
        return ""


# ---------------------------------------------------------------------------
# OpenAI 客户端
# ---------------------------------------------------------------------------
def _get_client():
    """惰性构造 OpenAI 客户端。未配置 key 时返回 None（进入 demo 模式）。"""
    cfg = get_config()
    if not cfg.OPENAI_API_KEY:
        return None
    try:
        from openai import OpenAI
    except ImportError as e:  # pragma: no cover
        logger.error("openai SDK 未安装: %s", e)
        return None
    kwargs: Dict[str, Any] = {"api_key": cfg.OPENAI_API_KEY}
    if cfg.OPENAI_BASE_URL:
        kwargs["base_url"] = cfg.OPENAI_BASE_URL
    return OpenAI(**kwargs)


def _strip_fences(text: str) -> str:
    """剥离 ```json ... ``` 等 markdown 代码围栏。"""
    s = text.strip()
    if s.startswith("```"):
        # 去掉首行 ```json / ```
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1:]
        if s.endswith("```"):
            s = s[: -3]
    return s.strip()


def _parse_structured(raw: str) -> Dict[str, Any]:
    """健壮地解析 LLM 返回的结构化 JSON。"""
    cleaned = _strip_fences(raw)
    # 尝试直接解析
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # 尝试抽取第一个 {...}
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(cleaned[start: end + 1])
        except json.JSONDecodeError:
            pass
    return {}


# ---------------------------------------------------------------------------
# OCR + 结构化（真实 / Demo）
# ---------------------------------------------------------------------------
_OCR_PROMPT = (
    "你是一个手写笔记 OCR 与结构化助手。请仔细识别图片中的手写内容，"
    "并以 JSON 返回：\n"
    '{"title": "简短标题", "ocr_text": "完整识别文本", '
    '"summary": "1-3 句摘要", "keywords": ["关键词1", "关键词2"]}\n'
    "要求：仅返回 JSON，不要任何解释；关键词 3-8 个；"
    "若有多张图，ocr_text 按页用 \\n\\n 分隔。"
)


def _ocr_structured(client, images: List[str]) -> Dict[str, Any]:
    """调用 GPT-4o vision 抽取结构化字段。"""
    cfg = get_config()
    content: List[Dict[str, Any]] = [{"type": "text", "text": _OCR_PROMPT}]
    for img_b64 in images[:10]:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
        })
    resp = client.chat.completions.create(
        model=cfg.LLM_MODEL,
        messages=[{"role": "user", "content": content}],
        temperature=0.1,
        max_tokens=2000,
    )
    raw = resp.choices[0].message.content or ""
    return _parse_structured(raw)


def _embed_text(client, text: str) -> List[float]:
    """调用 text-embedding-3-small 生成向量。"""
    cfg = get_config()
    resp = client.embeddings.create(model=cfg.EMBEDDING_MODEL, input=text)
    return list(resp.data[0].embedding)


def _demo_structured(file_path: str) -> Dict[str, Any]:
    """Demo 模式：从文件名派生 title，其余占位。"""
    base = os.path.splitext(os.path.basename(file_path))[0]
    return {
        "title": base.replace("_", " ").replace("-", " ").strip() or "(未命名笔记)",
        "ocr_text": "(demo 模式 — 设置 OPENAI_API_KEY 以启用真实 OCR)",
        "summary": f"演示笔记：{base}",
        "keywords": [],
    }


def _demo_embedding(seed: int = 42) -> List[float]:
    """Demo 模式：生成确定性的随机 1536 维向量。

    Args:
        seed: 随机种子，建议传入 note_id 使不同笔记得到不同向量，
              从而在 demo 模式下也能形成有差异的图谱。
    """
    cfg = get_config()
    dim = cfg.EMBEDDING_DIM
    rng = random.Random(seed)
    vec = [rng.uniform(-1.0, 1.0) for _ in range(dim)]
    norm = sum(x * x for x in vec) ** 0.5
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def process_note(note_id: int) -> None:
    """处理单条笔记的完整 OCR + 结构化 + embedding + 图谱重算流程。

    任何异常都把状态置为 'failed' 并记录日志，不向上抛出（用于后台 worker）。
    """
    note = database.get_note(note_id)
    if not note:
        logger.warning("process_note: 笔记 %s 不存在", note_id)
        return
    file_path = note["file_path"]
    if not os.path.exists(file_path):
        logger.error("文件不存在: %s", file_path)
        database.update_note_status(note_id, "failed")
        return

    database.update_note_status(note_id, "processing")
    client = _get_client()
    is_demo = client is None

    try:
        images = file_to_images(file_path)
        if not images:
            raise RuntimeError("未能从文件提取到任何图像")

        if is_demo:
            logger.info("[demo] 处理笔记 %s (%s)", note_id, file_path)
            structured = _demo_structured(file_path)
            embedding = _demo_embedding(seed=note_id)
        else:
            structured = _ocr_structured(client, images)
            if not structured:
                raise RuntimeError("LLM 返回内容无法解析为 JSON")
            embed_input = (
                (structured.get("title") or "")
                + "\n"
                + (structured.get("summary") or "")
                + "\n"
                + (structured.get("ocr_text") or "")
            )
            embedding = _embed_text(client, embed_input)

        # 缩略图
        cfg = get_config()
        thumb_name = f"{note_id}.jpg"
        thumb_path = os.path.join(cfg.THUMBNAIL_DIR, thumb_name)
        generate_thumbnail(file_path, thumb_path)

        database.update_note_content(
            note_id,
            title=structured.get("title") or os.path.basename(file_path),
            ocr_text=structured.get("ocr_text") or "",
            summary=structured.get("summary") or "",
            keywords=structured.get("keywords") or [],
            embedding=embedding,
            thumbnail_path=thumb_path if os.path.exists(thumb_path) else None,
            status="done",
        )

        # 重算候选链接
        try:
            graph_api.recompute_links_for_note(note_id)
        except Exception as ge:
            logger.warning("链接重算失败 note %s: %s", note_id, ge)

        logger.info("笔记 %s 处理完成 (demo=%s)", note_id, is_demo)

    except Exception as e:
        logger.exception("笔记 %s 处理失败: %s", note_id, e)
        database.update_note_status(note_id, "failed")
