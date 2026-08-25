# -*- coding: utf-8 -*-
"""跨格式标签写入器：只写 plan() 里给出的勾选字段，其它标签一律不动。

支持格式：m4a(MP4)、mp3/dsf(ID3v2)、flac/ogg/opus(VorbisComment)。
"""
import os
from mutagen import File as MFile
from mutagen.mp4 import MP4
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TPE2, TCON, TDRC, TRCK, TPOS, TCOM, COMM
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus

# MP4 键映射（不含 track/disc 单独处理）
MP4_TXT = {
    "title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb",
    "album_artist": "aART", "genre": "\xa9gen", "date": "\xa9day",
    "composer": "\xa9wrt", "comment": "\xa9cmt",
}

ID3_FRAME = {  # key -> (frame_class, frame_key)
    "title": (TIT2, "TIT2"), "artist": (TPE1, "TPE1"), "album": (TALB, "TALB"),
    "album_artist": (TPE2, "TPE2"), "genre": (TCON, "TCON"), "date": (TDRC, "TDRC"),
    "composer": (TCOM, "TCOM"),
}

VORBIS_KEY = {
    "title": "title", "artist": "artist", "album": "album",
    "album_artist": "albumartist", "genre": "genre", "date": "date",
    "composer": "composer", "comment": "comment",
    "track": "tracknumber", "disc": "discnumber",
}


def write_fields(path, plan):
    """plan: list[(field_key, current, new)]。
    只修改涉及的字段，其它标签原样保留。"""
    a = MFile(path)
    if a is None:
        raise ValueError("无法解析/写入文件: " + path)

    # 按需载入 tags（若文件尚无标签则补空对象）
    if a.tags is None:
        a.add_tags()

    if isinstance(a, MP4):
        _write_mp4(a, plan)
    elif isinstance(a, (FLAC, OggVorbis, OggOpus)):
        _write_vorbis(a, plan)
    else:
        _write_id3(path, plan, a)
    a.save()
    return len(plan)


def _put_text_tag(tags, key, value):
    if value in ("", "0"):
        tags.pop(key, None)
    else:
        tags[key] = [value]


def _write_mp4(a, plan):
    t = a.tags
    for k, _cur, new_val in plan:
        if k == "track":
            try:
                num = int(str(new_val).split("/")[0])
            except ValueError:
                num = 0
            t["trkn"] = [(num, 0)] if num else [(0, 0)]
        elif k == "disc":
            try:
                num = int(str(new_val).split("/")[0])
            except ValueError:
                num = 0
            t["disk"] = [(num, 0)] if num else [(0, 0)]
        elif k in MP4_TXT:
            _put_text_tag(t, MP4_TXT[k], "" if new_val is None else str(new_val).strip())
    return t


def _write_vorbis(a, plan):
    t = a.tags
    for k, _cur, new_val in plan:
        key = VORBIS_KEY.get(k)
        if not key:
            continue
        _put_text_tag(t, key, "" if new_val is None else str(new_val).strip())
    return t


def _write_id3(path, plan, a):
    tags = a.tags
    if tags is None:
        a.add_tags()
        tags = a.tags
    for k, _cur, new_val in plan:
        sval = "" if new_val is None else str(new_val).strip()
        if k == "track":
            tags.delall("TRCK")
            if sval:
                tags.add(TRCK(encoding=3, text=[sval]))
        elif k == "disc":
            tags.delall("TPOS")
            if sval:
                tags.add(TPOS(encoding=3, text=[sval]))
        elif k == "comment":
            tags.delall("COMM")
            if sval:
                tags.add(COMM(encoding=3, lang="eng", desc="", text=sval))
        elif k == "date":
            tags.delall("TDRC")
            if sval:
                tags.add(TDRC(encoding=3, text=[sval]))
        elif k in ID3_FRAME:
            _cls, _fk = ID3_FRAME[k]
            tags.delall(_fk)
            if sval:
                tags.add(_cls(encoding=3, text=[sval]))
    return tags
