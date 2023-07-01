import asyncio
import json
import logging
import os
import sys
import time

import markdown

from ebooklib import epub
from weasyprint import HTML, CSS

from . import utils

current_path = os.path.dirname(os.path.abspath(__file__))


class WeReadExporter(object):
    def __init__(self, page, save_dir):
        self._page = page
        self._save_dir = save_dir
        if not os.path.isdir(save_dir):
            os.makedirs(save_dir)
        self._meta_path = os.path.join(self._save_dir, "meta.json")
        self._chapter_dir = os.path.join(self._save_dir, "chapters")
        self._image_dir = os.path.join(self._save_dir, "images")
        if not os.path.isdir(self._image_dir):
            os.mkdir(self._image_dir)
        self._cover_image_path = os.path.join(self._save_dir, "cover.jpg")
        self._meta_data = {}
        self._current_chapter = 0

    async def get_book_title(self):
        meta_data = await self._load_meta_data()
        return meta_data["title"]

    def _make_chapter_path(self, index, chapter_id):
        return os.path.join(self._chapter_dir, "%d-%s.md" % (index + 1, chapter_id))

    async def _load_meta_data(self):
        if self._meta_data:
            return self._meta_data

        if not os.path.isfile(self._meta_path):
            self._meta_data = await self._page.get_book_info()
            with open(self._meta_path, "w") as fp:
                fp.write(json.dumps(self._meta_data))
        else:
            with open(self._meta_path) as fp:
                text = fp.read()
                if text:
                    self._meta_data = json.loads(text)
        return self._meta_data

    async def merge_markdown(self, save_path):
        meta_data = await self._load_meta_data()
        with open(save_path, "w") as fp:
            for index, chapter in enumerate(meta_data["chapters"]):
                file_path = self._make_chapter_path(index, chapter["id"])
                if not os.path.isfile(file_path):
                    raise RuntimeError("File %s not exist" % file_path)
                with open(file_path) as fd:
                    fp.write(fd.read() + "\n")

    async def pre_process_markdown(self):
        meta_data = await self._load_meta_data()
        for index, chapter in enumerate(meta_data["chapters"]):
            chapter_path = self._make_chapter_path(index, chapter["id"])
            if not os.path.isfile(chapter_path):
                logging.warning(
                    "[%s] File %s not exist" % (self.__class__.__name__, chapter_path)
                )
                continue
            with open(chapter_path, "rb") as fp:
                text = fp.read().decode()

            output = ""
            code_mode = False
            blank_line = False
            for line in text.split("\n"):
                if line == "```":
                    if not code_mode:
                        output += "\n%s\n" % line
                    else:
                        output += "%s\n" % line
                    code_mode = not code_mode
                elif code_mode:
                    output += line + "\n"
                elif line == "":
                    blank_line = True
                elif blank_line:
                    output += "\n\n%s" % line
                    blank_line = False
                else:
                    output += line
            output += "\n"
            pos = 0
            while pos >= 0:
                pos = output.find("](https://", pos)
                if pos < 0:
                    break
                pos1 = output.find(")", pos)
                url = output[pos + 2 : pos1]
                logging.info("[%s] Replace image %s" % (self.__class__.__name__, url))
                try:
                    data = await utils.fetch(url)
                except:
                    logging.exception(
                        "[%s] Fetch image data of %s failed"
                        % (self.__class__.__name__, url)
                    )
                    pos += 10
                else:
                    image_name = utils.md5(url) + ".jpg"
                    with open(os.path.join(self._image_dir, image_name), "wb") as fp:
                        fp.write(data)
                    output = output[: pos + 2] + "images/" + image_name + output[pos1:]
            if not os.path.isfile(chapter_path + ".bak"):
                os.rename(chapter_path, chapter_path + ".bak")
            with open(chapter_path, "wb") as fp:
                fp.write(output.encode())

    def _markdown_to_html(self, path_or_text, wrap=True):
        if os.path.isfile(path_or_text):
            with open(path_or_text, "rb") as fp:
                markdown_text = fp.read().decode()
        else:
            markdown_text = path_or_text
        html = markdown.markdown(
            markdown_text,
            extensions=[
                "markdown.extensions.fenced_code",
                "markdown.extensions.attr_list",
            ],
        )
        html += '<div class="page-break"></div>'
        if wrap:
            html = (
                '<html><head><link rel="stylesheet" href="style.css"></head><body>%s</body></html>'
                % html
            )
        return html

    async def markdown_to_pdf(self, save_path, font_size=None, dump_html=False):
        meta_data = await self._load_meta_data()
        raw_html = '<img src="cover.jpg" style="width: 100%;">\n'
        for index, chapter in enumerate(meta_data["chapters"]):
            chapter_path = self._make_chapter_path(index, chapter["id"])
            raw_html += self._markdown_to_html(chapter_path, wrap=False)
        raw_html = raw_html.replace(
            "<pre><code>", "<pre><code>\n"
        )  # Fix unexpected indent
        if dump_html:
            html_path = os.path.join(self._save_dir, "output.html")
            with open(html_path, "w") as fp:
                fp.write(raw_html)
        html = HTML(string=raw_html, base_url=self._save_dir)
        css = []
        css_path = os.path.join(current_path, "style.css")
        with open(css_path) as fp:
            raw_css = fp.read()
            if font_size:
                raw_css = raw_css.replace("14px", "%dpx" % font_size)
            css.append(CSS(string=raw_css))

        # Generate PDF
        html.write_pdf(save_path, stylesheets=css)

    async def markdown_to_epub(self, save_path):
        meta_data = await self._load_meta_data()
        book = epub.EpubBook()
        book.set_identifier("id123456")
        book.set_title(meta_data["title"])
        book.set_language("zh-cn")
        book.add_author(meta_data["author"])
        # add cover image
        with open(self._cover_image_path, "rb") as fp:
            image_data = fp.read()
            book.set_cover("cover.jpg", image_data)
        # define CSS style
        css_path = os.path.join(current_path, "epub.css")
        with open(css_path) as fp:
            style = fp.read()
        default_css = epub.EpubItem(
            uid="style_default",
            file_name="style/default.css",
            media_type="text/css",
            content=style,
        )

        # add CSS file
        book.add_item(default_css)
        chapters = []
        toc = []
        section = None
        for index, chapter in enumerate(meta_data["chapters"]):
            chapter_path = self._make_chapter_path(index, chapter["id"])
            xhtml_name = "chap_%.4d.xhtml" % (index + 1)
            chap = epub.EpubHtml(
                title=chapter["title"], file_name=xhtml_name, lang="hr"
            )
            html = self._markdown_to_html(chapter_path)
            chap.content = html.replace("code>", "epub-code>")
            chap.add_item(default_css)
            # add chapter
            book.add_item(chap)
            chapters.append(chap)

            if section:
                if chapter["level"] > 1:
                    section[1].append(chap)
                else:
                    toc.append(section)
                    section = None

            if not section:
                if chapter["anchors"]:
                    section = (epub.Section(chapter["title"], xhtml_name), [])
                    for i, it in enumerate(chapter["anchors"]):
                        # add anchor point
                        chap.content = chap.content.replace(
                            ">%s<" % it["title"].replace(" ", ""),
                            ' id="t%d">%s<' % ((i + 1), it["title"]),
                        )
                        section[1].append(
                            epub.Link(
                                "%s#t%d" % (xhtml_name, (i + 1)),
                                it["title"],
                                str(chapter["id"]),
                            )
                        )
                elif chapter["level"] > 1:
                    section = (toc.pop(-1), [])
                    section[1].append(
                        epub.Link(xhtml_name, chapter["title"], str(chapter["id"]))
                    )
                else:
                    toc.append(
                        epub.Link(xhtml_name, chapter["title"], str(chapter["id"]))
                    )

        for it in os.listdir(self._image_dir):
            with open(os.path.join(self._image_dir, it), "rb") as fp:
                content = fp.read()
                image = epub.EpubItem(
                    file_name="images/" + it,
                    media_type="image/jpeg",
                    content=content,
                )
                book.add_item(image)

        book.toc = toc
        # add default NCX and Nav file
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        book.spine = ["nav", *chapters]
        # write to the file
        epub.write_epub(save_path, book, {})

    async def epub_to_mobi(self, epub_path, save_path):
        kindlegen_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "bin", sys.platform, "kindlegen"
        )
        if not os.path.isfile(kindlegen_path):
            raise RuntimeError("File %s not exist" % kindlegen_path)
        if sys.platform != "win32":
            os.chmod(kindlegen_path, 0o755)
        cmdline = [
            kindlegen_path,
            os.path.abspath(epub_path),
            "-o",
            os.path.basename(save_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmdline, cwd=os.path.dirname(save_path)
        )
        await proc.wait()

    async def save_cover_image(self):
        meta_data = await self._load_meta_data()
        cover_url = meta_data["cover"].replace("/s_", "/t9_")
        data = await utils.fetch(cover_url)
        with open(self._cover_image_path, "wb") as fp:
            fp.write(data)

    async def export_markdown(self, timeout=30, interval=10):
        if not os.path.isdir(self._chapter_dir):
            os.makedirs(self._chapter_dir)
        meta_data = await self._load_meta_data()
        if not os.path.isfile(self._cover_image_path):
            await self.save_cover_image()

        min_wait_time = interval
        for index, chapter in enumerate(meta_data["chapters"]):
            logging.info(
                "[%s] Check chapter %s/%s"
                % (self.__class__.__name__, chapter["id"], chapter["title"])
            )

            file_path = self._make_chapter_path(index, chapter["id"])
            if os.path.isfile(file_path):
                continue
            logging.info(
                "[%s] File %s not exist" % (self.__class__.__name__, file_path)
            )

            time0 = 0
            for _ in range(3):
                time0 = time.time()
                try:
                    await self._page.goto_chapter(
                        chapter["id"],
                        timeout=timeout,
                    )
                except:
                    logging.exception(
                        "[%s] Go to chapter %s failed"
                        % (self.__class__.__name__, chapter["title"])
                    )
                else:
                    break
            else:
                raise utils.LoadChapterFailedError(
                    "Load chapter %s failed" % chapter["title"]
                )

            markdown = await self._page.get_markdown()
            logging.info(
                "[%s] Export chapter %s to %s"
                % (self.__class__.__name__, chapter["title"], file_path)
            )
            with open(file_path, "wb") as fp:
                fp.write(markdown.encode())

            wait_time = min_wait_time - (time.time() - time0)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
