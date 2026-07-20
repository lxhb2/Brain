"""OCR + 结构化 Pipeline（多模型支持）。

主流程 process_note(note_id, model_id=None):
  1. 加载笔记行
  2. 文件转图像（PDF 用 PyMuPDF，PNG/JPG 直接读字节）
  3. 调多模态 vision 模型抽取 {title, ocr_text, summary, keywords[]}
     - 若指定 model_id，仅用该模型
     - 否则用 primary 模型，失败时按 enabled 顺序 fallback
  4. 调 embedding 模型生成向量
  5. 写库（含 ocr_model 字段）+ 生成缩略图
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
import settings_store
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
_OCR_PROMPT = """你是一名专业的手写笔记 OCR 与结构化助手。请仔细识别图片中的所有手写内容，要求：

1. **完整准确地转录**所有手写文字，包括公式、符号、图表标注、箭头说明等。
2. 保留原文的段落结构与层次（标题、列表、缩进）。
3. 数学公式用 LaTeX 语法（行内 $...$，独立块 $$...$$）。
4. 表格用 Markdown 表格语法。
5. 无法识别的字用 □ 占位，不要瞎猜。
6. 若有多张图，按页顺序输出，页与页之间用 `---PAGE---` 分隔。

识别完成后，再用同样的 JSON 格式返回结构化字段：

```json
{
  "title": "简短标题（5-15字，概括主题）",
  "ocr_text": "完整识别的文本（含公式/表格的 markdown）",
  "summary": "1-3 句摘要，提炼核心知识点",
  "keywords": ["关键词1", "关键词2", ...]
}
```

要求：
- 仅返回上述 JSON 对象，不要任何额外解释或前后缀
- 关键词 3-8 个，涵盖主题、方法、对象等
- title 不要包含"笔记""note"等无意义词
- ocr_text 必须保留全部识别内容，不要截断"""


def _call_vision_model(client, model_id: str, images: List[str]) -> Dict[str, Any]:
    """调用指定的多模态模型做 OCR + 结构化。

    单图（图片笔记或单页 PDF）：一次调用，结构化输出。
    多图（多页 PDF）：分页调用，每页单独 OCR，最后合并 ocr_text，
    title 取首页，summary 综合各页摘要。这样能避免多图一次性发送导致
    模型注意力分散、内容丢失或被 token 上限截断。

    Args:
        client: OpenAI 客户端
        model_id: 模型 ID（如 Qwen/Qwen3-VL-32B-Instruct）
        images: base64 编码的图片列表

    Returns:
        解析后的结构化 dict（可能为空 dict 表示解析失败）
    """
    if len(images) <= 1:
        return _call_vision_single(client, model_id, images)

    # 多页：分页 OCR，最后合并
    logger.info("多页文档（%d 页），分页 OCR 后合并", len(images))
    page_results: List[Dict[str, Any]] = []
    for idx, img in enumerate(images):
        try:
            r = _call_vision_single(client, model_id, [img], page_idx=idx + 1, total_pages=len(images))
            if r:
                page_results.append(r)
            else:
                logger.warning("第 %d/%d 页 OCR 返回空，跳过", idx + 1, len(images))
        except Exception as e:
            logger.warning("第 %d/%d 页 OCR 失败: %s", idx + 1, len(images), e)
            continue

    if not page_results:
        return {}

    # 合并
    merged_ocr_parts: List[str] = []
    for i, r in enumerate(page_results, 1):
        page_text = r.get("ocr_text") or ""
        if page_text:
            merged_ocr_parts.append(f"--- 第 {i} 页 ---\n{page_text}")
    merged_ocr = "\n\n".join(merged_ocr_parts)

    # title 用第一页的
    merged_title = page_results[0].get("title") or ""
    # summary 综合各页
    summary_parts = [r.get("summary") for r in page_results if r.get("summary")]
    merged_summary = " | ".join(summary_parts) if summary_parts else ""

    # keywords 合并去重
    kw_set = []
    for r in page_results:
        for k in r.get("keywords") or []:
            if k not in kw_set:
                kw_set.append(k)

    return {
        "title": merged_title or "(多页笔记)",
        "ocr_text": merged_ocr,
        "summary": merged_summary,
        "keywords": kw_set[:10],
    }


def _call_vision_single(client, model_id: str, images: List[str],
                        page_idx: Optional[int] = None, total_pages: Optional[int] = None) -> Dict[str, Any]:
    """单次调用视觉模型（单图或单页）。

    Args:
        client: OpenAI 客户端
        model_id: 模型 ID
        images: 单张 base64 图片
        page_idx: 当前页码（多页时用）
        total_pages: 总页数（多页时用）
    """
    if page_idx and total_pages:
        prompt = f"""你是一名专业的手写笔记 OCR 与结构化助手。这是多页文档的第 {page_idx}/{total_pages} 页，请仔细识别本页的所有手写内容，要求：

1. **完整准确地转录**本页所有手写文字，包括公式、符号、图表标注、箭头说明等。
2. 保留原文的段落结构与层次（标题、列表、缩进）。
3. 数学公式用 LaTeX 语法（行内 $...$，独立块 $$...$$）。
4. 表格用 Markdown 表格语法。
5. 无法识别的字用 □ 占位，不要瞎猜。

