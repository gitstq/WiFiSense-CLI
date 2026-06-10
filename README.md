<div align="center">

<img src="assets/logo.jpg" alt="WiFiSense-CLI Logo" width="120" height="120">

# WiFiSense-CLI

**Lightweight Terminal WiFi Signal Intelligence & IoT Event Engine**

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Zero Deps](https://img.shields.io/badge/Dependencies-Zero-success.svg)](requirements.txt)
[![Cross Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg)]()
[![Version](https://img.shields.io/badge/Version-0.1.0-orange.svg)]()

[English](#english) | [简体中文](#简体中文) | [繁體中文](#繁體中文)

</div>

---

## English

### Introduction

WiFiSense-CLI is a zero-dependency, cross-platform Python CLI tool that turns your laptop's WiFi adapter into an intelligent environment sensor. It monitors WiFi signal strength (RSSI) from nearby access points, analyzes signal patterns to detect environmental changes, and triggers custom event-driven automations — all from your terminal.

Inspired by WiFi CSI-based motion detection research, WiFiSense-CLI brings signal intelligence to everyday devices without requiring specialized hardware.

### Core Features

- **Cross-Platform WiFi Scanning** — Collect RSSI data on Linux, macOS, and Windows using native OS APIs
- **Signal Analysis Engine** — Moving average, EWMA filtering, Z-Score & IQR anomaly detection, linear regression trend analysis
- **Environment Fingerprinting** — Generate unique fingerprints from multi-AP RSSI vectors for location identification
- **Event Rules Engine** — Define trigger conditions (threshold, rate-of-change, composite logic) with actions (shell, webhook, ntfy.sh notifications)
- **TUI Dashboard** — Real-time terminal UI with ASCII signal waveform, AP status panel, and event log (curses-based, Windows fallback)
- **Data Persistence** — JSON storage, CSV export, session management with start/stop/resume
- **Zero External Dependencies** — Built entirely on Python standard library

### Quick Start

```bash
# Clone the repository
git clone https://github.com/gitstq/WiFiSense-CLI.git
cd WiFiSense-CLI

# Run directly (no installation needed)
python -m wifisense --help

# Or install globally
pip install -e .
wifisense --help
```

### Usage Guide

#### Single Scan
```bash
# Scan all visible access points
python -m wifisense scan

# Scan on specific interface, sort by signal quality
python -m wifisense scan -i wlan0 -s quality

# Output in JSON format
python -m wifisense scan --json
```

#### Continuous Monitoring
```bash
# Start monitoring with data recording
python -m wifisense monitor -d

# Monitor with custom interval
python -m wifisense monitor --interval 2.0

# Monitor specific interface
python -m wifisense monitor -i en0
```

#### Signal Analysis
```bash
# Analyze latest recorded session
python -m wifisense analyze --latest --stats

# Analyze specific session with full report
python -m wifisense analyze -s 20260610_104000 --full

# Export analysis to CSV
python -m wifisense analyze --latest --csv
```

#### Event Rules
```bash
# List all event rules
python -m wifisense events list

# Add rules from JSON file
python -m wifisense events add -f rules.json

# Remove a rule
python -m wifisense events remove rssi_drop_alert

# Test rules against current scan data
python -m wifisense events test
```

#### TUI Dashboard
```bash
# Launch interactive dashboard
python -m wifisense dashboard

# Dashboard with custom refresh rate
python -m wifisense dashboard --refresh 1.0
```

#### Configuration
```bash
# Show current configuration
python -m wifisense config show

# Set a configuration value
python -m wifisense config set scanner.poll_interval 2.0

# Reset to defaults
python -m wifisense config reset

# Validate configuration
python -m wifisense config validate
```

### Event Rule Example

Create a `rules.json` file:

```json
{
  "rules": [
    {
      "name": "rssi_drop_alert",
      "description": "Alert when WiFi signal drops below threshold",
      "condition": {
        "type": "threshold",
        "field": "rssi",
        "operator": "below",
        "value": -75
      },
      "action": {
        "type": "webhook",
        "url": "https://ntfy.sh/mychannel",
        "method": "POST",
        "body": "WiFi signal degraded: {{rssi}} dBm on {{ssid}}"
      }
    },
    {
      "name": "rapid_change_detect",
      "description": "Detect rapid signal changes",
      "condition": {
        "type": "rate",
        "field": "rssi",
        "operator": "faster_than",
        "value": 5.0,
        "window": 10
      },
      "action": {
        "type": "shell",
        "command": "echo 'Rapid signal change detected' >> signal.log"
      }
    }
  ]
}
```

### Configuration Reference

Key configuration sections in `config.json`:

| Section | Key | Default | Description |
|---------|-----|---------|-------------|
| `scanner` | `poll_interval` | 1.0 | Scan interval in seconds |
| `scanner` | `interface` | auto | WiFi interface name |
| `analyzer` | `moving_average_window` | 5 | MA filter window size |
| `analyzer` | `ewma_alpha` | 0.3 | EWMA smoothing factor |
| `analyzer` | `z_score_threshold` | 2.0 | Anomaly detection threshold |
| `analyzer` | `iqr_factor` | 1.5 | IQR anomaly factor |
| `events` | `enabled` | true | Enable event engine |
| `events` | `cooldown` | 30.0 | Event cooldown in seconds |
| `dashboard` | `refresh_rate` | 0.5 | Dashboard refresh interval |
| `dashboard` | `history_length` | 60 | Signal history data points |

### Design Philosophy

- **Privacy First** — No data leaves your machine; all processing is local
- **Zero Dependencies** — No pip install needed; works with stock Python
- **Cross-Platform** — Consistent behavior across Linux, macOS, and Windows
- **Extensible** — Plugin-friendly event engine with composable rules
- **Developer-Friendly** — Clean architecture with type hints and comprehensive docstrings

### Roadmap

- [ ] Multi-language support for notifications
- [ ] MQTT integration for IoT ecosystems
- [ ] Machine learning-based prediction models
- [ ] Historical data visualization (ASCII charts)
- [ ] Network topology mapping
- [ ] Home Assistant integration via MQTT

### Contributing

Contributions are welcome! Please read our contribution guidelines:

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## 简体中文

### 项目介绍

WiFiSense-CLI 是一个零依赖、跨平台的 Python CLI 工具，能将笔记本电脑的 WiFi 网卡变成智能环境传感器。它监控附近接入点的 WiFi 信号强度（RSSI），分析信号模式以检测环境变化，并触发自定义的事件驱动自动化——一切都在你的终端中完成。

灵感来源于 WiFi CSI 运动检测研究，WiFiSense-CLI 将信号智能带入日常设备，无需专用硬件。

### 核心特性

- **跨平台 WiFi 扫描** — 在 Linux、macOS 和 Windows 上使用原生系统 API 采集 RSSI 数据
- **信号分析引擎** — 移动平均、EWMA 滤波、Z-Score 和 IQR 异常检测、线性回归趋势分析
- **环境指纹** — 从多 AP RSSI 向量生成唯一指纹，用于位置识别
- **事件规则引擎** — 定义触发条件（阈值、变化率、组合逻辑），执行动作（Shell 命令、Webhook、ntfy.sh 通知）
- **TUI 仪表盘** — 实时终端 UI，含 ASCII 信号波形图、AP 状态面板和事件日志
- **数据持久化** — JSON 存储、CSV 导出、会话管理（启动/停止/恢复）
- **零外部依赖** — 完全基于 Python 标准库构建

### 快速开始

```bash
# 克隆仓库
git clone https://github.com/gitstq/WiFiSense-CLI.git
cd WiFiSense-CLI

# 直接运行（无需安装）
python -m wifisense --help

# 或全局安装
pip install -e .
wifisense --help
```

### 使用指南

#### 单次扫描
```bash
# 扫描所有可见接入点
python -m wifisense scan

# 指定网卡扫描，按信号质量排序
python -m wifisense scan -i wlan0 -s quality

# JSON 格式输出
python -m wifisense scan --json
```

#### 持续监控
```bash
# 启动监控并记录数据
python -m wifisense monitor -d

# 自定义扫描间隔
python -m wifisense monitor --interval 2.0
```

#### 信号分析
```bash
# 分析最新会话
python -m wifisense analyze --latest --stats

# 导出 CSV
python -m wifisense analyze --latest --csv
```

#### 事件规则
```bash
# 列出所有规则
python -m wifisense events list

# 从文件添加规则
python -m wifisense events add -f rules.json

# 测试规则
python -m wifisense events test
```

#### TUI 仪表盘
```bash
# 启动交互式仪表盘
python -m wifisense dashboard
```

### 设计思路

- **隐私优先** — 所有数据在本地处理，不离开你的机器
- **零依赖** — 无需 pip install，使用 Python 自带库即可运行
- **跨平台** — Linux、macOS、Windows 行为一致
- **可扩展** — 插件化事件引擎，支持组合规则
- **开发者友好** — 清晰架构，类型注解，完整文档

### 迭代规划

- [ ] 多语言通知支持
- [ ] MQTT 集成，对接 IoT 生态
- [ ] 机器学习预测模型
- [ ] 历史数据可视化（ASCII 图表）
- [ ] 网络拓扑映射
- [ ] Home Assistant MQTT 集成

### 贡献指南

欢迎贡献！请遵循以下步骤：

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'feat: add amazing feature'`)
4. 推送分支 (`git push origin feature/amazing-feature`)
5. 发起 Pull Request

### 开源协议

本项目基于 MIT 协议开源 — 详见 [LICENSE](LICENSE) 文件。

---

## 繁體中文

### 專案介紹

WiFiSense-CLI 是一個零依賴、跨平台的 Python CLI 工具，能將筆記型電腦的 WiFi 網卡變成智慧環境感測器。它監控附近接入點的 WiFi 信號強度（RSSI），分析信號模式以偵測環境變化，並觸發自訂的事件驅動自動化——一切都在你的終端中完成。

靈感來源於 WiFi CSI 運動偵測研究，WiFiSense-CLI 將信號智慧帶入日常設備，無需專用硬體。

### 核心特性

- **跨平台 WiFi 掃描** — 在 Linux、macOS 和 Windows 上使用原生系統 API 採集 RSSI 資料
- **信號分析引擎** — 移動平均、EWMA 濾波、Z-Score 和 IQR 異常偵測、線性回歸趨勢分析
- **環境指紋** — 從多 AP RSSI 向量生成唯一指紋，用於位置識別
- **事件規則引擎** — 定義觸發條件（閾值、變化率、組合邏輯），執行動作（Shell 命令、Webhook、ntfy.sh 通知）
- **TUI 儀表盤** — 即時終端 UI，含 ASCII 信號波形圖、AP 狀態面板和事件日誌
- **資料持久化** — JSON 儲存、CSV 匯出、會話管理（啟動/停止/恢復）
- **零外部依賴** — 完全基於 Python 標準庫建構

### 快速開始

```bash
# 克隆倉庫
git clone https://github.com/gitstq/WiFiSense-CLI.git
cd WiFiSense-CLI

# 直接執行（無需安裝）
python -m wifisense --help

# 或全域安裝
pip install -e .
wifisense --help
```

### 使用指南

#### 單次掃描
```bash
# 掃描所有可見接入點
python -m wifisense scan

# 指定網卡掃描，按信號品質排序
python -m wifisense scan -i wlan0 -s quality

# JSON 格式輸出
python -m wifisense scan --json
```

#### 持續監控
```bash
# 啟動監控並記錄資料
python -m wifisense monitor -d

# 自訂掃描間隔
python -m wifisense monitor --interval 2.0
```

#### 信號分析
```bash
# 分析最新會話
python -m wifisense analyze --latest --stats

# 匯出 CSV
python -m wifisense analyze --latest --csv
```

#### 事件規則
```bash
# 列出所有規則
python -m wifisense events list

# 從檔案新增規則
python -m wifisense events add -f rules.json

# 測試規則
python -m wifisense events test
```

#### TUI 儀表盤
```bash
# 啟動互動式儀表盤
python -m wifisense dashboard
```

### 設計思路

- **隱私優先** — 所有資料在本地處理，不離開你的機器
- **零依賴** — 無需 pip install，使用 Python 自帶庫即可執行
- **跨平台** — Linux、macOS、Windows 行為一致
- **可擴展** — 插件化事件引擎，支援組合規則
- **開發者友善** — 清晰架構，類型註解，完整文件

### 迭代規劃

- [ ] 多語言通知支援
- [ ] MQTT 整合，對接 IoT 生態
- [ ] 機器學習預測模型
- [ ] 歷史資料視覺化（ASCII 圖表）
- [ ] 網路拓撲映射
- [ ] Home Assistant MQTT 整合

### 貢獻指南

歡迎貢獻！請遵循以下步驟：

1. Fork 本倉庫
2. 建立功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交變更 (`git commit -m 'feat: add amazing feature'`)
4. 推送分支 (`git push origin feature/amazing-feature`)
5. 發起 Pull Request

### 開源協議

本專案基於 MIT 協議開源 — 詳見 [LICENSE](LICENSE) 檔案。

---

<div align="center">

**Built with Python Standard Library | Zero Dependencies | Cross-Platform**

</div>
