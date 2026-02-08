# Codex 多账号管理器 - 快速部署指南

## 新电脑/重装系统后恢复

### 方法一：从备份恢复（推荐）

1. 备份这个文件夹到云盘/U盘：
   ```
   C:\Users\walty\.codex-profiles\
   ```

2. 在新系统复制回同样位置

3. 打开 PowerShell，运行安装脚本：
   ```powershell
   & "$env:USERPROFILE\.codex-profiles\install.ps1"
   ```

4. 重开 PowerShell，完成！

### 方法二：从零安装

1. 下载 `install.ps1` 到任意位置

2. 在 PowerShell 中运行：
   ```powershell
   & "下载路径\install.ps1"
   ```

3. 重开 PowerShell，完成！

## 需要备份的文件

如果想保留所有账号的登录状态和历史记录，备份这些：

```
C:\Users\walty\.codex-profiles\     # 配置（必须）
C:\Users\walty\.codex\              # 主账号数据（可选）
C:\Users\walty\.codex-yiye\         # yiye 账号数据（可选）
C:\Users\walty\.codex-man\          # man 账号数据（可选）
C:\Users\walty\.codex-bal\          # bal 账号数据（可选）
C:\Users\walty\.codex-dil\          # dil 账号数据（可选）
C:\Users\walty\.codex-vonadler\     # vonadler 账号数据（可选）
```

## 修改默认账号列表

编辑 `profiles.json`，添加/删除账号：

```powershell
notepad "$env:USERPROFILE\.codex-profiles\profiles.json"
```

格式：
```json
[
  { "name": "账号名", "home": "%USERPROFILE%\\.codex-账号名" }
]
```

查看账号列表：

```powershell
cdx -List
# 或兼容写法
cdx list
```

## 一键安装命令（复制粘贴即可）

```powershell
# 如果 install.ps1 已存在
& "$env:USERPROFILE\.codex-profiles\install.ps1"

# 如果从网络下载（示例）
# Invoke-WebRequest -Uri "你的URL/install.ps1" -OutFile "$env:TEMP\codex-install.ps1"
# & "$env:TEMP\codex-install.ps1"
```

## 文件清单

- `install.ps1` - 安装脚本（运行一次即可）
- `profiles.json` - 账号列表配置
- `codex-multi-account.profile.ps1` - `cdx`/`addcdx` 函数定义
- `README.md` - 完整使用文档
- `QUICKSTART.md` - 本文档
