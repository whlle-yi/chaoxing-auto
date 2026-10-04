# cxauto — 超星学习通自动刷课工具

<p align="center">
  <b>图形界面 · 双工位并行 · 断点续刷 · 协议级实现</b>
</p>

**cxauto** 是一个基于协议发包的超星学习通自动刷课工具，无需浏览器即可自动完成课程中的**视频类任务点**。支持密码登录、课程扫描、多工位并行、实时进度显示与断点续刷。

> ⚠️ **免责声明**：本项目仅供学习网络协议分析与技术交流使用，请勿用于违反所在学校/单位规定的场景，使用产生的一切后果由使用者自行承担。

---

## 功能特性

- **图形界面**：填账号 → 选课程 → 一键开始，全程无需命令行
- **协议级实现**：与官方播放器相同的上报协议与加密算法，后台挂机无感
- **多工位并行**：最多 3 个视频同时刷，固定并发上限 + 补位间隔，行为贴近真人
- **断点续刷**：中断/关机后重跑自动接续，已完成任务自动跳过
- **安全边界**：倍速硬性限制 ≤2.0、心跳随机化、请求限速，降低风控风险
- **只刷视频**：测验、文档等其他任务默认不碰（可配置）

## 环境要求

- Windows / macOS / Linux
- Python 3.10 及以上

## 安装

```bash
git clone https://github.com/whlle-yi/chaoxing-auto.git
cd chaoxing-auto
pip install -r requirements.txt
```

## 使用说明

### 方式一：图形界面（推荐）

双击项目目录下的 **`启动刷课助手.bat`**（或执行 `python gui.py`），没有黑窗口，进度全在界面里：

1. 填写学习通账号密码，点击 **「登录并获取课程列表」**
2. 在右侧列表选中要刷的课程（不选 = 全部）
3. 点击 **「开始刷课」**，实时查看每个工位的播放进度
4. 随时点 **「停止」**，进度保存在服务端，下次自动续刷

### 方式二：命令行

```bash
# 编辑 config.ini 填入账号密码后：
python main.py --list                                # 查看账号下的课程
python main.py --course 高等数学 --concurrency 2     # 指定课程并行刷
python main.py                                       # 刷全部课程
python main.py --live                                # 原地动画进度面板
```

| 参数 | 作用 |
|---|---|
| `--list` | 只列出课程，不刷课 |
| `--course 课程名1 课程名2` | 只刷指定课程（支持子串匹配） |
| `--concurrency 2` | 同时刷几个视频（建议 ≤3） |
| `--speed 1.5` | 视频倍速，1.0~2.0 |
| `--live` | 原地动画进度面板（默认事件快照模式） |

## 配置说明

复制 `config.example.ini` 为 `config.ini`，全部配置项均带中文注释。核心项：

| 配置项 | 说明 | 默认 |
|---|---|---|
| `username` / `password` | 学习通账号密码 | 必填 |
| `course_list` | 只刷指定课程，逗号分隔；留空刷全部 | 空 |
| `job_types` | 要自动完成的任务类型 | video |
| `concurrency` | 并行工位数 | 1 |
| `speed` | 视频倍速，上限 2.0 | 1.0 |

> `config.ini`、`cookies.txt`、`logs/` 含个人隐私，已被 `.gitignore` 排除，不会被上传。

## 项目结构

```
chaoxing-auto/
├── gui.py               # 图形界面入口
├── main.py              # 命令行入口
├── config.example.ini   # 配置模板
├── docs/
│   └── protocol-notes.md  # 超星协议要点（维护/适配用）
├── src/cxauto/
│   ├── api/             # 与超星服务器的交互（登录/抓取/上报/验证码）
│   ├── core/            # 调度决策（工位调度/配置/进度面板/限速）
│   └── utils/           # 日志等通用工具
└── tests/               # 单元测试
```

## 常见问题

**刷课会被检测吗？** 程序的行为边界与官方播放器一致（倍速 ≤2.0、随机心跳、请求限速），但无法承诺绝对安全，请自行评估。

**为什么视频要等真实时长？** 服务端会核对进度推进速率，超过 2 倍速会被判异常，因此刷一个 40 分钟的视频最快需要 20 分钟（2 倍速）。

**测验会自动做吗？** 不会。默认只刷视频，测验/文档/阅读需要本人处理。

## 许可证与致谢

[GPL-3.0](LICENSE) · 协议实现思路参考 [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing)、[RainySY/chaoxing-xuexitong-autoflush](https://github.com/RainySY/chaoxing-xuexitong-autoflush)
