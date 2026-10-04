# cxauto — 超星学习通自动刷课工具

**超星学习通/尔雅/泛雅全自动无人值守刷课工具**，基于协议发包实现（无需浏览器、无需图形界面），自动完成课程中的视频、文档、阅读类任务点。

> ⚠️ **免责声明**：本项目仅供学习 Python 网络协议分析与技术交流使用，请勿用于任何违反所在学校/单位规定的场景。使用本项目产生的一切后果由使用者自行承担。

## 功能

- **密码登录**：`fanyalogin` 接口 + AES-CBC 加密，Cookie 本地持久化，失效自动重登
- **课程扫描**：自动拉取全部课程（含文件夹内课程），支持按课程名过滤
- **视频刷课**：
  - 先尝试 `isdrag=4` 直接上报「已看完」**秒过**
  - 未秒过则进入心跳循环，进度按倍速平滑推进，随机 30~90s 上报一次，模拟真实观看节律
  - 服务端已看进度记忆，支持**断点续刷**
  - `enc` 参数按官方前端算法（八段拼接 MD5）本地计算
- **文档/阅读**：一次性 jtoken 校验接口直接完成
- **风控自愈**：视频日志上报严格限速（2s + 随机抖动）；遇 403 自动刷新 dtoken 重试；可选 `ddddocr` 自动过验证码
- **运行统计**：tqdm 进度条 + loguru 日志（控制台 + 文件轮转）

## 快速开始

```bash
# 1. 安装依赖（Python 3.10+）
pip install -r requirements.txt

# 2. 创建配置
cp config.example.ini config.ini
#    编辑 config.ini，填写 username / password

# 3. 查看账号下的课程（同时验证登录）
python main.py --list

# 4. 开始刷课
python main.py --course 高等数学 大学英语   # 只刷指定课程
python main.py --concurrency 2             # 刷全部课程，2 个视频同时刷
```

可选：`pip install ddddocr` 以启用风控验证码自动识别。

### 常用参数

| 命令 | 作用 |
|---|---|
| `--list` | 只列出课程，不刷课 |
| `--course 课程名1 课程名2` | 只刷指定课程（支持子串匹配） |
| `--concurrency 2` | 同时刷几个视频（同一账号不建议超过 3） |
| `--speed 1.5` | 视频倍速，1.0~2.0 |
| `--live` | 原地动画进度面板（默认为事件快照模式，任何终端不乱屏） |
| `-c myconfig.ini` | 使用其他配置文件 |

任务完成后统计成功/失败明细；中途 `Ctrl+C` 或关机都不影响——进度保存在服务端，重跑自动断点续刷，已完成的任务点自动跳过。

## 配置说明

见 [config.example.ini](config.example.ini)，全部配置项均带中文注释。常用项：

| 配置项 | 说明 | 默认 |
|---|---|---|
| `course_list` | 只刷指定课程，逗号分隔；留空刷全部 | 空 |
| `job_types` | 要自动完成的任务类型，**默认只刷视频**，文档/阅读不碰 | video |
| `speed` | 视频倍速，**上限 2.0**（超速必触发风控） | 1.0 |
| `concurrency` | 并行工位数（同时刷几个视频），建议 ≤3 | 1 |
| `slot_gap` | 一个视频刷完后等几秒再取下一个 | 10 |
| `max_retries` | 任务点失败重试次数 | 3 |
| `notopen_action` | 章节未开放时 `skip` / `stop` | skip |
| `cookie_file` | 登录态持久化文件 | cookies.txt |

## 项目结构

```
chaoxing-auto/
├── main.py                  # CLI 入口
├── config.example.ini       # 配置模板
├── requirements.txt
├── docs/
│   └── protocol-notes.md    # 超星协议要点（登录/章节/视频 enc/风控）
├── src/cxauto/
│   ├── api/
│   │   ├── client.py        # 会话管理、登录、Cookie 持久化
│   │   ├── cipher.py        # AES-CBC 登录加密
│   │   ├── course.py        # 课程/章节/任务卡片抓取
│   │   ├── study.py         # 视频心跳、enc、文档/阅读完成
│   │   ├── decode.py        # 页面解析（改版时只改这里）
│   │   └── captcha.py       # 风控验证码 OCR（可选）
│   ├── core/
│   │   ├── config.py        # 配置加载
│   │   ├── models.py        # Account/Course/Chapter/Job 数据模型
│   │   ├── runner.py        # 工位制任务调度与重试
│   │   ├── dashboard.py     # 实时进度面板
│   │   └── ratelimiter.py   # 线程安全限速器
│   └── utils/logger.py      # loguru 日志配置
└── tests/                   # 单元测试（pytest）
```

## 设计要点

**串行 + 限速 + 随机化**是本项目刻意保守的选择：刷课本质是向服务端模拟真实播放，任何高频、节律固定、多并发的上报模式都会显著提高风控命中率和封号风险。因此：

- 任务点串行处理，不做并发刷课；
- 心跳间隔随机 30~90s（官方 reportTimeInterval 为 60s 的随机化版本）；
- 视频日志上报强制 ≥2s 间隔 + 0~2s 抖动；
- 倍速硬性钳制在 2.0 以内。

## 已知限制与路线图

- [ ] **测验（workid）自动答题**：涉及题目字体反爬解密与题库对接，计划后续版本支持
- [ ] 直播任务
- [ ] 多账号支持

## 致谢

本项目在协议实现思路上参考了以下优秀开源项目：

- [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing)
- [RainySY/chaoxing-xuexitong-autoflush](https://github.com/RainySY/chaoxing-xuexitong-autoflush)

## License

[GPL-3.0](LICENSE)
