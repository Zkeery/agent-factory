"""配置读取：只读取不含秘密的配置项，密钥由 .env 提供且不回显。"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./data/factory.db"
    port: int = 8010
    # 可选 API Key：非空时要求 X-API-Key（SSE 可用查询参数 api_key）
    api_key: str = ""
    # LLM：mock=离线占位；deepseek=真实模型（OpenAI 兼容）
    llm_provider: str = "mock"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_timeout: float = 120.0  # 单次模型调用超时秒数（走代理/生成慢时可调大）
    cost_per_1m_input: float = 1.0  # 成本估算：每百万输入 token 元（DeepSeek 约价，非账单）
    cost_per_1m_output: float = 2.0  # 成本估算：每百万输出 token 元
    run_stuck_timeout: int = 300  # run 卡死阈值（秒）：超时无进度判定卡死
    watchdog_interval: int = 30  # 看门狗扫描间隔（秒）
    # 生成代码沙箱：import smoke 超时与内存软限制（0=不限制内存）
    sandbox_timeout_seconds: int = 10
    sandbox_memory_mb: int = 256
    # process=本机子进程；docker=强制容器；auto=有 Docker 用容器否则回退 process
    sandbox_mode: str = "auto"
    sandbox_docker_image: str = "agent-factory-sandbox:local"
    sandbox_docker_network: str = "none"
    # 短信验证码：mock=True 时验证码直接随接口返回（本地不花真钱）；真实短信服务接入后再关
    sms_mock: bool = True


settings = Settings()
