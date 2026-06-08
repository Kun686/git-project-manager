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

推荐使用项目内的圆角图标：

```bash
pip install pyinstaller
pyinstaller -F -w git_project_manager.py -n Git项目管理器Pro --icon assets/app.ico
```

生成文件：

```text
dist/Git项目管理器Pro.exe
```

## GitHub 首次推送流程

1. 在 GitHub 创建一个新仓库
2. 复制仓库地址，推荐 SSH：

```text
git@github.com:yourname/your-repo.git
```

也可以粘贴 HTTPS，工具默认会自动转换成 SSH：

```text
https://github.com/yourname/your-repo.git
```

3. 打开工具
4. 导入本地项目路径
5. 进入「初始化 / GitHub」
6. 填写远程地址
7. 点击「初始化 / 关联远程 / 推送」

如果远程仓库不是空的，例如已有 README、LICENSE、`.gitignore`，工具会在推送前自动执行拉取合并。

## 常见问题

### 打包后点击按钮会闪 cmd 窗口

v2.4 已修复。工具在 Windows 下调用 Git 子进程时使用隐藏窗口参数：

```text
STARTF_USESHOWWINDOW
CREATE_NO_WINDOW
```

### 为什么明明配置了 SSH，还是弹 GitHub 登录？

因为远程地址是 HTTPS：

```text
https://github.com/yourname/your-repo.git
```

HTTPS 不会使用本地 SSH key，会触发 GitHub Credential Manager 登录。

改成 SSH 即可：

```text
git@github.com:yourname/your-repo.git
```

v2.3 起工具默认开启「GitHub HTTPS 自动转 SSH」。

## License

MIT
