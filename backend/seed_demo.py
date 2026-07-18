"""开发用种子脚本：生成示例笔记图片并填充真实结构化数据。

用途：在没有 OpenAI Key 的情况下，让前端预览看到一个有节点、有边、
有 OCR 文本与关键词的「知识星座」。运行：

    cd backend && python seed_demo.py

会：
  1. 在各监听目录下生成若干 PNG「笔记」图片（手写页风格）
  2. 直接写入 done 状态的笔记（标题/摘要/关键词/聚类 embedding）
  3. 生成缩略图
  4. 计算候选链接

幂等：按 file_path 去重，重复运行不会产生重复数据。
"""
from __future__ import annotations

import math
import os
import random
from datetime import datetime, timedelta, timezone

import database
import ocr_processor
from config import get_config

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("Pillow 未安装，请先 pip install pillow")

# 主题簇：每簇若干笔记，簇内 embedding 高度相似 → 形成链接
CLUSTERS = [
    {
        "topic": "需求与产品",
        "centroid": [1.0] * 64 + [0.0] * (1536 - 64),
        "notes": [
            ("2026-07-08_甲方需求分析", "梳理甲方在二期提出的核心需求，包含权限分级、报表导出与移动端适配。", ["需求", "甲方", "权限", "报表"]),
            ("2026-07-09_用户调研纪要", "访谈 8 位目标用户，发现高频痛点集中在批量操作与历史回溯。", ["用户调研", "痛点", "批量操作", "访谈"]),
            ("2026-07-10_产品路线图", "Q3 聚焦协作能力，Q4 做数据看板，优先级：协作 > 看板 > 自动化。", ["路线图", "协作", "数据看板", "优先级"]),
            ("2026-07-10_需求优先级排序", "按影响面×紧急度打分，甲方需求与用户调研结论对齐。", ["优先级", "需求", "评分", "紧急度"]),
        ],
    },
    {
        "topic": "架构与技术",
        "centroid": [0.0] * 64 + [1.0] * 64 + [0.0] * (1536 - 128),
        "notes": [
            ("2026-07-07_系统架构设计", "采用 FastAPI + SQLite 的轻量中转架构，watchdog 监听 + 队列消费解耦。", ["架构", "FastAPI", "watchdog", "队列"]),
            ("2026-07-08_技术选型对比", "React Flow vs D3：交互优先选 React Flow；向量库选 SQLite 内存检索。", ["技术选型", "React Flow", "D3", "向量检索"]),
            ("2026-07-09_API接口设计", "REST 风格，/api/notes /api/graph /api/qa 三大资源，统一 JSON 返回。", ["API", "REST", "JSON", "接口"]),
            ("2026-07-09_数据库表设计", "notes/links/qa_history/feedback 四表，embedding 存 JSON 文本列便于调试。", ["数据库", "表设计", "embedding", "SQLite"]),
        ],
    },
    {
        "topic": "会议与记录",
        "centroid": [0.0] * 128 + [1.0] * 64 + [0.0] * (1536 - 192),
        "notes": [
            ("2026-07-05_周会记录", "本周完成需求评审，下周进入开发，风险点：第三方 OCR 接口稳定性。", ["周会", "评审", "开发", "风险"]),
            ("2026-07-08_评审会议纪要", "架构方案通过，需补充容量评估与降级策略，下次评审定在周五。", ["评审", "架构", "容量", "降级"]),
            ("2026-07-11_头脑风暴", "围绕「笔记如何互联」发散，提出语义+关键词+时间三维候选链接。", ["头脑风暴", "互联", "语义", "候选链接"]),
        ],
    },
    {
        "topic": "设计与创意",
        "centroid": [0.0] * 192 + [1.0] * 64 + [0.0] * (1536 - 256),
        "notes": [
            ("2026-07-06_UI草图", "深空墨蓝底 + 星光节点，图谱画布为主视觉，左导航右抽屉三栏结构。", ["UI", "草图", "深空", "图谱"]),
            ("2026-07-07_交互设计稿", "节点点击展开详情抽屉，边按权重粗细分级，hover 高亮关联节点。", ["交互", "详情抽屉", "权重", "高亮"]),
            ("2026-07-08_配色方案", "主色 #0B1020，强调 cyan #22D3EE，反馈玫红 #F472B6，避免通用紫渐变。", ["配色", "主色", "强调色", "反馈"]),
        ],
    },
]

DEVICE_MAP = [
    ("data/synced_notes/ipad-goodnotes", "iPad", "GoodNotes"),
    ("data/synced_notes/android-notes", "Android", "Samsung Notes"),
    ("data/synced_notes/pc-onenote", "PC", "OneNote"),
    ("data/synced_notes/camera-shots", "Camera", "白板拍摄"),
]


