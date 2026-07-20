"""百度智能云 OCR 集成（手写文字识别 / 通用文字识别高精度版）。

百度 OCR 不是 OpenAI 兼容接口，需要单独适配：
  1. 用 API Key + Secret Key 换 access_token（30 天有效，进程内缓存）
  2. POST https://aip.baidubce.com/rest/2.0/ocr/v1/handwriting
     body: image=<base64+urlencode> & recognize_granularity=big
  3. 返回 words_result 数组，每项含 words 字段，拼接成完整文本

支持场景：
  - 图片（jpg/png/bmp）：直接调 handwriting
  - PDF：用 PyMuPDF 逐页转图片，逐页调 OCR，合并结果

免费额度：500 次/天（手写接口）；后付费约 0.15 元/次。
"""
from __future__ import annotations

import base64
import logging
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger("brain.baidu_ocr")

# 百度 OCR 端点
_TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
_HANDWRITING_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/handwriting"
_ACCURATE_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic"  # 通用高精度

# 进程内 token 缓存：{(api_key, secret_key): (token, expire_ts)}
_token_cache: Dict[Tuple[str, str], Tuple[str, float]] = {}
_TOKEN_BUFFER = 600  # 提前 10 分钟过期

# 单张图片最大字节（百度限制 base64 后 4M，原图约 3M）
_MAX_IMAGE_BYTES = 3 * 1024 * 1024


