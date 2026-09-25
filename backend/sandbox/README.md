# 生成代码容器沙箱

本机未装 Docker 时，后端会自动回退到进程沙箱。

## 构建镜像

```bash
cd backend
docker build -t agent-factory-sandbox:local -f sandbox/Dockerfile sandbox
```

## 启用

在 `backend/.env`：

```
SANDBOX_MODE=docker   # 或 auto
SANDBOX_DOCKER_IMAGE=agent-factory-sandbox:local
```

`auto`：检测到 `docker` 可用且镜像存在时走容器，否则进程沙箱。
