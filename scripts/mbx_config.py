#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mbx_config.py —— 公共配置解析（环境变量优先，不写死个人路径）

优先级：真实环境变量 > `references/环境与配置.local.env`（本机私有，不发布） > 公共默认。
`环境与配置.local.env` 是不进 Git 的 KEY=VALUE 文件；没有它时全部走公共默认。
"""
import os

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_ENV = os.path.join(SKILL_ROOT, 'references', '环境与配置.local.env')


def _load_local_env():
    if not os.path.exists(LOCAL_ENV):
        return
    for line in open(LOCAL_ENV, encoding='utf-8'):
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _path(name, default=''):
    value = os.environ.get(name) or default
    return os.path.expanduser(os.path.expandvars(value)) if value else ''


_load_local_env()


def books_dir():
    """书籍输出根：默认当前目录下 ./books。"""
    return _path('MBX_BOOKS_DIR', os.path.join('.', 'books'))


def terms_dir():
    """术语体系：默认 <输出根>/_术语体系。"""
    return _path('MBX_TERMS_DIR', os.path.join(books_dir(), '_术语体系'))


def ocr_exe():
    """PaddleOCR-json 可执行文件；未配置时为空。"""
    return _path('MBX_OCR_EXE')


def ocr_engine_dir():
    """PPOCR_api.py 所在目录；未配置时从 exe 推导。"""
    d = _path('MBX_OCR_ENGINE_DIR')
    if d:
        return d
    exe = ocr_exe()
    return os.path.dirname(exe) if exe else ''


def usage_ledger():
    """DSH 用量账本；默认 ~/.dsh 下的通用位置，取不到就报取不到。"""
    return _path('MBX_USAGE_LEDGER', os.path.join(
        os.path.expanduser('~'), '.dsh', 'dsh-usage', 'usage-ledger.json'))


def vault_root():
    """Obsidian 库根；可选，空表示不假设。"""
    return _path('MBX_VAULT_ROOT')
