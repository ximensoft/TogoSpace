# TogoSpace Dockerfile
# 基于 Ubuntu 24.04 LTS 构建
#
# 构建方式：
#   1. 确保 frontend 子模块已初始化：git submodule update --init --recursive
#   2. docker build -t togospace:0.1.20 .
#   3. docker run -d -p 8080:8080 -v togospace-storage:/storage togospace:0.1.20

# ============================================
# Stage 1: 构建前端
# ============================================
FROM ubuntu:24.04 AS frontend-builder

# 安装 Node.js
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build/frontend

# 复制前端代码（需要在构建前执行 git submodule update --init --recursive）
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

COPY frontend/ ./
RUN npm run build

# ============================================
# Stage 2: 最终镜像
# ============================================
FROM ubuntu:24.04

LABEL maintainer="TogoSpace Team"
LABEL description="TogoSpace - Multi-Agent Chat Room Framework"
LABEL version="0.1.20"

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TOGOSPACE_HOME=/opt/togospace \
    STORAGE_ROOT=/storage \
    TOGOSPACE_RUN_ENV=docker

# 安装 Python 和运行依赖
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*


# ====================== 安装 Swift ======================
# 先复制已下载的 https://download.swift.org/swift-6.1-release/ubuntu2404/swift-6.1-RELEASE/swift-6.1-RELEASE-ubuntu24.04.tar.gz （放在 Dockerfile 同目录）
COPY swift-6.1-RELEASE-ubuntu24.04.tar.gz /tmp/swift.tar.gz

# 创建安装目录并解压 Swift
RUN apt-get update && apt-get install -y \
    clang \
    libicu-dev \
    libcurl4-openssl-dev \
    libxml2-dev \
    && rm -rf /var/lib/apt/lists/* \
    \
    && mkdir -p /usr/share/swift \
    && tar -xzf /tmp/swift.tar.gz -C /usr/share/swift --strip-components=1 \
    && rm /tmp/swift.tar.gz \
    \
    # 配置环境变量
    && echo 'export PATH=/usr/share/swift/usr/bin:$PATH' >> /etc/profile \
    && echo 'export PATH=/usr/share/swift/usr/bin:$PATH' >> /root/.bashrc \
    \
    # 验证安装
    && ls -la /usr/share/swift/usr/bin/swift* \
    && /usr/share/swift/usr/bin/swift --version

# 创建应用目录和数据目录
RUN mkdir -p ${TOGOSPACE_HOME} ${STORAGE_ROOT}

WORKDIR ${TOGOSPACE_HOME}

# 复制后端源代码
COPY src/ ${TOGOSPACE_HOME}/src/

# 复制资源文件
COPY assets/ ${TOGOSPACE_HOME}/assets/
COPY requirements.txt ${TOGOSPACE_HOME}/requirements.txt

# 复制前端构建产物
COPY --from=frontend-builder /build/frontend/dist ${TOGOSPACE_HOME}/assets/frontend

# 创建 Python 虚拟环境并安装依赖
RUN python3 -m venv .venv \
    && .venv/bin/pip install --upgrade pip \
    && .venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# 创建默认配置文件
RUN mkdir -p ${STORAGE_ROOT} \
    && if [ ! -f ${STORAGE_ROOT}/setting.json ]; then \
        cp ${TOGOSPACE_HOME}/assets/config_template.json ${STORAGE_ROOT}/setting.json; \
    fi

# 暴露端口
EXPOSE 8080

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/system/status.json || exit 1

# 启动命令
WORKDIR ${TOGOSPACE_HOME}/src
CMD ["../.venv/bin/python3", "backend_main.py", "--config-dir", "/storage"]