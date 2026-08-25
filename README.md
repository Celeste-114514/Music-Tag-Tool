# MusicTagTool（音乐标签批量修改工具）

批量从 **Apple Music**（CN / US / JP 三区）与 **MusicBrainz** 查询标签，对照预览后
**批量写入你勾选的字段**的本地图形工具，纯本地运行、只写勾选字段。

> 本工程是旧 Tkinter 版（曾因 Windows 高 DPI 下**列表内容渲染不显示**而受阻）的
> **PySide6 (Qt) 重写**。GUI 层换用 Qt 模型/视图架构 + QThread 后台线程，彻底绕开
> Tk 的 Listbox/Treeview 渲染问题；业务核心（scanner/model/writer/providers）为
> 旧工程已验证的成熟代码，整体复用。

## 运行环境与依赖
- Python 3.8+（本机 3.14）
- 依赖：`PySide6`、`mutagen`
  ```bash
  pip install -r requirements.txt
  ```

## 启动
- Windows：双击 `run.bat`（用 `pythonw` 无控制台窗口启动，已强制 UTF-8）
- 或用命令行：`python MusicTagTool.py`

## 功能
- **扫描文件夹**：递归扫描并读取现有标签（m4a / mp3 / mp4 / aac / flac / ogg / opus / dsf / wav…）
  - 扫描是**逐行增量**显示的，可随时 **⏸ 暂停 / ▶ 继续 / ■ 停止**；停止后已扫到的行**保留在列表**，重新点扫描会从断点续扫（不重复、不丢失）
- **查询标签**：Apple Music 三区 + MusicBrainz 后台查询候选（带磁盘缓存 + 限速，**不下载封面**，更快）
  - 查询同样支持 **暂停 / 继续 / 停止**，停止后保留已查结果，可断点续查
  - **🔄 重新查询**：改用当前勾选的数据源 / 店区 / 字段重新完整查询（换选项后生效）
  - 未匹配的行会在日志里写明原因（如 title/artist 为空 → 网易云 flac 转 ALAC 常见）
- **双表对照**：左表=原标签当前值；右表=数据源候选值，**黄色行 = 有差异可写**；列宽可拖动
- **写入勾选字段**：只写你在界面勾选的字段，且只写「平台给了新值、且与当前不同」的字段；其它标签一律不改（写前弹窗确认）
- **导出 / 导入 CSV**：Excel 编辑「新值」列后批量应用
- **整专辑套用**：选中一首查到的字段，套用到「同目录 + 同专辑名」整组
- 安全策略：默认只读，必须手动点「写入勾选字段」才写盘；写前确认
- 封面（artwork）不做查询/写入——封面由外部 `CelesteMusicPlayer` 等处理

## 目录结构
```
MusicTagTool.py        入口（PySide6）
model.py               AudioTags 统一数据模型 + 字段定义（复用）
scanner.py             扫描 + 读取现有标签（复用）
writer.py              跨格式写入器（只写勾选字段，复用）
providers.py           Apple(三区)/MusicBrainz 查询（复用）
app/
  main_window.py       PySide6 主窗口（双表 + 控制面板 + 后台线程）
  table_model.py       QAbstractTableModel（Qt 渲染，根治显示问题）
  workers.py           Scan/Query/Write 后台 QThread
tests/smoke_test.py    冒烟测试（含多行像素渲染验证）
run.bat                Windows 双击启动（pythonw）
```

## 测试
```bash
python tests/smoke_test.py
```
覆盖：字段完整性、AudioTags.needs/plan、scanner 解析、**双表 50 行像素渲染
（历史卡点）**、CSV 导入导出、整专辑套用、**暂停/继续/停止 gate 语义**、
**查询断点续扫**（停止→续跑精确衔接无重复）。写路径已在真实 m4a 副本上验证
（仅 genre 改变、其它标签不变）。

> 真实文件的读写验证用副本进行，不触碰原始文件；首次使用建议先只勾选「流派」
> 跑一遍确认效果。

## 已知提示
- Apple 三区对中文（CN）/日文（JP）名匹配更佳；流派做了 日文/中文 → 英文 映射
- 网络不佳时 Apple 接口可能偶发 403，可挂代理；`cache/` 会缓存查询结果，可续查
- MusicBrainz 限速 1 req/s，查询会偏慢
