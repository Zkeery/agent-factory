"""成品源码静态护栏：拦住「Python 普通字符串里嵌 JS，\n 被吃成真换行」等高危模式。"""
from __future__ import annotations

import re

_TRIPLE = re.compile(
    r"(?P<prefix>r|R|rb|Rb|rB|RB|br|Br|bR|BR)?(?P<q>\"\"\"|\'\'\')"
    r"(?P<body>[\s\S]*?)(?P=q)",
    re.MULTILINE,
)


def _script_chunks(html_like: str) -> list[str]:
    chunks: list[str] = []
    lower = html_like.lower()
    start = 0
    while True:
        i = lower.find("<script", start)
        if i < 0:
            break
        j = lower.find(">", i)
        if j < 0:
            break
        k = lower.find("</script>", j + 1)
        if k < 0:
            break
        chunks.append(html_like[j + 1 : k])
        start = k + len("</script>")
    return chunks


def _js_string_has_raw_newline(script: str) -> bool:
    """启发式：JS 单/双引号字符串内部出现未转义的真实换行。"""
    i = 0
    n = len(script)
    while i < n:
        ch = script[i]
        if ch in ("'", '"'):
            quote = ch
            i += 1
            while i < n:
                c = script[i]
                if c == "\\":
                    i += 2
                    continue
                if c == quote:
                    i += 1
                    break
                if c == "\n":
                    return True
                i += 1
            continue
        i += 1
    return False


def check_embedded_js_safety(app_py_source: str) -> tuple[bool, str]:
    """探测非 raw 三引号中嵌入的 <script> 是否含「字符串跨真换行」。"""
    if not app_py_source:
        return True, ""

    for m in _TRIPLE.finditer(app_py_source):
        prefix = (m.group("prefix") or "").lower()
        body = m.group("body") or ""
        if "r" in prefix:
            continue
        if "<script" not in body.lower():
            continue
        for script in _script_chunks(body):
            if _js_string_has_raw_newline(script):
                return (
                    False,
                    "嵌入的 JS 字符串含未转义换行（常见于 Python 普通三引号里写 \\n 被解释成真换行）。"
                    "请改用 r\"\"\"...\"\"\"，或确保写入文件的源码里 JS 换行是两个字符 \\\\n。",
                )
    return True, "embedded js ok"



def _looks_like_tryon_source(source: str) -> bool:
    blob = source or ""
    lower = blob.lower()
    keys = (
        "试衣", "试穿", "换装", "虚拟试穿", "try-on", "tryon", "virtual try-on",
        "上身效果", "看上身",
    )
    return any(k.lower() in lower if k.isascii() else k in blob for k in keys)


def check_tryon_produces_image(app_py_source: str) -> tuple[bool, str]:
    """试衣类源码必须带出图能力；禁止唯一产物为长文换装方案/提示词。

    强出图标记：image_base64 / image/png / /preview.png / Image.new / from PIL / PIL。
    仅有上传预览用的 <img、无服务端出图字段，且带换装文案回落特征 → 失败。
    """
    if not app_py_source or not _looks_like_tryon_source(app_py_source):
        return True, ""

    src = app_py_source
    strong = (
        "image_base64",
        "image/png",
        "/preview.png",
        "Image.new",
        "from PIL",
        "import PIL",
        "PIL.Image",
    )
    if any(m in src for m in strong):
        return True, "tryon image ok"

    # 弱标记：仅有 <img（常见于上传预览）不足以证明 generate 出图
    text_only_hints = (
        "换装方案", "换装建议", "换装预览说明", "提示词",
        "local_fallback", "规则化换装",
    )
    looks_text_only = any(h in src for h in text_only_hints)
    if looks_text_only or ("<img" in src and "image_base64" not in src and "image/png" not in src):
        return (
            False,
            "试衣/试穿类成品必须产出可查看预览图（Image / image_base64 / image/png / /preview.png），"
            "禁止唯一产物为长文换装方案或提示词。",
        )
    return (
        False,
        "试衣/试穿类成品必须产出可查看预览图（Image / image_base64 / image/png / <img 结果图），"
        "禁止仅返回文本。",
    )


def _looks_like_video_source(source: str) -> bool:
    blob = source or ""
    lower = blob.lower()
    keys = (
        "短视频", "生成视频", "成片", "视频",
        "short video", "video generator",
    )
    return any(k.lower() in lower if k.isascii() else k in blob for k in keys)


def looks_like_video_idea(idea: str) -> bool:
    """从用户想法文本判断是否为视频类（用于运行时护栏）。"""
    blob = (idea or "").lower()
    keys = ("视频", "短视频", "成片", "生成影像", "video", "小视频", "片段")
    return any((k.lower() if k.isascii() else k) in blob for k in keys)


def check_video_produces_video(app_py_source: str) -> tuple[bool, str]:
    """视频类源码必须带可播放视频出口；禁止合成失败时回退纯文案伪装成功。"""
    if not app_py_source or not _looks_like_video_source(app_py_source):
        return True, ""

    src = app_py_source
    video_exit = (
        "video_url", "/video", ".mp4", ".avi", ".webm",
        "videowriter", "imageio", "moviepy", "ffmpeg",
    )
    if not any(m in src.lower() for m in video_exit):
        return (
            False,
            "视频类成品必须产出可播放视频文件（video_url / /video / mp4 / avi / ffmpeg 等出口），"
            "禁止仅输出文案或提示词。",
        )

    # 捕获异常后回退纯文案：视频出口被绕过，闸门却拦不到（仍 HTTP 200）
    text_fallback_hints = ("本地视频合成异常", "视频合成异常", "合成异常")
    if any(h in src for h in text_fallback_hints):
        return (
            False,
            "视频类成品不得在合成失败时回退纯文案伪装成功；必须返回可播放视频，"
            "否则让工厂判失败。",
        )

    return True, "video ok"