def _make_note_image(path: str, title: str, lines: list[str]) -> None:
    """生成一张「手写笔记」风格的 PNG：浅色纸 + 横线 + 标题与正文。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    w, h = 1000, 1300
    img = Image.new("RGB", (w, h), "#FBF8F0")
    d = ImageDraw.Draw(img)
    # 顶部标题区
    d.rectangle([0, 0, w, 90], fill="#F0E9D6")
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
        body_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
    except Exception:
        title_font = ImageFont.load_default()
        body_font = ImageFont.load_default()
    d.text((40, 28), title, fill="#2B2A26", font=title_font)
    # 横线
    for y in range(150, h - 60, 48):
        d.line([(40, y), (w - 40, y)], fill="#D8CFB4", width=1)
    # 正文（模拟手写）
    for i, line in enumerate(lines[:14]):
        d.text((50, 150 + i * 48), line, fill="#3A382E", font=body_font)
    img.save(path, "PNG")


def _clustered_embedding(centroid: list[float], seed: int) -> list[float]:
    """在簇心向量上叠加小噪声，保证簇内高相似、簇间近正交。"""
    rng = random.Random(seed)
    noise_strength = 0.18
    vec = [c + rng.uniform(-noise_strength, noise_strength) for c in centroid]
    # 补齐到 1536 维（剩余维度加微小噪声）
    while len(vec) < 1536:
        vec.append(rng.uniform(-0.02, 0.02))
    vec = vec[:1536]
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def main() -> None:
    cfg = get_config()
    database.init_db()
    print("seed: 数据库已初始化")

    now = datetime.now(timezone.utc)
    dev_idx = 0
    created = 0

    for cluster in CLUSTERS:
        for j, (name, summary, keywords) in enumerate(cluster["notes"]):
            watch_dir, device, app = DEVICE_MAP[dev_idx % len(DEVICE_MAP)]
            dev_idx += 1
            file_path = os.path.join(watch_dir, f"{name}.png")
            # 生成图片
            body_lines = [
                f"# {name.replace('_', ' ')}",
                summary,
                "",
                f"关键词：{', '.join(keywords)}",
                f"所属主题：{cluster['topic']}",
                "（示例笔记 · 由 seed_demo.py 生成）",
            ]
            _make_note_image(file_path, name.replace("_", " "), body_lines)

            # 去重
            existing = database.get_note_by_path(file_path)
            if existing:
                note_id = existing["id"]
            else:
                file_hash = ocr_processor.compute_file_hash(file_path)
                note_id = database.insert_note(
                    file_path=file_path,
                    file_hash=file_hash,
                    source_device=device,
                    source_app=app,
                    title=name.replace("_", " "),
                    status="processing",
                )
            if note_id is None:
                continue

            # 缩略图
            thumb_path = os.path.join(cfg.THUMBNAIL_DIR, f"{note_id}.jpg")
            ocr_processor.generate_thumbnail(file_path, thumb_path)

            # 写入结构化数据 + 聚类 embedding
            embedding = _clustered_embedding(cluster["centroid"], seed=note_id)
            # 时间错开，让 temporal_decay 也有差异
            created_at = (now - timedelta(days=j * 1.5, hours=dev_idx)).isoformat()
            import sqlite3
            with database._db_lock, database.get_conn() as conn:
                conn.execute(
                    """
                    UPDATE notes SET title=?, ocr_text=?, summary=?, keywords=?,
                        embedding=?, thumbnail_path=?, status=?, processed_at=?, created_at=?
                    WHERE id=?
                    """,
                    (
                        name.replace("_", " "),
                        f"{summary}\n\n（示例笔记 · {cluster['topic']}）",
                        summary,
                        __import__("json").dumps(keywords, ensure_ascii=False),
                        __import__("json").dumps(embedding),
                        thumb_path if os.path.exists(thumb_path) else None,
                        "done",
                        now.isoformat(),
                        created_at,
                        note_id,
                    ),
                )
            created += 1

    print(f"seed: 已写入 {created} 条示例笔记，开始计算候选链接…")
    # 对每条 done 笔记重算链接
    for n in database.get_done_notes_with_embeddings():
        try:
            import graph_api
            cnt = graph_api.recompute_links_for_note(n["id"])
            if cnt:
                print(f"  note#{n['id']} 新增 {cnt} 条链接")
        except Exception as e:
            print(f"  note#{n['id']} 链接计算失败: {e}")

    stats = database.get_stats()
    print(f"seed: 完成。笔记 {stats['notes_total']} / 链接 {stats['links_total']}")


if __name__ == "__main__":
    main()
