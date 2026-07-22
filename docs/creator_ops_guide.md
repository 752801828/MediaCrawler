# 创作者运营工作流使用指南

该工作流从现有飞书多维表读取定向链接、定向用户主页和账号池任务，使用本机浏览器登录目录执行小红书与抖音任务，将运营快照保存到 MySQL，再把待同步记录写回现有飞书表。

## 使用边界

- 仅保存你自己的主账号创作者后台指标。
- 公开内容和评论沿用 MediaCrawler 上游匿名化规则。
- 不保存外部博主头像、IP、签名、性别或原始用户 ID。
- 项目仍受根目录 `LICENSE` 的非商业学习许可约束。

## 环境准备

1. 复制 `.env.example` 为本机 `.env`，填写 MySQL 与飞书配置。
2. 保持以下账号目录位于 `D:\browser_data`，或者通过 `BROWSER_DATA_ROOT` 指定其他根目录：
   - `xhs_use_data_dir`
   - `dy_use_data_dir`
   - `xhs_text_data_dir`
   - `dy_text_data_dir`
   - `dy_u1_data_dir`（启用时）
3. 飞书账号池的 `ID` 继续使用 `%s_use_data_dir`、`%s_text_data_dir` 等模板。
4. 飞书应用需要读取三张控制表及向结果表新增记录的权限。

`.env`、`D:\browser_data`、Cookie、运行日志和诊断截图不得提交到 Git。

## 配置检查

```cmd
.venv\Scripts\python.exe -m creator_ops validate-config
```

输出只包含脱敏后的数据库名、浏览器根目录和配置状态，不会输出密码、飞书密钥或 Token。

## 试运行

```cmd
.venv\Scripts\python.exe -m creator_ops run-all --dry-run
```

试运行会读取飞书任务、检查账号目录并解析主账号创作者后台页面，不写 MySQL 或飞书。公开链接任务在试运行中只检查规划和账号目录，避免上游 crawler 产生数据库写入。

## 正式运行

```cmd
start_creator_ops.cmd
```

或：

```cmd
.venv\Scripts\python.exe -m creator_ops run-all
```

程序完整运行一轮后退出。退出码：

- `0`：全部成功。
- `1`：部分任务或同步失败，其他任务已继续执行。
- `2`：配置、飞书控制表读取或任务规划失败，浏览器任务未启动。

## 分阶段运行与恢复

仅采集并写入 MySQL/outbox：

```cmd
.venv\Scripts\python.exe -m creator_ops collect-only
```

仅补传飞书 outbox：

```cmd
.venv\Scripts\python.exe -m creator_ops sync-only
```

飞书限流、超时或服务异常不会删除 MySQL 数据。恢复后执行 `sync-only` 即可补传。

## 登录失效

工作流使用可见浏览器。登录失效时在打开的 Chrome/Edge 窗口完成扫码或验证，然后重新运行任务。不要把 Cookie 导出到仓库或飞书表。

## Windows 任务计划

在 Windows 任务计划程序中创建“启动程序”操作：

- 程序：`D:\MediaCrawler-migration\MediaCrawler-upstream-source\start_creator_ops.cmd`
- 起始于：`D:\MediaCrawler-migration\MediaCrawler-upstream-source`

不要选择并行启动同一任务。相同浏览器 profile 不能被两个进程同时占用。

## GitHub 交付

迁移分支只推送到 `752801828/MediaCrawler` fork。`NanmiCoder/MediaCrawler` 仅作为只读上游来源，不向其推送分支，也不向其创建 PR。
