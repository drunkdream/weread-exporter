"""
curl 'https://weread.qq.com/web/book/chapterInfos' \
  -H 'content-type: application/json;charset=UTF-8' \
  --data-raw '{"bookIds":["34615967"]}' 
"""

import asyncio
import json
import logging
import os
import time

import pyppeteer

from . import utils


class WeReadWebPage(object):
    """"""

    root_url = "https://weread.qq.com"
    window_size = (1920, 1080)

    def __init__(self, book_id, cookie_path=None):
        self._book_id = book_id
        self._cookie_path = cookie_path
        self._cookie = {}
        self._home_url = "%s/web/bookDetail/%s" % (
            self.__class__.root_url,
            book_id,
        )
        self._chapter_root_url = self.__class__.root_url + "/web/reader/"
        self._browser = None
        self._page = None
        self._load_cookie()
        self._url = ""

    async def get_book_info(self):
        html = (await utils.fetch(self._home_url)).decode()
        pos1 = html.find("window.__INITIAL_STATE__")
        if pos1 <= 0:
            raise RuntimeError("Unexpected html: %s" % self._html)
        pos1 = html.find("=", pos1)
        pos2 = html.find("};", pos1)
        data = html[pos1 + 1 : pos2 + 1].strip()
        data = json.loads(data)
        book_info = {}
        book_info["title"] = data["reader"]["bookInfo"]["title"]
        book_info["author"] = data["reader"]["bookInfo"]["author"]
        book_info["cover"] = data["reader"]["bookInfo"]["cover"]
        book_info["intro"] = data["reader"]["bookInfo"]["intro"]
        book_info["chapters"] = []
        for chapter in data["reader"]["chapterInfos"]:
            book_info["chapters"].append(
                {
                    "id": chapter["chapterUid"],
                    "title": chapter["title"],
                    "level": chapter["level"],
                    "words": chapter["wordCount"],
                }
            )
        return book_info

    async def get_user_info(self):
        vid = self._cookie.get("wr_vid")
        if not vid:
            raise RuntimeError("Invalid cookie: %s" % self._format_cookie())
        url = "%s/web/user?userVid=%s" % (self.__class__.root_url, vid)
        headers = {"Cookie": self._format_cookie()}
        rsp = await utils.fetch(url, headers=headers)
        rsp = json.loads(rsp.decode())
        if rsp.get("errCode") == -2012:
            rsp_headers, _ = await utils.fetch(
                self.__class__.root_url, headers=headers, respond_with_headers=True
            )
            for it in rsp_headers.getall("Set-Cookie", []):
                cookie = it.split("; ")[0]
                if "=" not in cookie:
                    logging.warning(
                        "[%s] Ignore invalid cookie: %s"
                        % (self.__class__.__name__, cookie)
                    )
                    continue
                key, value = cookie.split("=", 1)
                self._cookie[key] = value
                logging.info(
                    "[%s] Update cookie %s" % (self.__class__.__name__, cookie)
                )
            self._save_cookie()
            headers = {"Cookie": self._format_cookie()}
            rsp = await utils.fetch(url, headers=headers)
            rsp = json.loads(rsp.decode())
        if rsp.get("errCode"):
            raise RuntimeError("Get user info failed: %s" % rsp)
        return rsp

    def _load_cookie(self):
        self._cookie = {}
        if not os.path.isfile(self._cookie_path):
            return
        with open(self._cookie_path) as fp:
            cookie = fp.read()
            try:
                cookie = json.loads(cookie)
            except:
                for it in cookie.split(";"):
                    it = it.strip()
                    if "=" not in it:
                        continue
                    key, value = it.split("=")
                    self._cookie[key] = value
            else:
                for key in cookie:
                    self._cookie[key] = cookie[key]

    def _save_cookie(self):
        if not self._cookie_path:
            return
        with open(self._cookie_path, "w") as fp:
            fp.write(json.dumps(self._cookie))

    def _format_cookie(self):
        cookies = []
        for key in self._cookie:
            cookies.append("%s=%s" % (key, self._cookie[key]))
        return "; ".join(cookies)

    # async def _update_cookie(self):
    #     self._cookie = await self._page.cookies()

    async def launch(self):
        logging.info("[%s] Launch url %s" % (self.__class__.__name__, self._home_url))
        self._browser = await pyppeteer.launch(
            headless=False,
            executablePath="chrome",
            args=[
                "--window-size=%d,%d" % self.__class__.window_size,
            ],
        )
        self._page = await self._browser.newPage()
        await self._page.setViewport(
            {
                "width": self.__class__.window_size[0],
                "height": self.__class__.window_size[1],
                "deviceScaleFactor": 0.3,
            }
        )
        if self._cookie:
            user_info = await self.get_user_info()
            logging.info(
                "[%s] Current login user is %s"
                % (self.__class__.__name__, user_info["name"])
            )
            await self._inject_cookie()
        await self._page.goto(self._home_url)
        await self._page.waitForSelector("div.readerFooter a")
        if self._cookie:
            await self.wait_for_avatar()
        self._page.on("console", self.handle_log)

    def handle_log(self, message):
        with open("console.log", "a+") as fp:
            fp.write("[%s] %s\n" % (self._url, message.text))

    async def wait_for_avatar(self, timeout=30):
        time0 = time.time()
        while time.time() - time0 < timeout:
            avatar_url = await self._page.evaluate(
                "document.querySelector('img.wr_avatar_img') && document.querySelector('img.wr_avatar_img').getAttribute('src');"
            )
            if avatar_url == None or not avatar_url.endswith("Default.svg"):
                break
            await asyncio.sleep(5)
        else:
            raise RuntimeError("Wait for avatar timeout")

    async def inject_cookie(self):
        if not self._cookie:
            return
        for it in self._cookie.split(";"):
            it = it.strip()
            if not it:
                continue
            key, value = it.split("=", 1)
            await self._page.setCookie(
                {"url": self.__class__.root_url, "name": key, "value": value}
            )

    async def _inject_cookie(self):
        for key in self._cookie:
            logging.info(
                "[%s] Inject cookie %s=%s"
                % (self.__class__.__name__, key, self._cookie[key])
            )
            await self._page.setCookie(
                {
                    "url": self.__class__.root_url,
                    "name": key,
                    "value": self._cookie[key],
                }
            )

    async def check_login(self):
        selector = "button.readerFooter_button"
        script = (
            "document.querySelector('%s') && document.querySelector('%s').innerText"
            % (selector, selector)
        )
        result = await self._page.evaluate(script)
        if "登录" in result:
            await self._page.click(selector)
            await self.pre_load_page()
            time0 = time.time()
            while time.time() - time0 < 300:
                logging.info("[%s] Waiting for login" % self.__class__.__name__)
                await asyncio.sleep(10)
                result = await self._page.evaluate(script)
                if not result:
                    continue
                if "登录" not in result:
                    logging.info("[%s] Login success" % self.__class__.__name__)
                    await self._update_cookie()
                    self._save_cookie()
                    return
            else:
                raise RuntimeError("Login timeout")

    async def _handle_request(self, request):
        logging.info("[%s] Fetch url %s" % (self.__class__.__name__, request.url))
        if request.url.startswith(self._chapter_root_url):
            # await request.continue_()
            headers = request.headers
            headers["Cookie"] = self._format_cookie()
            body = await utils.fetch(request.url, headers=headers)
            with open(
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "hook.js")
            ) as fp:
                hook_script = fp.read()
            inject_script = "<script>\n%s</script>\n" % hook_script
            response = {"body": inject_script.encode() + body}
            await request.respond(response)
        elif "/app." in request.url and request.url.endswith(".js"):
            body = await utils.fetch(request.url, headers=request.headers)
            pos = body.find(b"'isCopyRightForbiddenRead':function")
            if pos < 0:
                logging.warning(
                    "[%s] Lookup isCopyRightForbiddenRead failed"
                    % self.__class__.__name__
                )
                await request.continue_()
                return
            pos = body.find(b"{", pos)
            pos1 = body.find(b"}", pos)
            body = body[: pos + 1] + b"return false;" + body[pos1:]
            response = {"body": body}
            await request.respond(response)
            self._page.remove_listener("request", self.handle_request)
            await self._page.setRequestInterception(False)
        else:
            await request.continue_()

    def handle_request(self, request):
        asyncio.ensure_future(self._handle_request(request))

    async def pre_load_page(self):
        await self._page.setRequestInterception(True)
        self._page.on("request", self.handle_request)

    async def start_read(self):
        await self.pre_load_page()
        # await self._page.click(".readerFooter a")
        self._url = self._chapter_root_url + self._book_id
        await self._page.goto(self._url, timeout=60000)
        await self._page.waitForSelector("button.readerFooter_button", timeout=60000)

    async def get_markdown(self):
        script = "canvasContextHandler.data.markdown;"
        result = await self._page.evaluate(script)
        if not result:
            await self._page.evaluate("canvasContextHandler.updateMarkdown();")
            result = await self._page.evaluate(script)
        return result

    async def _check_next_page(self):
        while True:
            result = await self._page.evaluate(
                "document.getElementsByClassName('readerFooter_button')[0].innerText;"
            )
            if result == "下一页":
                logging.info("[%s] Go to next page" % self.__class__.__name__)
                await self._page.evaluate(
                    r"canvasContextHandler.data.markdown += '\n\n';"
                )
                await self.pre_load_page()
                await self._page.click("button.readerFooter_button")
                await asyncio.sleep(1)
                await self._page.waitForSelector("button.readerFooter_button")
            elif result == "下一章":
                break
            else:
                raise NotImplementedError(result)

    def _get_chapter_url(self, chapter_id):
        return "%s%sk%s" % (
            self._chapter_root_url,
            self._book_id,
            utils.wr_hash(str(chapter_id)),
        )

    async def goto_chapter(self, chapter_id, check_next_chapter=True):
        logging.info("[%s] Go to chapter %s" % (self.__class__.__name__, chapter_id))
        # await self.clear_cache()
        await self.pre_load_page()
        self._url = self._get_chapter_url(chapter_id)
        await self._page.goto(self._url, timeout=60000)
        await asyncio.sleep(5)
        if check_next_chapter:
            await self._page.waitForSelector("button.readerFooter_button")
            await self.check_login()
            await self._check_next_page()

    async def clear_cache(self):
        await self._page.evaluate("canvasContextHandler.clearCanvasCache();")
