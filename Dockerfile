FROM python:3.12-slim

ENV PYTHONIOENCODING=utf-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /worker

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# 复制代码
COPY src/ ./src/
COPY scripts/ ./scripts/

# 数据/录像卷挂载点
VOLUME ["/worker/output", "/data"]

# 非root
RUN useradd -m -u 1000 worker && chown -R worker:worker /worker
USER worker

# AI worker 是后台进程——被主后端 supervisor 拉起或独立运行
# 环境变量：AI_INVEST_DB（库路径）/ AI_REPO_ROOT（本仓根）/ W2_REAL_LLM
CMD ["python", "-X", "utf8", "-u", "scripts/queue_worker.py"]
