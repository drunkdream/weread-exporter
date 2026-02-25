import hashlib
import logging
import random
import sys
from typing import Callable, Dict, List, Optional, Tuple, Union

import aiohttp
from aiohttp.client import _RequestContextManager
from PIL import Image

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal


class BreakExportingError(RuntimeError):
    pass


class CairoNotInstalledError(Exception):
    pass


class ChromeNotInstalledError(Exception):
    pass


class InvalidUserError(RuntimeError):
    pass


class LoadChapterFailedError(RuntimeError):
    pass


class LoginRequiredError(RuntimeError):
    pass


def check_cairo_installed() -> None:
    """检查cairo是否安装，如果未安装则抛出异常并提示安装方法

    Raises:
        CairoNotInstalledError: 当cairo未安装时抛出
    """
    try:
        import cairocffi

        return
    except OSError:
        # 根据不同平台提供安装指导
        if sys.platform == "darwin":  # macOS
            install_msg = """Cairo is not installed or not working properly.

    Please install Cairo using one of the following methods:

    1. Using Homebrew (recommended):
    brew install cairo pango

    For more details, visit: https://pycairo.readthedocs.io/en/latest/getting_started.html"""

        elif sys.platform.startswith("linux"):  # Linux
            install_msg = """Cairo is not installed or not working properly.

    Please install Cairo using your system's package manager:

    Ubuntu/Debian:
    sudo apt-get install libcairo2-dev pkg-config python3-dev
    pip install pycairo

    CentOS/RHEL/Fedora:
    sudo yum install cairo-devel pkgconfig python3-devel  # CentOS/RHEL
    sudo dnf install cairo-devel pkgconfig python3-devel  # Fedora
    pip install pycairo

    Arch Linux:
    sudo pacman -S cairo pkgconf
    pip install pycairo

    For more details, visit: https://pycairo.readthedocs.io/en/latest/getting_started.html"""

        elif sys.platform == "win32":  # Windows
            install_msg = """Cairo is not installed or not working properly.

    Please install Cairo using one of the following methods:

    1. Using conda (recommended):
    conda install cairo

    2. Using pip with pre-compiled wheels:
    pip install pycairo

    3. Download pre-compiled binaries from:
    https://www.lfd.uci.edu/~gohlke/pythonlibs/#pycairo

    For more details, visit: https://pycairo.readthedocs.io/en/latest/getting_started.html"""

        else:
            install_msg = """Cairo is not installed or not working properly.

    Please install Cairo and its Python bindings (pycairo).
    Visit https://pycairo.readthedocs.io/en/latest/getting_started.html for installation instructions."""

        raise CairoNotInstalledError(install_msg)


def generate_user_agent() -> str:
    user_agent_tmpl = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/%d.0.0.0 Safari/537.36"
    return user_agent_tmpl % random.randint(90, 130)


async def fetch(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    data: Optional[Union[str, bytes]] = None,
    respond_with_headers: bool = False,
) -> Union[bytes, Tuple[int, Dict[str, str], bytes]]:
    headers: Dict[str, str] = headers or {}
    headers.pop("sec-ch-ua", None)
    headers.pop("sec-ch-ua-platform", None)
    async with aiohttp.ClientSession() as session:
        method_func: Callable[..., _RequestContextManager] = getattr(
            session, method.lower(), session.get
        )
        if data and not isinstance(data, bytes):
            data = data.encode("utf-8")

        for _ in range(3):
            try:
                async with method_func(url, headers=headers, data=data) as response:
                    # response.raise_for_status()
                    result = await response.read()
                    if respond_with_headers:
                        # 转换 headers 为字典以匹配类型注解
                        headers_dict = {k: v for k, v in response.headers.items()}
                        return response.status, headers_dict, result
                    else:
                        return result
            except:
                logging.exception("Fetch url %s failed" % url)
        else:
            raise RuntimeError("Fetch url %s failed" % url)


async def get_book_list(book_list_id: str) -> List[Dict[str, str]]:
    book_list: List[Dict[str, str]] = []
    url: str = "https://weread.qq.com/misc/booklist/" + book_list_id
    html: bytes = await fetch(url)
    html_str: str = html.decode()
    pos: int = html_str.find("window.__NUXT__")
    if pos <= 0:
        raise RuntimeError("Unexpected html: %s" % html_str)
    pos: int = html_str.find("bookEntities:", pos)
    while True:
        if book_list:
            pos: int = html_str.find('},"', pos)
            if pos < 0:
                break
        pos: int = html_str.find('"', pos)
        pos1: int = html_str.find('"', pos + 1)
        book_id: str = html_str[pos + 1 : pos1]
        pos: int = html_str.find("title:", pos)
        pos: int = html_str.find('"', pos)
        pos1: int = html_str.find('"', pos + 1)
        title: str = html_str[pos + 1 : pos1]
        book_list.append({"id": wr_hash(book_id), "title": title})
    return book_list


def format_filename(filename: str) -> str:
    for c in ("/", "\\", ":"):
        filename = filename.replace(c, "%%%.2x" % ord(c))
    return filename


def md5(s: Union[str, bytes]) -> str:
    if not isinstance(s, bytes):
        s: bytes = s.encode()
    return hashlib.md5(s).hexdigest()


def wr_hash(s: str) -> str:
    hash_str: str = md5(s)
    result: str = hash_str[:3] + "32" + hash_str[-2:]
    _0x22edbf: List[str] = []
    for i in range(0, len(s), 9):
        _0x22edbf.append("%x" % int(s[i : min(i + 9, len(s))]))

    for i, it in enumerate(_0x22edbf):
        _0x116344: str = "%x" % len(it)
        if len(_0x116344) == 1:
            _0x116344 = "0" + _0x116344
        result += _0x116344 + it
        if i < len(_0x22edbf) - 1:
            result += "g"

    if len(result) < 20:
        result += hash_str[: 20 - len(result)]
    result += hashlib.md5(result.encode()).hexdigest()[:3]
    return result


def save_to_png(img_path: str, png_path: str) -> None:
    img = Image.open(img_path)
    img.save(png_path)
