# 微信读书导出工具

## INSTALL

```bash
$ pip3 install -e .
```

## USAGE

```bash
$ python -m weread_exporter -b $book_id -o epub -o pdf
```

> 获取书籍ID的方法：在页面`https://weread.qq.com/`搜索目标书籍，进入到书籍介绍页，URL格式为：`https://weread.qq.com/web/bookDetail/08232ac0720befa90825d88`，这里的`08232ac0720befa90825d88`就是书籍ID。

`-o`参数用于指定要保存的文件格式，目前支持的格式有：`epub`、`pdf`、`mobi`，生成的文件在当前目录下的`output`目录中。

`epub`格式适合手机端访问，`pdf`格式适合电脑端访问，`mobi`格式适合kindle访问。

命令行还支持一个可选参数`--force-login`，默认为`False`，指定该参数时，会先进行登录操作。
