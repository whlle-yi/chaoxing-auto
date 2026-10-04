# cxauto — 超星学习通自动刷课工具

基于协议发包实现的超星学习通自动刷课工具（无需浏览器），自动完成课程中的**视频类任务点**：密码登录、课程扫描、多工位并行刷视频、断点续刷、进度面板。

> ⚠️ **免责声明**：本项目仅供学习网络协议分析与技术交流使用，请勿用于违反所在学校/单位规定的场景，使用产生的一切后果由使用者自行承担。

## 快速开始

```bash
# 1. 安装依赖（Python 3.10+）
pip install -r requirements.txt

# 2. 创建并编辑配置：填入学习通账号密码
cp config.example.ini config.ini

# 3. 查看账号下的课程（同时验证登录）
python main.py --list

# 4. 开始刷课
python main.py --course 高等数学 --concurrency 2   # 指定课程
python main.py                                     # 或刷全部课程
```

可选：`pip install ddddocr` 启用风控验证码自动识别。

中断后重跑同一条命令即可，进度保存在服务端，自动断点续刷、跳过已完成任务。

## 常用参数

| 参数 | 作用 |
|---|---|
| `--list` | 只列出课程，不刷课 |
| `--course 课程名1 课程名2` | 只刷指定课程（支持子串匹配） |
| `--concurrency 2` | 同时刷几个视频（建议 ≤3） |
| `--speed 1.5` | 视频倍速，1.0~2.0 |
| `--live` | 原地动画进度面板（默认事件快照模式） |

更多配置项见 [config.example.ini](config.example.ini)（全部带中文注释）。

## 许可证与致谢

[GPL-3.0](LICENSE) · 协议实现思路参考 [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing)、[RainySY/chaoxing-xuexitong-autoflush](https://github.com/RainySY/chaoxing-xuexitong-autoflush)
