# 第十四刀验收证据｜试衣/图像预览必须出图

## 自测命令

```bash
cd backend
.venv/bin/pytest tests/test_tryon_mock.py tests/test_video_mock.py tests/test_codegen_guard.py -q
```

热修试衣成品（若 8007 目录仍在）：

```bash
curl -s -X POST http://127.0.0.1:8007/generate \
  -H 'Content-Type: application/json' \
  -d '{"input":"白色衬衫"}' | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('image_base64') or d.get('preview_url') or 'image' in str(d).lower(); print('ok', list(d.keys()))"
```

## 预期

- mock「试衣/试穿」源码含 Pillow/`image_base64` 或 `/preview.png` 与结果 `<img`
- 纯长文换装方案源码 → `成品护栏` 失败
- video mock 回归仍含 `<video` / `video/mp4`
- 8007 热修后 `/generate` 返回含图片字段；页面可看到「本地演示图」

## 自测（开发）

- 日期：2026-09-24
- 命令：见上
- 结果：见执行报告；人工复验仍待

## 人工复验记录

- 日期：
- 结果：待复验
