# -*- coding: utf-8 -*-
"""扫描文件夹中的音频文件并读取现有标签，填入 model.AudioTags.current。"""
import os
from mutagen import File as MFile
from mutagen.mp4 import MP4
import model


AUDIO_EXTS = {".m4a", ".mp3", ".mp4", ".aac", ".flac", ".ogg", ".opus", ".wav", ".m4b", ".dsf", ".wma"}


def _first(v, idx=0):
    if not v:
        return ""
    el = v[idx] if isinstance(v, list) else v
    if hasattr(el, "text"):
        el = el.text
    if isinstance(el, (list, tuple)):
        return str(el[idx]) if el and len(el) > idx else (str(el[0]) if el else "")
    return str(el).replace("\x00", " ").strip()


def _trk_mp4(v):
    if not v:
        return ""
    el = v[0] if isinstance(v, list) else v
    if isinstance(el, (list, tuple)) and el:
        return str(el[0])
    if hasattr(el, "number"):
        return str(el.number)
    return str(el)


def _trk_num(v):
    """vorbis '12/15' -> '12'"""
    s = _first(v)
    return s.split("/")[0].strip() if s else ""


def read_file_tags(path):
    """读单个文件，返回 {field: current_value}（字段为 model 的 key）。"""
    cur = {k: "" for k, _ in model.FIELDS}
    a = MFile(path)
    if a is None:
        return cur
    t = a.tags
    if t is None:
        return cur
    if isinstance(a, MP4):
        cur["title"] = _first(t.get("\xa9nam"))
        cur["artist"] = _first(t.get("\xa9ART"))
        cur["album"] = _first(t.get("\xa9alb"))
        cur["album_artist"] = _first(t.get("aART"))
        cur["genre"] = _first(t.get("\xa9gen"))
        cur["date"] = _first(t.get("\xa9day"))[:4]
        cur["track"] = _trk_mp4(t.get("trkn"))
        cur["disc"] = _first(t.get("disk"))
        cur["composer"] = _first(t.get("\xa9wrt"))
        cur["comment"] = _first(t.get("\xa9cmt"))
        return cur
    # ID3 & Vorbis 通用键
    def g(*keys):
        for k in keys:
            if k in t:
                return _first(t[k])
        return ""
    cur["title"] = g("TIT2", "title")
    cur["artist"] = g("TPE1", "artist")
    cur["album"] = g("TALB", "album")
    cur["album_artist"] = g("TPE2", "albumartist", "album_artist", "performer")
    gval = g("TCON", "genre")
    cur["genre"] = gval.split(";")[0].split("/")[0].strip() if gval else ""
    d = g("TDRC", "date")
    cur["date"] = d[:4] if d else ""
    cur["track"] = _trk_num(g("TRCK", "tracknumber"))
    cur["disc"] = _trk_num(g("TPOS", "discnumber"))
    cur["composer"] = g("TCOM", "composer")
    cur["comment"] = g("COMM", "comment", "description")
    return cur


def is_audio(path):
    return os.path.splitext(path)[1].lower() in AUDIO_EXTS


def list_files(root):
    """返回目录下所有音频的绝对路径（含子目录），排序稳定。"""
    out = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if not d.startswith(".")]
        for fn in fns:
            p = os.path.join(dp, fn)
            if is_audio(p):
                out.append(p)
    return sorted(out)
