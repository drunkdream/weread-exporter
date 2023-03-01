import argparse
import asyncio
import logging
import os

from . import export, webpage


async def main():
    parser = argparse.ArgumentParser(
        prog="weread-exporter", description="WeRead book export cmdline tool"
    )
    parser.add_argument("-b", "--book-id", help="book id", required=True)
    args = parser.parse_args()

    page = webpage.WeReadWebPage(
        args.book_id, cookie_path=os.path.join("cache", "cookie.txt")
    )
    await page.launch()
    save_path = os.path.join("cache", args.book_id)
    exporter = export.WeReadExporter(page, save_path)
    await exporter.export_markdown()
    await exporter.pre_process_markdown()
    await exporter.markdown_to_epub("%s.epub" % args.book_id)


if __name__ == "__main__":
    logging.root.level = logging.INFO
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
