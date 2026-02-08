# Codex 多账号管理器

一套 PowerShell 方案，让你轻松管理多个 Codex 账号。

## 快速开始

```powershell
cdx              # 弹出菜单选择账号（输入数字）
cdx yiye         # 直接启动 yiye 账号
cdx bal -NewWindow  # 新窗口启动 bal 账号
cdx -All         # 同时启动所有账号（各开一个窗口）
```

## 常用命令

| 命令 | 说明 |
|------|------|
| `cdx` | 弹出数字菜单选择账号（输入 0-4 的数字） |
| `cdx <账号名>` | 直接启动指定账号（支持模糊匹配） |
| `cdx -List` | 列出所有账号（推荐写法） |
| `cdx list` | 列出所有账号（兼容写法） |
| `cdx -NewWindow` | 在新窗口启动 |
| `cdx -All` | 一键启动所有账号 |
| `addcdx <新账号名>` | 添加新账号 |

## 示例

```powershell
# 查看所有账号
cdx -List

# 方式一：菜单选择（输入数字）
cdx
# 然后输入: 0  (选择 yiye)

# 方式二：直接指定账号名
cdx man

# 模糊匹配（输入 von 会匹配 vonadler）
cdx von

# 新窗口启动 dil，同时跑多个任务
cdx dil -NewWindow
cdx bal -NewWindow

# 添加新账号
addcdx alice
cdx alice

# 一键开所有账号
cdx -All
```

## 共享资源

所有账号共享以下资源（修改一次，全部生效）：

- `skills/` - 技能脚本文件夹
- `config.toml` - Codex 配置文件
- `AGENTS.md` - 用户级 Agent 指令

独立资源（各账号互不影响）：

- `auth.json` - 登录凭证
- `sessions/` - 对话历史
- `history.jsonl` - 命令历史

## 项目文件结构

```
C:\Users\<用户名>\
 .codex\                          # 主 Codex 目录（共享资源源）
    skills\                      # 共享：技能脚本
    config.toml                  # 共享：配置文件
    AGENTS.md                    # 共享：用户级 Agent 指令
    auth.json                    # 主账号的登录凭证
    sessions\                    # 主账号的对话历史
    history.jsonl                # 主账号的命令历史

 .codex-profiles\                 # 多账号管理配置目录
    profiles.json                # 账号列表配置
    README.md                    # 本文档
    install.ps1                  # 安装脚本
    codex-multi-account.profile.ps1  # cdx / addcdx 函数块

 .codex-yiye\                     # yiye 账号目录
    skills\      -> (Junction 链接到 .codex\skills)
    config.toml  -> (Hardlink 链接到 .codex\config.toml)
    AGENTS.md    -> (Hardlink 链接到 .codex\AGENTS.md)
    auth.json                    # yiye 独立登录凭证
    sessions\                    # yiye 独立对话历史
    history.jsonl                # yiye 独立命令历史

 .codex-man\                      # man 账号目录（结构同上）
 .codex-bal\                      # bal 账号目录（结构同上）
 .codex-dil\                      # dil 账号目录（结构同上）
 .codex-vonadler\                 # vonadler 账号目录（结构同上）

C:\Users\<用户名>\Documents\WindowsPowerShell\
 Microsoft.PowerShell_profile.ps1  # PowerShell 启动脚本（包含 cdx 函数）
```

**说明：**
- `->` 表示符号链接/硬链接，指向同一份文件
- 修改任意一个链接文件，所有账号都会同步更新
- 删除链接文件不会影响源文件（除非删除所有硬链接）

## 配置文件位置

| 文件 | 路径 | 说明 |
|------|------|------|
| PowerShell Profile | `~\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1` | 主要逻辑代码 |
| 账号列表 | `~\.codex-profiles\profiles.json` | 所有账号配置 |
| 主 Codex 目录 | `~\.codex` | 共享资源源文件 |
| 各账号目录 | `~\.codex-<账号名>` | 各账号独立数据 |

## 工作原理

- 每个账号有独立的 `CODEX_HOME` 目录
- 使用 Junction（文件夹）和 Hardlink（文件）共享资源
- 启动时自动设置环境变量并调用 `codex --dangerously-bypass-approvals-and-sandbox`

## 添加新账号

方法一（推荐）：
```powershell
addcdx newaccount
```

方法二（手动）：
编辑 `~\.codex-profiles\profiles.json`，添加：
```json
{ "name": "newaccount", "home": "%USERPROFILE%\\.codex-newaccount" }
```

## 默认账号列表

- yiye
- man
- bal
- dil
- vonadler

## 重装系统/换电脑后恢复

1. 复制整个 `.codex-profiles` 文件夹到新系统
2. 在 PowerShell 中运行：
   ```powershell
   & "$env:USERPROFILE\.codex-profiles\install.ps1"
   ```
3. 重开 PowerShell 即可使用

## 注意事项

1. 首次使用每个账号需要登录一次，之后自动保持登录
2. 删除共享文件（如 AGENTS.md）需要删除所有账号目录里的硬链接
3. 项目级配置文件会覆盖用户级配置（Codex 原生逻辑）
4. 所有命令需在 PowerShell 中运行（不支持 CMD）
5. 使用菜单模式时，输入数字（0-4），不是输入账号名
6. 本模块不会覆盖 `cd` 函数（避免与其他 profile 逻辑冲突）
7. 安装时会自动移除旧的 “Auto Set Tab Title + 重写 cd” 旧块（若存在）

## 故障排查

**问题：cdx 命令不存在**
- 确保在 PowerShell（不是 CMD）中运行
- 重新打开 PowerShell 窗口

**问题：Invalid choice 错误**
- 使用菜单模式时，输入数字（如 3），不是输入 `cdx dil`
- 或者直接用：`cdx dil`（不弹菜单）

**问题：账号启动后还是原来的配置**
- 检查共享链接是否创建成功：`Get-ChildItem ~\.codex-<账号名>`
- 重新启动该账号：`cdx <账号名>`
