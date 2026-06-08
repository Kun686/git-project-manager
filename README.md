# Git Project Manager 

一个面向个人开发者的本地 Git 项目管理器。

它不是替代 Git，而是把常用、容易出错的 Git 操作做成桌面工具：

- 管理多个本地项目路径
- 初始化现有项目为 Git 仓库
- 绑定 GitHub 远程仓库
- 远程非空仓库自动拉取合并
- 一键提交 / 推送单个或多个项目
- 自动维护 `.gitignore`
- 自动清理 cache/log
- 自动阻止日志、虚拟环境、缓存、密钥文件进入 Git
- 提交前轻量 CI / 安全检查
- 查看历史提交
- 回退到历史版本

## 截图

后续可以在这里放软件截图：

```text
docs/screenshot.png
```

## 运行环境

- Python 3.10+
- Git

本项目只使用 Python 标准库和 Tkinter，不依赖 PyQt、customtkinter 等第三方 GUI 库。

## 启动

```bash
python git_project_manager.py
```

## 打包成 exe

```bash
pip install pyinstaller
pyinstaller -F -w git_project_manager.py -n Git项目管理器
```

生成文件：

```text
dist/Git项目管理器.exe
```

## GitHub 首次推送流程

1. 在 GitHub 创建一个新仓库
2. 复制仓库地址，例如：

```text
git@github.com:yourname/your-repo.git
```

或：

```text
https://github.com/yourname/your-repo.git
```

3. 打开工具
4. 导入本地项目路径
5. 进入「初始化 / GitHub」
6. 填写远程地址
7. 点击「初始化 / 关联远程 / 推送」

如果远程仓库不是空的，例如已有 README、LICENSE、`.gitignore`，工具会在推送前自动执行拉取合并。

## 安全策略

默认会阻止以下内容进入 Git：

```text
*.log
logs/
__pycache__/
*.pyc
.venv/
venv/
node_modules/
dist/
build/
.env
.env.*
*.db
*.sqlite
*.pem
*.key
```

如果检测到疑似 token、password、api_key、secret，也会阻止提交。

## 开发计划

- [ ] 更完整的冲突解决界面
- [ ] GitHub API 自动创建仓库
- [ ] 支持 GitLab / Gitee
- [ ] 支持自定义提交前命令
- [ ] 支持项目分组
- [ ] 支持主题切换
- [ ] 支持多语言

## License

MIT
