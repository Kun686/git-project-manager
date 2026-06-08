# Changelog

## v0.2.5

- 修复窗口左上角标题栏图标没有变化的问题。
- 将 ico 图标内嵌进 Python 文件，运行源码和打包 exe 都会设置 Tkinter 窗口图标。
- 新增 Windows AppUserModelID，改善任务栏图标识别。

## v0.2.4

- 修复 Windows 打包 exe 后执行 Git 命令时闪出 cmd 窗口的问题。
- 所有 Git 子进程统一使用 STARTF_USESHOWWINDOW + CREATE_NO_WINDOW。
- 新增圆角应用图标 assets/app.ico。
- README 新增带图标打包命令。

## v0.2.3

- 新增「GitHub HTTPS 自动转 SSH」开关，默认开启。
- 如果远程地址是 https://github.com/...，会自动改成 git@github.com:...。
- 修复项目列表、改动文件列表点击其他区域后选中状态消失的问题。

## v0.2.2

- 运行日志改为实时输出。

## v0.2.1

- 修复冲突标记检测误报。

## v0.2.0

- 新增远程非空仓库自动拉取合并
- 优化勾选框为苹果风格开关
- 新增提交前误提交扫描
- 新增基础 GitHub Actions CI 生成
- 新增 cache/log 清理
- 新增 .gitignore 管理

## v0.1.0

- 多项目路径管理
- Git 提交、推送、历史查看、回退
