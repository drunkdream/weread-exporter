import argparse
import asyncio
import logging
import os
import sys

from . import export, webpage


async def async_main():
    parser = argparse.ArgumentParser(
        prog="weread-exporter", description="WeRead book export cmdline tool"
    )
    parser.add_argument("-b", "--book-id", help="book id", required=True)
    parser.add_argument(
        "-o",
        "--output-format",
        help="output file format",
        action="append",
        choices=["md", "epub", "pdf", "mobi"],
    )
    parser.add_argument(
        "--force-login", help="force login first", action="store_true", default=False
    )
    args = parser.parse_args()
    args.output_format = args.output_format or ["epub"]
    if "mobi" in args.output_format and "epub" not in args.output_format:
        args.output_format.append("epub")

    page = webpage.WeReadWebPage(
        args.book_id, cookie_path=os.path.join("cache", "cookie.txt")
    )
    await page.launch(args.force_login)
    save_path = os.path.join("cache", args.book_id)
    output_dir = "output"
    if not os.path.isdir(output_dir):
        os.mkdir(output_dir)
    exporter = export.WeReadExporter(page, save_path)
    await exporter.export_markdown()
    await exporter.pre_process_markdown()
    title = await exporter.get_book_title()
    if "epub" in args.output_format:
        save_path = os.path.join(output_dir, "%s.epub" % title)
        await exporter.markdown_to_epub(save_path)
        logging.info("Save file %s complete" % save_path)

    if "pdf" in args.output_format:
        for font_size, desc in ((14, "small"), (32, "large")):
            save_path = os.path.join(output_dir, "%s-%s.pdf" % (title, desc))
            await exporter.markdown_to_pdf(save_path, font_size=font_size)
            logging.info("Save file %s complete" % save_path)

    if "mobi" in args.output_format:
        if sys.platform != "linux":
            logging.error("Only linux system supported to export mobi format")
            return -1
        epub_path = os.path.join(output_dir, "%s.epub" % title)
        save_path = os.path.join(output_dir, "%s.mobi" % title)
        await exporter.epub_to_mobi(epub_path, save_path)
        if not os.path.isfile(save_path):
            raise RuntimeError("Create mobi file failed")
        logging.info("Save file %s complete" % save_path)
    return 0


def main():
    logging.root.level = logging.INFO
    handler = logging.StreamHandler()
    fmt = "[%(asctime)s][%(levelname)s]%(message)s"
    formatter = logging.Formatter(fmt)
    handler.setFormatter(formatter)
    logging.root.addHandler(handler)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(async_main())


if __name__ == "__main__":
    main()
