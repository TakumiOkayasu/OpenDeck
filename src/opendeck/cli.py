import argparse
import json
import logging
import sys
from pathlib import Path

from .adapters.process import Processes
from .adapters.replay import ReplayFactory, parse_events
from .bindings import Binding
from .config import parse
from .launch import LaunchBuilder
from .model import Result, Slot, Status
from .ports import Factory, Product
from .runtime import Wake, drain


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opendeck")
    parser.add_argument(
        "--sdk-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "vendor" / "streamdock-sdk",
        help="path to the StreamDock-Device-SDK checkout",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("devices", help="list connected N4 Pro devices")
    run = commands.add_parser("run", help="run operations from an N4 Pro")
    run.add_argument("config", type=Path)
    run.add_argument("--device-index", type=int)
    run.add_argument("--debug", action="store_true", help="log device input to stderr")
    replay = commands.add_parser("replay", help="replay recorded button input")
    replay.add_argument("config", type=Path)
    replay.add_argument("events", type=Path)
    return parser


def _execute(product: Product, binding: Binding, live: bool) -> int:
    wake = Wake()
    exit_code = 0
    failure: Exception | None = None

    def report(slot: Slot, result: Result | None) -> None:
        nonlocal exit_code
        status = "unassigned" if result is None else result.status.value
        detail = "" if result is None else result.detail
        print(
            json.dumps({"input": slot, "status": status, "detail": detail}), flush=True
        )
        if result is not None and result.status is not Status.DONE:
            exit_code = 1

    product.subject.add(wake)
    try:
        product.link.open()
        if live:
            print(
                "opendeck: Waiting for N4 Pro input; press Ctrl+C to exit.",
                file=sys.stderr,
                flush=True,
            )
        wake.on_change()
        while True:
            wake.wait()
            drain(product.input, binding, report)
            if not live:
                break
    except KeyboardInterrupt:
        pass
    except Exception as error:
        failure = error
    finally:
        try:
            product.link.close()
        except Exception as error:
            failure = (
                error
                if failure is None
                else ExceptionGroup("Operation and cleanup failed", [failure, error])
            )
        finally:
            product.subject.remove(wake)
    if failure is not None:
        raise failure
    return exit_code


def _error_text(error: BaseException) -> str:
    if isinstance(error, BaseExceptionGroup):
        return f"{error.message}: " + "; ".join(
            _error_text(item) for item in error.exceptions
        )
    return str(error)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logger = logging.getLogger("opendeck")
    level, handlers, propagate = logger.level, logger.handlers[:], logger.propagate
    debug_handler: logging.StreamHandler | None = None
    try:
        if args.command == "run" and args.debug:
            debug_handler = logging.StreamHandler(sys.stderr)
            debug_handler.setFormatter(
                logging.Formatter("opendeck: %(levelname)s: %(message)s")
            )
            logger.setLevel(logging.DEBUG)
            logger.handlers = [debug_handler]
            logger.propagate = False
        if args.command == "devices":
            from .adapters.streamdock import list_devices

            for device in list_devices(args.sdk_dir):
                print(device)
            return 0
        settings = parse(_read(args.config), {"launch": LaunchBuilder(Processes())})
        factory: Factory
        if args.command == "replay":
            factory = ReplayFactory(
                settings.keys, settings.chords, parse_events(_read(args.events))
            )
        else:
            from .adapters.streamdock import StreamDockFactory

            factory = StreamDockFactory(
                settings.keys, settings.chords, args.sdk_dir, args.device_index
            )
        return _execute(factory.make(), settings.binding, args.command == "run")
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, ExceptionGroup) as error:
        print(f"opendeck: {_error_text(error)}", file=sys.stderr)
        return 1
    finally:
        if debug_handler is not None:
            logger.setLevel(level)
            logger.handlers = handlers
            logger.propagate = propagate
            debug_handler.close()
