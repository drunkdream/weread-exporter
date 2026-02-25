import argparse
import asyncio
import logging
import os
import sys
from typing import Callable, Optional, List

if sys.version_info >= (3, 8):
    from typing import TYPE_CHECKING
else:
    from typing_extensions import TYPE_CHECKING

from . import utils, webpage


def patch_windows() -> None:
    bin_path: str = os.path.join(
        os.path.abspath(os.path.dirname(__file__)), "bin", "win32"
    )
    os.environ["PATH"] += ";" + bin_path
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(bin_path)  # pyright: ignore[reportUnusedCallResult]


def patch_macos() -> None:
    fallback_lib_path: str = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    if not fallback_lib_path:
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] += "/opt/homebrew/lib"


def patch_generateRequestHash() -> None:
    from pyppeteer import network_manager

    orig_generateRequestHash: Callable[..., str] = network_manager.generateRequestHash

    def patched_generateRequestHash(request):
        request["headers"].pop("Origin", None)
        return orig_generateRequestHash(request)

    network_manager.generateRequestHash = patched_generateRequestHash


async def async_main() -> int:
    from . import export

    parser = argparse.ArgumentParser(
        prog="weread-exporter", description="WeRead book export cmdline tool"
    )
    parser.add_argument(
        "-b", "--book-id", help="book id", required=True
    )  # pyright: ignore[reportUnusedCallResult]
    parser.add_argument(  # pyright: ignore[reportUnusedCallResult]
        "-o",
        "--output-format",
        help="output file format",
        action="append",
        choices=["md", "epub", "pdf", "mobi", "txt"],
    )
    parser.add_argument(  # pyright: ignore[reportUnusedCallResult]
        "--load-timeout",
        help="load chapter page timeout",
        type=int,
        default=60,
    )
    parser.add_argument(  # pyright: ignore[reportUnusedCallResult]
        "--load-interval",
        help="load chapter page interval time",
        type=int,
        default=30,
    )
    parser.add_argument(  # pyright: ignore[reportUnusedCallResult]
        "--css-file",
        help="overide default css style",
    )
    parser.add_argument(  # pyright: ignore[reportUnusedCallResult]
        "--headless", help="chrome headless", action="store_true", default=False
    )
    parser.add_argument(  # pyright: ignore[reportUnusedCallResult]
        "--force-login", help="force login first", action="store_true", default=False
    )
    parser.add_argument(  # pyright: ignore[reportUnusedCallResult]
        "--use-default-profile",
        help="use default profile",
        action="store_true",
        default=False,
    )
    parser.add_argument(  # pyright: ignore[reportUnusedCallResult]
        "--mock-user-agent",
        help="use mock user-agent",
        action="store_true",
        default=False,
    )
    parser.add_argument(  # pyright: ignore[reportUnusedCallResult]
        "--proxy-server",
        help="http proxy server, e.g. http://127.0.0.1:8888",
    )
    args = parser.parse_args()
    args.output_format = args.output_format or ["epub"]  # pyright: ignore[reportAny]
    if "mobi" in args.output_format and "epub" not in args.output_format:
        args.output_format.append("epub")  # pyright: ignore[reportUnusedCallResult]

    extra_css: Optional[str] = None
    if args.css_file:  # pyright: ignore[reportAny]
        if not os.path.isfile(args.css_file):  # pyright: ignore[reportAny]
            raise RuntimeError(
                "CSS file %s not exist" % args.css_file
            )  # pyright: ignore[reportAny]
        with open(args.css_file) as fp:  # pyright: ignore[reportAny]
            extra_css = fp.read()

    if "_" in args.book_id:  # pyright: ignore[reportAny]
        # book list id
        book_list = [it["id"] for it in await utils.get_book_list(args.book_id)]
    else:
        book_list = [args.book_id]  # pyright: ignore[reportAny]

    for book_id in book_list:
        logging.info("Exporting book %s" % book_id)
        page = webpage.WeReadWebPage(
            book_id,
            cookie_path=os.path.join("cache", "cookie.txt"),
            webcache_path="cache",
        )
        if not await page.check_valid():
            logging.warning("Book %s status is invalid, stop exporting" % book_id)
            continue
        save_path = os.path.join("cache", book_id)
        output_dir = "output"
        if not os.path.isdir(output_dir):
            os.mkdir(output_dir)
        exporter = export.WeReadExporter(page, save_path)
        while True:
            try:
                await page.launch(
                    headless=args.headless,  # pyright: ignore[reportAny]
                    force_login=args.force_login,  # pyright: ignore[reportAny]
                    use_default_profile=args.use_default_profile,  # pyright: ignore[reportAny]
                    mock_user_agent=args.mock_user_agent,  # pyright: ignore[reportAny]
                    proxy_server=args.proxy_server,  # pyright: ignore[reportAny]
                )
            except utils.BreakExportingError:
                logging.info("Exit process...")
                return -1
            except RuntimeError:
                logging.exception("Launch book %s home page failed" % book_id)
                await asyncio.sleep(2)
                continue

            try:
                await exporter.export_markdown(args.load_timeout, args.load_interval)
            except utils.LoadChapterFailedError:
                logging.warning("Load chapter failed, close browser and retry")
                await page.close()
            else:
                await page.close()
                break

        await exporter.pre_process_markdown()
        title = await exporter.get_book_title()
        title = utils.format_filename(title)
        if "epub" in args.output_format:
            save_path = os.path.join(output_dir, "%s.epub" % title)
            if os.path.isfile(save_path):
                logging.info("File %s exist, ignore export" % save_path)
            else:
                await exporter.markdown_to_epub(save_path, extra_css=extra_css)
                logging.info("Save file %s complete" % save_path)

        if "pdf" in args.output_format:
            save_path = os.path.join(output_dir, "%s.pdf" % title)
            if os.path.isfile(save_path):
                logging.info("File %s exist, ignore export" % save_path)
            else:
                image_format = "jpg"
                if sys.platform == "win32":
                    image_format = "png"
                await exporter.markdown_to_pdf(
                    save_path,
                    extra_css=extra_css,
                    image_format=image_format,
                )
                logging.info("Save file %s complete" % save_path)

        if "mobi" in args.output_format:
            if sys.platform != "linux":
                logging.error("Only linux system supported to export mobi format")
                return -1
            epub_path = os.path.join(output_dir, "%s.epub" % title)
            save_path = os.path.join(output_dir, "%s.mobi" % title)
            if os.path.isfile(save_path):
                logging.info("File %s exist, ignore export" % save_path)
            else:
                await exporter.epub_to_mobi(epub_path, save_path)
                if not os.path.isfile(save_path):
                    logging.warning("Create mobi file failed")
                    continue
                logging.info("Save file %s complete" % save_path)

        if "txt" in args.output_format:
            save_path = os.path.join(output_dir, "%s.txt" % title)
            if os.path.isfile(save_path):
                logging.info("File %s exist, ignore export" % save_path)
            else:
                await exporter.markdown_to_txt(save_path)
                logging.info("Save file %s complete" % save_path)
    return 0


def main() -> int:
    if sys.platform == "win32":
        patch_windows()
    elif sys.platform == "darwin":
        patch_macos()
    patch_generateRequestHash()
    utils.check_cairo_installed()
    logging.root.level = logging.INFO
    handler = logging.StreamHandler()
    fmt = "[%(asctime)s][%(levelname)s]%(message)s"
    formatter = logging.Formatter(fmt)
    handler.setFormatter(formatter)
    logging.root.addHandler(handler)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(async_main())
    except:
        import traceback

        traceback.print_exc()
        return -1


if __name__ == "__main__":
    sys.exit(main())
