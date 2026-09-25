"""Mock 模型：离线占位，输出可被结构校验的固定内容，零真钱成本。

真实模型接入时替换本模块（保持相同函数签名），并走结构校验 + 有限重试。
"""
from __future__ import annotations

from typing import Any

from app.services.prd_normalize import normalize_prd_fields


def _clarify_cards(idea: str) -> list[dict[str, str]]:
    """基于想法生成 3 个"必须问"关键决策卡 + 1 个非关键决策卡（演示 A+B）。"""
    return [
        {
            "code": "Q1",
            "question": f"「{idea}」的目标用户是谁？",
            "options": "A 个人用户 / B 企业内部 / C 对外公开",
            "recommendation": "先内部/个人验证，再考虑对外",
            "consequence": "选错用户群会影响核心任务和上线范围",
            "critical": True,
        },
        {
            "code": "Q2",
            "question": "一次完整使用要拿到什么结果？",
            "options": "A 文档 / B 代码 / C 可上线产品",
            "recommendation": "先定最小可用结果",
            "consequence": "结果边界不清会无限扩大范围",
            "critical": True,
        },
        {
            "code": "Q3",
            "question": "什么算「生成得好」？",
            "options": "A 已有数字标准 / B 待样例打分 / C 不确定",
            "recommendation": "写不出数字就先「待样例打分」",
            "consequence": "无标准就无法验收",
            "critical": True,
        },
        {
            "code": "Q4",
            "question": "界面文案风格？",
            "options": "A 简洁直白 / B 活泼俏皮 / C 正式商务",
            "recommendation": "简洁直白",
            "consequence": "仅影响观感，不影响功能范围",
            "critical": False,
        },
    ]


def generate_clarify(idea: str) -> list[dict[str, str]]:
    """生成需求澄清决策卡（≤5 个）。"""
    return _clarify_cards(idea)


def generate_prd(idea: str, decisions: list[dict[str, Any]]) -> dict[str, str]:
    """基于想法 + 决策卡结论，生成 8 字段 PRD 草稿（占位）；出口做规范化。"""
    answers = {d["code"]: (d.get("answer") or "未答") for d in decisions}
    raw = {
        "goal_users": f"围绕「{idea}」的目标用户（决策 Q1：{answers.get('Q1', '')}）",
        "input_process_output": "输入想法 → 分阶段确认 → 拿到最小可用产物",
        "main_loop": "分阶段确认：先生成草稿，用户确认后再推进下一步",
        "quality": "待样例打分：跑通后用真实样例让产品经理打分定标准",
        "delivery": "第一版只做最小可用版本，其余后置",
        "model_cost": "产品经理自带 API Key；MVP 用 mock 不花真钱",
        "data_nonfunc": "国内部署、数据不出境；密钥不进仓库/前端/日志",
        "launch": "MVP 先内部验证，再开放对外",
    }
    return normalize_prd_fields(raw)


def _safe_comment(idea: str) -> str:
    return idea.replace("\r", " ").replace("\n", " ").strip() or "未命名想法"


def _is_video_idea(idea: str, prd: dict[str, str] | None = None) -> bool:
    """想法或 PRD 含视频类关键词，且目标是生成影像（非纯脚本写作工具）。"""
    blob = (idea or "").lower()
    if prd:
        blob += " " + " ".join(str(v) for v in prd.values()).lower()
    keys = ("视频", "短视频", "video", "成片", "mp4", "影像")
    if not any(k.lower() in blob if k.isascii() else k in blob for k in keys):
        return False
    # 排除「只写脚本/提示词」专用表述占主导且无生成影像意图时仍偏保守：有「视频」即视为视频类
    script_only = ("脚本写作", "分镜文案工具", "提示词生成器")
    if any(s in (idea or "") for s in script_only) and "生成视频" not in (idea or "") and "短视频" not in (idea or ""):
        return False
    return True



