# Docker 基础与应用镜像

> **学习时间：** 工作日 1  
> **主题：** Docker 核心概念、Dockerfile 指令、构建上下文与端口映射

---

## 1. 镜像 vs 容器 vs 仓库

### 核心概念对比

| 概念 | 类比 | 说明 |
| --- | --- | --- |
| **镜像 (Image)** | 类 / 模板 / 安装光盘 | 只读的模板，包含运行应用所需的文件系统、依赖和配置 |
| **容器 (Container)** | 对象 / 实例 / 运行的程序 | 镜像的运行实例，有独立的进程空间、网络和文件系统 |
| **仓库 (Registry)** | 代码托管平台（如 GitHub） | 存储和分发镜像的地方，如 Docker Hub、私有 Registry |

### 关系图

```text
Dockerfile (源代码)
    ↓ build
Image (只读模板)
    ↓ run
Container (运行实例)
    ↑ push/pull
Registry (镜像仓库)
```

**关键理解：**
- 一个镜像可以启动多个容器（就像用一个类创建多个对象）
- 容器是临时的，删除后数据会丢失（除非使用卷）
- 镜像是分层的，每一层都是只读的，容器层是可写的

---

## 2. Dockerfile 指令详解

### 本项目 Dockerfile 分析

```dockerfile
FROM python:3.11-slim                    # 1. 基础镜像
ENV PYTHONDONTWRITEBYTECODE=1 \          # 2. 环境变量
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app                             # 3. 工作目录
COPY pyproject.toml README.md ./         # 4. 复制依赖声明
COPY src ./src                           # 5. 复制源码
RUN python -m pip install --upgrade pip && \
    python -m pip install .              # 6. 安装依赖
COPY alembic.ini ./                      # 7. 复制迁移配置
COPY migrations ./migrations             # 8. 复制迁移脚本
RUN mkdir -p /app/data/uploads /app/logs # 9. 创建目录
EXPOSE 8000                              # 10. 声明端口
CMD ["uvicorn", "knowledge_assistant.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
                                         # 11. 启动命令
```

### 指令详细说明

#### `FROM` — 指定基础镜像

```dockerfile
FROM python:3.11-slim
```

- **作用：** 所有 Dockerfile 的第一条指令，指定基础镜像
- **为什么用 `slim`：** 精简版镜像体积小（约 150MB vs 完整版 900MB+），减少攻击面
- **常见基础镜像：** `alpine`（最小）、`slim`（精简）、`bullseye/bookworm`（完整 Debian）

#### `ENV` — 设置环境变量

```dockerfile
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
```

- **`PYTHONDONTWRITEBYTECODE=1`：** 不生成 `.pyc` 字节码文件，减少镜像层
- **`PYTHONUNBUFFERED=1`：** Python 输出不缓冲，日志实时可见
- **`PIP_NO_CACHE_DIR=1`：** pip 不缓存下载的包，减小镜像体积

#### `WORKDIR` — 设置工作目录

```dockerfile
WORKDIR /app
```

- **作用：** 后续 `RUN`、`CMD`、`COPY` 等指令的默认路径
- **如果目录不存在会自动创建**
- **不要用 `RUN cd /app`**，因为每条 `RUN` 是独立的 shell

#### `COPY` — 复制文件到镜像

```dockerfile
COPY pyproject.toml README.md ./
COPY src ./src
```

- **语法：** `COPY <源路径> <目标路径>`
- **源路径相对于构建上下文（build context）**
- **目标路径相对于 `WORKDIR`**
- **为什么先复制 `pyproject.toml` 再复制 `src`？** → 见下文"镜像层缓存"

#### `RUN` — 在构建时执行命令

```dockerfile
RUN python -m pip install --upgrade pip && python -m pip install .
RUN mkdir -p /app/data/uploads /app/logs
```

- **在镜像构建阶段执行**，结果保存到镜像层
- **每个 `RUN` 产生一个新层**，可以用 `&&` 合并相关命令
- **不要用 `RUN` 启动服务**，应该用 `CMD` 或 `ENTRYPOINT`

#### `EXPOSE` — 声明端口

```dockerfile
EXPOSE 8000
```

