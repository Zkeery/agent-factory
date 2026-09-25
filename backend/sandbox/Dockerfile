# Agent造物坊 · 生成代码冒烟测试镜像（无网络、只读挂载代码）
FROM python:3.12-slim

WORKDIR /work

# 预装常见骨架依赖，容器内 --network none 时无需再 pip
COPY requirements-smoke.txt /tmp/requirements-smoke.txt
RUN pip install --no-cache-dir -r /tmp/requirements-smoke.txt

# 默认只做 import smoke；代码目录挂载到 /work/code
CMD ["python", "-I", "-c", "import sys; sys.path.insert(0, '/work/code'); import app; print('sandbox_ok')"]