def _is_tryon_idea(idea: str, prd: dict[str, str] | None = None) -> bool:
    """想法或 PRD 含试衣/试穿/换装等，目标是出上身预览图。"""
    blob = (idea or "").lower()
    if prd:
        blob += " " + " ".join(str(v) for v in prd.values()).lower()
    keys = (
        "试衣", "试穿", "换装", "虚拟试穿", "try-on", "tryon", "virtual try-on",
        "上身效果", "看上身",
    )
    return any(k.lower() in blob if k.isascii() else k in blob for k in keys)


def _demo_app_source(title: str) -> str:
    """拼出可演示的 app.py 源码；HTML 用 r\"\"\"，避免护栏误杀。"""
    parts = [
        "# 本文件由 Agent造物坊 mock 生成（最小可演示 AI 应用）。",
        f"# 想法：{title}",
        "import os",
        "from fastapi import FastAPI",
        "from fastapi.responses import HTMLResponse",
        "from pydantic import BaseModel",
        "",
        "app = FastAPI()",
        "",
        "HOME_HTML = r\"\"\"<!DOCTYPE html>",
        "<html lang=\"zh-CN\">",
        "<head>",
        "<meta charset=\"utf-8\"/>",
        f"<title>{title}</title>",
        "<style>",
        "body { font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; }",
        "input { width: 70%; padding: 0.4rem; }",
        "button { padding: 0.4rem 0.8rem; margin-left: 0.4rem; }",
        "pre { background: #f4f4f5; padding: 0.8rem; border-radius: 6px; white-space: pre-wrap; }",
        ".hint { color: #666; font-size: 0.9rem; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{title}</h1>",
        "<p class=\"hint\">本地演示页（mock）。无 DEEPSEEK_API_KEY 时 /generate 仍返回 HTTP 200 本地结果。</p>",
        "<input id=\"inp\" placeholder=\"输入一句话，例如：你好\"/>",
        "<button id=\"btn\" type=\"button\">发送</button>",
        "<pre id=\"out\">等待发送…</pre>",
        "<script>",
        "(function () {",
        "  var inp = document.getElementById(\"inp\");",
        "  var btn = document.getElementById(\"btn\");",
        "  var out = document.getElementById(\"out\");",
        "  btn.addEventListener(\"click\", function () {",
        "    var text = (inp.value || \"\").trim() || \"你好\";",
        "    out.textContent = \"请求中…\";",
        "    fetch(\"/generate\", {",
        "      method: \"POST\",",
        "      headers: {\"Content-Type\": \"application/json\"},",
        "      body: JSON.stringify({input: text})",
        "    }).then(function (r) { return r.json().then(function (data) {",
        "      return { ok: r.ok, status: r.status, data: data };",
        "    }); }).then(function (res) {",
        "      var data = res.data || {};",
        "      out.textContent = (data.result != null ? data.result : JSON.stringify(data))",
        "        + \"\\n(HTTP \" + res.status + \")\";",
        "    }).catch(function (err) {",
        "      out.textContent = \"失败: \" + err;",
        "    });",
        "  });",
        "})();",
        "</script>",
        "</body>",
        "</html>",
        '"""',
        "",
        "",
        "class Req(BaseModel):",
        "    input: str",
        "",
        "",
        "@app.get(\"/\", response_class=HTMLResponse)",
        "def home():",
        "    return HOME_HTML",
        "",
        "",
        '@app.post("/generate")',
        "def generate(req: Req):",
        '    """无 Key → HTTP 200 本地回落；有 Key 可走 OpenAI 兼容，失败仍本地回落（禁止故意 5xx）。"""',
        '    text = (req.input or "").strip() or "（空输入）"',
        '    local = {"result": f"（本地回落）已收到：{text}"}',
        '    key = os.getenv("DEEPSEEK_API_KEY")',
        "    if not key:",
        "        return local",
        "    try:",
        "        from openai import OpenAI",
        "",
        "        client = OpenAI(",
        "            api_key=key,",
        '            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),',
        "        )",
        "        resp = client.chat.completions.create(",
        '            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),',
        '            messages=[{"role": "user", "content": text}],',
        "        )",
        '        content = (resp.choices[0].message.content or "").strip()',
        '        return {"result": content or local["result"]}',
        "    except Exception:",
        "        return local",
        "",
    ]
    return "\n".join(parts)


