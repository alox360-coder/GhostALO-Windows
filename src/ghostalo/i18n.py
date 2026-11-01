"""Traduzioni: il codice contiene i testi in italiano; con Windows non in italiano si usa l'inglese."""
import ctypes
import locale
import os

from .en import EN

_italian = True


def init():
    global _italian
    lang = ""
    try:
        if os.name == "nt":
            lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            lang = locale.windows_locale.get(lid, "")
        else:
            lang = locale.getlocale()[0] or ""
    except Exception:
        lang = ""
    _italian = lang.lower().startswith("it")


def set_italian(v):
    global _italian
    _italian = v


def tr(s):
    return s if _italian else EN.get(s, s)


def trf(s, *args):
    try:
        return tr(s) % args
    except (TypeError, ValueError):
        return s % args