- **只是文档说明**，告诉用户这个容器监听哪个端口
- **不会自动映射到宿主机**，需要用 `-p` 参数
- **不影响容器间通信**，容器间通过服务名和网络直接访问

#### `CMD` — 容器启动命令

```dockerfile
CMD ["uvicorn", "knowledge_assistant.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- **容器启动时执行的命令**
- **JSON 数组格式（exec 形式）推荐**，避免 shell 解析问题
- **可以被 `docker run` 的参数覆盖**
- **只有一个 CMD 生效**，最后一个覆盖前面的

---

## 3. 构建上下文和 .dockerignore

### 构建上下文 (Build Context)

```bash
docker build -t knowledge-assistant-api:week03 .
```

- **`.` 表示当前目录作为构建上下文**
- **Docker 会把整个上下文目录发送给 Docker Daemon**
- **上下文越大，构建越慢**（需要传输更多文件）

### .dockerignore 的作用

类似 `.gitignore`，排除不需要复制到镜像的文件：

```text
.git              # Git 元数据（镜像中不需要版本控制历史）
.venv             # 本地虚拟环境（镜像中重新安装依赖）
__pycache__       # Python 字节码缓存
*.py[cod]         # 编译后的 Python 文件
.env              # 敏感配置文件（不应提交到镜像）
data              # 上传的文档数据（应由卷管理）
logs              # 运行时日志（应挂载宿主机目录）
tests             # 测试代码（生产镜像不需要）
docs              # 文档（生产镜像不需要）
```

### 为什么这些文件要排除？

| 排除项 | 原因 |
| --- | --- |
| `.git` | 镜像不需要版本历史，且可能很大 |
| `.venv` | 镜像中会从 `pyproject.toml` 重新安装依赖 |
| `.env` | 包含密码等敏感信息，不应打包进镜像 |
| `data/uploads` | 用户上传的文件应由卷持久化，不属于镜像 |
| `logs` | 日志应该在运行时产生，通过卷或日志驱动收集 |
| `tests` | 测试代码增加镜像体积，生产环境不需要 |

---

## 4. 端口映射原理

### 三种端口场景

#### 场景 1：宿主机访问容器

```bash
docker run -p 8000:8000 knowledge-assistant-api
```

- **`-p 宿主机端口:容器端口`**
- **访问 `http://localhost:8000` 会转发到容器的 8000 端口**
- **Compose 中的 `ports` 也是同样作用**

#### 场景 2：容器间通信

```yaml
# compose.yaml
services:
  api:
    environment:
      DATABASE_URL: postgresql://user:pass@postgres:5432/db
  postgres:
    # 不需要 ports 映射
```

- **容器通过服务名（`postgres`）和容器端口（`5432`）通信**
- **不需要 `-p` 映射**，Compose 自动创建网络
- **`EXPOSE` 只是文档，不影响实际通信**

#### 场景 3：仅内部访问

```yaml
services:
  redis:
    # 没有 ports 映射
    # 只有其他容器能访问，宿主机无法直接连接
```

- **适合缓存、消息队列等内部服务**
- **提高安全性，外部无法直接访问**

### 端口映射示意图

```text
浏览器/客户端
    │
    │ http://localhost:8000
    ▼
宿主机端口 8000
    │
    │ Docker 端口转发
    ▼
容器端口 8000 (API 服务)
    │
    │ 容器网络 DNS: postgres:5432
    ▼
PostgreSQL 容器端口 5432
```

**关键理解：**
- `-p` 映射只对宿主机访问有效
- 容器间通信直接用服务名 + 容器端口
- `EXPOSE` 不自动映射，只是文档说明

---

## 5. 镜像层缓存

### 为什么先复制 `pyproject.toml` 再复制 `src`？

```dockerfile
# 第一步：复制依赖声明
COPY pyproject.toml README.md ./
RUN python -m pip install .

# 第二步：复制业务代码
COPY src ./src
```

### 镜像层缓存机制

Docker 会为每条指令创建一个层，并缓存该层的结果：