def _video_app_source(title: str) -> str:
    """视频类 idea：表单 → 本地合成演示片 → HTML5 <video> 可播。"""
    b64_chunks = [
        "AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAAIZnJlZQAABjBtZGF0AAACrgYF",
        "//+q3EXpvebZSLeWLNgg2SPu73gyNjQgLSBjb3JlIDE2NSByMzIyMiBiMzU2MDVhIC0gSC4y",
        "NjQvTVBFRy00IEFWQyBjb2RlYyAtIENvcHlsZWZ0IDIwMDMtMjAyNSAtIGh0dHA6Ly93d3cu",
        "dmlkZW9sYW4ub3JnL3gyNjQuaHRtbCAtIG9wdGlvbnM6IGNhYmFjPTEgcmVmPTMgZGVibG9j",
        "az0xOjA6MCBhbmFseXNlPTB4MzoweDExMyBtZT1oZXggc3VibWU9NyBwc3k9MSBwc3lfcmQ9",
        "MS4wMDowLjAwIG1peGVkX3JlZj0xIG1lX3JhbmdlPTE2IGNocm9tYV9tZT0xIHRyZWxsaXM9",
        "MSA4eDhkY3Q9MSBjcW09MCBkZWFkem9uZT0yMSwxMSBmYXN0X3Bza2lwPTEgY2hyb21hX3Fw",
        "X29mZnNldD0tMiB0aHJlYWRzPTcgbG9va2FoZWFkX3RocmVhZHM9MSBzbGljZWRfdGhyZWFk",
        "cz0wIG5yPTAgZGVjaW1hdGU9MSBpbnRlcmxhY2VkPTAgYmx1cmF5X2NvbXBhdD0wIGNvbnN0",
        "cmFpbmVkX2ludHJhPTAgYmZyYW1lcz0zIGJfcHlyYW1pZD0yIGJfYWRhcHQ9MSBiX2JpYXM9",
        "MCBkaXJlY3Q9MSB3ZWlnaHRiPTEgb3Blbl9nb3A9MCB3ZWlnaHRwPTIga2V5aW50PTI1MCBr",
        "ZXlpbnRfbWluPTI1IHNjZW5lY3V0PTQwIGludHJhX3JlZnJlc2g9MCByY19sb29rYWhlYWQ9",
        "NDAgcmM9Y3JmIG1idHJlZT0xIGNyZj0yMy4wIHFjb21wPTAuNjAgcXBtaW49MCBxcG1heD02",
        "OSBxcHN0ZXA9NCBpcF9yYXRpbz0xLjQwIGFxPTE6MS4wMACAAAAAQWWIhAA7//7jq/gU2FBU",
        "dEzFKP6FtGNPzxSXbPITNxyv/gd9NWAALGGW9CnGTJVG0AEsAAASwM2GMJqpyTz6+ldRAAAA",
        "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",
        "ABxkYXRhAAAAAQAAAABMYXZmNjMuMS4xMDI=",
    ]
    b64_joined = "\n".join(f'    "{c}"' for c in b64_chunks)
    parts = [
        "# 本文件由 Agent造物坊 mock 生成（视频类：本地合成可播短片）。",
        f"# 想法：{title}",
        "import base64",
        "import os",
        "import shutil",
        "import subprocess",
        "from pathlib import Path",
        "",
        "from fastapi import FastAPI",
        "from fastapi.responses import FileResponse, HTMLResponse",
        "from pydantic import BaseModel",
        "",
        "app = FastAPI()",
        "OUT_DIR = Path(__file__).resolve().parent / \"_demo_clips\"",
        "OUT_DIR.mkdir(exist_ok=True)",
        "CLIP_PATH = OUT_DIR / \"demo.mp4\"",
        "",
        "# 内置可播短片（约 2s）；无 ffmpeg 时回落此字节",
        "MINI_MP4_B64 = (",
    ]
    parts.extend(f'        "{c}"' for c in b64_chunks)
    parts.append(")")
    parts.extend([
        "",
        "HOME_HTML = r\"\"\"<!DOCTYPE html>",
        "<html lang=\"zh-CN\">",
        "<head>",
        "<meta charset=\"utf-8\"/>",
        f"<title>{title} · 生成视频</title>",
        "<style>",
        "body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }",
        "input { width: 70%; padding: 0.4rem; }",
        "button { padding: 0.4rem 0.8rem; margin-left: 0.4rem; }",
        "video { width: 100%; max-height: 360px; background: #111; border-radius: 8px; margin-top: 1rem; }",
        ".hint { color: #666; font-size: 0.9rem; }",
        "pre { background: #f4f4f5; padding: 0.8rem; border-radius: 6px; white-space: pre-wrap; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{title}</h1>",
        "<p class=\"hint\">这是「生成视频」本地演示：无云端视频 API Key 时合成<strong>本地演示片</strong>（可播放短视频，不是提示词）。</p>",
        "<input id=\"inp\" placeholder=\"片头标题，例如：我的短片\"/>",
        "<button id=\"btn\" type=\"button\">生成视频</button>",
        "<pre id=\"out\">等待生成…</pre>",
        "<video id=\"player\" controls playsinline></video>",
        "<p><a id=\"dl\" href=\"/download.mp4\" download=\"demo.mp4\">下载 mp4</a></p>",
        "<script>",
        "(function () {",
        "  var inp = document.getElementById(\"inp\");",
        "  var btn = document.getElementById(\"btn\");",
        "  var out = document.getElementById(\"out\");",
        "  var player = document.getElementById(\"player\");",
        "  btn.addEventListener(\"click\", function () {",
        "    var text = (inp.value || \"\").trim() || \"本地演示片\";",
        "    out.textContent = \"合成中…\";",
        "    fetch(\"/generate\", {",
        "      method: \"POST\",",
        "      headers: {\"Content-Type\": \"application/json\"},",
        "      body: JSON.stringify({input: text})",
        "    }).then(function (r) { return r.json().then(function (data) {",
        "      return { ok: r.ok, status: r.status, data: data };",
        "    }); }).then(function (res) {",
        "      var data = res.data || {};",
        "      out.textContent = (data.result != null ? data.result : JSON.stringify(data))",
        "        + \"\\n(HTTP \" + res.status + \")\";",
        "      var url = data.video_url || \"/download.mp4\";",
        "      player.src = url + (url.indexOf(\"?\") >= 0 ? \"&\" : \"?\") + \"t=\" + Date.now();",
        "      player.load();",
        "    }).catch(function (err) {",
        "      out.textContent = \"失败: \" + err;",
        "    });",
        "  });",
        "})();",
        "</script>",
        "</body>",
        "</html>",
        '"""',
        "",
        "",
        "def _write_demo_clip(title_text: str) -> Path:",
        '    """优先 ffmpeg；否则回落内置可播 mp4；可选 Pillow 标题帧。"""',
        "    (OUT_DIR / \"title.txt\").write_text(title_text, encoding=\"utf-8\")",
        "    label = \"\".join(c if (c.isalnum() or c in \" _-\") else \" \" for c in (title_text or \"本地演示片\"))[:40]",
        "    ffmpeg = shutil.which(\"ffmpeg\")",
        "    if ffmpeg:",
        "        try:",
        "            subprocess.run(",
        "                [",
        "                    ffmpeg, \"-y\",",
        "                    \"-f\", \"lavfi\", \"-i\", \"color=c=0x1e40af:s=640x360:d=3\",",
        "                    \"-vf\", f\"drawtext=text={label}:fontsize=36:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2\",",
        "                    \"-c:v\", \"libx264\", \"-pix_fmt\", \"yuv420p\", \"-t\", \"3\", \"-an\",",
        "                    str(CLIP_PATH),",
        "                ],",
        "                check=True,",
        "                capture_output=True,",
        "                timeout=30,",
        "            )",
        "            if CLIP_PATH.exists() and CLIP_PATH.stat().st_size > 100:",
        "                return CLIP_PATH",
        "        except Exception:",
        "            pass",
        "    try:",
        "        from PIL import Image, ImageDraw",
        "",
        "        img = Image.new(\"RGB\", (640, 360), color=(30, 64, 175))",
        "        draw = ImageDraw.Draw(img)",
        "        draw.text((40, 160), (title_text or \"本地演示片\")[:40], fill=(255, 255, 255))",
        "        img.save(OUT_DIR / \"frame.png\")",
        "    except Exception:",
        "        pass",
        "    CLIP_PATH.write_bytes(base64.b64decode(MINI_MP4_B64))",
        "    return CLIP_PATH",
        "",
        "",
        "class Req(BaseModel):",
        "    input: str",
        "",
        "",
        "@app.get(\"/\", response_class=HTMLResponse)",
        "def home():",
        "    return HOME_HTML",
        "",
        "",
        '@app.get("/download.mp4")',
        "def download_mp4():",
        "    if not CLIP_PATH.exists():",
        '        _write_demo_clip("本地演示片")',
        '    return FileResponse(str(CLIP_PATH), media_type="video/mp4", filename="demo.mp4")',
        "",
        "",
        '@app.post("/generate")',
        "def generate(req: Req):",
        '    """无云端视频 Key：本地合成演示片，HTTP 200；禁止只返回提示词。"""',
        '    text = (req.input or "").strip() or "本地演示片"',
        "    path = _write_demo_clip(text)",
        "    return {",
        '        "result": f"已生成本地演示片（标题：{text}），可在页面播放或下载。",',
        '        "video_url": "/download.mp4",',
        '        "path": str(path),',
        "    }",
        "",
    ])
    return "\n".join(parts)



