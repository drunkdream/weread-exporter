import hashlib
import logging

import aiohttp


class LoginRequiredError(RuntimeError):
    pass


async def fetch(url, headers=None, respond_with_headers=False):
    headers = headers or {}
    if "User-Agent" not in headers:
        headers[
            "User-Agent"
        ] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.63 Safari/537.36"
    async with aiohttp.ClientSession() as session:
        for _ in range(3):
            try:
                async with session.get(url, headers=headers) as response:
                    response.raise_for_status()
                    result = await response.read()
                    if respond_with_headers:
                        return response.headers, result
                    else:
                        return result
            except:
                logging.exception("Fetch url %s failed" % url)
        else:
            raise RuntimeError("Fetch url %s failed" % url)


def md5(s):
    if not isinstance(s, bytes):
        s = s.encode()
    return hashlib.md5(s).hexdigest()


def wr_hash(s):
    hash = md5(s)
    result = hash[:3] + "32" + hash[-2:]
    _0x22edbf = []
    for i in range(0, len(s), 9):
        _0x22edbf.append("%x" % int(s[i : min(i + 9, len(s))]))

    for i, it in enumerate(_0x22edbf):
        _0x116344 = "%x" % len(it)
        if len(_0x116344) == 1:
            _0x116344 = "0" + _0x116344
        result += _0x116344 + it
        if i < len(_0x22edbf) - 1:
            result += "g"

    if len(result) < 20:
        result += hash[: 20 - len(result)]
    result += hashlib.md5(result.encode()).hexdigest()[:3]
    return result
