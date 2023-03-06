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
    parser.add_argument(
        "-o",
        "--output-format",
        help="output file format",
        action="append",
        choices=["md", "epub", "pdf"],
    )
    args = parser.parse_args()
    args.output_format = args.output_format or ["epub", "pdf"]

    page = webpage.WeReadWebPage(
        args.book_id, cookie_path=os.path.join("cache", "cookie.txt")
    )
    await page.launch()
    save_path = os.path.join("cache", args.book_id)
    exporter = export.WeReadExporter(page, save_path)
    await exporter.export_markdown()
    await exporter.pre_process_markdown()
    title = await exporter.get_book_title()
    if "epub" in args.output_format:
        save_path = "%s.epub" % title
        await exporter.markdown_to_epub(save_path)
        logging.info("Save file %s complete" % save_path)

    if "pdf" in args.output_format:
        for font_size, desc in ((14, "small"), (32, "large")):
            save_path = "%s-%s.pdf" % (title, desc)
            await exporter.markdown_to_pdf(save_path, font_size=font_size)
            logging.info("Save file %s complete" % save_path)


if __name__ == "__main__":
    logging.root.level = logging.INFO
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
