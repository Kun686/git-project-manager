# Changelog

## v0.2.3

- 新增「GitHub HTTPS 自动转 SSH」开关，默认开启。
- 如果远程地址是 https://github.com/...，会自动改成 git@github.com:...，避免反复弹 GitHub 登录。
- 修复项目列表、改动文件列表点击其他区域后选中状态消失的问题。
- Listbox 已设置 exportselection=False。

## v0.2.2

- 运行日志改为实时输出。
- 初始化、提交、清理、检查、pull、push 等关键步骤会边执行边写入日志。
- push / pull 前会显示正在执行的 Git 命令，避免长时间等待时看起来像卡死。

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
