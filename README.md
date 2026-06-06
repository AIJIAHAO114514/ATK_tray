# ATK Tray Charge Notification

![Screenshot](images/screenshot.png)

Windows 系统托盘电池指示器，支持 **ATK / VXE / VGN** 无线鼠标。

> 基于 [Fan4Metal/ATK_tray](https://github.com/Fan4Metal/ATK_tray) 修改，使用 [DeepSeek] 辅助完成。  
> 仅在以下型号测试，**未在其他型号验证**。

## 功能

- 轮询鼠标 HID 报告获取电池百分比
- 系统托盘显示电量数字图标（蓝 / 黄 / 红）
- 充电时播放闪烁动画
- 满电桌面通知 + 计时器
- PyInstaller 一键打包为单文件 exe

## 支持的型号

| 型号 | VID:PID (无线) | VID:PID (有线) |
|------|---------------|---------------|
| ATK F1 Ultimate | 373B:1031 | 373B:102E |
| ATK A9 Ultimate | 373B:11D9 | 373B:11B6 |
| VXE MAD R | 373B:104D | 373B:103F |
| VXE MAD R Major Plus | 373B:1040 | 373B:104C |
| VXE R1 Pro Max | 3554:F58A | 3554:F58C |
| VXE R1 SE+ | 3554:F58E | 3554:F58F |
| VGN F1 Pro | 3554:F503 | 3554:F502 |
| VGN Dragonfly 3 Master | 391D:1A05 | 3554:FB59 |

## 运行

```powershell
pip install -r requirements.txt
python atk_tray.py
```

## 打包

```powershell
python make_release.py
```

输出 `dist\ATK_tray.exe`。

## 设置

修改 `atk_tray.py` 顶部常量：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `poll_rate` | 无线模式轮询间隔（秒） | `15` |
| `foreground_color` | 数字颜色 RGB | `(91, 184, 255)` 蓝 |
| `background_color` | 背景 RGBA | `(0, 0, 0, 0)` 透明 |
| `font` | 备选字体文件名 | `"consola.ttf"` |

## 致谢

- [Fan4Metal/ATK_tray](https://github.com/Fan4Metal/ATK_tray) — 原始项目
- [DeepSeek](https://deepseek.com/) — AI 辅助开发与审计
- [hidapi](https://github.com/libusb/hidapi) — HID 通信库 (BSD-3-Clause)
