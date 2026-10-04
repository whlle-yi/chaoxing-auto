"""命令行入口。

用法::

    python main.py                     # 使用 config.ini
    python main.py -c myconfig.ini     # 指定配置文件
    python main.py --course "高等数学" "大学英语"   # 临时只刷指定课程
    python main.py --speed 2.0         # 临时指定倍速
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from cxauto.core.config import Config  # noqa: E402
from cxauto.core.runner import Runner  # noqa: E402
from cxauto.utils.logger import logger, setup_logger  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cxauto",
        description="超星学习通自动刷课工具（协议版，无需浏览器）",
    )
    parser.add_argument("-c", "--config", default="config.ini", help="配置文件路径（默认 config.ini）")
    parser.add_argument("--course", nargs="*", default=None, help="只刷指定课程（可多个，覆盖配置文件）")
    parser.add_argument("--speed", type=float, default=None, help="视频倍速，1.0~2.0（覆盖配置文件）")
    parser.add_argument("--list", action="store_true", help="只列出账号下的课程，不刷课")
    parser.add_argument("--log-level", default=None, help="控制台日志级别（默认 INFO）")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = Config.from_ini(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"配置错误: {e}", file=sys.stderr)
        return 2

    if args.course:
        config.course_list = args.course
    if args.speed is not None:
        config.speed = args.speed
    if args.log_level:
        config.log_level = args.log_level.upper()

    setup_logger(config.log_file, config.log_level)
    logger.info("cxauto 启动：账号 {}，倍速 {}x", config.username[:3] + "****", config.speed)

    if args.list:
        from cxauto.api.client import ChaoxingClient
        from cxauto.api.course import CourseAPI

        client = ChaoxingClient(config)
        client.login()
        courses = CourseAPI(client).get_course_list()
        if courses:
            print()
            for course in courses:
                print(f"  {course.name}  （教师: {course.teacher or '未知'}）")
        return 0

    try:
        runner = Runner(config)
        stats = runner.run()
    except KeyboardInterrupt:
        logger.warning("用户中断，退出")
        return 130
    except Exception as e:  # noqa: BLE001
        logger.exception("运行失败: {}", e)
        return 1

    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