def _tryon_app_source(title: str) -> str:
    """试衣类 idea：可选上传 + 衣服描述 → Pillow 本地演示图 → <img> 展示。"""
    parts = [
        "# 本文件由 Agent造物坊 mock 生成（试衣类：本地合成可查看预览图）。",
        f"# 想法：{title}",
        "import base64",
        "import io",
        "import os",
        "from pathlib import Path",
        "",
        "from fastapi import FastAPI, File, Form, UploadFile",
        "from fastapi.responses import FileResponse, HTMLResponse",
        "from pydantic import BaseModel",
        "",
        "app = FastAPI()",
        'OUT_DIR = Path(__file__).resolve().parent / "_demo_previews"',
        "OUT_DIR.mkdir(exist_ok=True)",
        'PREVIEW_PATH = OUT_DIR / "preview.png"',
        "",
        'HOME_HTML = r"""<!DOCTYPE html>',
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8"/>',
        f"<title>{title} · 试穿预览</title>",
        "<style>",
        "body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }",
        "input[type=text] { width: 70%; padding: 0.4rem; }",
        "button { padding: 0.4rem 0.8rem; margin-left: 0.4rem; }",
        "img.result { max-width: 100%; border-radius: 8px; margin-top: 1rem; background: #f4f4f5; }",
        ".hint { color: #666; font-size: 0.9rem; }",
        "pre { background: #f4f4f5; padding: 0.8rem; border-radius: 6px; white-space: pre-wrap; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{title}</h1>",
        '<p class="hint">这是「试穿预览」本地演示：无云端图像 API Key 时用 Pillow 合成<strong>本地演示图</strong>（可查看预览图，不是换装方案/提示词）。</p>',
        '<p><label>全身照（可选） <input id="photo" type="file" accept="image/*"/></label></p>',
        '<input id="inp" placeholder="想试穿的衣服，例如：白色衬衫 + 蓝色牛仔裤"/>',
        '<button id="btn" type="button">生成试穿预览</button>',
        '<pre id="out">等待生成…</pre>',
        '<img id="preview" class="result" alt="试穿预览"/>',
        '<p><a id="dl" href="/preview.png" download="preview.png">下载预览图</a></p>',
        "<script>",
        "(function () {",
        '  var inp = document.getElementById("inp");',
        '  var btn = document.getElementById("btn");',
        '  var out = document.getElementById("out");',
        '  var preview = document.getElementById("preview");',
        '  btn.addEventListener("click", function () {',
        '    var text = (inp.value || "").trim() || "白色衬衫";',
        '    out.textContent = "合成中…";',
        '    fetch("/generate", {',
        '      method: "POST",',
        '      headers: {"Content-Type": "application/json"},',
        "      body: JSON.stringify({input: text})",
        "    }).then(function (r) { return r.json().then(function (data) {",
        "      return { ok: r.ok, status: r.status, data: data };",
        "    }); }).then(function (res) {",
        "      var data = res.data || {};",
        '      out.textContent = (data.result != null ? data.result : JSON.stringify(data))',
        '        + "\\n(HTTP " + res.status + ")";',
        "      if (data.image_base64) {",
        '        preview.src = "data:image/png;base64," + data.image_base64;',
        "      } else {",
        '        var url = data.preview_url || "/preview.png";',
        '        preview.src = url + (url.indexOf("?") >= 0 ? "&" : "?") + "t=" + Date.now();',
        "      }",
        "    }).catch(function (err) {",
        '      out.textContent = "失败: " + err;',
        "    });",
        "  });",
        "})();",
        "</script>",
        "</body>",
        "</html>",
        '"""',
        "",
        "",
        "def _compose_demo_preview(outfit: str) -> tuple[Path, str]:",
        '    """Pillow 本地演示图；返回路径与 base64。"""',
        "    from PIL import Image, ImageDraw",
        "",
        '    img = Image.new("RGB", (640, 800), color=(245, 245, 247))',
        "    draw = ImageDraw.Draw(img)",
        "    # 简易人物剪影",
        "    draw.ellipse((270, 40, 370, 140), fill=(220, 190, 170))",
        "    draw.rectangle((250, 150, 390, 420), fill=(60, 90, 160))  # 上衣色块",
        "    draw.rectangle((260, 420, 380, 700), fill=(40, 40, 50))  # 下装色块",
        '    label = (outfit or "本地演示图")[:36]',
        '    draw.text((40, 720), f"本地演示图 · {label}", fill=(30, 30, 30))',
        "    buf = io.BytesIO()",
        '    img.save(buf, format="PNG")',
        "    raw = buf.getvalue()",
        "    PREVIEW_PATH.write_bytes(raw)",
        '    return PREVIEW_PATH, base64.b64encode(raw).decode("ascii")',
        "",
        "",
        "class Req(BaseModel):",
        '    input: str = ""',
        "",
        "",
        '@app.get("/", response_class=HTMLResponse)',
        "def home():",
        "    return HOME_HTML",
        "",
        "",
        '@app.get("/preview.png")',
        "def preview_png():",
        "    if not PREVIEW_PATH.exists():",
        '        _compose_demo_preview("本地演示图")',
        '    return FileResponse(str(PREVIEW_PATH), media_type="image/png", filename="preview.png")',
        "",
        "",
        '@app.post("/generate")',
        "def generate(req: Req):",
        '    """无云端图像 Key：Pillow 本地演示图，HTTP 200；禁止只返回换装文案。"""',
        '    text = (req.input or "").strip() or "白色衬衫"',
        "    path, b64 = _compose_demo_preview(text)",
        "    return {",
        '        "result": f"已生成本地演示图（试穿：{text}），可在页面查看。",',
        '        "image_base64": b64,',
        '        "preview_url": "/preview.png",',
        '        "path": str(path),',
        "    }",
        "",
    ]
    return "\n".join(parts)


