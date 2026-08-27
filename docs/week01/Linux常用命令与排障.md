# Linux 常用命令与排障

本文件用于记录第一周实际执行过的 Linux 命令和问题排查过程。

---

## 1. 基础命令

### 查看当前位置

```bash
pwd
```

输出当前所在目录的绝对路径，例如 `/root/knowledge-assistant`。

### 切换目录

```bash
cd /root/knowledge-assistant
cd ..        # 返回上一级
cd ~         # 返回用户主目录
```

### 列出文件

```bash
ls           # 简单列出
ls -la       # 详细列出，包括隐藏文件
ll           # ls -l 的别名，很多系统已预置
```

---

## 2. 文件与目录操作

### 创建目录

```bash
mkdir mydir
mkdir -p data/uploads    # 递归创建父目录
```

### 复制文件

```bash
cp source.txt dest.txt
cp -r src_dir dest_dir   # 递归复制目录
```

### 移动/重命名

```bash
mv old_name.txt new_name.txt
mv file.txt /path/to/dest/
```

### 删除

```bash
rm file.txt
rm -rf mydir             # 强制递归删除，慎用
```

### 打包与解压

```bash
# 解压 zip
unzip knowledge-assistant.zip -d knowledge-assistant/

# 压缩 zip（PowerShell 命令，供参考）
Compress-Archive -Path .\src, .\pyproject.toml, .\README.md -DestinationPath knowledge-assistant.zip -Force
```

---

## 3. 文本查看与编辑

### 查看文件内容

```bash
cat file.txt          # 一次性显示全部
head -n 20 file.txt   # 显示前 20 行
tail -n 20 file.txt   # 显示后 20 行
less file.txt         # 分页查看，按 q 退出
```

### 搜索文本

```bash
grep "keyword" file.txt
grep -r "keyword" /path/to/dir   # 递归搜索
```

### 简单编辑

```bash
nano file.txt
```

或

```bash
vi file.txt
```

---

## 4. 权限管理

### 查看权限

```bash
ls -l file.txt
```

输出示例：

```text
-rw-r--r-- 1 root root 1234 Aug 14 07:25 file.txt
```

### 修改权限

```bash
chmod +x script.sh         # 添加可执行权限
chmod 755 script.sh        # 设置权限为 rwxr-xr-x
```

### 修改所有者

```bash
chown user:group file.txt
```

---

## 5. 进程管理

### 查看进程

```bash
ps aux
ps aux | grep python       # 过滤出 Python 进程
```

### 查看端口占用

```bash
netstat -tlnp              # 查看监听端口
netstat -ano | grep :5432  # 查看 5432 端口
```

### 结束进程

```bash
kill 1234                  # 发送 SIGTERM 结束进程
kill -9 1234               # 强制结束
```

---

## 6. 网络与端口

### 测试网络连通

```bash
ping github.com
ping 127.0.0.1
```

### 测试端口

```bash
pg_isready -h 127.0.0.1 -p 5432
```

### 查看网络配置

```bash
ip addr
```

---

## 7. 系统信息

### 查看系统版本

```bash
cat /etc/os-release
uname -a
```

### 查看磁盘空间

```bash
df -h
```

### 查看内存使用

```bash
free -h
```

---

## 8. Python 虚拟环境

### 创建虚拟环境

```bash
python3 -m venv .venv
```

如果提示 `ensurepip is not available`，需要安装：

```bash
apt update
apt install -y python3-venv
```

### 激活虚拟环境

```bash
source .venv/bin/activate
```

激活后提示符前面会出现 `(.venv)`。

### 退出虚拟环境

```bash
deactivate
```

---

## 9. 常用排障

### 命令找不到

```bash
command not found
```

可能原因：

- 虚拟环境未激活
- 软件包未安装
- 命令名拼写错误

检查：

```bash
which python3
which knowledge-assistant
```

### 虚拟环境创建失败

错误信息：

```text
The virtual environment was not created successfully because ensurepip is not available.
```

解决：

```bash
apt update
apt install -y python3-venv
rm -rf .venv
python3 -m venv .venv
```

### 端口连接失败

错误信息：

```text
Failed to connect to github.com port 443
```

可能原因：

- 网络不通
- 防火墙限制
- 代理未配置

排查：

```bash
ping github.com
netstat -ano | grep :443
```

---

## 10. 常用快捷键

| 快捷键 | 作用 |
|--------|------|
| `Ctrl + C` | 中断当前命令 |
| `Ctrl + D` | 退出当前终端/程序 |
| `Tab` | 自动补全命令或路径 |
| `↑ / ↓` | 查看历史命令 |
| `clear` | 清屏 |

---

## 11. 第一周实际用到的命令记录

```bash
# SSH 连接到虚拟机
ssh -p 22 root@10.3.70.26

# 修改 root 密码
passwd

# 检查 git 是否安装
git status

# 检查 Python 版本
python3 --version

# 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装项目依赖
pip install --upgrade pip
pip install -e ".[dev]"

# 验证命令
knowledge-assistant --help
knowledge-assistant add samples/example.txt
knowledge-assistant list
```