识别完成后，用 JSON 返回本页的结构化字段：

```json
{{
  "title": "本页标题（5-15字）",
  "ocr_text": "本页完整识别的文本",
  "summary": "本页 1-2 句摘要",
  "keywords": ["本页关键词1", "本页关键词2"]
}}
```

要求：
- 仅返回上述 JSON 对象，不要任何额外解释
- ocr_text 必须保留本页全部识别内容，不要截断"""
    else:
        prompt = _OCR_PROMPT

    content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
    for img_b64 in images[:1]:  # 单次只发一张图
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
        })
    resp = client.chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": content}],
        temperature=0.1,
        max_tokens=8000,  # 单页 OCR 上限放宽
        timeout=120,
    )
    raw = resp.choices[0].message.content or ""
    return _parse_structured(raw)


def _ocr_structured(client, images: List[str], model_id: Optional[str] = None) -> tuple[Dict[str, Any], Optional[str]]:
    """OCR + 结构化，支持指定模型与 fallback。

    Args:
        client: OpenAI 客户端
        images: base64 图片列表
        model_id: 指定使用的模型 id（settings_store 中的 id）。
                  None 表示用 primary，失败时 fallback。

    Returns:
        (structured_dict, used_model_id)
        - structured_dict 解析失败时为空 dict
        - used_model_id 实际成功调用的模型 id（settings_store 里的 id），
          失败时为 None
    """
    if model_id:
        # 指定模型：只试这一个
        m = settings_store.get_ocr_model_by_id(model_id)
        if not m:
            logger.warning("指定的 OCR 模型 %s 不存在", model_id)
            return {}, None
        try:
            result = _call_vision_model(client, m["model"], images)
            if result:
                return result, m["id"]
            logger.warning("模型 %s 返回内容无法解析", m["model"])
            return {}, None
        except Exception as e:
            logger.warning("模型 %s (%s) 调用失败: %s", m.get("name"), m["model"], e)
            return {}, None

    # 未指定模型：按 enabled 顺序尝试，primary 在前
    candidates = settings_store.get_enabled_ocr_models()
    if not candidates:
        # 回退到 env 默认
        cfg = get_config()
        try:
            result = _call_vision_model(client, cfg.LLM_MODEL, images)
            return result, None
        except Exception as e:
            logger.warning("默认模型 %s 调用失败: %s", cfg.LLM_MODEL, e)
            return {}, None

    last_err: Optional[Exception] = None
    for m in candidates:
        try:
            logger.info("尝试 OCR 模型: %s (%s)", m.get("name"), m["model"])
            result = _call_vision_model(client, m["model"], images)
            if result:
                logger.info("OCR 成功，使用模型: %s", m["model"])
                return result, m["id"]
            logger.warning("模型 %s 返回内容无法解析，尝试下一个", m["model"])
        except Exception as e:
            last_err = e
            logger.warning("模型 %s (%s) 失败，尝试下一个: %s",
                           m.get("name"), m["model"], e)
            continue
    if last_err:
        logger.error("所有 OCR 模型均失败，最后错误: %s", last_err)
    return {}, None


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
def process_note(note_id: int, model_id: Optional[str] = None) -> bool:
    """处理单条笔记的完整 OCR + 结构化 + embedding + 图谱重算流程。

    Args:
        note_id: 笔记 id
        model_id: 指定使用哪个 OCR 模型（settings_store 中的 id）。
                  None 表示用 primary 模型，失败时 fallback。

    Returns:
        True 表示处理成功，False 表示失败。

    任何异常都把状态置为 'failed' 并记录日志，不向上抛出（用于后台 worker）。
    """
    note = database.get_note(note_id)
    if not note:
        logger.warning("process_note: 笔记 %s 不存在", note_id)
        return False
    file_path = note["file_path"]
    if not os.path.exists(file_path):
        logger.error("文件不存在: %s", file_path)
        database.update_note_status(note_id, "failed")
        return False

    database.update_note_status(note_id, "processing")
    client = _get_client()
    is_demo = client is None

    try:
        images = file_to_images(file_path)
        if not images:
            raise RuntimeError("未能从文件提取到任何图像")

        used_model_id: Optional[str] = None
        if is_demo:
            logger.info("[demo] 处理笔记 %s (%s)", note_id, file_path)
            structured = _demo_structured(file_path)
            embedding = _demo_embedding(seed=note_id)
        else:
            structured, used_model_id = _ocr_structured(client, images, model_id=model_id)
            if not structured:
                raise RuntimeError("LLM 返回内容无法解析为 JSON（所有候选模型均失败）")
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
            ocr_model=used_model_id,
        )

        # 重算候选链接
        try:
            graph_api.recompute_links_for_note(note_id)
        except Exception as ge:
            logger.warning("链接重算失败 note %s: %s", note_id, ge)

        logger.info("笔记 %s 处理完成 (demo=%s, model=%s)", note_id, is_demo, used_model_id)
        return True

    except Exception as e:
        logger.exception("笔记 %s 处理失败: %s", note_id, e)
        database.update_note_status(note_id, "failed")
        return False
