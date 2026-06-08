# Git Project Manager

一个面向个人开发者的本地 Git 项目管理器。

它不是替代 Git，而是把常用、容易出错的 Git 操作做成桌面工具：

- 管理多个本地项目路径
- 初始化现有项目为 Git 仓库
- 绑定 GitHub 远程仓库
- GitHub HTTPS 远程自动转换为 SSH
- 远程非空仓库自动拉取合并
- 一键提交 / 推送单个或多个项目
- 实时运行日志
- 自动维护 `.gitignore`
- 自动清理 cache/log
- 自动阻止日志、虚拟环境、缓存、密钥文件进入 Git
- 提交前轻量 CI / 安全检查
- 查看历史提交
- 回退到历史版本
- Windows 打包后隐藏 Git 子进程 cmd 闪窗
- 自带圆角应用图标
- 防止 exe 被命名为 git.exe 后无限自我打开

## 运行环境

- Python 3.10+
- Git
- 已配置 GitHub SSH key，推荐使用 SSH 远程地址

本项目只使用 Python 标准库和 Tkinter，不依赖 PyQt、customtkinter 等第三方 GUI 库。

## 启动

```bash
python git_project_manager.py
```

## 打包成 exe

```bash
pip install pyinstaller
pyinstaller -F -w git_project_manager.py -n Git项目管理器 --icon assets/app.ico
```

不要把生成的 exe 命名为：

```text
git.exe
```

因为本工具内部需要调用真正的 Git。如果工具本身叫 `git.exe`，系统可能把工具当成 Git 命令反复启动。

## 常见问题

### 下载后的 exe 无限自动打开怎么办？

先用任务管理器结束进程，或执行：

```bat
taskkill /F /IM git.exe
taskkill /F /IM Git项目管理器.exe
```

然后检查 exe 名字，不要叫 `git.exe`。v2.6 起已加入启动保护，并且程序内部会查找真正的 Git 路径，不再直接调用裸命令 `git`。

## License

MIT
