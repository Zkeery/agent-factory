# AI 记账小工具

一个基于自然语言的智能记账助手，把一句话变成结构化的账目记录，并给出分类与理财建议。

## 功能
- 输入自然语言描述（如"今天午饭花了 25 块"），自动提取金额、类别、收支方向
- 缺失信息时自动推断或提示待确认
- 支持统计、预算、理财相关的问答

## 安装依赖
```bash
pip install -r requirements.txt
```

## 配置 API Key
```bash
export DEEPSEEK_API_KEY=你的key
# 可选：自定义 base_url 与 model
export DEEPSEEK_BASE_URL=https://api.deepseek.com
export DEEPSEEK_MODEL=deepseek-chat
```

## 启动服务
```bash
uvicorn app:app --port 8000
```

## 调用接口
```bash
curl -X POST http://127.0.0.1:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"input": "今天打车花了38元，晚上买菜花了52块"}'
```

返回示例：
```json
{"result": "记录如下：\n1. 交通 - 打车 - 支出 38 元\n2. 餐饮 - 买菜 - 支出 52 元\n..."}
```

## 错误说明
- 未设置 `DEEPSEEK_API_KEY` 时，接口返回 HTTP 500，内容为 `{"detail": "缺少 DEEPSEEK_API_KEY"}`
- 调用模型出错时，返回 HTTP 500 及错误详情