def generate_code(idea: str, prd: dict[str, str]) -> dict[str, str]:
    """生成最小可演示 FastAPI 应用；试衣/视频类分别返回本地出图/出片模板。"""
    title = _safe_comment(idea)
    if _is_tryon_idea(idea, prd):
        app = _tryon_app_source(title)
        readme = (
            f"# {title}\n\n"
            "这是「试穿预览」本地演示成品：主路径产出**可查看预览图**（`<img>` + `image_base64` / `/preview.png`），"
            "不是换装方案/提示词。无云端图像 API Key 时用 Pillow 合成本地演示图。\n\n"
            "## 启动\n\n"
            "```sh\n"
            "pip install -r requirements.txt\n"
            "uvicorn app:app --port 8000\n"
            "```\n\n"
            "浏览器打开 http://127.0.0.1:8000/ ，输入衣服描述后点「生成试穿预览」即可查看图片。\n\n"
            "## 调用\n\n"
            "```sh\n"
            "curl -X POST http://127.0.0.1:8000/generate -H 'Content-Type: application/json' -d '{\"input\":\"白色衬衫\"}'\n"
            "curl -OJ http://127.0.0.1:8000/preview.png\n"
            "```\n"
        )
        return {
            "app": app,
            "requirements": "fastapi\nuvicorn\npillow\npython-multipart\n",
            "readme": readme,
        }
    if _is_video_idea(idea, prd):
        app = _video_app_source(title)
        readme = (
            f"# {title}\n\n"
            "这是「生成视频」本地演示成品：主路径产出**可播放短视频**（HTML5 `<video>` + `/download.mp4`），"
            "不是提示词/分镜文案。无云端视频 API Key 时写入内置最小 mp4（本地演示片）；"
            "可选安装 `pillow` 生成标题静帧预览图。系统若有 ffmpeg 可自行替换成更长成片。\n\n"
            "## 启动\n\n"
            "```sh\n"
            "pip install -r requirements.txt\n"
            "uvicorn app:app --port 8000\n"
            "```\n\n"
            "浏览器打开 http://127.0.0.1:8000/ ，输入片头标题后点「生成视频」即可播放。\n\n"
            "## 调用\n\n"
            "```sh\n"
            "curl -X POST http://127.0.0.1:8000/generate -H 'Content-Type: application/json' -d '{\"input\":\"片头\"}'\n"
            "curl -OJ http://127.0.0.1:8000/download.mp4\n"
            "```\n"
        )
        return {
            "app": app,
            "requirements": "fastapi\nuvicorn\npillow\n",
            "readme": readme,
        }
    app = _demo_app_source(title)
    readme = (
        f"# {title}\n\n"
        "本地 mock / 演示成品。无 `DEEPSEEK_API_KEY` 时 `POST /generate` 仍返回 **HTTP 200** 与本地回落结果（非 5xx）。\n\n"
        "## 启动\n\n"
        "```sh\n"
        "pip install -r requirements.txt\n"
        "# 可选：export DEEPSEEK_API_KEY=...\n"
        "uvicorn app:app --port 8000\n"
        "```\n\n"
        "浏览器打开 http://127.0.0.1:8000/ 即可点「发送」演示。\n\n"
        "## 调用\n\n"
        "```sh\n"
        "curl -X POST http://127.0.0.1:8000/generate -H 'Content-Type: application/json' -d '{\"input\":\"你好\"}'\n"
        "```\n"
    )
    return {
        "app": app,
        "requirements": "fastapi\nuvicorn\nopenai\n",
        "readme": readme,
    }