def _get_access_token(api_key: str, secret_key: str) -> str:
    """获取 access_token，带缓存。

    百度 access_token 有效期 30 天，进程内缓存避免重复请求。
    """
    cache_key = (api_key, secret_key)
    cached = _token_cache.get(cache_key)
    if cached:
        token, expire_ts = cached
        if time.time() < expire_ts - _TOKEN_BUFFER:
            return token

    try:
        resp = requests.post(
            _TOKEN_URL,
            params={
                "grant_type": "client_credentials",
                "client_id": api_key,
                "client_secret": secret_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("获取百度 access_token 失败: %s", e)
        raise RuntimeError(f"百度 access_token 获取失败: {e}")

    token = data.get("access_token")
    if not token:
        err = data.get("error_description") or data.get("error") or "未知错误"
        raise RuntimeError(f"百度 access_token 获取失败: {err}")

    expires_in = float(data.get("expires_in", 2592000))  # 默认 30 天
    expire_ts = time.time() + expires_in
    _token_cache[cache_key] = (token, expire_ts)
    logger.info("百度 access_token 已获取，有效期至 %s", time.strftime("%Y-%m-%d %H:%M", time.localtime(expire_ts)))
    return token


def _encode_image(image_bytes: bytes) -> str:
    """base64 + urlencode 编码图片字节。"""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return urllib.parse.quote(b64, safe="")


def _call_handwriting(image_bytes: bytes, token: str) -> str:
    """调用手写文字识别接口，返回识别文本（多行用 \\n 连接）。"""
    encoded = _encode_image(image_bytes)
    try:
        resp = requests.post(
            _HANDWRITING_URL,
            params={"access_token": token},
            data={
                "image": encoded,
                "recognize_granularity": "big",  # 不定位单字，更快
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error("百度 OCR 请求失败: %s", e)
        raise RuntimeError(f"百度 OCR 请求失败: {e}")

    if "error_code" in data:
        err_code = data.get("error_code")
        err_msg = data.get("error_msg", "")
        # 常见错误：111 token 过期、17 配额超限、216201 缺参数
        logger.error("百度 OCR 错误: code=%s msg=%s", err_code, err_msg)
        raise RuntimeError(f"百度 OCR 错误 [{err_code}]: {err_msg}")

    words_result = data.get("words_result") or []
    lines = [item.get("words", "") for item in words_result if item.get("words")]
    return "\n".join(lines)


def recognize_image(
    image_bytes: bytes,
    *,
    api_key: str,
    secret_key: str,
) -> str:
    """识别单张图片中的手写文字。

    Args:
        image_bytes: 原始图片字节（jpg/png/bmp）
        api_key: 百度智能云 API Key
        secret_key: 百度智能云 Secret Key

    Returns:
        识别出的文本（多行用 \\n 连接）。空字符串表示未识别到内容。
    """
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        logger.warning("图片过大 %d bytes，可能超过百度 4M base64 限制", len(image_bytes))

    token = _get_access_token(api_key, secret_key)
    return _call_handwriting(image_bytes, token)


def recognize_pdf(
    pdf_bytes: bytes,
    *,
    api_key: str,
    secret_key: str,
    max_pages: int = 10,
    dpi: int = 200,
) -> str:
    """识别 PDF 文件中的手写文字。

    把 PDF 每页转成图片，逐页调手写 OCR，合并结果。
    每页结果用 '--- 第 N 页 ---' 分隔。

    Args:
        pdf_bytes: PDF 文件字节
        api_key / secret_key: 百度凭证
        max_pages: 最多处理前 N 页（避免超额）
        dpi: 渲染 DPI，200 是清晰度和文件大小的平衡点

    Returns:
        合并后的文本。
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise RuntimeError(f"PyMuPDF(fitz) 未安装，无法处理 PDF: {e}")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = min(len(doc), max_pages)
    if total_pages == 0:
        return ""

    logger.info("百度 OCR 多页文档（%d 页），分页 OCR 后合并", total_pages)
    token = _get_access_token(api_key, secret_key)

    all_texts: List[str] = []
    for page_idx in range(total_pages):
        page = doc.load_page(page_idx)
        # 渲染为 PNG 字节
        pix = page.get_pixmap(dpi=dpi)
        img_bytes = pix.tobytes("png")

        # 压缩到 3M 以下（如果超过）
        if len(img_bytes) > _MAX_IMAGE_BYTES:
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(img_bytes))
                # 等比缩放
                ratio = (_MAX_IMAGE_BYTES / len(img_bytes)) ** 0.5
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="PNG", optimize=True)
                img_bytes = buf.getvalue()
                logger.info("第 %d 页图片压缩: %d -> %d bytes", page_idx + 1, len(img_bytes), len(img_bytes))
            except Exception as e:
                logger.warning("第 %d 页图片压缩失败: %s", page_idx + 1, e)

        try:
            page_text = _call_handwriting(img_bytes, token)
            logger.info("百度 OCR 第 %d/%d 页完成，识别 %d 字符",
                        page_idx + 1, total_pages, len(page_text))
        except Exception as e:
            logger.error("百度 OCR 第 %d 页失败: %s", page_idx + 1, e)
            page_text = f"[第 {page_idx + 1} 页 OCR 失败: {e}]"

        all_texts.append(f"--- 第 {page_idx + 1} 页 ---\n{page_text}")

    doc.close()
    return "\n\n".join(all_texts)


def recognize_file(
    file_path: str,
    *,
    api_key: str,
    secret_key: str,
    max_pdf_pages: int = 10,
) -> str:
    """根据文件类型路由到 recognize_image 或 recognize_pdf。

    Args:
        file_path: 文件路径
        api_key / secret_key: 百度凭证
        max_pdf_pages: PDF 最大页数

    Returns:
        识别出的文本。
    """
    if not api_key or not secret_key:
        raise RuntimeError("百度 OCR 未配置 API_KEY / SECRET_KEY")

    ext = file_path.lower().rsplit(".", 1)[-1] if "." in file_path else ""
    if ext == "pdf":
        with open(file_path, "rb") as f:
            pdf_bytes = f.read()
        return recognize_pdf(pdf_bytes, api_key=api_key, secret_key=secret_key, max_pages=max_pdf_pages)
    elif ext in ("jpg", "jpeg", "png", "bmp"):
        with open(file_path, "rb") as f:
            img_bytes = f.read()
        return recognize_image(img_bytes, api_key=api_key, secret_key=secret_key)
    else:
        raise RuntimeError(f"百度 OCR 不支持的文件类型: .{ext}")


def is_configured(api_key: Optional[str], secret_key: Optional[str]) -> bool:
    """检查百度 OCR 是否已配置凭证。"""
    return bool(api_key and secret_key)