```text
步骤 1: FROM python:3.11-slim        → 层 1（基础镜像，几乎不变）
步骤 2: ENV ...                       → 层 2（环境变量，很少变）
步骤 3: WORKDIR /app                  → 层 3（工作目录，不变）
步骤 4: COPY pyproject.toml ...       → 层 4（依赖声明，偶尔变）
步骤 5: RUN pip install ...           → 层 5（安装依赖，耗时最长）★
步骤 6: COPY src ./src                → 层 6（业务代码，经常变）
步骤 7: COPY alembic.ini ...          → 层 7（迁移配置，偶尔变）
步骤 8: RUN mkdir ...                 → 层 8（创建目录，不变）
步骤 9: EXPOSE 8000                   → 层 9（端口声明，不变）
步骤 10: CMD [...]                    → 层 10（启动命令，不变）
```

### 缓存复用规则

- **如果某一层的内容没变，Docker 会复用之前的缓存层**
- **一旦某一层变化，该层及之后的所有层都要重新构建**

### 示例对比

#### ❌ 不好的顺序（每次改代码都重新安装依赖）

```dockerfile
COPY src ./src                        # 经常变化
COPY pyproject.toml ./                # 偶尔变化
RUN pip install .                     # 每次都重新执行（因为 src 变了）
```

#### ✅ 好的顺序（只改代码时复用依赖安装缓存）

```dockerfile
COPY pyproject.toml ./                # 偶尔变化
RUN pip install .                     # 只在依赖变化时重新执行 ★
COPY src ./src                        # 经常变化（不影响上面的缓存）
```

### 实际效果

| 修改内容 | 不好的顺序 | 好的顺序 |
| --- | --- | --- |
| 修改业务代码 | 重新安装依赖（2-5分钟） | 复用缓存（几秒） |
| 修改依赖 | 重新安装依赖 | 重新安装依赖 |
| 修改基础镜像 | 全部重建 | 全部重建 |

**结论：** 把变化频率低的文件放在前面，变化频率高的放在后面，最大化缓存复用。

---

## 6. 容器日志和调试技巧

### 常用调试命令

#### 查看运行中的容器

```bash
docker ps                    # 列出运行中的容器
docker ps -a                 # 列出所有容器（包括已停止的）
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

#### 查看容器日志

```bash
docker logs <container-name>              # 查看所有日志
docker logs -f <container-name>           # 实时跟踪日志（类似 tail -f）
docker logs --tail=100 <container-name>   # 只看最后 100 行
docker logs --since=5m <container-name>   # 只看最近 5 分钟的日志
```

#### 进入容器内部

```bash
docker exec -it <container-name> sh       # 进入 shell（Alpine 用 sh）
docker exec -it <container-name> bash     # 进入 shell（Debian/Ubuntu 用 bash）
docker exec -it <container-name> python   # 直接进入 Python REPL
```

#### 检查容器详情

```bash
docker inspect <container-name>           # 查看完整配置（JSON 格式）
docker inspect --format='{{.NetworkSettings.IPAddress}}' <container-name>
docker top <container-name>               # 查看容器内进程
docker stats <container-name>             # 查看资源使用情况
```

#### 管理容器生命周期

```bash
docker stop <container-name>              # 优雅停止（发送 SIGTERM）
docker kill <container-name>              # 强制停止（发送 SIGKILL）
docker rm <container-name>                # 删除已停止的容器
docker rm -f <container-name>             # 强制删除运行中的容器
```

### 常见问题排查

#### 问题 1：容器启动后立即退出

```bash
# 查看退出码和日志
docker ps -a
docker logs <container-name>

# 常见原因：
# - CMD 命令执行完就退出了（应该是长期运行的服务）
# - 缺少必要的环境变量
# - 依赖的服务未启动
```

#### 问题 2：端口无法访问

```bash
# 检查端口映射
docker ps | grep <container-name>

# 检查容器内服务是否监听
docker exec <container-name> netstat -tlnp

# 检查防火墙规则
# Windows: 检查 Docker Desktop 设置
# Linux: sudo iptables -L
```

#### 问题 3：容器间无法通信

```bash
# 检查是否在同一个网络
docker network ls
docker network inspect <network-name>

# 测试 DNS 解析
docker exec <container-a> ping <container-b-name>

# 检查服务名是否正确（Compose 中是服务名，不是容器名）
```

#### 问题 4：磁盘空间不足

```bash
docker system df                # 查看 Docker 磁盘使用
docker system prune -a          # 清理未使用的镜像、容器、网络
docker volume prune             # 清理未使用的卷（谨慎使用！）
```

---

## 7. 常见错误排查

### 错误 1：`failed to solve: failed to compute cache key`

**原因：** 构建上下文中文件不存在或路径错误

**解决：**
```bash
# 检查文件是否存在
ls pyproject.toml

# 检查 .dockerignore 是否排除了必要文件
cat .dockerignore
```

### 错误 2：`Error response from daemon: conflict`

**原因：** 容器名称已存在

**解决：**
```bash
docker rm <container-name>
# 或者使用不同名称
docker run --name my-app-v2 ...
```

### 错误 3：`bind: address already in use`

**原因：** 宿主机端口已被占用

**解决：**
```bash
# Windows
netstat -ano | findstr :8000
taskkill /PID <pid>

# Linux
lsof -i :8000
sudo kill <pid>

# 或者使用不同端口
docker run -p 8001:8000 ...
```

### 错误 4：`permission denied` 访问卷

**原因：** 容器内用户权限与宿主机文件权限不匹配

**解决：**
```bash
# 在 Dockerfile 中设置正确的用户
RUN chown -R appuser:appgroup /app
USER appuser

# 或者调整宿主机文件权限
chmod -R 777 ./data
```

### 错误 5：镜像构建很慢

**原因：** 未充分利用缓存，或上下文太大

**解决：**
```bash
# 优化 Dockerfile 顺序（见上文"镜像层缓存"）
# 添加 .dockerignore 排除不必要文件
# 使用多阶段构建（高级技巧）
```

---

## 8. 实践记录

### Docker 版本信息

```bash
$ docker version
Client:
 Version:           29.6.1
 API version:       1.55
 Go version:        go1.26.4
 Git commit:        8900f1d
 Built:             Fri Jun 26 11:43:32 2026
 OS/Arch:           windows/amd64
 Context:           desktop-linux

$ docker compose version
Docker Compose version v5.2.0
```

### 基础命令练习

```bash
# 运行测试容器
docker run --name test-alpine -d alpine sleep 3600
docker ps
docker logs test-alpine
docker exec -it test-alpine sh
docker stop test-alpine
docker rm test-alpine

# 拉取镜像
docker pull redis:7-alpine
docker images
```

### 构建项目镜像

```bash
# 构建镜像
docker build -t knowledge-assistant-api:week03 .

# 查看镜像
docker image ls

# 运行容器（需要 Docker Desktop 运行）
docker run --rm -p 8000:8000 --env-file .env knowledge-assistant-api:week03
```

---

## 9. 关键知识点总结

### 必须掌握的概念

1. **镜像 vs 容器**
   - 镜像是只读模板，容器是运行实例
   - 一个镜像可以启动多个容器

2. **Dockerfile 核心指令**
   - `FROM`、`ENV`、`WORKDIR`、`COPY`、`RUN`、`EXPOSE`、`CMD`
   - 理解每条指令的作用和执行时机

3. **构建上下文与缓存**
   - 先复制变化少的文件（依赖声明），再复制变化多的文件（业务代码）
   - `.dockerignore` 排除不必要文件，加速构建

4. **端口映射**
   - `-p` 用于宿主机访问容器
   - 容器间通信直接用服务名 + 容器端口
   - `EXPOSE` 只是文档，不自动映射

5. **容器生命周期**
   - `run` → `ps` → `logs` → `exec` → `stop` → `rm`
   - 学会通过日志和 inspect 调试问题

### 下一步

- [ ] 启动 Docker Desktop
- [ ] 练习基础 Docker 命令
- [ ] 构建并运行 API 镜像
- [ ] 继续学习 Docker Compose

---

**参考资源：**
- [Docker 官方文档](https://docs.docker.com/)
- [Dockerfile 最佳实践](https://docs.docker.com/build/building/best-practices/)
- [Docker Compose 文档](https://docs.docker.com/compose/)
